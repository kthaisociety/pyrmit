"""
Corpus snapshot of a few kommuner plus the statutes: a self-contained CORPUS_DATA_DIR (chunks, documents, plan
registry, gazetteer) for demos and the Neon demo branch. Its corpus/raw is a junction to the full corpus's raw folder,
so the PDFs and OCR outputs are the same files.

    cd backend && python -m corpus.snapshot --kommuner 0380 0115 0180 --out data/demo
    CORPUS_DATA_DIR=data/demo python -m localrag.index --model st-bge-m3     # then localrag.store as usual
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from corpus.common import BACKEND_DIR, write_jsonl

SOURCE = BACKEND_DIR / "data" / "corpus"


def _rows(path: Path, kommuner: set[str], with_laws: bool):
    """Rows of a corpus JSONL file for these kommuner (and the statutes); the raw line is tested first, because
    parsing the 3.5 GB chunks file line by line takes minutes."""
    keys = [f'"kommun_code": "{code}"' for code in kommuner] + (['"kind": "law"'] if with_laws else [])
    with path.open(encoding="utf-8") as file:
        for line in file:
            if any(key in line for key in keys):
                row = json.loads(line)
                if row.get("kommun_code") in kommuner or (with_laws and row.get("kind") == "law"):
                    yield row


def _link(target: Path, link: Path) -> None:
    """Directory junction on Windows (no admin rights needed), symlink elsewhere."""
    if link.exists() or link.is_symlink():
        return
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def build(kommuner: list[str], out: Path) -> None:
    wanted = set(kommuner)
    corpus = out / "corpus"
    for name in ("chunks.jsonl", "documents.jsonl"):
        print(f"{name}: {write_jsonl(corpus / name, _rows(SOURCE / name, wanted, with_laws=True))} rows", flush=True)
    plans = write_jsonl(corpus / "plans.jsonl", _rows(SOURCE / "plans.jsonl", wanted, with_laws=False))
    print(f"plans.jsonl: {plans} plans")
    shutil.copy2(SOURCE / "municipalities.json", corpus / "municipalities.json")
    _link(SOURCE / "raw", corpus / "raw")
    print(f"Snapshot -> {out} (set CORPUS_DATA_DIR={out.relative_to(BACKEND_DIR).as_posix()})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Corpus snapshot of a few kommuner + the statutes")
    parser.add_argument("--kommuner", nargs="+", required=True, help="kommun codes, e.g. 0380 0115 0180")
    parser.add_argument("--out", default="data/demo", help="snapshot directory, relative to backend/")
    args = parser.parse_args()
    build(args.kommuner, BACKEND_DIR / args.out)


if __name__ == "__main__":
    main()
