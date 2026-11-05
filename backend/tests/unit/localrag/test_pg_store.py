import gzip
import re
import sqlite3
import threading

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


class FakeStore:
    """execute() answers the SQL the sync and the place detection send."""

    def __init__(self, files: dict[str, bytes], built: str, places: list[tuple] = ()):
        self.files, self.meta, self.places = files, {"built": built}, list(places)

    def execute(self, sql: str, params: tuple = ()) -> list:
        if sql.startswith("SELECT path FROM"):
            return [(path,) for path in self.files]
        if sql.startswith("SELECT path, data"):
            return [(path, gzip.compress(self.files[path])) for path in params[0]]
        if "corpus_places" in sql:
            return [row for row in self.places if row[0] in params[0]]
        raise AssertionError(sql)


@pytest.fixture
def install(tmp_path, monkeypatch):
    """An install without data: the sync writes corpus/ files under the data root, geo/ files in the geo folder."""
    monkeypatch.setattr(pg_store, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(pg_store, "DATA_DIR", tmp_path / "data" / "corpus")
    monkeypatch.setattr(pg_store, "GEO_DIR", tmp_path / "geo")
    return tmp_path


def test_sync_writes_the_missing_files(install):
    store = FakeStore({"corpus/plans.jsonl": b"{}\n", "geo/0380/plans.geojson": b'{"features": []}'}, "v1")
    assert sorted(pg_store.sync_files(store)) == ["corpus/plans.jsonl", "geo/0380/plans.geojson"]
    assert (install / "data" / "corpus" / "plans.jsonl").read_bytes() == b"{}\n"
    assert (install / "geo" / "0380" / "plans.geojson").exists()
    assert pg_store.sync_files(store) == []  # same build: nothing to write


def test_sync_keeps_files_it_did_not_write(install):
    own = install / "data" / "corpus" / "plans.jsonl"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"the full registry\n")  # a machine with the national corpus
    store = FakeStore({"corpus/plans.jsonl": b"demo registry\n"}, "v1")
    assert pg_store.sync_files(store) == []
    assert pg_store.sync_files(FakeStore(store.files, "v2")) == []  # a new build does not touch it either
    assert own.read_bytes() == b"the full registry\n"


def test_sync_refreshes_its_files_on_a_new_build(install):
    pg_store.sync_files(FakeStore({"corpus/plans.jsonl": b"old\n"}, "v1"))
    assert pg_store.sync_files(FakeStore({"corpus/plans.jsonl": b"new\n"}, "v2")) == ["corpus/plans.jsonl"]
    assert (install / "data" / "corpus" / "plans.jsonl").read_bytes() == b"new\n"


def test_places_detected_in_one_query():
    store = FakeStore({}, "v1", places=[("fyrisån", "0380", 40), ("kårsta", "0115", 9), ("kårsta", "1880", 1),
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
