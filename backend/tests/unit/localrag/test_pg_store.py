import gzip
import json
import re
import sqlite3
import threading
from pathlib import Path

import pytest

from agentic.tools import _DiskCorpus
from localrag import pg_store
from localrag.store import COLUMNS, DiskStore


def test_sqlite_sql_runs_on_postgres():
    sql = pg_store._pg_sql("SELECT * FROM chunks WHERE title LIKE ? AND kommun_code IN (?, ?) AND x = '5%'")
    assert sql == "SELECT * FROM chunks WHERE title ILIKE %s AND kommun_code IN (%s, %s) AND x = '5%%'"


@pytest.mark.parametrize("python, postgres", [
    (r"\bnockhöjd\b", r"\ynockhöjd\y"),        # \b is a backspace in Postgres' regex
    (r"\\b", r"\\b"),                           # an escaped backslash followed by b stays
    (r"(?i)byggnadsarea", "byggnadsarea"),     # ~* already ignores case
    (r"(?P<nr>\d+:\d+)", r"(\d+:\d+)"),         # named group
    (r"(?<=e)\d", r"(?<=e)\d"),                 # lookbehind kept
])
def test_python_regex_for_postgres(python, postgres):
    assert pg_store._pg_regex(python) == postgres


def test_models_with_the_same_vectors():
    assert pg_store.same_vectors("or-bge-m3", "st-bge-m3")  # baai/bge-m3 on OpenRouter = BAAI/bge-m3 locally
    assert not pg_store.same_vectors("st-arctic-l-v2", "st-bge-m3")


class FakeDatabase:
    """execute() answers the SQL load_files and sync_files send, over an in-memory corpus_files and corpus_meta."""

    def __init__(self, files: dict[str, bytes] | None = None, size_mb: float = 600.0, built: str = "v1",
                 places: list[tuple] = (), packed: dict[str, bytes] | None = None):
        self.files = packed if packed is not None else {path: gzip.compress(data) for path, data in (files or {}).items()}
        self.meta, self.places, self.size_mb = {"built": built}, list(places), size_mb

    def execute(self, sql: str, params: tuple = ()) -> list:
        if "pg_database_size" in sql:
            return [(int(self.size_mb * 1e6 + sum(len(d) for d in self.files.values())),)]
        if sql.startswith("SELECT path, octet_length"):
            return [(path, len(self.files[path])) for path in params[0] if path in self.files]
        if sql.startswith("SELECT path FROM"):
            return [(path,) for path in self.files]
        if sql.startswith("SELECT path, data"):
            return [(path, self.files[path]) for path in params[0]]
        if sql.startswith("INSERT INTO corpus_files"):
            self.files[params[0]] = bytes(params[1])
            return []
        if sql.startswith("INSERT INTO corpus_meta"):
            self.meta[params[0]] = json.loads(params[1])
            return []
        if "corpus_places" in sql:
            return [row for row in self.places if row[0] in params[0]]
        raise AssertionError(sql)

    def text(self, path: str) -> bytes:
        return gzip.decompress(self.files[path])



@pytest.fixture
def install(tmp_path, monkeypatch):
    """An install without data: the sync writes corpus/ files under the data root, geo/ files in the geo folder."""
    monkeypatch.setattr(pg_store, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(pg_store, "DATA_DIR", tmp_path / "data" / "corpus")
    monkeypatch.setattr(pg_store, "GEO_DIR", tmp_path / "geo")
    return tmp_path


def snapshot(geo: Path, code: str, plans: str) -> None:
    folder = geo / code
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"code": code}), encoding="utf-8")
    (folder / "plans.geojson").write_text(plans, encoding="utf-8")
    (folder / "plan_links.jsonl").write_text("", encoding="utf-8")


@pytest.fixture
def geo(install) -> Path:
    """Two kommuner with a snapshot on disk and one folder without a manifest (a fetch that never finished)."""
    tmp_path = install
    snapshot(tmp_path / "geo", "0380", '{"features": ["uppsala"]}')
    snapshot(tmp_path / "geo", "0180", '{"features": ["stockholm"]}')
    (tmp_path / "geo" / "0115").mkdir()
    (tmp_path / "geo" / "0115" / "plans.geojson").write_text("{}", encoding="utf-8")
    return tmp_path / "geo"



def test_sync_writes_the_missing_files(install):
    store = FakeDatabase({"corpus/plans.jsonl": b"{}\n", "geo/0380/plans.geojson": b'{"features": []}'}, built="v1")
    assert sorted(pg_store.sync_files(store)) == ["corpus/plans.jsonl", "geo/0380/plans.geojson"]
    assert (install / "data" / "corpus" / "plans.jsonl").read_bytes() == b"{}\n"
    assert (install / "geo" / "0380" / "plans.geojson").exists()
    assert pg_store.sync_files(store) == []  # same build: nothing to write


def test_sync_keeps_files_it_did_not_write(install):
    own = install / "data" / "corpus" / "plans.jsonl"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"the full registry\n")  # a machine with the national corpus
    store = FakeDatabase({"corpus/plans.jsonl": b"demo registry\n"}, built="v1")
    assert pg_store.sync_files(store) == []
    assert pg_store.sync_files(FakeDatabase(built="v2", packed=store.files)) == []  # a new build does not touch it either
    assert own.read_bytes() == b"the full registry\n"


def test_sync_refreshes_its_files_on_a_new_build(install):
    pg_store.sync_files(FakeDatabase({"corpus/plans.jsonl": b"old\n"}, built="v1"))
    assert pg_store.sync_files(FakeDatabase({"corpus/plans.jsonl": b"new\n"}, built="v2")) == ["corpus/plans.jsonl"]
    assert (install / "data" / "corpus" / "plans.jsonl").read_bytes() == b"new\n"


def test_places_detected_in_one_query():
    store = FakeDatabase(places=[("fyrisån", "0380", 40), ("kårsta", "0115", 9), ("kårsta", "1880", 1),
                                        ("centrum", "0380", 5), ("centrum", "0115", 5)])
    # Fyrisån: Uppsala only; Kårsta: 90 % Vallentuna; centrum: split between kommuner, not a clue
    assert pg_store.PgPlaces(store).detect("Bygga vid Fyrisån", "Kårsta centrum") == ["0380", "0115"]


@pytest.fixture
def sqlite_store(tmp_path):
    """A DiskStore over a three-chunk SQLite file (no vectors: the SQL of the agent tools only)."""
    connection = sqlite3.connect(tmp_path / "corpus.sqlite")
    connection.execute(f"CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, {', '.join(f'{c} TEXT' for c in COLUMNS)})")
    rows = [("c1", "pdf:0115:aa11", "0", "pdf", "detaljplan", "0115", "Vallentuna", "Plan B", "u1", "Nockhöjd 8 m"),
            ("c2", "pdf:0115:aa11", "1", "pdf", "detaljplan", "0115", "Vallentuna", "Plan B", "u1", "Byggnadsarea 200"),
            ("c3", "pdf:0115:bb22", "0", "pdf", "taxa", "0115", "Vallentuna", "Avgifter", "u2", "Avgift för nockhöjden")]
    for rowid, (chunk_id, doc_id, index, kind, doc_type, code, kommun, title, url, text) in enumerate(rows):
        values = {"chunk_id": chunk_id, "doc_id": doc_id, "chunk_index": index, "kind": kind, "doc_type": doc_type,
                  "kommun_code": code, "kommun": kommun, "title": title, "url": url, "header": title, "text": text}
        connection.execute(f"INSERT INTO chunks VALUES ({', '.join('?' * (len(COLUMNS) + 1))})",
                           (rowid, *[values.get(c) for c in COLUMNS]))
    connection.commit()
    store = DiskStore.__new__(DiskStore)
    store.dir, store._local = tmp_path, threading.local()
    return store


def test_agent_tool_sql_on_sqlite(sqlite_store):
    """The SQL made portable for Postgres (MIN() per document, LIKE, regexp condition) still runs on the disk store."""
    corpus = _DiskCorpus(sqlite_store)
    docs = corpus.documents({"0115"}, None, None)
    assert [(d["doc_id"], d["title"], d["chunks"]) for d in docs] == [("pdf:0115:bb22", "Avgifter", 1),
                                                                       ("pdf:0115:aa11", "Plan B", 2)]
    assert corpus.doc_ids_ending("bb22") == ["pdf:0115:bb22"]
    total, hits = corpus.grep(re.compile(r"\bnockhöjd\b", re.IGNORECASE), "kommun", {"0115"}, 10)
    assert total == 1 and hits[0][0]["chunk_id"] == "c1"  # "nockhöjden" is another word


def test_load_writes_every_kommun_snapshot(geo):
    """A load with no kommuner given puts every snapshot on disk in the database, file by file, gzip."""
    db = FakeDatabase()
    result = pg_store.load_files(db)
    assert sorted(result["kommuner"]) == ["0180", "0380"]
    assert result["files"] == 6
    assert db.text("geo/0380/plans.geojson") == b'{"features": ["uppsala"]}'
    assert db.text("geo/0180/manifest.json") == b'{"code": "0180"}'


def test_load_skips_a_folder_without_a_manifest(geo):
    """A kommun folder without a manifest is not a snapshot: nothing of it is loaded."""
    db = FakeDatabase()
    pg_store.load_files(db)
    assert not any(path.startswith("geo/0115/") for path in db.files)


def test_load_replaces_a_kommun_snapshot(geo):
    """A second load of a kommun replaces its files with what is on disk now."""
    db = FakeDatabase()
    pg_store.load_files(db, ["0380"])
    (geo / "0380" / "plans.geojson").write_text('{"features": ["uppsala", "new"]}', encoding="utf-8")
    pg_store.load_files(db, ["0380"])
    assert db.text("geo/0380/plans.geojson") == b'{"features": ["uppsala", "new"]}'


def test_load_leaves_other_rows_untouched(geo):
    """A load of one kommun leaves the registry, the gazetteer and the other kommuner's files as they were."""
    db = FakeDatabase({"corpus/plans.jsonl": b"registry\n", "geo/0180/plans.geojson": b"old stockholm"})
    pg_store.load_files(db, ["0380"])
    assert db.text("corpus/plans.jsonl") == b"registry\n"
    assert db.text("geo/0180/plans.geojson") == b"old stockholm"
    assert "geo/0380/plans.geojson" in db.files


def test_load_stops_before_the_storage_limit(geo):
    """A load that would pass the storage limit writes nothing and says how much it needed."""
    db = FakeDatabase(size_mb=999.9999)
    with pytest.raises(pg_store.StorageLimitError) as raised:
        pg_store.load_files(db, limit_mb=1000)
    assert raised.value.needed_mb > 1000
    assert raised.value.limit_mb == 1000
    assert db.files == {}


def test_load_counts_the_rows_it_replaces(geo):
    """The space a load needs is net of the rows it replaces: reloading the same files needs nothing new."""
    db = FakeDatabase()
    pg_store.load_files(db)
    db.size_mb = 1000 - sum(len(d) for d in db.files.values()) / 1e6 - 0.0001  # just under the limit with them
    pg_store.load_files(db, limit_mb=1000)  # the same bytes again: no StorageLimitError


def test_load_marks_when_the_files_were_built(geo):
    """A load records when it ran, so an install can tell the snapshots changed."""
    db = FakeDatabase()
    pg_store.load_files(db)
    assert db.meta[pg_store.FILES_BUILT]


def test_sync_writes_the_loaded_snapshots_to_an_install(geo, tmp_path):
    """A backend starting without a snapshot gets it on disk from the database, where the place lookup reads it."""
    db = FakeDatabase()
    pg_store.load_files(db)
    for folder in (geo / "0380", geo / "0180"):
        for file in folder.iterdir():
            file.unlink()
        folder.rmdir()
    written = pg_store.sync_files(db)
    assert "geo/0380/plans.geojson" in written
    assert (geo / "0380" / "plans.geojson").read_bytes() == b'{"features": ["uppsala"]}'


def test_sync_refreshes_its_snapshots_after_a_new_load(geo):
    """A snapshot the sync wrote is written again after a later load replaced it in the database."""
    db = FakeDatabase({"geo/0188/plans.geojson": b"first"})
    db.meta[pg_store.FILES_BUILT] = "2026-11-05T10:00:00+00:00"
    assert pg_store.sync_files(db) == ["geo/0188/plans.geojson"]
    db.files["geo/0188/plans.geojson"] = gzip.compress(b"second")
    db.meta[pg_store.FILES_BUILT] = "2026-11-05T11:00:00+00:00"
    assert pg_store.sync_files(db) == ["geo/0188/plans.geojson"]
    assert (geo / "0188" / "plans.geojson").read_bytes() == b"second"



class _CopyCursor:
    """Records the rows each COPY sends (the chunk load's only contact with Postgres besides plain statements)."""

    def __init__(self):
        self.copied, self.statements = [], []

    def execute(self, sql, params=()):
        self.statements.append(sql)

    def copy_expert(self, sql, buffer):
        self.copied.extend(line.split(",")[0] for line in buffer.getvalue().splitlines())


def _chunk_store(n: int) -> sqlite3.Connection:
    lite = sqlite3.connect(":memory:")
    lite.row_factory = sqlite3.Row
    lite.execute(f"CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, {', '.join(COLUMNS)})")
    lite.executemany(f"INSERT INTO chunks VALUES ({', '.join('?' * (len(COLUMNS) + 1))})",
                     [(i, f"c{i}", "pdf:0180:x", i, "pdf", "detaljplan", "0180", "Stockholm", "Plan", "u", None, None,
                       None, None, "Stockholm - Plan", f"Byggnadshöjd {i} meter") for i in range(n)])
    return lite


def test_chunk_ranges_split_the_store_without_gap_or_overlap(monkeypatch):
    """The parallel load's workers each copy one rowid range: together, every chunk exactly once."""
    import numpy as np

    monkeypatch.setattr(pg_store, "BATCH", 3)
    lite, vectors = _chunk_store(10), np.zeros((10, 4), dtype=np.float16)
    cursor, reports = _CopyCursor(), []
    counts = [pg_store._copy_range(cursor, lite, vectors, low, high, reports.append) for low, high in [(0, 4), (4, 10)]]
    assert counts == [4, 6]
    assert sorted(map(int, cursor.copied)) == list(range(10))
    assert reports == [3, 4, 3, 6]  # after every batch of each range, the last one partial
