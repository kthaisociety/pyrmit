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
import re
import subprocess
import sys

from corpus.common import BACKEND_DIR, DATA_DIR, DOCUMENTS_PATH, WEB_DIR, read_jsonl
from corpus.extract import doc_type

ENGINE = "rapid-v6-medium"
ENGINE_FAMILY = "rapid-v6"  # an output of any PP-OCRv6 setting counts as done (corpus/ocr_engines.py run_jobs)
# Detection input of a 2000 px tile capped at 1280 px (recognition still reads full-resolution crops): 25 % faster,
# the same words and property labels on the benchmark's synthetic maps (139 vs 140 of 305); 0 = whole tile.
# small (-32 %) loses 14 % of the labels and 5 points on text pages; float16 models are no faster on DirectML
DET_SIDE = 1280
OCR_PYTHON = BACKEND_DIR / ".venv-ocr" / "Scripts" / "python.exe"
JOBS_PATH = DATA_DIR / "ocr_jobs.jsonl"
MAX_PAGES = 40   # long scanned reports: OCR the first pages only


# Scans typed "other" that are plan documents (2026-10-24: 2.1k of 3.8k): the current doc_type rules (_PB / _PK
# archive codes, byggnadsplan) apply at the next extract; these words (Huddinge's "Bestämmelse0126k-7018",
# samrådsredogörelse, illustrationskarta...) are not in them
PLAN_WORDS = re.compile(r"beskrivning|bestämmelse|planhandling|plankarta|illustrationsplan|illustrationskarta|"
                        r"grundkarta|nybyggnadskarta|stadsplan|byggnadsplan|områdesplan|\bädp\b|samrådsredogörelse|"
                        r"granskningsutlåtande|planuppdrag|planprogram|teckenförklaring|genomförande", re.I)


def ocr_group(document: dict) -> int:
    """0 = detaljplan (also plan documents typed "other"), 1 = other planning types, 2 = other."""
    kind = document.get("doc_type")
    text = f"{document.get('title') or ''} {document.get('url') or ''}"
    if kind == "other" and (doc_type(text) == "detaljplan" or PLAN_WORDS.search(text)):
        kind = "detaljplan"
    return 0 if kind == "detaljplan" else 2 if kind == "other" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR scanned PDFs flagged by corpus.extract")
    parser.add_argument("--max-docs", type=int, default=0, help="0 = all")
    parser.add_argument("--kommuner", nargs="*")
    parser.add_argument("--engine", default=ENGINE)
    parser.add_argument("--cpu", action="store_true", help="no GPU (about 6x slower)")
    parser.add_argument("--det-side", type=int, default=DET_SIDE,
                        help="longest side of the detection input (0 = whole 2000 px tile)")
    args = parser.parse_args()

    if not OCR_PYTHON.exists():
        sys.exit(f"{OCR_PYTHON} is missing: see the install line in corpus/ocr_engines.py")
    # Scans without text, and scans OCRed earlier (their text is in documents.jsonl; the engine is checked by the
    # worker, which skips its own outputs)
    todo = [d for d in read_jsonl(DOCUMENTS_PATH) if d["kind"] == "pdf" and (d.get("needs_ocr") or d.get("ocr"))]
    if args.kommuner:
        todo = [d for d in todo if d["kommun_code"] in set(args.kommuner)]
    # Hours of work: detaljplaner first (plankartor are the point), then the other planning types, the "other" scans last
    # (studies, guidelines, permit drawings: the run can stop before them); short documents first within a group
    todo.sort(key=lambda d: (ocr_group(d), d.get("pages") or 0))
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
               "--jobs", str(JOBS_PATH), "--det-side", str(args.det_side)] + ([] if args.cpu else ["--gpu"])
    # The .venv interpreter sets PYTHONHOME to its own base Python (3.13): inherited, it made .venv-ocr's 3.12 load
    # the 3.13 standard library ("SRE module mismatch")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "__PYVENV_LAUNCHER__")}
    sys.exit(subprocess.run(command, cwd=BACKEND_DIR, env=env).returncode)


if __name__ == "__main__":
    main()
