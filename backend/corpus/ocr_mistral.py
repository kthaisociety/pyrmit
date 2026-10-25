"""
OCR with Mistral's API (mistral-ocr-latest) for the scanned PDFs of some kommuner: a PDF whose text layer has fewer
than 150 characters a page (corpus.extract's needs_ocr rule) is sent page by page, and its text is written to
raw/web/<code>/ocr/<pdf id>.json, the file corpus.extract reads, as corpus.ocr (local EasyOCR, needs a GPU) does.
Paid (about $1 per 1,000 pages); `--max-pages` stops before a budget is spent. Already OCR'd PDFs are skipped.

    cd backend && python -m corpus.ocr_mistral --kommuner 0380 --max-pages 3000
"""

import argparse
import base64
import json
import os
import time
from pathlib import Path

from corpus.common import WEB_DIR, read_jsonl

MIN_CHARS_PER_PAGE = 150  # as corpus.extract: below this a PDF counts as scanned
MAX_PAGES_PER_PDF = 40    # as corpus.ocr: long scanned reports, the first pages only
MODEL = "mistral-ocr-latest"


def needs_ocr(path: Path) -> tuple[bool, int]:
    """(scanned, page count) of a PDF, by the characters of its text layer."""
    import pymupdf

    with pymupdf.open(path) as pdf:
        chars = sum(len(page.get_text()) for page in pdf)
        return chars / max(pdf.page_count, 1) < MIN_CHARS_PER_PAGE, pdf.page_count


def scanned_pdfs(codes: list[str], web_dir: Path = WEB_DIR) -> list[tuple[Path, Path, int]]:
    """(pdf, ocr output, pages) of the scanned PDFs of the kommuner's crawls that have no OCR output yet, shortest
    first (plankartor are mostly one page)."""
    todo = []
    for code in codes:
        folder = web_dir / code
        for entry in read_jsonl(folder / "manifest.jsonl"):
            if entry.get("type") != "pdf":
                continue
            pdf, out = folder / "pdf" / f"{entry['id']}.pdf", folder / "ocr" / f"{entry['id']}.json"
            if pdf.exists() and not out.exists():
                try:
                    scanned, pages = needs_ocr(pdf)
                except RuntimeError:  # an unreadable PDF
                    continue
                if scanned:
                    todo.append((pdf, out, pages))
    return sorted(dict.fromkeys(todo), key=lambda item: item[2])


def ocr_pdf(client, pdf: Path, pages: int) -> list[str]:
    """The markdown text of each of the PDF's `pages` (the first MAX_PAGES_PER_PDF)."""
    data = base64.b64encode(pdf.read_bytes()).decode()
    response = client.ocr.process(model=MODEL, include_image_base64=False,
                                  pages=list(range(min(pages, MAX_PAGES_PER_PDF))),
                                  document={"type": "document_url", "document_url": f"data:application/pdf;base64,{data}"})
    return [page.markdown for page in response.pages]


def main() -> None:
    from dotenv import load_dotenv
    from mistralai.client import Mistral

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    parser = argparse.ArgumentParser(description="OCR scanned PDFs with Mistral's API")
    parser.add_argument("--kommuner", nargs="+", required=True)
    parser.add_argument("--max-pages", type=int, default=3000, help="stop before OCR'ing more pages than this")
    args = parser.parse_args()

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    todo = scanned_pdfs(args.kommuner)
    print(f"{len(todo)} scanned PDFs, {sum(min(p, MAX_PAGES_PER_PDF) for _, _, p in todo)} pages to OCR", flush=True)
    done_pages = 0
    for index, (pdf, out, pages) in enumerate(todo, start=1):
        if done_pages + min(pages, MAX_PAGES_PER_PDF) > args.max_pages:
            print(f"stopping: --max-pages {args.max_pages} reached")
            break
        started = time.perf_counter()
        try:
            texts = ocr_pdf(client, pdf, pages)
        except Exception as exc:  # one failing PDF must not stop the batch; it stays without OCR
            print(f"[{index}/{len(todo)}] {pdf.name}: failed ({type(exc).__name__}: {str(exc)[:120]})", flush=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"pages": texts, "engine": MODEL}, ensure_ascii=False), encoding="utf-8")
        done_pages += len(texts)
        if index % 25 == 0 or index == len(todo):
            print(f"[{index}/{len(todo)}] {done_pages} pages, last {pdf.name} {sum(map(len, texts))} chars "
                  f"in {time.perf_counter() - started:.1f}s", flush=True)
    print(f"OCR'd {done_pages} pages")


if __name__ == "__main__":
    main()
