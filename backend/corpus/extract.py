"""
Turn every raw source into one text document in data/corpus/documents.jsonl.

  - laws:   raw/laws/*.txt (Riksdagen)
  - pages:  raw/web/<code>/pages/*.json (crawled HTML, main text by trafilatura)
  - pdfs:   raw/web/<code>/pdf/*.pdf, text extracted locally with PyMuPDF. Scanned PDFs
            (almost no text layer) are kept with needs_ocr=true and no text: OCR them
            later (Mistral OCR is paid, Tesseract is free but needs installing).
  - legacy: the Vallentuna documents already in the database, rebuilt from
            benchmark/data/corpus.jsonl (python -m benchmark.export_corpus)

    cd backend && python -m corpus.extract
"""

import argparse
import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from urllib.parse import unquote

from corpus.common import DOCUMENTS_PATH, LAWS_DIR, MUNICIPALITIES_PATH, WEB_DIR, clean_text, read_jsonl, write_jsonl
from corpus.crawl import KEEP_SCORE, content_relevance, fold

LEGACY_CORPUS = Path(__file__).resolve().parent.parent / "benchmark" / "data" / "corpus.jsonl"
LEGACY_TITLES = {
    "2040vision": "Översiktsplan Vallentuna 2040 (samrådshandling 2017)",
    "samrad_2040": "Samrådsredogörelse, översiktsplan Vallentuna 2040",
    "miljoe_miljoe": "Miljökonsekvensbeskrivning, översiktsplan Vallentuna",
    "moerby_backe": "Detaljplan Vallentuna-Mörby (Mörby backe), planbeskrivning",
    "kristineberg_etapp1": "Detaljplan Kristineberg etapp 1, plan- och genomförandebeskrivning",
    "kristineberg_etapp2": "Startpromemoria detaljplan Kristineberg etapp 2",
    "kumla_stensta": "Detaljplan Kumla-Stensta, planbeskrivning",
}

# Document type from URL / title / link text, first match wins
_DOC_TYPES = [
    ("oversiktsplan", ("oversiktsplan", "fordjupad oversikt", "fop", "op20", "op-20")),
    ("detaljplan", ("detaljplan", "planbeskrivning", "plankarta", "planbestammelse", "genomforandebeskrivning",
                    "planprogram", "omradesbestammelse", "startpromemoria", "dp-", "dp_")),
    ("taxa", ("taxa", "avgift")),
    ("avlopp", ("avlopp", "va-plan", "vatten och avlopp", "vatten-och-avlopp", "dagvatten")),
    ("bygglov", ("bygglov", "forhandsbesked", "attefall", "startbesked", "rivningslov", "marklov", "anmalan")),
    ("strandskydd", ("strandskydd",)),
]


def doc_type(*texts: str) -> str:
    haystack = fold(" ".join(texts))
    for name, words in _DOC_TYPES:
        if any(word in haystack for word in words):
            return name
    return "other"


def law_documents() -> list[dict]:
    index = json.loads((LAWS_DIR / "index.json").read_text(encoding="utf-8"))
    return [
        {
            "doc_id": f"law:{law['slug']}",
            "kind": "law",
            "doc_type": "lag",
            "kommun_code": None,
            "kommun": None,
            "title": law["title"],
            "url": law["url"],
            "text": (LAWS_DIR / f"{law['slug']}.txt").read_text(encoding="utf-8"),
        }
        for law in index
    ]


def page_documents(names: dict[str, str]) -> list[dict]:
    documents = []
    for path in sorted(WEB_DIR.glob("*/pages/*.json")):
        code = path.parent.parent.name
        page = json.loads(path.read_text(encoding="utf-8"))
        if content_relevance(page["url"].split("/", 3)[-1], page["title"]) < KEEP_SCORE:
            continue  # kept by an older, looser crawl filter
        documents.append({
            "doc_id": f"page:{code}:{path.stem}",
            "kind": "page",
            "doc_type": doc_type(page["url"], page["title"]),
            "kommun_code": code,
            "kommun": names.get(code),
            "title": page["title"],
            "url": page["url"],
            "text": clean_text(page["text"]),
        })
    return documents


_PAGE_NUMBER = re.compile(r"^((page|sida|s\.)\s*)?\d{1,3}(\s*(of|av|/)\s*\d{1,3})?$", re.I)


def page_blocks(page) -> list[str]:
    """Text blocks of a page (roughly paragraphs), with wrapped lines and hyphenation rejoined."""
    blocks = []
    for block in page.get_text("blocks", sort=True):
        if block[6] != 0:  # image block
            continue
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", block[4].strip())
        text = " ".join(text.split())
        if text:
            blocks.append(text)
    return blocks


def strip_boilerplate(pages: list[list[str]]) -> list[str]:
    """Drop running headers/footers (blocks repeated on many pages) and page numbers."""
    counts: dict[str, int] = {}
    for blocks in pages:
        for block in set(blocks):
            counts[block] = counts.get(block, 0) + 1
    threshold = max(3, len(pages) * 0.3)
    repeated = {block for block, count in counts.items() if count >= threshold and len(block) < 150}
    return [
        "\n\n".join(block for block in blocks if block not in repeated and not _PAGE_NUMBER.match(block))
        for blocks in pages
    ]


def _pdf_document(args: tuple[str, str, dict, str | None]) -> dict:
    path, code, entry, kommun = args
    import pymupdf  # imported in the worker

    try:
        pdf = pymupdf.open(path)
    except Exception as exc:
        return {"doc_id": f"pdf:{code}:{entry['id']}", "error": repr(exc)}
    pages = [page_blocks(page) for page in pdf]
    text = clean_text("\n\n".join(strip_boilerplate(pages)))
    chars_per_page = len(text) / max(len(pages), 1)
    title = (pdf.metadata or {}).get("title") or ""
    # Metadata titles are often file paths ("G:\SBF\...") or template names
    if (not title or len(title) < 4 or "\\" in title or re.fullmatch(r"[\w\-]+\.(docx?|indd|pdf)", title, re.I)
            or title.lower() in {"djvu-dokument", "untitled", "microsoft word"}):
        title = entry.get("anchor") or unquote(Path(entry["url"].split("?")[0]).stem)
    needs_ocr = chars_per_page < 150
    ocr_path = Path(path).parent.parent / "ocr" / f"{entry['id']}.json"
    ocr = needs_ocr and ocr_path.exists()
    if ocr:  # written by corpus.ocr
        text = clean_text("\n\n".join(json.loads(ocr_path.read_text(encoding="utf-8"))["pages"]))
        needs_ocr = False
    return {
        "doc_id": f"pdf:{code}:{entry['id']}",
        "kind": "pdf",
        "doc_type": doc_type(entry["url"], entry.get("anchor", ""), title, text[:600]),
        "kommun_code": code,
        "kommun": kommun,
        "title": " ".join(title.split())[:200],
        "url": entry["url"],
        "source_page": entry.get("source"),
        "pages": len(pages),
        "needs_ocr": needs_ocr,
        "ocr": ocr,
        "text": "" if needs_ocr else text,
    }


def pdf_documents(names: dict[str, str], workers: int) -> list[dict]:
    jobs = []
    for manifest in sorted(WEB_DIR.glob("*/manifest.jsonl")):
        code = manifest.parent.name
        for entry in read_jsonl(manifest):
            if entry.get("type") == "pdf":
                path = manifest.parent / "pdf" / f"{entry['id']}.pdf"
                if path.exists():
                    jobs.append((str(path), code, entry, names.get(code)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        documents = list(pool.map(_pdf_document, jobs, chunksize=4))
    errors = [d for d in documents if "error" in d]
    if errors:
        print(f"  {len(errors)} unreadable PDFs skipped")
    return [d for d in documents if "error" not in d]


def legacy_documents() -> list[dict]:
    if not LEGACY_CORPUS.exists():
        return []
    by_source: dict[str, list[dict]] = {}
    for row in read_jsonl(LEGACY_CORPUS):
        if row["table"] == "document":
            by_source.setdefault(row["source"], []).append(row)
    documents = []
    for source, rows in sorted(by_source.items()):
        rows.sort(key=lambda row: row["chunk_index"] or 0)
        parts, last_section = [], None
        for row in rows:
            match = re.match(r"Section: ([^\n]*)\n\n?(.*)", row["content"], re.S)
            section, body = (match.group(1), match.group(2)) if match else (None, row["content"])
            if section and section != last_section:
                parts.append(f"## {section.split(' > ')[-1]}")
                last_section = section
            if body.strip():
                parts.append(body.strip())
        documents.append({
            "doc_id": f"legacy:{source}",
            "kind": "pdf",
            "doc_type": doc_type(LEGACY_TITLES.get(source, source)),
            "kommun_code": "0115",
            "kommun": "Vallentuna",
            "title": LEGACY_TITLES.get(source, source),
            "url": None,
            "text": clean_text("\n\n".join(parts)),
        })
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text documents from the raw corpus")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    names = {m["code"]: m["short_name"] for m in json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))}
    documents = law_documents() + legacy_documents() + page_documents(names) + pdf_documents(names, args.workers)
    count = write_jsonl(DOCUMENTS_PATH, documents)
    by_kind: dict[str, int] = {}
    for document in documents:
        by_kind[document["kind"]] = by_kind.get(document["kind"], 0) + 1
    ocr = sum(1 for d in documents if d.get("needs_ocr"))
    print(f"{count} documents {by_kind}, {ocr} scanned PDFs need OCR -> {DOCUMENTS_PATH}")


if __name__ == "__main__":
    main()
