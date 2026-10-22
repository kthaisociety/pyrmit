"""
Embed the corpus chunks with a local model and keep the vectors on disk.

Vectors are stored per model in data/index/dense/<model>/ (float16 matrix + chunk ids) and
grow incrementally: re-running after a new crawl only embeds the chunks not seen yet, and re-embeds in place a
chunk whose embedded text changed (digests.json: a hash of the header + text; chunk ids only hash the text, so a
re-chunk that fixes a header, e.g. a chapter label, keeps the id).

    cd backend
    python -m localrag.index --model st-bge-m3                  # all chunks
    python -m localrag.index --model st-bge-m3 --kommuner 0115  # laws + one kommun only
"""

import argparse
import hashlib
import json
import time
import tomllib
from pathlib import Path

import numpy as np

from corpus.common import CHUNKS_PATH, DATA_DIR, read_jsonl
from embeddings import EmbeddingConfig, Embedder

INDEX_DIR = DATA_DIR.parent / "index"
MODELS_PATH = Path(__file__).resolve().parent / "models.toml"


def chunk_text(chunk: dict) -> str:
    """What gets embedded and BM25-indexed: the context header, then the chunk."""
    return f"{chunk['header']}\n\n{chunk['text']}"


def text_digest(chunk: dict) -> str:
    return hashlib.sha1(chunk_text(chunk).encode()).hexdigest()[:16]


def load_chunks(kommuner: list[str] | None = None, path: Path = CHUNKS_PATH) -> list[dict]:
    chunks = list(read_jsonl(path))
    if kommuner:
        wanted = set(kommuner)
        chunks = [c for c in chunks if c["kind"] == "law" or c.get("kommun_code") in wanted]
    return chunks


def load_model_config(name: str) -> EmbeddingConfig:
    with MODELS_PATH.open("rb") as file:
        entry = tomllib.load(file)["models"][name]
    fields = {key: value for key, value in entry.items() if key not in {"notes", "skip"}}
    return EmbeddingConfig(**{"dim": None, **fields})


class VectorStore:
    """float16 vectors of one model, addressed by chunk_id."""

    def __init__(self, model: str):
        self.dir = INDEX_DIR / "dense" / model
        self.ids: list[str] = []
        self.matrix = np.zeros((0, 0), dtype=np.float16)
        if (self.dir / "ids.json").exists():
            self.ids = json.loads((self.dir / "ids.json").read_text())
            self.matrix = np.load(self.dir / "vectors.npy")
        self.position = {chunk_id: i for i, chunk_id in enumerate(self.ids)}
        # chunk_id -> digest of the embedded text; vectors from before digests.json have none (trusted as current)
        path = self.dir / "digests.json"
        self.digests: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}

    def missing(self, chunks: list[dict]) -> list[dict]:
        return [c for c in chunks if c["chunk_id"] not in self.position
                or self.digests.get(c["chunk_id"], text_digest(c)) != text_digest(c)]

    def add(self, chunks: list[dict], vectors: np.ndarray) -> None:
        vectors = vectors.astype(np.float16)
        new = [i for i, chunk in enumerate(chunks) if chunk["chunk_id"] not in self.position]
        for i, chunk in enumerate(chunks):  # re-embedded: replaced in place
            if chunk["chunk_id"] in self.position:
                self.matrix[self.position[chunk["chunk_id"]]] = vectors[i]
        if new:
            self.matrix = vectors[new] if not self.ids else np.vstack([self.matrix, vectors[new]])
            for i in new:
                self.position[chunks[i]["chunk_id"]] = len(self.ids)
                self.ids.append(chunks[i]["chunk_id"])
        self.digests.update({chunk["chunk_id"]: text_digest(chunk) for chunk in chunks})

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        np.save(self.dir / "vectors.npy", self.matrix)
        (self.dir / "ids.json").write_text(json.dumps(self.ids))
        (self.dir / "digests.json").write_text(json.dumps(self.digests))

    def get(self, chunk_ids: list[str]) -> np.ndarray:
        return self.matrix[[self.position[chunk_id] for chunk_id in chunk_ids]]


def embed_chunks(model: str, chunks: list[dict], save_every: int = 5000) -> VectorStore:
    store = VectorStore(model)
    todo = store.missing(chunks)
    if not todo:
        return store
    embedder = Embedder(load_model_config(model))
    started = time.perf_counter()
    for start in range(0, len(todo), save_every):
        batch = todo[start:start + save_every]
        vectors = np.asarray(embedder.embed_documents([chunk_text(c) for c in batch]), dtype=np.float32)
        store.add(batch, vectors)
        store.save()
        done = start + len(batch)
        rate = done / (time.perf_counter() - started)
        print(f"  {model}: {done}/{len(todo)} chunks ({rate:.0f}/s)", flush=True)
    return store


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed corpus chunks with a local model")
    parser.add_argument("--model", required=True, nargs="+")
    parser.add_argument("--kommuner", nargs="*", help="only laws + these kommun codes")
    args = parser.parse_args()
    chunks = load_chunks(args.kommuner)
    for model in args.model:
        print(f"# {model}: {len(chunks)} chunks")
        embed_chunks(model, chunks)


if __name__ == "__main__":
    main()
