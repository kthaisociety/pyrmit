"""
OCR of the scanned PDFs (no text layer, flagged `needs_ocr` by corpus.extract): mostly old plans, whose rules are
printed on the plankarta itself, and old planbeskrivningar. Writes raw/web/<code>/ocr/<pdf id>.json (the text of
each page + every word with its box in PDF coordinates); the next `corpus.extract` uses the text.

Engine: PP-OCRv6 medium (RapidOCR, ONNX, on DirectML) chosen on corpus.ocr_bench (real map crops: 87 % of the words
and 8 of 13 property labels read, EasyOCR 69 % and 0). It runs in backend/.venv-ocr (see corpus/ocr_engines.py):
this module picks the PDFs and starts it. PDFs OCRed by another engine (EasyOCR until 2026-10-23, no word boxes)
are redone. Resumable: stop it any time, the next run skips what this engine already did.

    cd backend && python -m corpus.ocr --max-docs 20
    then corpus.extract, corpus.pdf_filter features/classify/llm/classify/apply, corpus.chunk, localrag.index,
    localrag.store, corpus.plans
"""

import argparse
import json
import os
import subprocess
import sys

from corpus.common import BACKEND_DIR, DATA_DIR, DOCUMENTS_PATH, WEB_DIR, read_jsonl

ENGINE = "rapid-v6-medium"
OCR_PYTHON = BACKEND_DIR / ".venv-ocr" / "Scripts" / "python.exe"
JOBS_PATH = DATA_DIR / "ocr_jobs.jsonl"
MAX_PAGES = 40   # long scanned reports: OCR the first pages only


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR scanned PDFs flagged by corpus.extract")
    parser.add_argument("--max-docs", type=int, default=0, help="0 = all")
    parser.add_argument("--kommuner", nargs="*")
    parser.add_argument("--engine", default=ENGINE)
    parser.add_argument("--cpu", action="store_true", help="no GPU (about 6x slower)")
    args = parser.parse_args()

    if not OCR_PYTHON.exists():
        sys.exit(f"{OCR_PYTHON} is missing: see the install line in corpus/ocr_engines.py")
    # Scans without text, and scans OCRed earlier (their text is in documents.jsonl; the engine is checked by the
    # worker, which skips its own outputs)
    todo = [d for d in read_jsonl(DOCUMENTS_PATH) if d["kind"] == "pdf" and (d.get("needs_ocr") or d.get("ocr"))]
    if args.kommuner:
        todo = [d for d in todo if d["kommun_code"] in set(args.kommuner)]
    # Hours of work: detaljplaner first (plankartor are the point, ~31 h), then the other planning types (~6 h), the
    # "other" scans last (~30 h, decisions and studies of unknown value: the run can stop before them); short documents
    # first within a group
    todo.sort(key=lambda d: (d.get("doc_type") != "detaljplan", d.get("doc_type") == "other", d.get("pages") or 0))
    if args.max_docs:
        todo = todo[:args.max_docs]
    with JOBS_PATH.open("w", encoding="utf-8") as handle:
        for document in todo:
            _, code, pdf_id = document["doc_id"].split(":")
            handle.write(json.dumps({
                "pdf": str(WEB_DIR / code / "pdf" / f"{pdf_id}.pdf"), "out": str(WEB_DIR / code / "ocr" / f"{pdf_id}.json"),
                "max_pages": MAX_PAGES, "label": f"{document['kommun']} – {document['title']}",
            }, ensure_ascii=False) + "\n")
    print(f"{len(todo)} scanned PDFs -> {JOBS_PATH}", flush=True)
    command = [str(OCR_PYTHON), str(BACKEND_DIR / "corpus" / "ocr_engines.py"), "--engine", args.engine,
               "--jobs", str(JOBS_PATH)] + ([] if args.cpu else ["--gpu"])
    # The .venv interpreter sets PYTHONHOME to its own base Python (3.13): inherited, it made .venv-ocr's 3.12 load
    # the 3.13 standard library ("SRE module mismatch")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "__PYVENV_LAUNCHER__")}
    sys.exit(subprocess.run(command, cwd=BACKEND_DIR, env=env).returncode)


if __name__ == "__main__":
    main()
