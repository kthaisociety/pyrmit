"""Unit tests for corpus_admin (issue #114): upload parts and resume, the replace job's steps on a fake database (no
Postgres, PCR-0011), the roll back, the download link."""
import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import corpus_admin
import models
from corpus_admin import CorpusError

DUMP = b"PGDMP" + bytes(range(256)) * 40  # 10,245 bytes standing in for a dump
TOC = "7; 2615 1 SCHEMA - corpus_next pyrmit\n3641; 0 2 TABLE DATA corpus_next corpus_chunks pyrmit\n"
OWNER = models.User(id="o", email="owner@kth.se", role="owner")


def manifest(**changes):
    return {"format": "pyrmit-corpus-dump", "version": 1, "schema": "corpus_next", "model": "st-bge-m3", "dim": 1024,
            "chunks": 4500, "kommuner": ["0115", "0380"], "label_schema_version": 1, "built": "2026-11-14T19:45:32",
            "database_mb": 15.5, "dump_file": "b.dump", "dump_bytes": len(DUMP),
            "sha256": hashlib.sha256(DUMP).hexdigest(), **changes}


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("CORPUS_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CORPUS_UPLOAD_PART_MB", str(4096 / (1 << 20)))  # 4 KB parts
    monkeypatch.setenv("LOCAL_RAG_MODEL", "or-bge-m3")
    monkeypatch.setenv("CORPUS_DB_DISK_GB", "40")


def send(upload, data=DUMP, stop_after=None):
    """The browser's loop: parts from what the server holds."""
    state, parts = upload, 0
    while state["received"] < state["size"] and (stop_after is None or parts < stop_after):
        end = min(state["received"] + state["part_bytes"], state["size"])
        state = corpus_admin.write_part(state["id"], state["received"], data[state["received"]:end])
        parts += 1
    return state


# --- uploads ----------------------------------------------------------------------------------------------------------

def test_parts_assemble_the_file():
    state = send(corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER))
    assert state["complete"] and state["received"] == len(DUMP)
    assert (corpus_admin.upload_root() / state["id"] / "dump").read_bytes() == DUMP


def test_the_same_file_resumes_where_it_stopped():
    first = send(corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER), stop_after=2)
    assert first["received"] == 8192 and not first["complete"]
    again = corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER)
    assert again["id"] == first["id"] and again["received"] == 8192
    assert send(again)["complete"]
    assert (corpus_admin.upload_root() / first["id"] / "dump").read_bytes() == DUMP


def test_another_file_replaces_an_unfinished_upload():
    first = send(corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER), stop_after=1)
    other = corpus_admin.create_upload("c.dump", len(DUMP), manifest(sha256="cd" * 32), OWNER)
    assert other["id"] != first["id"] and other["received"] == 0
    assert [upload["id"] for upload in corpus_admin.list_uploads()] == [other["id"]]


def test_a_part_sent_again_changes_nothing_and_a_gap_is_refused():
    state = send(corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER), stop_after=2)
    assert corpus_admin.write_part(state["id"], 4096, DUMP[4096:8192])["received"] == 8192  # its answer was lost
    with pytest.raises(CorpusError, match="offset 8192") as gap:
        corpus_admin.write_part(state["id"], 8193, b"x")
    assert gap.value.status == 409


def test_a_part_past_the_end_or_too_big_is_refused():
    state = corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER)
    with pytest.raises(CorpusError) as big:
        corpus_admin.write_part(state["id"], 0, b"x" * 4097)
    assert big.value.status == 413
    state = send(state, stop_after=2)  # 8,192 of 10,245 bytes
    with pytest.raises(CorpusError, match="past the end"):
        corpus_admin.write_part(state["id"], 8192, b"x" * 4096)


def test_an_upload_with_a_bad_manifest_or_without_room_is_refused(monkeypatch):
    from localrag.corpus_dump import InvalidManifest

    with pytest.raises(InvalidManifest):
        corpus_admin.create_upload("b.dump", len(DUMP) + 1, manifest(), OWNER)
    monkeypatch.setattr(corpus_admin.shutil, "disk_usage", lambda path: type("U", (), {"free": 100})())
    with pytest.raises(CorpusError) as full:
        corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER)
    assert full.value.status == 507


def test_upload_ids_are_never_paths():
    with pytest.raises(CorpusError) as error:
        corpus_admin.upload_state("../../etc")
    assert error.value.status == 404


# --- free space -------------------------------------------------------------------------------------------------------

GB = 1e9


def test_space_plan():
    assert corpus_admin.space_plan(40 * GB, 30 * GB, 9 * GB, 0, 14 * GB) == "ok"
    assert corpus_admin.space_plan(40 * GB, 34 * GB, 9 * GB, 4 * GB, None) == "ok"  # a leftover corpus_next goes
    assert corpus_admin.space_plan(40 * GB, 34 * GB, 14 * GB, 0, 14 * GB) == "drop_prev"
    with pytest.raises(CorpusError, match="needs 30.0 GB, 6.0 GB is free"):
        corpus_admin.space_plan(40 * GB, 34 * GB, 30 * GB, 0, 14 * GB)


# --- the replace job ----------------------------------------------------------------------------------------------------

class FakeOps:
    """corpus_admin.PgOps over a set of schema names, recording what the job asks of the database."""

    def __init__(self, schemas=("corpus",), facts=None, lock=True, prev_size=14 * GB, database=20 * GB):
        self.now = set(schemas)
        self.calls: list = []
        self.got_lock, self.prev_size, self.database = lock, prev_size, database
        self.metas = {"corpus": {"model": "st-bge-m3", "dim": 1024, "chunks": 3000, "kommuner": ["0115"],
                                 "built": "2026-11-01"},
                      "corpus_prev": {"model": "st-bge-m3", "dim": 1024, "chunks": 2000, "kommuner": [],
                                      "built": "2026-10-01"}}
        self.facts_ = facts or {"meta": {"model": "st-bge-m3", "dim": 1024, "chunks": 4500}, "chunks": 4500,
                                "dim": 1024, "columns": list(__import__("localrag.store").store.COLUMNS),
                                "query_error": None}

    @contextmanager
    def lock(self):
        yield self.got_lock

    def lock_free(self):
        return self.got_lock

    def schemas(self):
        return set(self.now)

    def schema_size(self, schema):
        return (self.prev_size if schema == "corpus_prev" else 1 * GB) if schema in self.now else None

    def database_size(self):
        return int(self.database)

    def meta(self, schema):
        return self.metas.get(schema) if schema in self.now else None

    def drop(self, schema):
        self.calls.append(("drop", schema))
        self.now.discard(schema)

    def toc(self, path):
        return TOC

    def restore(self, path, progress):
        self.calls.append(("restore", path.read_bytes() == DUMP))
        progress("pg_restore: finished item 3641 TABLE DATA corpus_chunks")
        self.now.add("corpus_next")

    def facts(self, schema):
        return self.facts_

    def run(self, statements, uploaded=None):
        self.calls.append(("run", statements, uploaded))
        for statement in statements:
            words = statement.split()
            if words[0] == "DROP":
                self.now.discard(words[2])
            else:  # ALTER SCHEMA a RENAME TO b
                self.now.discard(words[2])
                self.now.add(words[5])


@pytest.fixture
def sessions():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.CorpusVersion.__table__])
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(models.User(id="o", name="Owner", email="owner@kth.se", role="owner"))
        db.commit()
    yield factory
    engine.dispose()


def run_job(sessions, ops, upload_manifest=None, data=DUMP):
    upload = send(corpus_admin.create_upload("b.dump", len(data), upload_manifest or manifest(), OWNER), data)
    refreshed = []
    with sessions() as db:
        row = corpus_admin.start_replace(db, upload["id"], OWNER, ops=ops, start=False)
        row_id = row.id
    corpus_admin.run_replace(row_id, upload["id"], ops, sessions, refresh=lambda: refreshed.append(True))
    with sessions() as db:
        row = db.get(models.CorpusVersion, row_id)
        return row, upload["id"], refreshed


def test_a_valid_dump_goes_live_and_the_live_one_becomes_the_previous(sessions):
    ops = FakeOps(schemas=("corpus", "corpus_prev"))
    row, upload_id, refreshed = run_job(sessions, ops)
    assert row.status == "done" and row.detail == "Live: 4,500 chunks of st-bge-m3"
    assert ("restore", True) in ops.calls
    run = next(call for call in ops.calls if call[0] == "run")
    assert run[1] == ["DROP SCHEMA corpus_prev CASCADE", "ALTER SCHEMA corpus RENAME TO corpus_prev",
                      "ALTER SCHEMA corpus_next RENAME TO corpus"]
    assert run[2]["by"] == "owner@kth.se" and run[2]["file"] == "b.dump"
    assert ops.now == {"corpus", "corpus_prev"}
    assert refreshed == [True]
    assert not (corpus_admin.upload_root() / upload_id).exists()  # the uploaded file is deleted after success
    assert row.progress["phase"] == "done"


def test_an_invalid_dump_is_dropped_and_the_live_corpus_untouched(sessions):
    facts = FakeOps().facts_ | {"chunks": 4499}
    ops = FakeOps(facts=facts)
    row, upload_id, refreshed = run_job(sessions, ops)
    assert row.status == "failed" and "Chunk counts differ: rows 4499" in row.detail
    assert not any(call[0] == "run" for call in ops.calls)  # no swap
    assert ops.calls[-1] == ("drop", "corpus_next") and ops.now == {"corpus"}
    assert refreshed == []
    assert (corpus_admin.upload_root() / upload_id).exists()  # kept for a retry


def test_a_damaged_upload_is_refused_before_the_restore_and_deleted(sessions):
    damaged = bytes([DUMP[0] ^ 1]) + DUMP[1:]
    ops = FakeOps()
    row, upload_id, _ = run_job(sessions, ops, data=damaged)
    assert row.status == "failed" and "sha256" in row.detail
    assert not any(call[0] in ("restore", "run") for call in ops.calls)
    assert not (corpus_admin.upload_root() / upload_id).exists()


def test_a_failed_restore_leaves_the_live_corpus(sessions):
    ops = FakeOps()

    def failing(path, progress):
        ops.now.add("corpus_next")
        raise CorpusError("pg_restore failed: disk full", 500)

    ops.restore = failing
    row, _, _ = run_job(sessions, ops)
    assert row.status == "failed" and row.detail == "pg_restore failed: disk full"
    assert ops.now == {"corpus"}


def test_another_running_job_is_left_alone(sessions):
    ops = FakeOps(schemas=("corpus", "corpus_next"), lock=False)
    row, _, _ = run_job(sessions, ops)
    assert row.status == "failed" and "Another corpus job" in row.detail
    assert ops.calls == []  # its corpus_next is not dropped


def test_without_room_the_previous_version_goes_first(sessions):
    ops = FakeOps(schemas=("corpus", "corpus_prev"), database=39 * GB)
    row, _, _ = run_job(sessions, ops, manifest(database_mb=10_000))  # 11.5 GB with the margin, 1 GB free
    assert row.status == "done" and "no roll back" in row.detail
    assert ops.calls[0] == ("drop", "corpus_prev")


def test_a_job_left_running_by_a_restart_is_marked_failed(sessions):
    with sessions() as db:
        db.add(models.CorpusVersion(action="replace", status="running", started_at=datetime.now(UTC) - timedelta(hours=1)))
        db.commit()
        assert corpus_admin.running_job(db, FakeOps(lock=True)) is None
        row = db.query(models.CorpusVersion).one()
        assert row.status == "failed" and "Interrupted" in row.detail


def test_a_job_another_process_runs_is_reported_running(sessions):
    with sessions() as db:
        db.add(models.CorpusVersion(action="replace", status="running", started_at=datetime.now(UTC) - timedelta(hours=1)))
        db.commit()
        assert corpus_admin.running_job(db, FakeOps(lock=False)).status == "running"


def test_a_second_job_is_refused_while_one_runs(sessions):
    upload = send(corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER))
    with sessions() as db:
        db.add(models.CorpusVersion(action="replace", status="running", started_at=datetime.now(UTC)))
        db.commit()
        with pytest.raises(CorpusError, match="already running"):
            corpus_admin.start_replace(db, upload["id"], OWNER, ops=FakeOps(lock=False), start=False)


def test_an_unfinished_upload_cannot_be_restored(sessions):
    upload = send(corpus_admin.create_upload("b.dump", len(DUMP), manifest(), OWNER), stop_after=1)
    with sessions() as db, pytest.raises(CorpusError, match="4,096 of 10,245"):
        corpus_admin.start_replace(db, upload["id"], OWNER, ops=FakeOps(), start=False)


def test_app_dim_comes_from_the_live_corpus_when_the_model_has_none():
    assert corpus_admin.app_dim(FakeOps(), "or-bge-m3") == 1024  # models.toml has no dim for it
    assert corpus_admin.app_dim(FakeOps(schemas=()), "or-bge-m3") is None


# --- roll back --------------------------------------------------------------------------------------------------------

def test_roll_back_swaps_back_and_is_recorded(sessions):
    ops, refreshed = FakeOps(schemas=("corpus", "corpus_prev")), []
    with sessions() as db:
        row = corpus_admin.rollback(db, OWNER, ops=ops, refresh=lambda: refreshed.append(True))
        assert row.action == "rollback" and row.chunks == 2000
    assert ops.calls[0][1][0] == "ALTER SCHEMA corpus RENAME TO corpus_rollback"
    assert refreshed == [True]


@pytest.mark.parametrize("ops, message", [
    (FakeOps(schemas=("corpus",)), "no previous version"),
    (FakeOps(schemas=("corpus", "corpus_prev"), lock=False), "job is running"),
])
def test_roll_back_is_refused_without_a_previous_version_or_during_a_job(sessions, ops, message):
    with sessions() as db, pytest.raises(CorpusError, match=message):
        corpus_admin.rollback(db, OWNER, ops=ops, refresh=lambda: None)
    assert not any(call[0] == "run" for call in ops.calls)


def test_roll_back_is_refused_to_vectors_the_app_cannot_query(sessions):
    ops = FakeOps(schemas=("corpus", "corpus_prev"))
    ops.metas["corpus_prev"]["model"] = "st-arctic-l-v2"
    with sessions() as db, pytest.raises(CorpusError, match="st-arctic-l-v2 vectors"):
        corpus_admin.rollback(db, OWNER, ops=ops, refresh=lambda: None)


# --- download ---------------------------------------------------------------------------------------------------------

def test_the_download_link_names_its_owner(sessions):
    token = corpus_admin.download_token(OWNER)
    with sessions() as db:
        assert corpus_admin.download_user(db, token).id == "o"
        db.get(models.User, "o").role = "developer"  # no longer an owner: the link stops working
        db.commit()
        with pytest.raises(CorpusError) as error:
            corpus_admin.download_user(db, token)
        assert error.value.status == 403


def test_a_sign_in_token_or_an_expired_link_is_no_download_link(sessions):
    import jwt

    from security import ALGORITHM, create_access_token, get_jwt_secret_key

    sign_in = create_access_token("user:o", "sid", datetime.now(UTC) + timedelta(minutes=5))
    expired = jwt.encode({"sub": "user:o", "purpose": "corpus-download", "exp": datetime.now(UTC) - timedelta(seconds=1)},
                         get_jwt_secret_key(), algorithm=ALGORITHM)
    with sessions() as db:
        for token in (sign_in, expired, "nonsense"):
            with pytest.raises(CorpusError) as error:
                corpus_admin.download_user(db, token)
            assert error.value.status == 401


def test_a_download_link_is_never_a_sign_in():
    from fastapi import HTTPException

    from security import decode_access_token

    with pytest.raises(HTTPException):
        decode_access_token(corpus_admin.download_token(OWNER))


def test_the_active_manifest_says_its_schema():
    assert corpus_admin.active_manifest(FakeOps())["schema"] == "corpus"
    with pytest.raises(CorpusError):
        corpus_admin.active_manifest(FakeOps(schemas=()))
    assert json.dumps(corpus_admin.active_manifest(FakeOps()))  # serialisable
