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
import hashlib
import heapq
import json
import re
import ssl
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser, RuleLine

import httpx
import trafilatura
import truststore
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
# PDFs obviously off the planning / building topic, not downloaded. Deliberately short: anything that could hold a
# planning fact (meeting packs, waste rooms, schools and care homes as buildings, budgets) is downloaded and left to
# corpus.pdf_filter (second opinion before any drop). Until 2026-10-23 a longer list (avfall, kallelse, budget,
# förskol, omsorg...) also ran on the PDF's metadata title in corpus.extract: it dropped a planuppdrag decision whose
# template title was "Kallelse". Skipped links are recorded in the manifest ("skipped_pdf") so they can be checked.
_PDF_OFF_TOPIC = re.compile(
    r"arsredovisning|delarsrapport|internkontroll|dodsbo|alkohol|tobak|felparkering|parkeringsovervakning"
    r"|kopiering|hygienisk|gardsforsaljning|nationella minoriteter|elevhalsa|fardtjanst|hemtjanst")
# Words that keep a PDF whatever else it mentions ("Detaljplan för återvinningscentral (avfall)")
_PLAN_WORDS = re.compile(r"detaljplan|planbeskrivning|plankarta|planbestammelse|oversiktsplan|planprogram"
                         r"|omradesbestammelse|fordjupad oversikt")
# A page about plans (path or title): a plan, a list of plans. Every PDF it links that is not off topic is taken, and
# the plan pages it links are followed one level past --max-depth (crawl.take_pdf_link, process_page)
_PLAN_PAGE = re.compile(r"detaljplan|byggnadsplan|stadsplan|planprogram|oversiktsplan|omradesbestammelse")


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


# Recorded in the done line. 2 = the short off-topic list above, skipped links recorded (2026-10-23); 3 = every PDF
# of a plan page (2026-10-25). A manifest below it lacks the PDF links the older rules refused: `--revisit` adds them
# without a full crawl
PDF_LINKS_VERSION = 3

# Default caps per kommun (CLI flags; the technical report quotes them). 3000 PDFs / 15000 requests since 2026-10-23:
# at 1000 / 6000, 9 kommuner (Malmö, Västerås, Huddinge...) left plans out; a PDF already on disk costs a request but
# no download
MAX_PAGES, MAX_PDFS, MAX_PDF_MB, MAX_REQUESTS = 1000, 3000, 40, 15000


def is_pdf_link(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf") or "/download/" in url.lower()


def off_topic_pdf(url: str, *texts: str) -> bool:
    """A PDF obviously off topic (annual reports, alcohol licences, estate notices...; file name and link text),
    unless it is a plan. Only the
    file name of the URL counts: Nacka's water PDFs live under /nackavattenavfall/ (one section for water and waste)."""
    name = urlparse(url).path.rsplit("/", 1)[-1] if "://" in url else url
    haystack = fold(unquote(" ".join((name, *texts))))
    return bool(_PDF_OFF_TOPIC.search(haystack)) and not _PLAN_WORDS.search(haystack)


# Query parameters that only change the view of a page (Sitevision accordions "?open.12_4c7c...=true", "sv.url=...
# &state=...", print versions): 6.5k of the 31k pages crawled before 2026-10-22 were such copies
_VIEW_PARAMS = re.compile(r"^(open\..*|sv\..*|state|contactpage|contactuserid|profiling|addtocart|print)$", re.I)


def url_key(url: str) -> str:
    """One key per resource: http/https and www./bare host variants served the same PDF twice (264 pairs), and
    view-only variants of a page."""
    parsed = urlparse(urldefrag(url)[0])
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.removesuffix(".printable").rstrip("/") or "/"
    query = "&".join(part for part in parsed.query.split("&") if part and not _VIEW_PARAMS.match(part.split("=")[0]))
    return host + path + ("?" + query if query else "")


class _WildcardRule(RuleLine):
    """robots.txt rule with the * and $ of Google's syntax (urllib.robotparser compares plain prefixes,
    so "Disallow: /*.html.printable" never matched)."""

    def __init__(self, rule: RuleLine):
        self.path, self.allowance = rule.path, rule.allowance
        pattern = re.escape(unquote(rule.path)).replace(r"\*", ".*")
        if pattern.endswith(r"\$"):
            pattern = pattern[:-2] + "$"
        self.regex = re.compile(pattern)

    def applies_to(self, filename: str) -> bool:
        return bool(self.regex.match(unquote(filename)))


def robots_parser(text: str) -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    for entry in parser.entries + ([parser.default_entry] if parser.default_entry else []):
        # Most specific rule first (Google: the longest matching rule wins)
        entry.rulelines = sorted((_WildcardRule(rule) for rule in entry.rulelines), key=lambda r: -len(r.path))
    return parser


def parse_sitemap(content: bytes):
    """Sitemap XML, gzipped or not; a stray non-UTF-8 byte made lxml drop all of Luleå's sitemap."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    content = re.sub(rb"^\s*<\?xml[^>]*\?>", b"", content).decode("utf-8", "replace").encode("utf-8")
    return etree.fromstring(content, parser=etree.XMLParser(recover=True))


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


def link_relevance(path: str, anchor: str) -> int:
    """Score of a link to a page. A negative word in the link text does not hide a section whose text is on
    topic: Surahammar's home card "Bygg, miljö och boende — Bygglov, ... detaljplaner, ... livsmedel" left the
    kommun with no page. A negative path (/nyheter/, /skola/) still excludes the link."""
    by_path = relevance(path)
    score = relevance(path, anchor)
    if by_path < 0 or score >= 0:
        return score
    positive = sum(weight for word, weight in _KEYWORDS.items() if word in fold(path + " " + anchor))
    return positive if positive >= KEEP_SCORE else score


# Site index pages: Härryda's section pages build their menus in JavaScript, its "Webbkarta" lists every page
_SITE_INDEX = re.compile(r"^(webbkarta|webbplatskarta|sitemap|site map|a-o|a-o index|innehall a-o|hitta a-o)$")


def site_section(url: str) -> str:
    return "/".join(urlparse(url).path.strip("/").split("/")[:3])


# A city's own top-level domain: start.stockholm, bygglov.stockholm and vaxer.stockholm (plans) are one site
_CITY_TLDS = {"stockholm"}


def base_domain(host: str) -> str:
    parts = host.lower().split(".")
    if parts[-1] in _CITY_TLDS:
        return parts[-1]
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
        self.domains = {base_domain(self.root.hostname or "")}
        self.out = WEB_DIR / kommun["code"]
        self.manifest = self.out / "manifest.jsonl.part"  # replaces manifest.jsonl when the crawl ends
        self.robots: dict[str, RobotFileParser | None] = {}
        self.seen: set[str] = set()
        self.queue: list[Task] = []
        self.pages = self.pdfs = self.pdf_bytes = 0
        self.stored_pages: set[str] = set()
        self.pdf_hashes: set[str] = set()
        self.page_hashes: set[str] = set()
        self.section_pages: dict[str, int] = {}
        self.skipped = {"duplicate": 0, "off_topic": 0, "too_big": 0}
        self.skipped_urls: set[str] = set()

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
                    parser = robots_parser(response.text)
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
                self.skipped["too_big"] += 1
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > stream_limit:
                    self.skipped["too_big"] += 1
                    return None
            response._content = bytes(body)
            return response

    # --- queueing -----------------------------------------------------------------

    def push(self, url: str, kind: str, score: int, anchor: str = "", source: str = "", depth: int = 0) -> None:
        url = urldefrag(url)[0]
        if url_key(url) in self.seen or not url.startswith("http"):
            return
        self.seen.add(url_key(url))
        heapq.heappush(self.queue, Task(-score, url, kind, anchor, source, depth))

    def is_internal(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == domain or host.endswith("." + domain) for domain in self.domains)

    async def resolve_root(self) -> None:
        """Follow the website's redirects first: angelholm.se -> engelholm.se left Ängelholm with no internal
        page; a home URL that moved (Mariestad's ".../Mariestads-kommun.html", 404) falls back to the host root,
        and an http:// address whose redirect fails (Ängelholm's malformed body, Gävle's 503) to https://."""
        host = self.root.hostname
        candidates = [self.root.geturl(), f"https://{host}/"] + ([f"http://{host}/"] if self.root.scheme == "http" else [])
        for url in dict.fromkeys(candidates):
            try:
                response = await self.get(url)
            except Exception as exc:  # network errors, and h11 errors httpx does not wrap
                self.log(f"home page {url}: {exc!r}")
                continue
            if response is not None and response.status_code < 400:
                self.root = urlparse(urldefrag(str(response.url))[0])
                self.domains.add(base_domain(self.root.hostname or ""))
                return

    async def seed_from_sitemaps(self) -> None:
        sitemap_urls = []
        try:
            robots = await self.get(f"{self.root.scheme}://{self.root.hostname}/robots.txt", check_robots=False)
        except Exception:
            robots = None
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
                tree = parse_sitemap(response.content)
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
                    if kind == "pdf" and off_topic_pdf(url):
                        self.skip_pdf(url, "", "sitemap")
                        continue
                    self.push(url, kind, score + 2, source="sitemap")
                    found += 1
        self.log(f"sitemaps: {visited} read, {found} relevant URLs")

    # --- processing ---------------------------------------------------------------

    def record(self, entry: dict) -> None:
        with self.manifest.open("a", encoding="utf-8") as manifest:
            manifest.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def skip_pdf(self, url: str, anchor: str, source: str) -> None:
        """An off-topic PDF link, recorded once (not downloaded; corpus.extract reads only "pdf" entries). Not added to
        `seen`: the same PDF linked elsewhere with a plan word in the link text is still taken."""
        if url_key(url) in self.skipped_urls:
            return
        self.skipped_urls.add(url_key(url))
        self.skipped["off_topic"] += 1
        self.record({"type": "skipped_pdf", "url": url, "anchor": anchor, "source": source})

    def take_pdf_link(self, url: str, anchor: str, page_score: int, source: str, depth: int,
                      plan_page: bool = False) -> None:
        # PDFs may live on another host (plan archive, GIS portal); keep those linked from relevant pages. A plan
        # page's attachments are named after the place or the step ("Lagakraftbevis", "Protokollsutdrag",
        # "1507-280-torsberg-139-mfl.pdf"), with no plan word or a negative one: until 2026-10-25 they were left out
        # (164 of the PDFs the coverage benchmark's municipalities list). A plan word outweighs a negative one
        # ("Planbeskrivning - Förskolan på norr")
        score = relevance(urlparse(url).path, anchor)
        if not plan_page and not _PLAN_WORDS.search(fold(unquote(urlparse(url).path) + " " + anchor)):
            if score < 0 or (score == 0 and page_score <= 0):
                return
            if score == 0 and not any(hint in fold(anchor + url) for hint in _PDF_HINTS):
                return
        if off_topic_pdf(url, anchor):
            self.skip_pdf(url, anchor, source)
            return
        self.push(url, "pdf", max(score, 1) + page_score // 2, anchor, source, depth)

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
        if not self.is_internal(final_url) or url_key(final_url) in self.stored_pages:
            return
        try:
            # The charset httpx found (header / detection), as for the text: lxml alone falls back to latin-1
            # when the HTML declares none, which garbled titles and link texts ("fÃ¶r")
            parser = lxml_html.HTMLParser(encoding=response.encoding or "utf-8")
            document = lxml_html.fromstring(response.content, base_url=final_url, parser=parser)
        except (etree.ParserError, ValueError):
            return
        title = " ".join((document.findtext(".//title") or "").split())
        page_score = relevance(urlparse(final_url).path, title)
        keep = content_relevance(urlparse(final_url).path, title) >= KEEP_SCORE

        if keep:
            text = trafilatura.extract(response.text, url=final_url, include_tables=True, favor_recall=True) or ""
            digest = hashlib.sha1(" ".join(text.split()).encode()).hexdigest()
            if digest in self.page_hashes:  # the same page under another URL: not stored, not counted
                self.skipped["duplicate"] += 1
                text = ""
            self.page_hashes.add(digest)
            if len(text) > 200:
                page_id = stable_id(final_url)
                (self.out / "pages").mkdir(parents=True, exist_ok=True)
                (self.out / "pages" / f"{page_id}.json").write_text(json.dumps({
                    "url": final_url, "title": title, "text": text, "score": page_score,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False), encoding="utf-8")
                self.record({"type": "page", "id": page_id, "url": final_url, "title": title, "score": page_score})
                self.pages += 1
                self.stored_pages.add(url_key(final_url))
                section = site_section(final_url)
                self.section_pages[section] = self.section_pages.get(section, 0) + 1

        # At the last depth only PDF links are taken: a plan list reached through a site index (Härryda, Surahammar)
        # sits at depth 4, and its PDFs were left out. A plan page at the last depth still gives its plan pages: a
        # list of plans in force there kept its plans out (Haparanda: 103 of the coverage benchmark's PDFs, 2026-10-25)
        follow_pages = task.depth < self.args.max_depth
        plan_page = bool(_PLAN_PAGE.search(fold(urlparse(final_url).path + " " + title)))
        for element in document.iter("a"):
            href = element.get("href")
            if not href:
                continue
            url = urljoin(final_url, href.strip())
            if _SKIP_EXTENSIONS.search(url):
                continue
            anchor = " ".join(element.text_content().split())[:200]
            if is_pdf_link(url):
                self.take_pdf_link(url, anchor, page_score, final_url, task.depth + 1, plan_page)
            elif self.is_internal(url) and (follow_pages or (
                    plan_page and task.depth == self.args.max_depth and _PLAN_PAGE.search(fold(urlparse(url).path)))):
                score = link_relevance(urlparse(url).path, anchor)
                if task.depth == 0 and _SITE_INDEX.match(fold(anchor)):
                    score = max(score, 5)
                # From the homepage, also follow navigation hubs with neutral scores
                if score > 0 or (task.depth == 0 and score == 0 and len(urlparse(url).path.strip("/").split("/")) <= 1):
                    self.push(url, "page", max(score, 1) + page_score // 3, anchor, final_url, task.depth + 1)

    async def store_pdf(self, task: Task, response=None) -> None:
        if self.pdfs >= self.args.max_pdfs:
            return
        pdf_id = stable_id(task.url)
        path = self.out / "pdf" / f"{pdf_id}.pdf"
        if path.exists():  # downloaded by an earlier pass
            content = path.read_bytes()
        else:
            if response is None or response.content is None:
                response = await self.get(task.url, stream_limit=self.args.max_pdf_mb * 1024 * 1024)
            if response is None or response.status_code != 200 or not response.content.startswith(b"%PDF"):
                return
            content = response.content
        # The same file under another URL (a /download/<id>/<timestamp>/ link per page, a copy of a national guide)
        digest = hashlib.sha1(content).hexdigest()
        if digest in self.pdf_hashes:
            self.skipped["duplicate"] += 1
            return
        self.pdf_hashes.add(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        size = len(content)
        self.record({"type": "pdf", "id": pdf_id, "url": task.url, "anchor": task.anchor,
                     "source": task.source, "bytes": size, "score": -task.priority})
        self.pdfs += 1
        self.pdf_bytes += size

    async def run(self) -> None:
        manifest = self.out / "manifest.jsonl"
        if manifest.exists() and not self.args.force:
            done = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if '"done": true' in line]
            # Skip unless this pass asks for more than the previous one (e.g. HTML-only first, then PDFs)
            if done and done[-1].get("max_pdfs", 0) >= self.args.max_pdfs \
                    and done[-1].get("max_pages", 0) >= self.args.max_pages:
                return
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest.unlink(missing_ok=True)
        started = time.monotonic()
        await self.resolve_root()
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
        old_items = sum(1 for line in manifest.read_text(encoding="utf-8").splitlines()
                        if '"type": "page"' in line or '"type": "pdf"' in line) \
            if manifest.exists() else 0
        if self.pages + self.pdfs == 0 and old_items:
            # Site down or blocking this time (Göteborg, Gävle...): keep the previous crawl
            self.manifest.unlink(missing_ok=True)
            self.log(f"nothing fetched ({fetched} requests): kept the previous crawl ({old_items} items)")
            return
        self.record({"done": True, "pages": self.pages, "pdfs": self.pdfs, "pdf_mb": round(self.pdf_bytes / 1e6, 1),
                     "requests": fetched, "seconds": round(time.monotonic() - started),
                     "queue_left": len(self.queue), "skipped": self.skipped,
                     "max_pdfs": self.args.max_pdfs, "max_pages": self.args.max_pages,
                     "max_pdf_mb": self.args.max_pdf_mb, "max_requests": self.args.max_requests,
                     "pdf_links": PDF_LINKS_VERSION})
        self.manifest.replace(manifest)
        self.log(f"done: {self.pages} pages, {self.pdfs} PDFs ({self.pdf_bytes / 1e6:.0f} MB), "
                 f"{fetched} requests, {len(self.queue)} left in the queue, skipped {self.skipped}, "
                 f"{time.monotonic() - started:.0f}s")

    async def revisit(self) -> None:
        """Re-read only the pages that linked the kommun's PDFs, its stored pages and its sitemaps, and add the PDF
        links the manifest lacks (refused by an older PDF list, left at the cap, published since), skipping the
        rest of the site: ~35k page requests for the country instead of ~160k for a full crawl. Pages that linked
        refused PDFs only and were neither stored nor a PDF source are not re-read. New PDFs are not deduplicated by
        content against the old ones (corpus.extract drops identical texts)."""
        manifest = self.out / "manifest.jsonl"
        lines = manifest.read_text(encoding="utf-8").splitlines() if manifest.exists() else []
        done = json.loads(lines[-1]) if lines and '"done": true' in lines[-1] else None
        if done is None or done.get("pdf_links", 1) >= PDF_LINKS_VERSION:
            return
        entries = [json.loads(line) for line in lines[:-1]]
        sources = []
        for entry in entries:
            if entry.get("type") == "pdf":
                self.seen.add(url_key(entry["url"]))
                self.pdfs += 1
                self.pdf_bytes += entry.get("bytes", 0)
                if entry.get("source") and entry["source"] != "sitemap":
                    sources.append(entry["source"])
            elif entry.get("type") == "page":
                self.pages += 1
                sources.append(entry["url"])
            elif entry.get("type") == "skipped_pdf":
                self.skipped_urls.add(url_key(entry["url"]))
        self.manifest.write_text("".join(line + "\n" for line in lines[:-1]), encoding="utf-8")
        started, before, fetched = time.monotonic(), self.pdfs, 0
        await self.resolve_root()
        await self.seed_from_sitemaps()
        self.queue = [task for task in self.queue if task.kind == "pdf"]  # sitemap pages: not re-read
        heapq.heapify(self.queue)
        for url in dict.fromkeys(sources):
            if fetched >= self.args.max_requests:
                break
            fetched += 1
            try:
                await self.pdf_links_of(url)
            except Exception as exc:
                if self.args.verbose:
                    self.log(f"error {url}: {exc!r}")
        while self.queue and self.pdfs < self.args.max_pdfs and fetched < self.args.max_requests:
            task = heapq.heappop(self.queue)
            fetched += 1
            try:
                await self.store_pdf(task)
            except Exception as exc:
                if self.args.verbose:
                    self.log(f"error {task.url}: {exc!r}")
        skipped = {**done.get("skipped", {}), "off_topic": len(self.skipped_urls)}
        self.record({**done, "pdfs": self.pdfs, "pdf_mb": round(self.pdf_bytes / 1e6, 1), "skipped": skipped,
                     "pdf_links": PDF_LINKS_VERSION,
                     "revisit": {"requests": fetched, "pdfs_added": self.pdfs - before,
                                 "seconds": round(time.monotonic() - started)}})
        self.manifest.replace(manifest)
        self.log(f"revisited {len(set(sources))} pages: {self.pdfs - before} PDFs added, "
                 f"{len(self.skipped_urls)} off-topic links recorded, {fetched} requests, "
                 f"{time.monotonic() - started:.0f}s")

    async def pdf_links_of(self, url: str) -> None:
        """The PDF links of one page, judged as in process_page (the page itself is not stored again)."""
        response = await self.get(url)
        if response is None or response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
            return
        final_url = urldefrag(str(response.url))[0]
        try:
            parser = lxml_html.HTMLParser(encoding=response.encoding or "utf-8")
            document = lxml_html.fromstring(response.content, base_url=final_url, parser=parser)
        except (etree.ParserError, ValueError):
            return
        title = " ".join((document.findtext(".//title") or "").split())
        page_score = relevance(urlparse(final_url).path, title)
        plan_page = bool(_PLAN_PAGE.search(fold(urlparse(final_url).path + " " + title)))
        for element in document.iter("a"):
            href = element.get("href")
            if not href:
                continue
            link = urljoin(final_url, href.strip())
            if is_pdf_link(link) and not _SKIP_EXTENSIONS.search(link):
                self.take_pdf_link(link, " ".join(element.text_content().split())[:200], page_score, final_url, 1,
                                   plan_page)


async def crawl(municipalities: list[dict], args) -> None:
    limiter = HostLimiter(args.delay)
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "sv,en;q=0.5"},
        timeout=httpx.Timeout(30, read=60),
        follow_redirects=True,
        # Windows' certificate store fetches missing intermediates (Högsby); HTTP/2 avoids Malmö's HTTP/1.1
        # "multiple Transfer-Encoding headers" that h11 rejects
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        http2=True,
        limits=httpx.Limits(max_connections=args.concurrency * 2),
    ) as client:

        async def one(kommun):
            async with semaphore:
                try:
                    crawler = KommunCrawler(kommun, client, limiter, args)
                    await (crawler.revisit() if args.revisit else crawler.run())
                except Exception as exc:
                    print(f"[{kommun['code']}] failed: {exc!r}", flush=True)

        await asyncio.gather(*(one(kommun) for kommun in municipalities))


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl municipal websites for planning documents")
    parser.add_argument("--codes", nargs="*", help="kommun codes (default: all)")
    parser.add_argument("--concurrency", type=int, default=12, help="kommuner crawled in parallel")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one host")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES, help="HTML pages kept per kommun")
    parser.add_argument("--max-pdfs", type=int, default=MAX_PDFS, help="PDFs kept per kommun")
    parser.add_argument("--max-pdf-mb", type=int, default=MAX_PDF_MB)
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS, help="requests per kommun (1 per second per host)")
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="re-crawl kommuner already done")
    parser.add_argument("--revisit", action="store_true",
                        help="only re-read the pages that linked PDFs and add the PDF links a manifest older than "
                             "PDF_LINKS_VERSION lacks (no full crawl)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    municipalities = json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))
    if args.codes:
        municipalities = [m for m in municipalities if m["code"] in set(args.codes)]
    asyncio.run(crawl([m for m in municipalities if m.get("website")], args))


if __name__ == "__main__":
    main()
