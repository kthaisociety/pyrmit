"""
The corpus in Postgres (Neon + pgvector): the app queries it instead of local files (LOCAL_RAG_STORE=neon), so a
tester needs no corpus download. Built from a disk store (localrag.store, usually of a corpus.snapshot of a few
kommuner).

    corpus_chunks   one row per chunk: the disk store's columns, `stems` (tsvector of the Swedish stems
                    localrag.analyzer gives, what FTS5 indexes locally) and `embedding` (halfvec, L2-normalised)
    corpus_places   proper nouns per kommun (kommun detection from place names)
    corpus_terms    chunks per stem (document frequency): the IDF of the BM25-like ranking
    corpus_ocr      corpus.ocr output per scanned PDF (gzip of its JSON): the word boxes view_map_area needs,
                    which the kommun sites don't have (the PDFs themselves are fetched from there, corpus.pdf_files)
    corpus_files    small files the app reads from disk (gazetteer, plan registry, place snapshots), gzip: written
                    to this install at startup when it lacks them (sync_files)
    corpus_meta     embedding model, dimension, counts, build time
    chunks, places  views with the disk store's columns, so the SQL of the agent tools (_DiskCorpus) and of the
                    Database view runs unchanged (PgStore.query adapts the placeholders)

Footprint on Neon: ~5.1 KB per chunk (vector 2 KB, stems 0.9 KB, GIN, text); laws + Uppsala + Vallentuna +
Stockholm (115k chunks) ~670 MB of the free plan's 1 GB. Neon suspends an idle compute after 5 minutes, which closes
the connections: PgStore reconnects once on a connection error.

    cd backend && CORPUS_DATA_DIR=data/demo CORPUS_DATABASE_URL=... python -m localrag.pg_store --model st-bge-m3
"""

import argparse
import csv
import gzip
import io
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from corpus import pdf_files
from corpus.common import BACKEND_DIR, DATA_DIR, DATA_ROOT, MUNICIPALITIES_PATH
from corpus.plans import PLANS_PATH
from embeddings import Embedder
from localrag.analyzer import SWEDISH_STOPWORDS, analyze
from localrag.index import chunk_text, load_model_config
from localrag.store import (
    _WORD,
    COLUMNS,
    DiskPlaces,
    DiskRetriever,
    DiskStore,
    store_dir,
)

logger = logging.getLogger(__name__)

BATCH = 2000
CANDIDATE_DF = 0.10  # bm25_top: candidate chunks come from the stems in under 10 % of the chunks
GEO_DIR =BACKEND_DIR / "data" / "geo"  # place.store.GEO_DIR (not imported: shapely for a path)
SYNC_STAMP = "neon_sync.json"
STORAGE_LIMIT_MB = 1000  # the free plan's storage per project; a files load stops short of it
FILES_BUILT = "files_built"  # corpus_meta key: when load_files last ran (the sync refreshes its files on a change)
UPSERT_FILE = "INSERT INTO corpus_files VALUES (%s, %s) ON CONFLICT (path) DO UPDATE SET data = EXCLUDED.data"  # bytes -> bytea


class StorageLimitError(RuntimeError):
    """A files load that would pass the storage limit: `needed_mb` is the database size after the load, `limit_mb`
    the limit it refused. Nothing was written."""

    def __init__(self, needed_mb: float, limit_mb: float):
        super().__init__(f"The load needs {needed_mb:.0f} MB of the database's {limit_mb:.0f} MB: nothing written")
        self.needed_mb, self.limit_mb = needed_mb, limit_mb


def snapshot_files(kommuner: list[str] | None = None) -> dict[str, Path]:
    """The snapshot files on disk of every kommun with a snapshot (a manifest.json in data/geo/<code>/), by their
    corpus_files path ("geo/<code>/<file>"), in path order. `kommuner` restricts to those codes; a code without a
    snapshot is skipped, so a wrong code gives no files rather than an error."""
    codes = sorted(kommuner) if kommuner is not None else sorted(path.name for path in GEO_DIR.iterdir() if path.is_dir())
    files = {}
    for code in codes:
        if (GEO_DIR / code / "manifest.json").is_file():
            files.update({f"geo/{code}/{path.name}": path for path in sorted((GEO_DIR / code).iterdir()) if path.is_file()})
    return files


def load_files(store, kommuner: list[str] | None = None, limit_mb: float = STORAGE_LIMIT_MB) -> dict:
    """Add or replace the snapshots of snapshot_files(kommuner) in corpus_files (gzip), without rebuilding the
    corpus: the chunks, the plan registry, the gazetteer and every other kommun's files stay as they are. `store`
    is a PgStore (anything with execute(sql, params)). Sets corpus_meta FILES_BUILT to now, so an install's sync
    writes the new snapshots (sync_files).

    Returns {"files": the files written, "kommuner": their codes, "mb": the gzip bytes written in MB,
    "database_mb": the database size after the load}. Raises StorageLimitError, with nothing written, when the
    database would pass `limit_mb` after the load (its size now, plus the files' gzip size, minus the rows they
    replace)."""
    files = snapshot_files(kommuner)
    packed = {path: gzip.compress(file.read_bytes(), 6) for path, file in files.items()}
    size = store.execute("SELECT pg_database_size(current_database())")[0][0]
    replaced = sum(length for _, length in store.execute(
        "SELECT path, octet_length(data) FROM corpus_files WHERE path = ANY(%s)", (list(packed),)))
    needed_mb = (size + sum(len(data) for data in packed.values()) - replaced) / 1e6
    if needed_mb > limit_mb:
        raise StorageLimitError(needed_mb, limit_mb)
    for path, data in packed.items():
        store.execute(UPSERT_FILE, (path, data))
    built = datetime.now(UTC).isoformat(timespec="seconds")
    store.execute("INSERT INTO corpus_meta VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                  (FILES_BUILT, json.dumps(built)))
    if isinstance(getattr(store, "meta", None), dict):
        store.meta[FILES_BUILT] = built
    return {"files": len(packed), "kommuner": sorted({path.split("/")[1] for path in packed}),
            "mb": round(sum(len(data) for data in packed.values()) / 1e6, 1),
            "database_mb": round(store.execute("SELECT pg_database_size(current_database())")[0][0] / 1e6, 1)}

CHUNKS_SCHEMA = """
DROP TABLE IF EXISTS corpus_chunks, corpus_places CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE corpus_chunks (
    rowid integer PRIMARY KEY, chunk_id text NOT NULL, doc_id text NOT NULL, chunk_index integer, kind text NOT NULL,
    doc_type text, kommun_code text, kommun text, title text, url text, section text, chapter text, paragraph text,
    heading text, header text, text text, stems tsvector, embedding halfvec({dim}) NOT NULL);
CREATE TABLE corpus_places (word text NOT NULL, kommun_code text NOT NULL, count integer NOT NULL);
"""
EXTRAS_SCHEMA = """
DROP TABLE IF EXISTS corpus_plans, corpus_ocr, corpus_terms, corpus_meta;
CREATE TABLE corpus_ocr (doc_id text PRIMARY KEY, data bytea NOT NULL);
CREATE TABLE IF NOT EXISTS corpus_files (path text PRIMARY KEY, data bytea NOT NULL);  -- kept: load_files' snapshots
ALTER TABLE corpus_ocr ALTER COLUMN data SET STORAGE EXTERNAL;  -- already gzip: no second compression
ALTER TABLE corpus_files ALTER COLUMN data SET STORAGE EXTERNAL;
CREATE TABLE corpus_meta (key text PRIMARY KEY, value jsonb NOT NULL);
CREATE TABLE corpus_terms AS SELECT word, ndoc FROM ts_stat('SELECT stems FROM corpus_chunks');
ALTER TABLE corpus_terms ADD PRIMARY KEY (word);
"""
# Same lookups as the disk store's indexes (localrag.store.build); kind + kommun_code first: every kommun query
INDEXES = f"""
CREATE INDEX IF NOT EXISTS corpus_chunks_pool ON corpus_chunks (kind, kommun_code);
CREATE INDEX IF NOT EXISTS corpus_chunks_doc ON corpus_chunks (doc_id, chunk_index);
CREATE INDEX IF NOT EXISTS corpus_chunks_id ON corpus_chunks (chunk_id);
CREATE INDEX IF NOT EXISTS corpus_chunks_law ON corpus_chunks (title, section) WHERE kind = 'law';
CREATE INDEX IF NOT EXISTS corpus_chunks_stems ON corpus_chunks USING gin (stems);
CREATE INDEX IF NOT EXISTS corpus_places_word ON corpus_places (word);
CREATE OR REPLACE VIEW chunks AS SELECT rowid, {", ".join(COLUMNS)} FROM corpus_chunks;
CREATE OR REPLACE VIEW places AS SELECT word, kommun_code, count FROM corpus_places;
"""


# --- load ---------------------------------------------------------------------------------------------------------

def _clean(value):
    """Postgres text refuses NUL characters (some PDF texts carry them)."""
    return value.replace("\x00", "") if isinstance(value, str) else value


def _copy(cursor, table: str, columns: str, rows: list[list]) -> None:
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    buffer.seek(0)
    cursor.copy_expert(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)", buffer)


def _copy_range(cursor, lite: sqlite3.Connection, vectors: np.ndarray, low: int, high: int, report) -> int:
    """Copy the chunks with low <= rowid < high; report(done) after every batch. Returns the chunks copied."""
    # Staging table with the stems as text: to_tsvector keeps their positions (term frequencies for ranking).
    # Emptied after every batch: the vectors as text would take ~1.2 GB of the compute's temp space
    cursor.execute(f"CREATE TEMP TABLE staging (rowid integer, {', '.join(f'{c} text' for c in COLUMNS)}, "
                   "stems text, embedding text)")
    rows, done = [], 0

    def flush() -> None:
        _copy(cursor, "staging", f"rowid, {', '.join(COLUMNS)}, stems, embedding", rows)
        cursor.execute("""INSERT INTO corpus_chunks SELECT rowid, chunk_id, doc_id, chunk_index::integer, kind,
                          doc_type, kommun_code, kommun, title, url, section, chapter, paragraph, heading, header,
                          text, to_tsvector('simple', stems), embedding::halfvec FROM staging""")
        cursor.execute("TRUNCATE staging")

    for row in lite.execute("SELECT * FROM chunks WHERE rowid >= ? AND rowid < ? ORDER BY rowid", (low, high)):
        chunk = {key: _clean(value) for key, value in dict(row).items()}
        vector = "[" + ",".join(map(str, vectors[chunk["rowid"]].tolist())) + "]"  # float16 values, exact
        rows.append([chunk["rowid"], *[chunk[c] for c in COLUMNS], " ".join(analyze(chunk_text(chunk), "stem")),
                     vector])
        if len(rows) >= BATCH:
            flush()
            done, rows = done + len(rows), []
            report(done)
    if rows:
        flush()
        done += len(rows)
        report(done)
    cursor.execute("DROP TABLE staging")
    return done


def _load_range(job: tuple) -> int:
    """One worker of a parallel load (multiprocessing): its own SQLite reader and Postgres connection."""
    import psycopg2

    model, url, low, high, worker = job
    directory = store_dir(model)
    lite = sqlite3.connect(f"file:{directory / 'corpus.sqlite'}?mode=ro", uri=True)
    lite.row_factory = sqlite3.Row
    vectors = np.load(directory / "vectors.npy", mmap_mode="r")
    connection = psycopg2.connect(url)
    connection.autocommit = True
    started = time.perf_counter()

    def report(done: int) -> None:
        if done % 50_000 < BATCH:
            print(f"  worker {worker}: {done} chunks ({time.perf_counter() - started:.0f}s)", flush=True)

    try:
        return _copy_range(connection.cursor(), lite, vectors, low, high, report)
    finally:
        connection.close()


def _load_chunks(cursor, lite: sqlite3.Connection, vectors: np.ndarray, total: int, started: float,
                 model: str = "", url: str = "", workers: int = 1) -> None:
    """workers > 1: that many processes copy one rowid range each (the time goes into the Python side, the Swedish
    stems and the vectors as text: 8 workers ~5x faster, 2.4M chunks in ~32 min instead of ~2.5 h)."""
    cursor.execute(CHUNKS_SCHEMA.format(dim=vectors.shape[1]))
    low, high = lite.execute("SELECT MIN(rowid), MAX(rowid) FROM chunks").fetchone()
    if low is None:
        done = 0
    elif workers <= 1:
        done = _copy_range(cursor, lite, vectors, low, high + 1, lambda n: print(
            f"  {n}/{total} chunks ({time.perf_counter() - started:.0f}s)", flush=True))
    else:
        import multiprocessing

        step = -(-(high + 1 - low) // workers)
        jobs = [(model, url, low + k * step, min(low + (k + 1) * step, high + 1), k) for k in range(workers)]
        with multiprocessing.Pool(workers) as pool:
            done = sum(pool.map(_load_range, jobs))
        print(f"  {done}/{total} chunks with {workers} workers ({time.perf_counter() - started:.0f}s)", flush=True)
    if done != total:
        raise SystemExit(f"copied {done} of the store's {total} chunks")
    _copy(cursor, "corpus_places", "word, kommun_code, count",
          [list(r) for r in lite.execute("SELECT word, kommun_code, count FROM places")])


def _small_files(kommuner: list[str]) -> dict[str, Path]:
    """Files the app reads from disk, by their corpus_files path: gazetteer, plan registry, the kommuner's place
    snapshots (snapshot_files)."""
    return {"corpus/municipalities.json": MUNICIPALITIES_PATH, "corpus/plans.jsonl": PLANS_PATH, **snapshot_files(kommuner)}


def load(model: str, url: str, skip_chunks: bool = False, workers: int = 1) -> dict:
    """skip_chunks: keep the chunks and places a previous run loaded (~17 min for 115k chunks from home), redo the
    rest. workers: processes copying the chunks (_load_chunks)."""
    import psycopg2

    directory = store_dir(model)
    lite = sqlite3.connect(f"file:{directory / 'corpus.sqlite'}?mode=ro", uri=True)
    lite.row_factory = sqlite3.Row
    vectors = np.load(directory / "vectors.npy", mmap_mode="r")
    connection = psycopg2.connect(url)
    connection.autocommit = True
    cursor = connection.cursor()
    started = time.perf_counter()
    total = lite.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    if skip_chunks:
        cursor.execute("SELECT COUNT(*) FROM corpus_chunks")
        if cursor.fetchone()[0] != total:
            raise SystemExit("corpus_chunks does not hold this store's chunks: run without --skip-chunks")
    else:
        _load_chunks(cursor, lite, vectors, total, started, model, url, workers)

    cursor.execute(EXTRAS_SCHEMA)  # corpus_terms: ts_stat over every chunk, ~30 s
    kommuner = sorted(r[0] for r in lite.execute("SELECT DISTINCT kommun_code FROM chunks WHERE kommun_code IS NOT NULL"))
    files = _small_files(kommuner)
    for name, path in files.items():
        cursor.execute(UPSERT_FILE, (name, gzip.compress(path.read_bytes(), 6)))
    ocr = 0
    for (doc_id,) in lite.execute("SELECT DISTINCT doc_id FROM chunks WHERE kind = 'pdf'"):
        path = pdf_files.ocr_path(doc_id)
        if path is not None:
            cursor.execute("INSERT INTO corpus_ocr VALUES (%s, %s)",
                           (doc_id, psycopg2.Binary(gzip.compress(path.read_bytes(), 6))))
            ocr += 1
    print(f"  {len(files)} files, {ocr} OCR outputs ({time.perf_counter() - started:.0f}s)", flush=True)

    cursor.execute(INDEXES)
    cursor.execute("VACUUM ANALYZE")
    meta = {"model": model, "dim": int(vectors.shape[1]), "chunks": total, "kommuner": kommuner, "files": len(files),
            "ocr": ocr, "built": datetime.now(UTC).isoformat(timespec="seconds")}
    cursor.executemany("INSERT INTO corpus_meta VALUES (%s, %s)", [(k, json.dumps(v)) for k, v in meta.items()])
    cursor.execute("SELECT relname, pg_total_relation_size(oid) FROM pg_class WHERE relname LIKE 'corpus\\_%%' "
                   "AND relkind = 'r' ORDER BY 2 DESC", ())
    meta["mb"] = {name: round(size / 1e6, 1) for name, size in cursor.fetchall()}
    cursor.execute("SELECT pg_database_size(current_database())")
    meta["database_mb"] = round(cursor.fetchone()[0] / 1e6, 1)
    print(f"Loaded in {time.perf_counter() - started:.0f}s: {json.dumps(meta)}")
    return meta


# --- serve --------------------------------------------------------------------------------------------------------

def _pg_sql(sql: str) -> str:
    """The disk store's SQLite SQL for psycopg2: ? placeholders become %s, LIKE becomes ILIKE (SQLite's LIKE ignores
    case, Postgres' does not)."""
    return re.sub(r"\bLIKE\b", "ILIKE", sql.replace("%", "%%").replace("?", "%s"))


def _pg_regex(pattern: str) -> str:
    """A Python regex (what the grep tool gets) for Postgres' ~*: word boundaries are \\y / \\Y there (\\b is a
    backspace), named groups are plain groups, and a leading inline flag goes (~* already ignores case)."""
    pattern = re.sub(r"^\(\?[aiLmsux]+\)", "", pattern).replace("(?P<", "(?<")
    out, i = [], 0
    while i < len(pattern):
        if pattern[i] == "\\" and i + 1 < len(pattern):
            pair = pattern[i:i + 2]
            out.append({"\\b": "\\y", "\\B": "\\Y"}.get(pair, pair))
            i += 2
        elif pattern.startswith("(?<", i) and not pattern.startswith(("(?<=", "(?<!"), i):  # named group
            out.append("(")
            i = pattern.index(">", i) + 1
        else:
            out.append(pattern[i])
            i += 1
    return "".join(out)


def same_vectors(model: str, other: str) -> bool:
    """Two models.toml entries giving the same vectors: the same underlying model (st-bge-m3 runs BAAI/bge-m3
    locally, or-bge-m3 calls baai/bge-m3 on OpenRouter: cosine 0.99999 on 18,440 chunks embedded both ways) with
    the same query prefix."""
    if model == other:
        return True
    a, b = load_model_config(model), load_model_config(other)
    return a.model.lower() == b.model.lower() and a.query_prefix == b.query_prefix


class PgStore:
    """DiskStore's read side on Postgres: query() takes the same SQLite SQL (agent tools, Database view), the
    searches run in SQL. One connection per thread."""

    def __init__(self, url: str):
        self.url = url
        self._local = threading.local()
        self.meta = {row[0]: row[1] for row in self.execute("SELECT key, value FROM corpus_meta")}
        self._summary: list[dict] | None = None
        self._ocr_ids: set[str] | None = None

    def execute(self, sql: str, params: tuple = ()) -> list:
        """Postgres SQL. A connection Neon closed (compute suspended when idle) is reopened once."""
        import psycopg2
        import psycopg2.extras

        for attempt in (0, 1):
            connection = getattr(self._local, "connection", None)
            try:
                if connection is None or connection.closed or attempt:
                    connection = self._local.connection = psycopg2.connect(self.url, connect_timeout=30)
                    connection.autocommit = True
                with connection.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                    cursor.execute(sql, params)
                    return cursor.fetchall() if cursor.description else []
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                if attempt:
                    raise
                logger.info("Corpus database connection lost: reconnecting")
        return []

    def query(self, sql: str, params: tuple = ()) -> list:
        return self.execute(_pg_sql(sql), tuple(params))

    @staticmethod
    def regexp(expression: str, pattern: str) -> tuple[str, str]:
        return f"{expression} ~* ?", _pg_regex(pattern)

    chunks_by_rowid = DiskStore.chunks_by_rowid
    chunk = DiskStore.chunk
    _chunk = staticmethod(DiskStore._chunk)

    def summary(self) -> list[dict]:
        if self._summary is None:
            self._summary = [
                {"kommun_code": code, "kommun": kommun, "kind": kind, "doc_type": doc_type, "documents": documents,
                 "chunks": chunks}
                for code, kommun, kind, doc_type, documents, chunks in self.execute(
                    "SELECT kommun_code, kommun, kind, doc_type, COUNT(DISTINCT doc_id), COUNT(*) FROM corpus_chunks "
                    "WHERE kind != 'law' GROUP BY kommun_code, kommun, kind, doc_type")]
        return self._summary

    def ocr_bytes(self, doc_id: str) -> bytes | None:
        rows = self.execute("SELECT data FROM corpus_ocr WHERE doc_id = %s", (doc_id,))
        return gzip.decompress(bytes(rows[0][0])) if rows else None

    def ocr_doc_ids(self, code: str) -> set[str]:
        if self._ocr_ids is None:
            self._ocr_ids = {row[0] for row in self.execute("SELECT doc_id FROM corpus_ocr")}
        return {doc_id for doc_id in self._ocr_ids if doc_id.startswith(f"pdf:{code}:")}

    @staticmethod
    def _pool(pool: str, kommuner: list[str] | None, doc_types: list[str] | None,
              title_contains: str | None) -> tuple[str, list]:
        if pool == "law":
            return "kind = 'law'", []
        sql, params = "kind IN ('page', 'pdf')", []
        if kommuner:
            sql, params = sql + " AND kommun_code = ANY(%s)", params + [list(kommuner)]
        if doc_types:
            sql, params = sql + " AND doc_type = ANY(%s)", params + [list(doc_types)]
        if title_contains:
            sql, params = sql + " AND title ILIKE %s", params + [f"%{title_contains}%"]
        return sql, params

    def dense_top(self, vector: np.ndarray, pool: str, kommuner: list[str] | None, n: int,
                  doc_types: list[str] | None = None, title_contains: str | None = None) -> list[int]:
        """Exact search (no ANN index): 0.05-0.09 s on the statutes or a small kommun, 0.5 s on Uppsala's 93k chunks."""
        where, params = self._pool(pool, kommuner, doc_types, title_contains)
        literal = "[" + ",".join(f"{x:.6g}" for x in vector) + "]"
        return [row[0] for row in self.execute(
            f"SELECT rowid FROM corpus_chunks WHERE {where} ORDER BY embedding <#> %s::halfvec LIMIT %s",
            (*params, literal, n))]

    def bm25_top(self, query: str, pool: str, kommuner: list[str] | None, n: int, doc_types: list[str] | None = None,
                 title_contains: str | None = None) -> list[int]:
        """FTS5's bm25 approached in SQL: sum over the query stems of IDF x ts_rank divided by 1 + log(chunk length)
        (normalization 1), on the chunks holding a stem found in under CANDIDATE_DF of the chunks (all stems still
        score). Against the disk store's bm25 on the 34 eval questions of the demo corpus (laws + their kommun): top-10
        overlap 0.80, 0.17 s mean, 2 s max; without the pruning 0.83 but 6.4 s max (common stems hold tens of
        thousands of Uppsala chunks); without the length normalization 0.57."""
        tokens = [t for t in dict.fromkeys(analyze(query, "stem")) if t.isalnum()]
        if not tokens or (pool != "law" and not kommuner):
            return []  # whole local corpus: as DiskStore, dense covers it
        df = dict(self.execute("SELECT word, ndoc FROM corpus_terms WHERE word = ANY(%s)", (tokens,)))
        candidates = [t for t in tokens if df.get(t, 0) < CANDIDATE_DF * self.meta["chunks"]] or tokens
        where, params = self._pool(pool, kommuner, doc_types, title_contains)
        return [row[0] for row in self.execute(
            f"""WITH q AS (SELECT to_tsquery('simple', word) AS term, ln(1 + (%s - ndoc + 0.5) / (ndoc + 0.5)) AS idf
                           FROM corpus_terms WHERE word = ANY(%s))
                SELECT rowid FROM corpus_chunks c WHERE {where} AND stems @@ to_tsquery('simple', %s)
                ORDER BY (SELECT sum(q.idf * ts_rank(c.stems, q.term, 1)) FROM q) DESC LIMIT %s""",
            (self.meta["chunks"], tokens, *params, " | ".join(candidates), n))]


class PgPlaces(DiskPlaces):
    """DiskPlaces in one query per detection (one per word was ~40 ms each to Neon)."""

    def detect(self, *texts: str) -> list[str]:
        words = [w for w in dict.fromkeys(_WORD.findall(" ".join(t for t in texts if t).lower()))
                 if w not in SWEDISH_STOPWORDS]
        counts: dict[str, list[tuple[str, int]]] = {}
        for word, code, count in self.store.execute(
                "SELECT word, kommun_code, count FROM corpus_places WHERE word = ANY(%s) ORDER BY count DESC", (words,)):
            counts.setdefault(word, []).append((code, count))
        found = []
        for word in words:
            rows = counts.get(word)
            if not rows or len(rows) > 3:
                continue
            code, top = rows[0]
            if top >= self.min_mentions and top / sum(c for _, c in rows) >= self.share and code not in found:
                found.append(code)
        return found


def _sync_target(path: str) -> Path:
    head, rest = path.split("/", 1)
    return {"corpus": DATA_DIR, "geo": GEO_DIR}[head] / rest


def sync_files(store: PgStore) -> list[str]:
    """Write the small files the app reads from disk (gazetteer, plan registry, place snapshots) from corpus_files
    when this install lacks them, or when the sync wrote them for an older build or an older files load (corpus_meta
    FILES_BUILT, load_files). A file the sync did not write is never overwritten: a machine with the full corpus
    keeps its own."""
    stamp_path = DATA_ROOT / SYNC_STAMP
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamp = {"built": None, "files": []}
    ours, built = set(stamp["files"]), f"{store.meta['built']} {store.meta.get(FILES_BUILT, '')}".strip()
    todo = [path for (path,) in store.execute("SELECT path FROM corpus_files")
            if not _sync_target(path).exists() or (path in ours and stamp["built"] != built)]
    if todo:
        for path, data in store.execute("SELECT path, data FROM corpus_files WHERE path = ANY(%s)", (todo,)):
            target = _sync_target(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(gzip.decompress(bytes(data)))
        logger.info("Corpus database: %d files written (%s)", len(todo), ", ".join(todo[:5]))
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(json.dumps({"built": built, "files": sorted(ours | set(todo))}), encoding="utf-8")
    return todo


class PgRetriever(DiskRetriever):
    """DiskRetriever's search() on the corpus database: filters, dense and BM25 run in SQL. `model` embeds the
    queries and must give the vectors stored (or-bge-m3 for a st-bge-m3 corpus: queries through OpenRouter)."""

    def __init__(self, model: str, url: str):
        self.store = PgStore(url)
        stored = self.store.meta["model"]
        if not same_vectors(model, stored):
            raise ValueError(f"The corpus database holds {stored} vectors: LOCAL_RAG_MODEL={model} would embed queries "
                             "with another model")
        self.model = model
        self.embedder = Embedder(load_model_config(model))
        self.places = PgPlaces(self.store)
        self.bm25 = {"stem": True}
        self.reranker = None
        sync_files(self.store)
        pdf_files.remote_ocr = self.store.ocr_bytes

    def _rankings(self, pool: str, vectors: list[np.ndarray], bm25_query: str | None, kommuner: list[str] | None,
                  filters: tuple, candidates: int) -> list[list[int]]:
        rankings = [self.store.dense_top(v, pool, kommuner, candidates, *filters) for v in vectors]
        if bm25_query is not None:
            rankings.append(self.store.bm25_top(bm25_query, pool, kommuner, candidates, *filters))
        return rankings


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy a disk store, the small files and OCR outputs to Postgres; or "
                                                 "with --files, the kommuner's place snapshots alone")
    parser.add_argument("--model", help="disk store to copy (localrag.store), e.g. st-bge-m3")
    parser.add_argument("--skip-chunks", action="store_true", help="keep the chunks already loaded, redo the rest")
    parser.add_argument("--workers", type=int, default=1,
                        help="processes copying the chunks (8: the national corpus in ~32 min instead of ~2.5 h)")
    parser.add_argument("--files", action="store_true", help="add or replace the place snapshots (data/geo), nothing else")
    parser.add_argument("--kommun", action="append", help="with --files: these kommun codes only (default: every snapshot)")
    parser.add_argument("--limit-mb", type=float, default=STORAGE_LIMIT_MB, help="with --files: the database's storage limit")
    args = parser.parse_args()
    url = os.getenv("CORPUS_DATABASE_URL")
    if not url:
        parser.error("set CORPUS_DATABASE_URL to the target database (e.g. the Neon demo branch)")
    if args.files:
        try:
            result = load_files(PgStore(url), args.kommun, args.limit_mb)
        except StorageLimitError as error:
            raise SystemExit(str(error)) from None
        print(f"Loaded {result['files']} files of {len(result['kommuner'])} kommuner ({result['mb']} MB gzip): "
              f"database {result['database_mb']} MB")
    elif args.model:
        load(args.model, url, args.skip_chunks, args.workers)
    else:
        parser.error("give --model (the whole corpus) or --files (the place snapshots)")


if __name__ == "__main__":
    main()
