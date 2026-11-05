"""#57: the plan polygons of every fetched kommun in the corpus database, and an install without local data getting
them from there."""

import gzip
import json
from pathlib import Path

import pytest

from localrag import pg_store


class FakeDatabase:
    """execute() answers the SQL load_files and sync_files send, over an in-memory corpus_files and corpus_meta."""

    def __init__(self, files: dict[str, bytes] | None = None, size_mb: float = 600.0, built: str = "v1"):
        self.files = {path: gzip.compress(data) for path, data in (files or {}).items()}
        self.meta = {"built": built}
        self.size_mb = size_mb

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
        raise AssertionError(sql)

    def text(self, path: str) -> bytes:
        return gzip.decompress(self.files[path])


def snapshot(geo: Path, code: str, plans: str) -> None:
    folder = geo / code
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"code": code}), encoding="utf-8")
    (folder / "plans.geojson").write_text(plans, encoding="utf-8")
    (folder / "plan_links.jsonl").write_text("", encoding="utf-8")


@pytest.fixture
def geo(tmp_path, monkeypatch) -> Path:
    """Two kommuner with a snapshot on disk and one folder without a manifest (a fetch that never finished)."""
    monkeypatch.setattr(pg_store, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(pg_store, "DATA_DIR", tmp_path / "data" / "corpus")
    monkeypatch.setattr(pg_store, "GEO_DIR", tmp_path / "geo")
    snapshot(tmp_path / "geo", "0380", '{"features": ["uppsala"]}')
    snapshot(tmp_path / "geo", "0180", '{"features": ["stockholm"]}')
    (tmp_path / "geo" / "0115").mkdir()
    (tmp_path / "geo" / "0115" / "plans.geojson").write_text("{}", encoding="utf-8")
    return tmp_path / "geo"


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

