"""
Coverage benchmark: how many of the detailed plans a municipality publishes are in the corpus.

The other benchmarks are built from documents of the corpus (their evidence, their generated cases), so a plan the
crawl never fetched cannot appear in them: a missing plan costs nothing in their scores. This one starts from
outside the corpus: each sampled municipality's own list of plans in force, fetched live, and for each listed plan
the PDFs its page links to. The score is the share of those PDFs (and of plans with at least one PDF) found in the
corpus (documents.jsonl, matched by URL).

    cd backend
    python -m agentic.coverage sample      # pick municipalities and their list page -> agentic/coverage_sources.jsonl
    python -m agentic.coverage fetch       # live: list -> plan pages -> their PDF links -> agentic/coverage_plans.jsonl
    python -m agentic.coverage score       # against the current corpus -> data/agentic/coverage-<date>.json

`fetch` makes ~25 requests per municipality (1 every 2 s per host: a crawl may run at the same time). The
reference (coverage_plans.jsonl) is versioned with its fetch date; re-fetch it when the sites change.
"""

import argparse
import asyncio
import json
import random
import re
import ssl
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse

import httpx
import truststore
from lxml import html as lxml_html

from corpus.common import DOCUMENTS_PATH, MUNICIPALITIES_PATH, USER_AGENT, read_jsonl
from corpus.crawl import off_topic_pdf, robots_parser, url_key

HERE = Path(__file__).resolve().parent
SOURCES_PATH = HERE / "coverage_sources.jsonl"
PLANS_PATH = HERE / "coverage_plans.jsonl"
RESULTS_DIR = HERE.parent / "data" / "agentic"
SAMPLE = 30
PLANS_PER_KOMMUN = 20  # listed plans fetched per municipality (a random sample of the list)
DELAY = 2.0
LIST_PAGE = re.compile(r"g[aä]llande[ -]?detaljplaner|antagna[ -]?detaljplaner|laga[ -]?kraft", re.I)


def sample(seed: int) -> None:
    """Municipalities with a page listing their plans in force (found among the crawled pages), stratified by
    how many documents the corpus has for them (small / medium / large)."""
    lists, docs = defaultdict(set), defaultdict(int)
    for doc in read_jsonl(DOCUMENTS_PATH):
        if not doc.get("kommun_code"):
            continue
        docs[doc["kommun_code"]] += 1
        if doc["kind"] != "page":
            continue
        url = urldefrag(doc["url"])[0].split("?")[0].removesuffix(".printable")
        last = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        # The list itself ("gallande-detaljplaner"), not a plan under it nor a map of the plans
        if LIST_PAGE.search(last) and "karta" not in last.lower():
            lists[doc["kommun_code"]].add(url)
    names = {m["code"]: m["short_name"] for m in json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))}
    candidates = sorted(lists, key=lambda code: docs[code])
    thirds = [candidates[i * len(candidates) // 3:(i + 1) * len(candidates) // 3] for i in range(3)]
    rng = random.Random(seed)
    chosen = [code for third in thirds for code in rng.sample(third, SAMPLE // 3)]
    with SOURCES_PATH.open("w", encoding="utf-8") as out:
        for code in chosen:
            url = min(lists[code], key=len)  # the list itself, not one plan under it
            out.write(json.dumps({"kommun_code": code, "kommun": names.get(code), "list_url": url},
                                 ensure_ascii=False) + "\n")
    print(f"{len(chosen)} municipalities -> {SOURCES_PATH} (check each list_url by hand)")


class Fetcher:
    def __init__(self, client: httpx.AsyncClient):
        self.client, self.last, self.robots = client, {}, {}

    async def get(self, url: str):
        host = urlparse(url).hostname or ""
        if host not in self.robots:
            try:
                response = await self.client.get(f"https://{host}/robots.txt")
                self.robots[host] = robots_parser(response.text) if response.status_code == 200 else None
            except Exception:  # h2 errors are not wrapped in httpx.HTTPError
                self.robots[host] = None
        if self.robots[host] is not None and not self.robots[host].can_fetch(USER_AGENT, url):
            return None
        pause = self.last.get(host, 0) + DELAY - time.monotonic()
        if pause > 0:
            await asyncio.sleep(pause)
        self.last[host] = time.monotonic()
        try:
            return await self.client.get(url)
        except Exception:
            return None


def links(response) -> list[tuple[str, str]]:
    document = lxml_html.fromstring(response.content, base_url=str(response.url),
                                    parser=lxml_html.HTMLParser(encoding=response.encoding or "utf-8"))
    out = []
    for element in document.iter("a"):
        href = element.get("href")
        if href and not href.startswith(("mailto:", "tel:", "javascript:")):
            out.append((urldefrag(urljoin(str(response.url), href.strip()))[0], " ".join(element.text_content().split())))
    return out


PLAN_WORDS = re.compile(r"detaljplan|områdesbestämmelse|omradesbestammelse|stadsplan|byggnadsplan|\bdp[ -]?\d|"
                        r"ändring av|andring-av|plan för|plan-for", re.I)
NAV_WORDS = re.compile(r"^(hoppa|gå till|till innehåll|meny|startsida|tillbaka|skriv ut|dela|lyssna)", re.I)
# A link naming one plan: "Detaljplan för ...", "Ändring av detaljplan ...", a property designation ("Vi 3:54")
ONE_PLAN = re.compile(r"detaljplan för|ändring av|ändring genom|upphävande|områdesbestämmelser för|\b\d+:\d+\b|"
                      r"\bdp[ -]?\d|\bp\d{2,}", re.I)
# Pages about plans in general, not one plan
GENERIC = re.compile(r"^(ansök|begär|om |vad |hur |så |planprocess|pågående|gällande|antagna|aktuella|detaljplaner\b|"
                     r"detaljplanering|utanför|hålla djur|kontrollplan|planbesked|planprogram|översiktsplan)", re.I)
MAX_PLAN_PDFS = 40  # a page linking more PDFs is a list, not one plan
# A PDF of a plan (not a guide on how to read plans)
PLAN_DOCUMENT = re.compile(r"plankarta|planbeskrivning|planbestämmelse|detaljplan|\bdp\b|-dp-|granskning|antagande|"
                           r"samråd|genomförande|\b\d+[:.]\d+\b|\b\d{2}-[a-zåäö]{2,4}-\d+", re.I)


def is_pdf(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf") or "/download/" in url.lower()


def maybe_document(url: str) -> bool:
    """Episerver "/link/<id>.aspx" and "/globalassets/" links often redirect to a PDF: resolved by a request."""
    lower = url.lower()
    return bool(re.search(r"/link/[0-9a-f]{32}\.aspx", lower)) or "/globalassets/" in lower


async def documents_of(fetcher: Fetcher, found: list[tuple[str, str]]) -> list[str]:
    """The PDF links of a plan page, with "/link/" redirects resolved (kept under the URL the page links to,
    as the crawler stores it, and under the final URL)."""
    pdfs = [u for u, a in found if is_pdf(u) and not off_topic_pdf(u, a)]
    for url, anchor in found[:60]:
        if maybe_document(url) and not is_pdf(url) and PLAN_WORDS.search(anchor + " " + url) is not None:
            response = await fetcher.get(url)
            if response is not None and "pdf" in response.headers.get("content-type", ""):
                pdfs.append(url + " -> " + str(response.url))
    return list(dict.fromkeys(pdfs))


def plan_links(listing, found: list[tuple[str, str]]) -> dict:
    """Links of a list page that lead to plans: under the list's path, or naming a plan, on the same site."""
    base = urlparse(str(listing.url)).path.rstrip("/").rsplit(".", 1)[0]
    host = (urlparse(str(listing.url)).hostname or "").removeprefix("www.")
    entries = {}
    for url, anchor in found:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").rsplit(".", 1)[0]
        same_site = (parsed.hostname or "").removeprefix("www.") == host
        if (not anchor or NAV_WORDS.match(anchor) or not same_site or is_pdf(url) or maybe_document(url)
                or path == base or base.startswith(path)):
            continue
        # Under the list's path: a plan or a group of plans ("Detaljplaner 2021"); elsewhere: a link naming one plan
        if path.startswith(base + "/") or (ONE_PLAN.search(anchor) and not GENERIC.match(anchor)):
            entries.setdefault(url_key(url), (url, anchor))
    return entries


async def fetch_kommun(fetcher: Fetcher, source: dict, rng: random.Random) -> list[dict]:
    """The plans listed on the municipality's page: a PDF linked from the list is a plan document; a page under the
    list's path or naming a plan is a plan page, or a group of plans (Östhammar: list -> area -> plan): one more level."""
    listing = await fetcher.get(source["list_url"])
    if listing is None or listing.status_code != 200 or "html" not in listing.headers.get("content-type", ""):
        print(f"[{source['kommun']}] list page unreachable")
        return [_unmeasured(source, "list page unreachable")]
    found = links(listing)
    pdfs_on_list = [(u, a) for u, a in found if is_pdf(u) and not off_topic_pdf(u, a)
                    and PLAN_DOCUMENT.search(a + " " + unquote(u.rsplit("/", 1)[-1]))]
    entries = plan_links(listing, found)
    plans = [{"plan": anchor, "plan_url": None, "pdfs": [url]} for url, anchor in pdfs_on_list]
    pages = list(entries.values())
    rng.shuffle(pages)
    visited, groups = 0, 0
    while pages and visited < PLANS_PER_KOMMUN * 3:
        if len([p for p in plans if p["plan_url"]]) >= PLANS_PER_KOMMUN:
            break
        url, anchor = pages.pop(0)
        visited += 1
        response = await fetcher.get(url)
        if response is None or response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
            continue
        page_links = links(response)
        pdfs = await documents_of(fetcher, page_links)
        if 0 < len(pdfs) <= MAX_PLAN_PDFS:
            plans.append({"plan": anchor, "plan_url": str(response.url), "pdfs": pdfs})
        elif groups < 5:  # a group of plans: its plan links go to the front of the queue
            groups += 1
            more = [e for k, e in plan_links(response, page_links).items() if k not in entries]
            entries.update({url_key(u): (u, a) for u, a in more})
            rng.shuffle(more)
            pages = more + pages
    rng.shuffle(plans)
    # A list of PDFs (Hallsberg, Mullsjö) or a list of plan pages, whichever gave more plans
    with_page = [p for p in plans if p["plan_url"]]
    plans = (with_page if len(with_page) >= len(pdfs_on_list) else [p for p in plans if not p["plan_url"]])
    plans = plans[:PLANS_PER_KOMMUN]
    print(f"[{source['kommun']}] {len(entries)} plan pages and {len(pdfs_on_list)} PDFs listed, {visited} visited, "
          f"{len(plans)} plans kept")
    if not plans:
        # The page only points to a map or search application: the plans are out of reach of a crawler
        return [_unmeasured(source, "no plan with a PDF reachable from the list page (map or search application)")]
    return [{**plan, "kommun_code": source["kommun_code"], "kommun": source["kommun"], "list_url": source["list_url"],
             "listed_pages": len(entries), "listed_pdfs": len(pdfs_on_list)} for plan in plans]


def _unmeasured(source: dict, note: str) -> dict:
    return {"plan": None, "plan_url": None, "pdfs": [], "kommun_code": source["kommun_code"], "kommun": source["kommun"],
            "list_url": source["list_url"], "note": note}


async def fetch_all(seed: int) -> None:
    sources = list(read_jsonl(SOURCES_PATH))
    fetched_at = datetime.now(timezone.utc).date().isoformat()
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept-Language": "sv,en;q=0.5"},
                                 timeout=httpx.Timeout(30, read=60), follow_redirects=True,
                                 verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as client:
        fetcher = Fetcher(client)
        results = await asyncio.gather(*(fetch_kommun(fetcher, s, random.Random(f"{seed}{s['kommun_code']}"))
                                         for s in sources))
    with PLANS_PATH.open("w", encoding="utf-8") as out:
        for rows in results:
            for row in rows:
                out.write(json.dumps({**row, "fetched_at": fetched_at}, ensure_ascii=False) + "\n")
    print(f"{sum(len(r) for r in results)} plans -> {PLANS_PATH}")


def score() -> dict:
    corpus_pdfs, corpus_pages = {}, set()
    for doc in read_jsonl(DOCUMENTS_PATH):
        if doc["kind"] == "pdf" and doc.get("url"):
            corpus_pdfs[url_key(doc["url"])] = doc["doc_id"]
        elif doc["kind"] == "page":
            corpus_pages.add(url_key(doc["url"]))
    rows = list(read_jsonl(PLANS_PATH))
    unmeasured = {row["kommun"]: row["note"] for row in rows if row["plan"] is None}
    # One or two "plans" are a guide or a process page linked from the list (Solna, Hallstahammar), not a sample
    counts = defaultdict(int)
    for row in rows:
        counts[row["kommun"]] += row["plan"] is not None
    for kommun, count in counts.items():
        if 0 < count < 3:
            unmeasured[kommun] = f"only {count} plan(s) with a PDF reachable from the list page"
    rows = [row for row in rows if row["kommun"] not in unmeasured]
    by_kommun = defaultdict(list)
    for row in rows:
        if row["plan"] is None:
            continue
        found = [url for url in row["pdfs"] if any(url_key(u) in corpus_pdfs for u in url.split(" -> "))]
        by_kommun[row["kommun"]].append({
            "plan": row["plan"], "pdfs": len(row["pdfs"]), "found": len(found),
            "page_found": bool(row["plan_url"]) and url_key(row["plan_url"]) in corpus_pages})
    table = {}
    print(f"{'municipality':<16} {'plans':>5} {'with a PDF':>11} {'all PDFs':>9} {'PDFs found':>11} {'plan page':>10}")
    for kommun, plans in sorted(by_kommun.items()):
        pdfs, found = sum(p["pdfs"] for p in plans), sum(p["found"] for p in plans)
        table[kommun] = {"plans": len(plans), "plans_with_a_pdf": sum(p["found"] > 0 for p in plans),
                         "plans_complete": sum(p["found"] == p["pdfs"] for p in plans),
                         "pdfs": pdfs, "pdfs_found": found, "plan_pages_found": sum(p["page_found"] for p in plans)}
        t = table[kommun]
        print(f"{kommun:<16} {t['plans']:>5} {t['plans_with_a_pdf'] / t['plans']:>11.0%} "
              f"{t['plans_complete'] / t['plans']:>9.0%} {found / max(pdfs, 1):>11.0%} "
              f"{t['plan_pages_found'] / t['plans']:>10.0%}")
    plans = [p for ps in by_kommun.values() for p in ps]
    total = {"plans": len(plans), "plans_with_a_pdf": sum(p["found"] > 0 for p in plans) / max(len(plans), 1),
             "plans_complete": sum(p["found"] == p["pdfs"] for p in plans) / max(len(plans), 1),
             "pdfs_found": sum(p["found"] for p in plans) / max(sum(p["pdfs"] for p in plans), 1),
             "municipalities": len(by_kommun), "unmeasured": len(unmeasured),
             "reference_fetched": rows[0]["fetched_at"] if rows else None}
    print(f"\nall: {total['plans']} plans in {total['municipalities']} municipalities; at least one PDF in the corpus "
          f"{total['plans_with_a_pdf']:.0%}, all PDFs {total['plans_complete']:.0%}; PDFs found {total['pdfs_found']:.0%}")
    for kommun, note in sorted(unmeasured.items()):
        print(f"not measurable: {kommun}: {note}")
    out = RESULTS_DIR / f"coverage-{date.today():%Y%m%d}.json"
    out.write_text(json.dumps({"total": total, "by_kommun": table, "unmeasured": unmeasured}, ensure_ascii=False,
                              indent=1), encoding="utf-8")
    print(f"-> {out}")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Coverage of the municipalities' plans in the corpus")
    parser.add_argument("step", choices=["sample", "fetch", "score"])
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.step == "sample":
        sample(args.seed)
    elif args.step == "fetch":
        asyncio.run(fetch_all(args.seed))
    else:
        score()


if __name__ == "__main__":
    main()
