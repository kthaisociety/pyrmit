"""
Local OCR (EasyOCR, Swedish + English, GPU) for scanned PDFs that have no text layer,
mostly old plankartor: extract.py flags them `needs_ocr`, this step writes their text to
raw/web/<code>/ocr/<pdf id>.json, and the next `corpus.extract` uses it.

OCR only recovers the words (legend, zone codes, heights, property names). What a plan
says spatially (which zone has which height) needs a vision model looking at the page.

    cd backend && python -m corpus.ocr --max-docs 20
"""

import argparse
import json
import time

from corpus.common import DOCUMENTS_PATH, WEB_DIR, read_jsonl

TILE = 2000      # pixels; large-format plans are cut into overlapping tiles
OVERLAP = 150
MAX_PAGES = 40   # long scanned reports: OCR the first pages only


def ocr_page(reader, page, dpi: int) -> str:
    import numpy as np

    pixmap = page.get_pixmap(dpi=dpi)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)[:, :, :3]
    lines = []
    for top in range(0, max(image.shape[0] - OVERLAP, 1), TILE - OVERLAP):
        for left in range(0, max(image.shape[1] - OVERLAP, 1), TILE - OVERLAP):
            tile = image[top:top + TILE, left:left + TILE]
            for _, text, confidence in reader.readtext(tile, paragraph=False):
                if confidence >= 0.3 and len(text.strip()) > 1:
                    lines.append(text.strip())
    # Tiles overlap: drop exact repeats while keeping reading order
    return "\n".join(dict.fromkeys(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR scanned PDFs flagged by corpus.extract")
    parser.add_argument("--max-docs", type=int, default=0, help="0 = all")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--kommuner", nargs="*")
    args = parser.parse_args()

    import easyocr
    import pymupdf

    reader = easyocr.Reader(["sv", "en"], gpu=True)
    todo = [d for d in read_jsonl(DOCUMENTS_PATH) if d.get("needs_ocr")]
    if args.kommuner:
        todo = [d for d in todo if d["kommun_code"] in set(args.kommuner)]
    # Hours of work: detaljplaner first (plankartor are the point), short documents first within a type
    todo.sort(key=lambda d: (d.get("doc_type") != "detaljplan", d.get("pages") or 0))
    if args.max_docs:
        todo = todo[:args.max_docs]

    for index, document in enumerate(todo, start=1):
        _, code, pdf_id = document["doc_id"].split(":")
        out = WEB_DIR / code / "ocr" / f"{pdf_id}.json"
        if out.exists():
            continue
        started = time.perf_counter()
        pdf = pymupdf.open(WEB_DIR / code / "pdf" / f"{pdf_id}.pdf")
        pages = [ocr_page(reader, page, args.dpi) for page in list(pdf)[:MAX_PAGES]]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"pages": pages, "dpi": args.dpi, "engine": "easyocr sv+en"}, ensure_ascii=False),
                       encoding="utf-8")
        print(f"[{index}/{len(todo)}] {document['kommun']} – {document['title'][:60]}: "
              f"{sum(len(p) for p in pages)} chars, {time.perf_counter() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
