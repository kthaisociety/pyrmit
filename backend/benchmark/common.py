"""Shared helpers for the embedding benchmark: paths, corpus/question loading, relevance matching."""

import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = Path(__file__).resolve().parent
CORPUS_PATH = BENCHMARK_DIR / "data" / "corpus.jsonl"
CACHE_DIR = BENCHMARK_DIR / "cache"
RESULTS_DIR = BENCHMARK_DIR / "results"
MODELS_PATH = BENCHMARK_DIR / "models.toml"
QUESTIONS_PATH = BENCHMARK_DIR / "questions.jsonl"

sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

# Windows consoles default to cp1252 and choke on Swedish characters
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

_MATCHER_KEYS = {"source", "chapter", "section", "chunk_index", "contains", "any"}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip() and not line.lstrip().startswith("//")]


def load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        raise SystemExit(f"{CORPUS_PATH} missing: run `python -m benchmark.export_corpus` first")
    corpus = read_jsonl(CORPUS_PATH)
    for chunk in corpus:
        chunk["_normalized"] = normalize(chunk["content"])
    return corpus


def matches(chunk: dict, matcher: dict) -> bool:
    """A matcher is a dict of required fields; `contains` is a verbatim excerpt (or a list of them),
    compared case- and whitespace-insensitively so labels survive re-chunking.
    `any` holds alternative matchers, for a fact stated in several places."""
    if "any" in matcher:
        return any(matches(chunk, alternative) for alternative in matcher["any"])
    unknown = set(matcher) - _MATCHER_KEYS
    if unknown:
        raise ValueError(f"Unknown matcher keys {unknown} in {matcher}")
    for key in ("source", "chapter", "section", "chunk_index"):
        if key in matcher and str(chunk.get(key)) != str(matcher[key]):
            return False
    excerpts = matcher.get("contains", [])
    if isinstance(excerpts, str):
        excerpts = [excerpts]
    normalized = chunk.get("_normalized") or normalize(chunk["content"])
    return all(normalize(excerpt) in normalized for excerpt in excerpts)


def relevant_sets(question: dict, corpus: list[dict]) -> list[set[int]]:
    """For each matcher of the question, the corpus indexes (within the question's table) it matches."""
    return [
        {index for index, chunk in enumerate(corpus) if chunk["table"] == question["table"] and matches(chunk, matcher)}
        for matcher in question["relevant"]
    ]
