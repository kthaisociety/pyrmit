"""
Download Mark- och miljööverdomstolen precedents (MÖD) from lagen.nu: real permit decisions with
facts, outcome and reasons, used to build the agent's case benchmark (agentic/cases_from_caselaw.py).

lagen.nu's robots.txt allows the case pages; 1 request/s, resumable (cases already saved are skipped).

    cd backend && python -m corpus.caselaw                 # MÖD 2011- (the current PBL, 2010:900)
    python -m corpus.caselaw --since 2016 --limit 20
"""

import argparse
import html
import json
import re
import time

import httpx

from corpus.common import RAW_DIR, USER_AGENT, clean_text, read_jsonl

CASELAW_PATH = RAW_DIR / "caselaw" / "mod.jsonl"
SITEMAPS = [f"https://lagen.nu/sitemap-{i}.xml" for i in range(1, 10)]

# Keywords (Sökord) or headnote words marking a case about what Pyrmit covers
TOPICS = ("förhandsbesked", "bygglov", "strandskydd", "detaljplan", "planbesked", "avlopp", "sammanhållen bebyggelse",
          "liten avvikelse", "planenlig", "jordbruksmark", "bygglovsbefri", "attefall", "marklov", "rivningslov",
          "lokaliseringsprövning", "byggnadsnämnd", "vattentjänst", "fastighetsbildning", "anmälan", "kulturhistori")


def _text(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S)
    fragment = re.sub(r"</(p|h\d|li|dd|dt|div)>|<br\s*/?>", "\n", fragment)
    return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def parse_case(url: str, page: str) -> dict:
    meta = dict(re.findall(r"<dt>(.*?)</dt><dd>(.*?)</dd>", page))
    meta_at = page.find('<dl class="meta"')
    header_end = page.find("</header>", meta_at)
    # The headnote: "<rubrik> ----- <summary>", the paragraph just before the metadata list
    headnote = _text(page[page.rfind("<p", 0, meta_at):meta_at])
    title, _, summary = headnote.partition("-----")
    sokord = re.search(r'class="sokord".*?</p>', page, re.S)
    keywords = re.findall(r'<a href="/begrepp/[^"]*">(.*?)</a>', sokord.group(0)) if sokord else []
    body = page[header_end + len("</header>"):]
    body = body[:body.find("<footer")] if "<footer" in body else body
    text = _text(body)
    text = re.sub(r"\n(Innehåll Sök Kontext|Innehåll)\s*$", "", text)
    lagrum = re.search(r"\nLagrum\n(.+)$", text, re.S)
    source = re.search(r'href="(https://rattspraxis[^"]+)"', page)
    return {
        "id": url.rsplit("/", 1)[-1].replace(":", "-"),
        "reference": "MÖD " + url.rsplit("/", 1)[-1],
        "url": url,
        "source_url": source.group(1) if source else None,
        "date": _text(meta.get("Avgörandedatum", "")),
        "case_number": _text(meta.get("Målnummer", "")),
        "title": clean_text(title),
        "summary": clean_text(summary),
        "keywords": [html.unescape(k) for k in keywords],
        "statutes": clean_text(lagrum.group(1)) if lagrum else "",
        "text": text,
    }


def relevant(case: dict) -> bool:
    haystack = " ".join([case["title"], case["summary"], " ".join(case["keywords"])]).lower()
    return any(topic in haystack for topic in TOPICS)


def case_urls(client: httpx.Client, since: int) -> list[str]:
    urls = []
    for sitemap in SITEMAPS:
        urls += re.findall(r"https://lagen\.nu/dom/mod/(\d{4}):(\d+)", client.get(sitemap).text)
        time.sleep(1)
    unique = sorted({(int(y), int(n)) for y, n in urls if int(y) >= since})
    return [f"https://lagen.nu/dom/mod/{y}:{n}" for y, n in unique]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download MÖD precedents from lagen.nu")
    parser.add_argument("--since", type=int, default=2011)
    parser.add_argument("--limit", type=int, default=0, help="stop after this many new downloads (0: all)")
    args = parser.parse_args()

    done = {row["url"] for row in read_jsonl(CASELAW_PATH)} if CASELAW_PATH.exists() else set()
    CASELAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client, \
            CASELAW_PATH.open("a", encoding="utf-8") as out:
        todo = [url for url in case_urls(client, args.since) if url not in done]
        print(f"{len(done)} cases saved, {len(todo)} to fetch")
        fetched = kept = 0
        for url in todo:
            if args.limit and fetched >= args.limit:
                break
            try:
                response = client.get(url)
                response.raise_for_status()
                case = parse_case(url, response.text)
            except Exception as exc:  # one bad page must not stop the run
                print(f"  {url}: {exc}")
                time.sleep(1)
                continue
            case["relevant"] = relevant(case)
            out.write(json.dumps(case, ensure_ascii=False) + "\n")
            out.flush()
            fetched += 1
            kept += case["relevant"]
            if fetched % 50 == 0:
                print(f"  {fetched}/{len(todo)} fetched, {kept} relevant")
            time.sleep(1)
    print(f"done: {fetched} fetched, {kept} relevant -> {CASELAW_PATH}")


if __name__ == "__main__":
    main()
