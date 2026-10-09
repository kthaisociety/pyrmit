"""
Disk-based store for serving the local corpus without loading it in RAM.

    data/index/store/<model>/corpus.sqlite   chunks + documents + places, FTS5 index of Swedish stems (BM25)
    data/index/store/<model>/vectors.f16     L2-normalised float16 vectors, row i = chunks.rowid i (memmap)

Searches filter rows in SQL first (pool law/local, kommun), then read only those vectors from the memmap;
BM25 is FTS5's bm25() over pre-stemmed text. RAM stays at a few hundred MB plus the embedding model.

    cd backend && python -m localrag.store --model st-arctic-l-v2     # build (after localrag.index)
"""

import argparse
import json
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from corpus.common import CHUNKS_PATH, read_jsonl
from embeddings import Embedder
from localrag.analyzer import SWEDISH_STOPWORDS, analyze
from localrag.gazetteer import detect_kommuner
from localrag.index import INDEX_DIR, VectorStore, chunk_text, load_model_config
from localrag.retriever import RRF_K, Hit

STORE_DIR = INDEX_DIR / "store"
COLUMNS = ("chunk_id", "doc_id", "chunk_index", "kind", "doc_type", "kommun_code", "kommun", "title", "url",
           "section", "chapter", "paragraph", "heading", "header", "text")
_PROPER_NOUN = re.compile(r"(?<![\w])[A-ZÅÄÖ][a-zåäöé]{3,}")
_WORD = re.compile(r"[a-zåäöé]{4,}")


def store_dir(model: str) -> Path:
    return STORE_DIR / model


def build(model: str) -> None:
    out = store_dir(model)
    out.mkdir(parents=True, exist_ok=True)
    vectors = VectorStore(model)
    database = out / "corpus.sqlite"
    database.unlink(missing_ok=True)
    connection = sqlite3.connect(database)
    connection.executescript(f"""
        PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
        CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, {", ".join(f"{c} TEXT" for c in COLUMNS)});
        CREATE VIRTUAL TABLE chunks_fts USING fts5(stems, content='', tokenize='unicode61 remove_diacritics 0');
        CREATE TABLE places (word TEXT, kommun_code TEXT, count INTEGER);
    """)
    started = time.perf_counter()
    rows, kept = [], []
    places: dict[str, Counter] = defaultdict(Counter)
    for chunk in read_jsonl(CHUNKS_PATH):
        if chunk["chunk_id"] not in vectors.position:
            continue  # not embedded: not served
        rowid = len(kept)
        kept.append(vectors.position[chunk["chunk_id"]])
        rows.append((rowid, *[None if chunk.get(c) is None else str(chunk.get(c)) for c in COLUMNS]))
        # Filter tokens in the FTS row ("zzpoollaw", "zzk0115"): FTS5 intersects posting lists instead of
        # scoring every chunk that contains a common term and filtering afterwards
        filters = "zzpoollaw" if chunk["kind"] == "law" else f"zzpoollocal zzk{chunk.get('kommun_code') or 'none'}"
        connection.execute("INSERT INTO chunks_fts(rowid, stems) VALUES (?, ?)",
                           (rowid, " ".join(analyze(chunk_text(chunk), "stem")) + " " + filters))
        if chunk["kind"] != "law" and chunk.get("kommun_code"):
            for word in {w.lower() for w in _PROPER_NOUN.findall(chunk["text"])}:
                places[word][chunk["kommun_code"]] += 1
        if len(rows) >= 5000:
            connection.executemany(f"INSERT INTO chunks VALUES ({', '.join('?' * (len(COLUMNS) + 1))})", rows)
            rows = []
            print(f"  {len(kept)} chunks ({time.perf_counter() - started:.0f}s)", flush=True)
    if rows:
        connection.executemany(f"INSERT INTO chunks VALUES ({', '.join('?' * (len(COLUMNS) + 1))})", rows)
    connection.executemany("INSERT INTO places VALUES (?, ?, ?)",
                           [(word, code, count) for word, counts in places.items() for code, count in counts.items()])
    connection.executescript("""
        CREATE INDEX chunks_pool ON chunks(kind, kommun_code);
        CREATE INDEX chunks_doc ON chunks(doc_id, chunk_index);
        CREATE INDEX chunks_id ON chunks(chunk_id);
        CREATE INDEX chunks_law ON chunks(title, section);
        CREATE INDEX places_word ON places(word);
    """)
    connection.commit()
    connection.close()

    # Vectors in rowid order, normalised once so that a search is a plain dot product
    memmap = np.lib.format.open_memmap(out / "vectors.npy", mode="w+", dtype=np.float16,
                                       shape=(len(kept), vectors.matrix.shape[1]))
    for start in range(0, len(kept), 20000):
        block = vectors.matrix[kept[start:start + 20000]].astype(np.float32)
        block /= np.clip(np.linalg.norm(block, axis=1, keepdims=True), 1e-12, None)
        memmap[start:start + len(block)] = block.astype(np.float16)
    memmap.flush()
    (out / "meta.json").write_text(json.dumps({"model": model, "chunks": len(kept)}))
    print(f"Store: {len(kept)} chunks -> {out} ({time.perf_counter() - started:.0f}s)")


def _regexp(pattern: str, value: str | None) -> bool:
    return value is not None and re.search(pattern, value, re.I) is not None


class DiskPlaces:
    """CorpusPlaces backed by the `places` table."""

    def __init__(self, store: "DiskStore", min_mentions: int = 3, share: float = 0.8):
        self.store = store
        self.min_mentions = min_mentions
        self.share = share

    def detect(self, *texts: str) -> list[str]:
        found = []
        for word in _WORD.findall(" ".join(t for t in texts if t).lower()):
            if word in SWEDISH_STOPWORDS:
                continue
            counts = self.store.query("SELECT kommun_code, count FROM places WHERE word = ? ORDER BY count DESC", (word,))
            if not counts or len(counts) > 3:
                continue
            code, top = counts[0]
            if top >= self.min_mentions and top / sum(c for _, c in counts) >= self.share and code not in found:
                found.append(code)
        return found


class DiskStore:
    """Read side, shared by the retriever and the agent tools. Thread-safe (one connection per thread)."""

    def __init__(self, model: str):
        self.model = model
        self.dir = store_dir(model)
        if not (self.dir / "corpus.sqlite").exists():
            raise FileNotFoundError(f"No store for {model}: run `python -m localrag.store --model {model}`")
        self.vectors = np.load(self.dir / "vectors.npy", mmap_mode="r")
        self._local = threading.local()
        self.gpu = self._to_gpu()

    def _to_gpu(self):
        """The float16 matrix in GPU memory (copied block by block from the memmap, no RAM copy); None on CPU."""
        try:
            import torch
            if not torch.cuda.is_available():
                return None
            tensor = torch.empty(self.vectors.shape, dtype=torch.float16, device="cuda")
            for start in range(0, self.vectors.shape[0], 50000):
                block = np.array(self.vectors[start:start + 50000])  # writable copy of one block only
                tensor[start:start + len(block)] = torch.from_numpy(block).cuda()
            return tensor
        except Exception:
            return None

    @property
    def connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "connection"):
            connection = sqlite3.connect(f"file:{self.dir / 'corpus.sqlite'}?mode=ro", uri=True, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.create_function("REGEXP", 2, _regexp, deterministic=True)
            self._local.connection = connection
        return self._local.connection

    def query(self, sql: str, params: tuple = ()) -> list:
        return self.connection.execute(sql, params).fetchall()

    def chunks_by_rowid(self, rowids: list[int]) -> dict[int, dict]:
        if not rowids:
            return {}
        rows = self.query(f"SELECT * FROM chunks WHERE rowid IN ({','.join('?' * len(rowids))})", tuple(rowids))
        return {row["rowid"]: self._chunk(row) for row in rows}

    def chunk(self, chunk_id: str) -> dict | None:
        rows = self.query("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,))
        return self._chunk(rows[0]) if rows else None

    @staticmethod
    def _chunk(row: sqlite3.Row) -> dict:
        chunk = {key: row[key] for key in row.keys()}
        if chunk.get("chunk_index") is not None:
            chunk["chunk_index"] = int(chunk["chunk_index"])
        return chunk

    def pool_rowids(self, pool: str, kommuner: list[str] | None) -> np.ndarray | None:
        """Row ids of a pool; None = the whole local pool (too big to list, scanned in blocks)."""
        if pool == "law":
            return np.array([r[0] for r in self.query("SELECT rowid FROM chunks WHERE kind = 'law'")], dtype=np.int64)
        if not kommuner:
            return None
        sql = f"SELECT rowid FROM chunks WHERE kind != 'law' AND kommun_code IN ({','.join('?' * len(kommuner))})"
        return np.array([r[0] for r in self.query(sql, tuple(kommuner))], dtype=np.int64)

    def _law_mask(self) -> np.ndarray:
        if not hasattr(self, "_law_rows"):
            mask = np.zeros(self.vectors.shape[0], dtype=bool)
            mask[self.pool_rowids("law", None)] = True
            self._law_rows = mask
        return self._law_rows

    def dense_top(self, vector: np.ndarray, rowids: np.ndarray | None, n: int) -> list[int]:
        if self.gpu is not None:
            import torch

            query_gpu = torch.from_numpy(vector.astype(np.float16)).cuda()
            if rowids is not None:
                if len(rowids) == 0:
                    return []
                index = torch.from_numpy(rowids).cuda()
                scores = self.gpu.index_select(0, index) @ query_gpu
                top = torch.topk(scores.float(), min(n, len(rowids))).indices.cpu().numpy()
                return [int(rowids[i]) for i in top]
            scores = (self.gpu @ query_gpu).float()
            scores[torch.from_numpy(self._law_mask()).cuda()] = -float("inf")
            return [int(i) for i in torch.topk(scores, n).indices.cpu().numpy()]
        query = vector.astype(np.float32)
        if rowids is not None:
            if len(rowids) == 0:
                return []
            rowids = np.sort(rowids)
            scores = self.vectors[rowids].astype(np.float32) @ query
            return [int(rowids[i]) for i in np.argsort(-scores)[:n]]
        # Unfiltered local pool: stream the memmap in blocks, laws masked out
        law = self._law_mask()
        best: list[tuple[float, int]] = []
        for start in range(0, self.vectors.shape[0], 50000):
            scores = self.vectors[start:start + 50000].astype(np.float32) @ query
            scores[law[start:start + len(scores)]] = -np.inf
            top = np.argpartition(-scores, min(n, len(scores) - 1))[:n]
            best.extend((float(scores[i]), start + int(i)) for i in top)
        best.sort(reverse=True)
        return [rowid for _, rowid in best[:n]]

    def bm25_top(self, query: str, pool: str, kommuner: list[str] | None, n: int) -> list[int]:
        tokens = [t for t in dict.fromkeys(analyze(query, "stem")) if t.isalnum()]
        if not tokens:
            return []
        terms = " OR ".join(f'"{t}"' for t in tokens)
        if pool == "law":
            match = f"({terms}) AND zzpoollaw"
        elif kommuner:
            match = f"({terms}) AND ({' OR '.join(f'zzk{code}' for code in kommuner)})"
        else:
            return []  # whole local corpus: common terms match ~100k chunks, too slow to score; dense covers it
        sql = "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?"
        return [r[0] for r in self.query(sql, (match, n))]


class DiskRetriever:
    """Same search() as LocalRetriever, served from DiskStore."""

    def __init__(self, model: str):
        self.model = model
        self.store = DiskStore(model)
        self.embedder = Embedder(load_model_config(model))
        self.places = DiskPlaces(self.store)
        self.bm25 = {"stem": True}  # FTS5: BM25 over Swedish stems is always available
        self.reranker = None

    def search(self, query: str, query_sv: str | None = None, k: int = 5, mode: str = "dense",
               kommuner: list[str] | None | str = "auto", dense_lang: str = "sv", candidates: int = 50,
               rerank: bool = False, bm25_mode: str | None = None) -> dict:
        if kommuner == "auto":
            kommuner = list(dict.fromkeys(detect_kommuner(query, query_sv or "") +
                                          self.places.detect(query, query_sv or "")))
        texts = {"en": [query], "sv": [query_sv or query], "both": [query, query_sv or query]}[dense_lang]
        vectors = [np.asarray(self.embedder.embed_query(t), dtype=np.float32) for t in texts] \
            if mode in ("dense", "hybrid") else []
        vectors = [v / max(np.linalg.norm(v), 1e-12) for v in vectors]
        results: dict = {}
        for pool in ("law", "local"):
            rowids = self.store.pool_rowids(pool, kommuner or None)
            rankings = [self.store.dense_top(v, rowids, candidates) for v in vectors]
            if mode in ("bm25", "hybrid"):
                rankings.append(self.store.bm25_top(query_sv or query, pool, kommuner or None, candidates))
            fused: dict[int, float] = {}
            for ranking in rankings:
                for rank, rowid in enumerate(ranking):
                    fused[rowid] = fused.get(rowid, 0.0) + 1.0 / (RRF_K + rank + 1)
            order = sorted(fused, key=fused.get, reverse=True)[:k]
            chunks = self.store.chunks_by_rowid(order)
            results[pool] = [Hit(chunks[rowid], fused[rowid], rank) for rank, rowid in enumerate(order, start=1)]
        results["kommuner"] = kommuner or []
        return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the disk store from chunks.jsonl + embedded vectors")
    parser.add_argument("--model", default="st-arctic-l-v2")
    args = parser.parse_args()
    build(args.model)


if __name__ == "__main__":
    main()
