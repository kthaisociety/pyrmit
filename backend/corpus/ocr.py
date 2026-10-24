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
# One process: on real plan pages two were 34 % slower in total and three 50 % (8 GB of GPU memory; small benchmark
# crops had shown +28 %, so measure on real pages)
WORKERS = 1
OCR_PYTHON = BACKEND_DIR / ".venv-ocr" / "Scripts" / "python.exe"
JOBS_PATH = DATA_DIR / "ocr_jobs.jsonl"
# Tiers of the scans by what they bring, OCRed in this order (every page; --max-tier stops after a tier)
TIERS = {1: "plan maps and provisions", 2: "plan texts (descriptions, consultation reports)",
         3: "other planning types (översiktsplan, avlopp, bygglov, strandskydd, taxa)",
         4: "studies attached to plans (noise, soil, stormwater, traffic...)", 5: "other"}
MAX_TIER = 5


# Scans typed "other" that are plan documents (2026-10-24: 2.1k of 3.8k): the current doc_type rules (_PB / _PK
# archive codes, byggnadsplan) apply at the next extract; these words (Huddinge's "Bestämmelse0126k-7018",
# samrådsredogörelse, illustrationskarta...) are not in them
PLAN_WORDS = re.compile(r"beskrivning|bestämmelse|planhandling|plankarta|illustrationsplan|illustrationskarta|"
                        r"grundkarta|nybyggnadskarta|stadsplan|byggnadsplan|områdesplan|\bädp\b|samrådsredogörelse|"
                        r"granskningsutlåtande|planuppdrag|planprogram|teckenförklaring|genomförande", re.I)


MAP_WORDS = re.compile(r"plankarta|karta|bestämmelse|_pk\b|_pk[._ -]|illustration", re.I)
STUDY_WORDS = re.compile(r"utredning|\bpm\b|rapport|buller|geotek|dagvatten|skyfall|översvämning|trafik|inventering|"
                         r"\bmkb\b|miljökonsekvens|dagsljus|solstudie|vindstudie|\brisk|markmiljö|naturvärde|arkeolog|"
                         r"kulturmiljö|parkering|lokalklimat", re.I)


def large_first_page(path) -> bool:
    """A sheet larger than A3 (a map), the way ocr_engines renders it at the map resolution."""
    import pymupdf

    try:
        with pymupdf.open(path) as pdf:
            return len(pdf) > 0 and max(pdf[0].rect.width, pdf[0].rect.height) > 1200
    except Exception:
        return False


def ocr_tier(document: dict, large: bool) -> int:
    """TIERS key of a scan: plan documents (also those typed "other") are maps / provisions, studies or texts."""
    kind = document.get("doc_type")
    text = f"{document.get('title') or ''} {document.get('url') or ''}"
    if kind == "other" and (doc_type(text) == "detaljplan" or PLAN_WORDS.search(text)):
        kind = "detaljplan"
    if kind == "detaljplan":
        if STUDY_WORDS.search(text) and not MAP_WORDS.search(text):
            return 4
        return 1 if large or MAP_WORDS.search(text) else 2
    return 5 if kind == "other" else 3


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR scanned PDFs flagged by corpus.extract")
    parser.add_argument("--max-docs", type=int, default=0, help="0 = all")
    parser.add_argument("--kommuner", nargs="*")
    parser.add_argument("--engine", default=ENGINE)
    parser.add_argument("--cpu", action="store_true", help="no GPU (about 6x slower)")
    parser.add_argument("--det-side", type=int, default=DET_SIDE,
                        help="longest side of the detection input (0 = whole 2000 px tile)")
    parser.add_argument("--workers", type=int, default=WORKERS, help="OCR processes sharing the GPU")
    parser.add_argument("--max-tier", type=int, default=MAX_TIER,
                        help="last tier to OCR: " + "; ".join(f"{k} {v}" for k, v in TIERS.items()))
    args = parser.parse_args()

    if not OCR_PYTHON.exists():
        sys.exit(f"{OCR_PYTHON} is missing: see the install line in corpus/ocr_engines.py")
    # Scans without text, and scans OCRed earlier (their text is in documents.jsonl; the engine is checked by the
    # worker, which skips its own outputs)
    todo = [d for d in read_jsonl(DOCUMENTS_PATH) if d["kind"] == "pdf" and (d.get("needs_ocr") or d.get("ocr"))]
    if args.kommuner:
        todo = [d for d in todo if d["kommun_code"] in set(args.kommuner)]
    # By tier (TIERS), short documents first within one; outputs to redo (lines cut by a tile edge kept from both
    # tiles until 2026-10-24, no "text_from") after the PDFs of their tier not read yet
    for document in todo:
        _, code, pdf_id = document["doc_id"].split(":")
        document["_pdf"] = WEB_DIR / code / "pdf" / f"{pdf_id}.pdf"
        document["_tier"] = ocr_tier(document, large_first_page(document["_pdf"]))
        out = WEB_DIR / code / "ocr" / f"{pdf_id}.json"
        document["_redo"] = out.exists() and b'"text_from"' not in out.open("rb").read(300)
    counts = {tier: sum(1 for d in todo if d["_tier"] == tier) for tier in TIERS}
    todo = sorted((d for d in todo if d["_tier"] <= args.max_tier),
                  key=lambda d: (d["_tier"], d["_redo"], d.get("pages") or 0))
    if args.max_docs:
        todo = todo[:args.max_docs]
    with JOBS_PATH.open("w", encoding="utf-8") as handle:
        for document in todo:
            handle.write(json.dumps({
                "pdf": str(document["_pdf"]), "out": str(document["_pdf"].parent.parent / "ocr" / f"{document['_pdf'].stem}.json"),
                "max_pages": None, "tier": document["_tier"],
                "label": f"{document['kommun']} – {document['title']}",
            }, ensure_ascii=False) + "\n")
    print("scans per tier: " + "; ".join(f"{t} {TIERS[t].split(' (')[0]}: {n}" for t, n in counts.items()), flush=True)
    print(f"{len(todo)} scanned PDFs (tiers 1-{args.max_tier}) -> {JOBS_PATH}", flush=True)
    command = [str(OCR_PYTHON), str(BACKEND_DIR / "corpus" / "ocr_engines.py"), "--engine", args.engine,
               "--jobs", str(JOBS_PATH), "--det-side", str(args.det_side)] + ([] if args.cpu else ["--gpu"])
    # The .venv interpreter sets PYTHONHOME to its own base Python (3.13): inherited, it made .venv-ocr's 3.12 load
    # the 3.13 standard library ("SRE module mismatch")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "__PYVENV_LAUNCHER__")}
    workers = [subprocess.Popen(command + ["--shard", f"{i}/{args.workers}"], cwd=BACKEND_DIR, env=env)
               for i in range(args.workers)]
    sys.exit(max(worker.wait() for worker in workers))


if __name__ == "__main__":
    main()
