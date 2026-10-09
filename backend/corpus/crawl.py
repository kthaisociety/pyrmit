"""
Crawl the municipalities' websites for planning and building content.

For each kommun (municipalities.json) the crawler reads robots.txt and the sitemaps, then
fetches, by relevance, the pages about planning, building permits, sewage, fees, etc.
(scored on URL, link text and title keywords) and the PDFs linked from them (detaljplaner:
planbeskrivning + plankarta, översiktsplan, taxor, ...). It is polite and resumable:
robots.txt is honoured, one request per second per host, caps per kommun, and a kommun
whose manifest is complete is skipped on the next run.

Output per kommun in data/corpus/raw/web/<code>/:
    pages/<id>.json   {url, title, text, score, fetched_at}
    pdf/<id>.pdf      raw PDFs
    manifest.jsonl    one line per stored item, plus a final {"done": true, ...} line

    cd backend
    python -m corpus.crawl --codes 0115 0188          # pilot on Vallentuna + Norrtälje
    python -m corpus.crawl --concurrency 16           # all 290 (hours; resumable)
"""

import argparse
import asyncio
import gzip
import heapq
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from lxml import etree, html as lxml_html

from corpus.common import MUNICIPALITIES_PATH, USER_AGENT, WEB_DIR, stable_id

# Keyword weights, matched on ASCII-folded, lowercased URL path + link text + title
_KEYWORDS = {
    # plans
    "detaljplan": 6, "oversiktsplan": 6, "planbeskrivning": 6, "plankarta": 6, "planbestammelse": 6,
    "omradesbestammelse": 5, "planprogram": 5, "planbesked": 6, "gallande-plan": 6, "gallande plan": 6,
    "planer-och-program": 5, "planarbete": 4, "pagaende-plan": 4, "fordjupad": 4, "samhallsplanering": 4,
    "stadsplanering": 4, "bostadsbyggnad": 4, "bostadsforsorjning": 4, "markanvisning": 4,
    "exploatering": 3, "tomt": 3, "byggbar": 3, "planeringsunderlag": 3, "strukturplan": 4, "riktlinjer": 2,
    # permits and building
    "bygglov": 6, "forhandsbesked": 6, "marklov": 5, "rivningslov": 5, "startbesked": 5, "slutbesked": 4,
    "attefall": 5, "anmalan": 2, "bygga-nytt": 4, "byggnadsnamnd": 4, "plan-och-bygg": 5, "kontrollansvarig": 3,
    "strandskydd": 5, "kulturmiljo": 3, "bevarandeprogram": 4, "lantmateri": 3, "fastighetsbildning": 4,
    "nybyggnadskarta": 4, "situationsplan": 3,
    # fees, water, sewage
    "taxa": 4, "avgift": 2, "enskilt-avlopp": 6, "enskilt avlopp": 6, "avlopp": 4, "va-plan": 5,
    "vatten-och-avlopp": 4, "dagvatten": 3, "verksamhetsomrade": 4, "markavvattning": 2,
}
# Section names: worth following, but not enough to keep a page ("bygga-bo-och-miljo/alkohol")
_HUBS = {"bygga-bo": 3, "bygga och bo": 3, "bygga-och-bo": 3, "bygga, bo": 3, "samhallsbyggnad": 3, "planering": 2}
KEEP_SCORE = 4
_NEGATIVE = (
    "nyhet", "news", "evenemang", "kalender", "jobb", "ledigt", "lediga", "skola", "forskola", "gymnasi",
    "omsorg", "aldre", "stod-och-omsorg", "kultur-och-fritid", "idrott", "uppleva", "turism", "english",
    "/en/", "politik-och-demokrati/protokoll", "sammantraden", "facebook", "instagram", "linkedin",
    "youtube", "twitter", "login", "e-tjanst", "mailto:", "tel:", "javascript:", "alkohol", "tobak",
    "livsmedel", "serveringstillstand", "minasidor", "mina-sidor", "anslagstavla", "kungorelse", "kallelse",
    "protokoll", "/ledning/", "/namnder/",
)
_PDF_HINTS = ("plan", "taxa", "avlopp", "bygg", "va-", "strand", "riktlinje", "program", "beskrivning", "karta",
              "bestammelse", "dp", "samrad", "granskning", "antagande")
_SKIP_EXTENSIONS = re.compile(r"\.(jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|dwg|dxf|mp4|mp3|ics|css|js)(\?|$)", re.I)


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def content_relevance(*texts: str) -> int:
    """Topic score: decides whether a page is kept."""
    haystack = fold(" ".join(texts))
    if any(word in haystack for word in _NEGATIVE):
        return -1
    return sum(weight for word, weight in _KEYWORDS.items() if word in haystack)


def relevance(*texts: str) -> int:
    """Crawl priority: topic score plus section hubs."""
    score = content_relevance(*texts)
    if score < 0:
        return score
    haystack = fold(" ".join(texts))
    return score + sum(weight for word, weight in _HUBS.items() if word in haystack)


def site_section(url: str) -> str:
    return "/".join(urlparse(url).path.strip("/").split("/")[:3])


def base_domain(host: str) -> str:
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


@dataclass(order=True)
class Task:
    priority: int
    url: str = field(compare=False)
    kind: str = field(compare=False)  # "page" | "pdf"
    anchor: str = field(compare=False, default="")
    source: str = field(compare=False, default="")
    depth: int = field(compare=False, default=0)


class HostLimiter:
    """At most one request per `delay` seconds per host, shared by all kommun crawls."""

    def __init__(self, delay: float):
        self.delay = delay
        self.locks: dict[str, asyncio.Lock] = {}
        self.last: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        lock = self.locks.setdefault(host, asyncio.Lock())
        async with lock:
            pause = self.last.get(host, 0) + self.delay - time.monotonic()
            if pause > 0:
                await asyncio.sleep(pause)
            self.last[host] = time.monotonic()


class KommunCrawler:
    def __init__(self, kommun: dict, client: httpx.AsyncClient, limiter: HostLimiter, args):
        self.kommun = kommun
        self.client = client
        self.limiter = limiter
        self.args = args
        self.root = urlparse(kommun["website"] if "://" in kommun["website"] else "https://" + kommun["website"])
        self.domain = base_domain(self.root.hostname or "")
        self.out = WEB_DIR / kommun["code"]
        self.robots: dict[str, RobotFileParser | None] = {}
        self.seen: set[str] = set()
        self.queue: list[Task] = []
        self.pages = self.pdfs = self.pdf_bytes = 0
        self.stored_pages: set[str] = set()
        self.section_pages: dict[str, int] = {}

    def log(self, message: str) -> None:
        print(f"[{self.kommun['code']} {self.kommun['short_name']}] {message}", flush=True)

    # --- fetching -----------------------------------------------------------------

    async def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host not in self.robots:
            parser = None
            try:
                response = await self.get(f"{parsed.scheme}://{host}/robots.txt", check_robots=False)
                if response is not None and response.status_code == 200:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
            except Exception:
                parser = None
            self.robots[host] = parser
        parser = self.robots[host]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    async def get(self, url: str, check_robots: bool = True, stream_limit: int | None = None):
        if check_robots and not await self.allowed(url):
            return None
        await self.limiter.wait(urlparse(url).hostname or "")
        if stream_limit is None:
            return await self.client.get(url)
        async with self.client.stream("GET", url) as response:
            if response.status_code != 200:
                return response
            length = int(response.headers.get("content-length") or 0)
            if length > stream_limit:
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > stream_limit:
                    return None
            response._content = bytes(body)
            return response

    # --- queueing -----------------------------------------------------------------

    def push(self, url: str, kind: str, score: int, anchor: str = "", source: str = "", depth: int = 0) -> None:
        url = urldefrag(url)[0]
        if url in self.seen or not url.startswith("http"):
            return
        self.seen.add(url)
        heapq.heappush(self.queue, Task(-score, url, kind, anchor, source, depth))

    def is_internal(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == self.domain or host.endswith("." + self.domain)

    async def seed_from_sitemaps(self) -> None:
        sitemap_urls = []
        robots = await self.get(f"{self.root.scheme}://{self.root.hostname}/robots.txt", check_robots=False)
        if robots is not None and robots.status_code == 200:
            sitemap_urls = re.findall(r"(?im)^sitemap:\s*(\S+)", robots.text)
        sitemap_urls = sitemap_urls or [f"{self.root.scheme}://{self.root.hostname}/sitemap.xml"]
        visited, found = 0, 0
        while sitemap_urls and visited < 30:
            sitemap_url = sitemap_urls.pop(0)
            visited += 1
            try:
                response = await self.get(sitemap_url)
                if response is None or response.status_code != 200:
                    continue
                content = response.content
                if sitemap_url.endswith(".gz"):
                    content = gzip.decompress(content)
                tree = etree.fromstring(content, parser=etree.XMLParser(recover=True))
            except Exception:
                continue
            if tree is None:
                continue
            for loc in tree.iter("{*}loc"):
                url = (loc.text or "").strip()
                if "sitemap" in url.rsplit("/", 1)[-1].lower() and url.endswith((".xml", ".gz")):
                    sitemap_urls.append(url)
                    continue
                score = relevance(urlparse(url).path)
                if score > 0 and self.is_internal(url):
                    kind = "pdf" if url.lower().split("?")[0].endswith(".pdf") else "page"
                    self.push(url, kind, score + 2, source="sitemap")
                    found += 1
        self.log(f"sitemaps: {visited} read, {found} relevant URLs")

    # --- processing ---------------------------------------------------------------

    def record(self, entry: dict) -> None:
        with (self.out / "manifest.jsonl").open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def process_page(self, task: Task) -> None:
        response = await self.get(task.url)
        if response is None or response.status_code != 200:
            return
        content_type = response.headers.get("content-type", "")
        if "pdf" in content_type:
            await self.store_pdf(task, response)
            return
        if "html" not in content_type:
            return
        # Redirects may add a fragment ("...#startskede"): one page, not one per anchor
        final_url = urldefrag(str(response.url))[0]
        if not self.is_internal(final_url) or final_url in self.stored_pages:
            return
        try:
            document = lxml_html.fromstring(response.content, base_url=final_url)
        except (etree.ParserError, ValueError):
            return
        title = " ".join((document.findtext(".//title") or "").split())
        page_score = relevance(urlparse(final_url).path, title)
        keep = content_relevance(urlparse(final_url).path, title) >= KEEP_SCORE

        if keep:
            text = trafilatura.extract(response.text, url=final_url, include_tables=True, favor_recall=True) or ""
            if len(text) > 200:
                page_id = stable_id(final_url)
                (self.out / "pages").mkdir(parents=True, exist_ok=True)
                (self.out / "pages" / f"{page_id}.json").write_text(json.dumps({
                    "url": final_url, "title": title, "text": text, "score": page_score,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False), encoding="utf-8")
                self.record({"type": "page", "id": page_id, "url": final_url, "title": title, "score": page_score})
                self.pages += 1
                self.stored_pages.add(final_url)
                section = site_section(final_url)
                self.section_pages[section] = self.section_pages.get(section, 0) + 1

        if task.depth >= self.args.max_depth:
            return
        for element in document.iter("a"):
            href = element.get("href")
            if not href:
                continue
            url = urljoin(final_url, href.strip())
            if _SKIP_EXTENSIONS.search(url):
                continue
            anchor = " ".join(element.text_content().split())[:200]
            is_pdf = url.lower().split("?")[0].endswith(".pdf") or "/download/" in url.lower()
            if is_pdf:
                # PDFs may live on another host (plan archive, GIS portal); keep those linked from relevant pages
                score = relevance(urlparse(url).path, anchor)
                if score < 0 or (score == 0 and page_score <= 0):
                    continue
                if score == 0 and not any(hint in fold(anchor + url) for hint in _PDF_HINTS):
                    continue
                self.push(url, "pdf", score + page_score // 2, anchor, final_url, task.depth + 1)
            elif self.is_internal(url):
                score = relevance(urlparse(url).path, anchor)
                # From the homepage, also follow navigation hubs with neutral scores
                if score > 0 or (task.depth == 0 and score == 0 and len(urlparse(url).path.strip("/").split("/")) <= 1):
                    self.push(url, "page", max(score, 1) + page_score // 3, anchor, final_url, task.depth + 1)

    async def store_pdf(self, task: Task, response=None) -> None:
        if self.pdfs >= self.args.max_pdfs:
            return
        pdf_id = stable_id(task.url)
        path = self.out / "pdf" / f"{pdf_id}.pdf"
        if path.exists():  # downloaded by an earlier pass
            size = path.stat().st_size
        else:
            if response is None or response.content is None:
                response = await self.get(task.url, stream_limit=self.args.max_pdf_mb * 1024 * 1024)
            if response is None or response.status_code != 200 or not response.content.startswith(b"%PDF"):
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            size = len(response.content)
        self.record({"type": "pdf", "id": pdf_id, "url": task.url, "anchor": task.anchor,
                     "source": task.source, "bytes": size, "score": -task.priority})
        self.pdfs += 1
        self.pdf_bytes += size

    async def run(self) -> None:
        manifest = self.out / "manifest.jsonl"
        if manifest.exists() and not self.args.force:
            done = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if '"done": true' in line]
            # Skip unless this pass asks for more than the previous one (e.g. HTML-only first, then PDFs)
            if done and done[-1].get("max_pdfs", 10**6) >= self.args.max_pdfs \
                    and done[-1].get("max_pages", 10**6) >= self.args.max_pages:
                return
        self.out.mkdir(parents=True, exist_ok=True)
        manifest.unlink(missing_ok=True)
        started = time.monotonic()
        self.push(self.root.geturl(), "page", 100, source="home", depth=0)
        await self.seed_from_sitemaps()

        fetched = 0
        while self.queue and fetched < self.args.max_requests:
            if self.pages >= self.args.max_pages and self.pdfs >= self.args.max_pdfs:
                break
            task = heapq.heappop(self.queue)
            if task.kind == "page" and (
                self.pages >= self.args.max_pages
                # One site section (e.g. a plan archive with thousands of pages) gets at most 1/5 of the budget
                or self.section_pages.get(site_section(task.url), 0) >= max(20, self.args.max_pages // 5)
            ):
                continue
            if task.kind == "pdf" and self.pdfs >= self.args.max_pdfs:
                continue
            fetched += 1
            try:
                if task.kind == "pdf":
                    await self.store_pdf(task)
                else:
                    await self.process_page(task)
            except Exception as exc:  # network errors, broken HTML: keep crawling
                if self.args.verbose:
                    self.log(f"error {task.url}: {exc!r}")
        self.record({"done": True, "pages": self.pages, "pdfs": self.pdfs, "pdf_mb": round(self.pdf_bytes / 1e6, 1),
                     "requests": fetched, "seconds": round(time.monotonic() - started),
                     "max_pdfs": self.args.max_pdfs, "max_pages": self.args.max_pages})
        self.log(f"done: {self.pages} pages, {self.pdfs} PDFs ({self.pdf_bytes / 1e6:.0f} MB), "
                 f"{fetched} requests, {time.monotonic() - started:.0f}s")


async def crawl(municipalities: list[dict], args) -> None:
    limiter = HostLimiter(args.delay)
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "sv,en;q=0.5"},
        timeout=httpx.Timeout(30, read=60),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=args.concurrency * 2),
    ) as client:

        async def one(kommun):
            async with semaphore:
                try:
                    await KommunCrawler(kommun, client, limiter, args).run()
                except Exception as exc:
                    print(f"[{kommun['code']}] failed: {exc!r}", flush=True)

        await asyncio.gather(*(one(kommun) for kommun in municipalities))


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl municipal websites for planning documents")
    parser.add_argument("--codes", nargs="*", help="kommun codes (default: all)")
    parser.add_argument("--concurrency", type=int, default=12, help="kommuner crawled in parallel")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one host")
    parser.add_argument("--max-pages", type=int, default=300, help="HTML pages kept per kommun")
    parser.add_argument("--max-pdfs", type=int, default=150, help="PDFs kept per kommun")
    parser.add_argument("--max-pdf-mb", type=int, default=40)
    parser.add_argument("--max-requests", type=int, default=1500, help="requests per kommun")
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="re-crawl kommuner already done")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    municipalities = json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))
    if args.codes:
        municipalities = [m for m in municipalities if m["code"] in set(args.codes)]
    asyncio.run(crawl([m for m in municipalities if m.get("website")], args))


if __name__ == "__main__":
    main()
