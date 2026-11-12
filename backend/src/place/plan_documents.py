"""
The documents of every plan in a kommun's snapshot, into the corpus crawl: each plan's document link (Uppsala's
UrlDokument, the plan's page on uppsala.se) is opened, the page kept and its PDFs (plankarta, planbeskrivning, ...)
downloaded into data/corpus/raw/web/<code>/ in the crawler's format, so corpus.extract, corpus.ocr_mistral,
corpus.chunk, localrag.index, localrag.store and corpus.plans pick them up. The crawl of 2026-10-08 stopped at 60 PDFs
for Uppsala, so the corpus held none of most plans' provisions.

The plan page each aktbeteckning leads to is saved in data/geo/<code>/plan_pages.json ({aktbeteckning: page url}):
place.profile matches a snapshot plan to its corpus plan through that page, not by name. One request a second;
resumable (plans already in plan_pages.json and in the manifest are skipped).

The new entries go before the manifest's {"done": true} line, which must stay last: `corpus.crawl --revisit` reads the
last line, and a manifest not ending with it is skipped. The manifest and plan_pages.json are rewritten together every
25 plans. A plan whose page the manifest lacks (a later `corpus.crawl --force` rewrote it) is fetched again and
recorded; its PDFs are already on disk.

    cd backend && python -m place.plan_documents --kommun 0380 [--limit 50]
"""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx

from corpus.common import WEB_DIR, stable_id
from place.sources import USER_AGENT
from place.store import GEO_DIR

PLAN_LAYERS = ("plans", "plan_additions", "area_regulations")
MAX_PDF_MB = 40
DELAY_S = 1.0
SCORE = 30  # above the crawl's plan pages: these are the plans in force


def plan_links(code: str, geo_dir: Path = GEO_DIR) -> dict[str, str]:
    """{aktbeteckning: document link} of every plan, tillägg and områdesbestämmelse in the kommun's snapshot."""
    links = {}
    for layer in PLAN_LAYERS:
        path = geo_dir / code / f"{layer}.geojson"
        if path.exists():
            for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
                props = feature["properties"]
                if props.get("Aktbeteckning") and props.get("UrlDokument"):
                    links.setdefault(props["Aktbeteckning"], props["UrlDokument"])
    return links


def pdf_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """(absolute url, link text) of the page's PDF links, each once."""
    from lxml import html as lxml_html

    document = lxml_html.fromstring(html, base_url=base_url)
    found = {}
    for anchor in document.iter("a"):
        href = anchor.get("href") or ""
        if ".pdf" in href.lower().split("?")[0]:
            found.setdefault(urljoin(base_url, href), " ".join(anchor.text_content().split()))
    return list(found.items())


def read_manifest(manifest: Path) -> tuple[list[str], str | None]:
    """The manifest's entry lines and its done line, wherever it is (until 2026-10-25 this module appended after it)."""
    lines = manifest.read_text(encoding="utf-8").splitlines() if manifest.exists() else []
    done = [line for line in lines if '"done": true' in line]
    return [line for line in lines if line and '"done": true' not in line], (done[-1] if done else None)


class _Throttle:
    def __init__(self, delay: float):
        self.delay, self.last = delay, 0.0

    def wait(self) -> None:
        pause = self.delay - (time.monotonic() - self.last)
        if pause > 0:
            time.sleep(pause)
        self.last = time.monotonic()


def fetch_plan_documents(code: str, *, limit: int | None = None, client: httpx.Client | None = None,
                         web_dir: Path = WEB_DIR, geo_dir: Path = GEO_DIR, delay: float = DELAY_S) -> dict:
    """Fetch the page and PDFs of every plan of kommun `code` not fetched yet (at most `limit` plans), adding them
    to the kommun's crawl manifest. Returns {"plans", "pages", "pdfs", "skipped_pdfs", "errors"}."""
    import trafilatura

    out, mapping_path = web_dir / code, geo_dir / code / "plan_pages.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
    manifest = out / "manifest.jsonl"
    lines, done = read_manifest(manifest)
    known = {json.loads(line).get("id") for line in lines}
    todo = [(ref, url) for ref, url in plan_links(code, geo_dir).items()
            if ref not in mapping or stable_id(mapping[ref]) not in known][:limit]
    counts = {"plans": 0, "pages": 0, "pdfs": 0, "skipped_pdfs": 0, "errors": 0}
    throttle = _Throttle(delay)
    http = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "pdf").mkdir(parents=True, exist_ok=True)

    def record(entry: dict) -> None:
        if entry["id"] not in known:
            known.add(entry["id"])
            lines.append(json.dumps(entry, ensure_ascii=False))

    def save() -> None:
        """The manifest (entries, then the done line), then the plan pages: a plan saved in plan_pages.json but not
        in the manifest would never be recorded."""
        if lines or done:
            temp = manifest.with_name("manifest.jsonl.tmp")
            temp.write_text("".join(line + "\n" for line in lines + ([done] if done else [])), encoding="utf-8")
            temp.replace(manifest)
        if mapping:
            mapping_path.parent.mkdir(parents=True, exist_ok=True)
            mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=0), encoding="utf-8")

    try:
        for ref, link in todo:
            try:
                throttle.wait()
                response = http.get(link)
                response.raise_for_status()
            except httpx.HTTPError:
                counts["errors"] += 1
                continue
            page_url = str(response.url)
            page_id = stable_id(page_url)
            title = ""
            try:
                from lxml import html as lxml_html
                title = " ".join((lxml_html.fromstring(response.text).findtext(".//title") or "").split())
            except ValueError:
                pass
            text = trafilatura.extract(response.text, url=page_url, include_tables=True, favor_recall=True) or ""
            if page_id not in known:
                (out / "pages" / f"{page_id}.json").write_text(json.dumps(
                    {"url": page_url, "title": title, "text": text, "score": SCORE}, ensure_ascii=False), encoding="utf-8")
                counts["pages"] += 1
            record({"type": "page", "id": page_id, "url": page_url, "title": title, "score": SCORE})
            for pdf_url, anchor in pdf_links(response.text, page_url):
                pdf_id = stable_id(pdf_url)
                path = out / "pdf" / f"{pdf_id}.pdf"
                if not path.exists():
                    try:
                        throttle.wait()
                        pdf = http.get(pdf_url)
                        pdf.raise_for_status()
                    except httpx.HTTPError:
                        counts["errors"] += 1
                        continue
                    if not pdf.content.startswith(b"%PDF") or len(pdf.content) > MAX_PDF_MB * 1024 * 1024:
                        counts["skipped_pdfs"] += 1
                        continue
                    path.write_bytes(pdf.content)
                    counts["pdfs"] += 1
                record({"type": "pdf", "id": pdf_id, "url": pdf_url, "anchor": anchor, "source": page_url,
                        "bytes": path.stat().st_size, "score": SCORE})
            mapping[ref] = page_url
            counts["plans"] += 1
            if counts["plans"] % 25 == 0:
                save()
                print(f"  {counts['plans']}/{len(todo)} plans, {counts['pdfs']} PDFs", flush=True)
    finally:
        save()
        if client is None:
            http.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the documents of every plan in a kommun's snapshot")
    parser.add_argument("--kommun", default="0380")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(fetch_plan_documents(args.kommun, limit=args.limit))


if __name__ == "__main__":
    main()
