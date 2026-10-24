"""Paths and small helpers shared by the corpus steps."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")
# Benchmark results and evals (data/agentic, data/eval, versioned) stay here whatever corpus is selected
RESULTS_ROOT = BACKEND_DIR / "data"
# Corpus snapshot: corpus/ + index/ under CORPUS_DATA_DIR (relative to backend/), default backend/data. The small
# corpus of 2026-10-22 (7.8k PDFs, kept for demos) is data/small; its corpus/raw is a junction to data/corpus/raw
DATA_ROOT = BACKEND_DIR / os.getenv("CORPUS_DATA_DIR", "data")
DATA_DIR = DATA_ROOT / "corpus"
INDEX_DIR = DATA_ROOT / "index"
RAW_DIR = DATA_DIR / "raw"
LAWS_DIR = RAW_DIR / "laws"
WEB_DIR = RAW_DIR / "web"
MUNICIPALITIES_PATH = DATA_DIR / "municipalities.json"
DOCUMENTS_PATH = DATA_DIR / "documents.jsonl"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"

USER_AGENT = "PyrmitCorpusBuilder/0.1 (research prototype on Swedish planning documents)"

sys.path.insert(0, str(BACKEND_DIR))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def stable_id(*parts: str, length: int = 16) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:length]


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


# UTF-8 bytes read as latin-1 or cp1252: "fÃ¶r" for "för", "â" / "â€“" for "–", "ÃŒP" for "ÖP"
_CP1252 = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
_MOJIBAKE_RUN = re.compile(f"[\xc2-\xf4][\x80-\xbf{_CP1252}]+")


def _byte(char: str) -> bytes:
    return char.encode("cp1252") if char in _CP1252 else char.encode("latin-1")


def repair_mojibake(text: str) -> str:
    """Undo UTF-8 decoded as latin-1 / cp1252 (page titles, link texts and PDF metadata titles)."""
    if not text:
        return text
    # "Å" is C3 85 and 0x85 (a control character in latin-1) became a space: "Ã rsta" for "Årsta"
    text = re.sub(r"Ã (?=[a-zåäö])", "Å", text)
    if not _MOJIBAKE_RUN.search(text):
        return text

    def decode(match: re.Match) -> str:
        try:
            return b"".join(_byte(char) for char in match.group()).decode("utf-8")
        except UnicodeDecodeError:
            return match.group()

    return _MOJIBAKE_RUN.sub(decode, text)


def clean_text(text: str) -> str:
    """Normalise whitespace while keeping paragraph breaks."""
    text = text.replace("\r", "").replace("­", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
