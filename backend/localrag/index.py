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
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

from corpus.common import CHUNKS_PATH, INDEX_DIR, read_jsonl
from embeddings import EmbeddingConfig, Embedder

MODELS_PATH = Path(__file__).resolve().parent / "models.toml"


def chunk_text(chunk: dict) -> str:
    """What gets embedded and BM25-indexed: the context header, then the chunk."""
    return f"{chunk['header']}\n\n{chunk['text']}"


def text_digest(chunk: dict) -> str:
    return hashlib.sha1(chunk_text(chunk).encode()).hexdigest()[:16]


def iter_chunks(kommuner: list[str] | None = None, path: Path = CHUNKS_PATH) -> Iterator[dict]:
    wanted = set(kommuner or ())
    for chunk in read_jsonl(path):
        if not wanted or chunk["kind"] == "law" or chunk.get("kommun_code") in wanted:
            yield chunk


def load_chunks(kommuner: list[str] | None = None, path: Path = CHUNKS_PATH) -> list[dict]:
    return list(iter_chunks(kommuner, path))


def load_model_config(name: str) -> EmbeddingConfig:
    with MODELS_PATH.open("rb") as file:
        entry = tomllib.load(file)["models"][name]
    fields = {key: value for key, value in entry.items() if key not in {"notes", "skip"}}
    return EmbeddingConfig(**{"dim": None, **fields})


class VectorStore:
    """float16 vectors of one model, addressed by chunk_id. vectors.npy is a memmap that can hold more rows than
    ids.json (room for the next batches): rows past len(ids) are unused. Rewriting the whole matrix after every
    batch (np.vstack + np.save) was quadratic, hours of copying for the ~2M chunks of the 2026-10-23 crawl."""

    def __init__(self, model: str, writable: bool = False):
        self.dir = INDEX_DIR / "dense" / model
        self.path = self.dir / "vectors.npy"
        self.writable = writable
        self.ids: list[str] = []
        self.matrix = np.zeros((0, 0), dtype=np.float16)
        if (self.dir / "ids.json").exists():
            self.ids = json.loads((self.dir / "ids.json").read_text())
            self.matrix = np.load(self.path, mmap_mode="r+" if writable else "r")
        self.position = {chunk_id: i for i, chunk_id in enumerate(self.ids)}
        # chunk_id -> digest of the embedded text; vectors from before digests.json have none (trusted as current)
        path = self.dir / "digests.json"
        self.digests: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
        self.capacity_hint = 0  # rows to make room for at the next growth (the count of new chunks)

    def needs(self, chunk: dict) -> bool:
        return (chunk["chunk_id"] not in self.position
                or self.digests.get(chunk["chunk_id"], text_digest(chunk)) != text_digest(chunk))

    def missing(self, chunks: list[dict]) -> list[dict]:
        return [c for c in chunks if self.needs(c)]

    def _reserve(self, rows: int, dim: int) -> None:
        if self.matrix.shape[0] >= rows and self.matrix.shape[1] == dim:
            return
        rows = max(rows, self.capacity_hint, int(self.matrix.shape[0] * 1.5))
        self.dir.mkdir(parents=True, exist_ok=True)
        grown_path = self.dir / "vectors.grow.npy"
        grown = np.lib.format.open_memmap(grown_path, mode="w+", dtype=np.float16, shape=(rows, dim))
        for start in range(0, len(self.ids), 100000):
            end = min(start + 100000, len(self.ids))
            grown[start:end] = self.matrix[start:end]
        grown.flush()
        del grown
        if isinstance(self.matrix, np.memmap):
            self.matrix._mmap.close()  # Windows cannot replace a mapped file
        self.matrix = None
        grown_path.replace(self.path)
        self.matrix = np.load(self.path, mmap_mode="r+")

    def add(self, chunks: list[dict], vectors: np.ndarray) -> None:
        if not self.writable:
            raise RuntimeError("VectorStore opened read-only")
        vectors = vectors.astype(np.float16)
        new = [i for i, chunk in enumerate(chunks) if chunk["chunk_id"] not in self.position]
        self._reserve(len(self.ids) + len(new), vectors.shape[1])
        for i, chunk in enumerate(chunks):
            if chunk["chunk_id"] in self.position:  # re-embedded: replaced in place
                self.matrix[self.position[chunk["chunk_id"]]] = vectors[i]
            else:
                self.position[chunk["chunk_id"]] = len(self.ids)
                self.matrix[len(self.ids)] = vectors[i]
                self.ids.append(chunk["chunk_id"])
        self.digests.update({chunk["chunk_id"]: text_digest(chunk) for chunk in chunks})

    def save(self) -> None:
        """ids.json is written after the vectors: an interrupted run resumes from the last save."""
        self.dir.mkdir(parents=True, exist_ok=True)
        if isinstance(self.matrix, np.memmap):
            self.matrix.flush()
        (self.dir / "ids.json").write_text(json.dumps(self.ids))
        (self.dir / "digests.json").write_text(json.dumps(self.digests))

    def get(self, chunk_ids: list[str]) -> np.ndarray:
        return np.asarray(self.matrix[[self.position[chunk_id] for chunk_id in chunk_ids]])


def _embed_batches(store: VectorStore, model: str, todo: Iterable[dict], total: int, batch_size: int = 5000,
                   save_every: int = 50000) -> None:
    embedder = Embedder(load_model_config(model))
    started, done, unsaved, batch = time.perf_counter(), 0, 0, []

    def flush() -> None:
        nonlocal done, unsaved, batch
        vectors = np.asarray(embedder.embed_documents([chunk_text(c) for c in batch]), dtype=np.float32)
        store.add(batch, vectors)
        done, unsaved, batch = done + len(batch), unsaved + len(batch), []
        if unsaved >= save_every or done == total:
            store.save()
            unsaved = 0
        rate = done / (time.perf_counter() - started)
        print(f"  {model}: {done}/{total} chunks ({rate:.0f}/s, {(total - done) / rate / 3600:.1f} h left)",
              flush=True)

    for chunk in todo:
        batch.append(chunk)
        if len(batch) >= batch_size:
            flush()
    if batch:
        flush()
    store.save()


def embed_chunks(model: str, chunks: list[dict]) -> VectorStore:
    """Embeds the chunks of a list not embedded yet (memory retriever, evals)."""
    store = VectorStore(model, writable=True)
    todo = store.missing(chunks)
    if todo:
        store.capacity_hint = len(store.ids) + len(todo)
        _embed_batches(store, model, todo, len(todo))
    return store


def index_corpus(model: str, kommuner: list[str] | None = None) -> VectorStore:
    """Embeds the new and changed chunks of chunks.jsonl, read twice from disk (a count, then the batches) rather
    than held in RAM."""
    store = VectorStore(model, writable=True)
    total = new = 0
    for chunk in iter_chunks(kommuner):
        if store.needs(chunk):
            total += 1
            new += chunk["chunk_id"] not in store.position
    print(f"# {model}: {len(store.ids)} chunks embedded, {total} to embed ({new} new)", flush=True)
    if total:
        store.capacity_hint = len(store.ids) + new
        _embed_batches(store, model, (c for c in iter_chunks(kommuner) if store.needs(c)), total)
    return store


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed corpus chunks with a local model")
    parser.add_argument("--model", required=True, nargs="+")
    parser.add_argument("--kommuner", nargs="*", help="only laws + these kommun codes")
    args = parser.parse_args()
    for model in args.model:
        index_corpus(model, args.kommuner)


if __name__ == "__main__":
    main()
