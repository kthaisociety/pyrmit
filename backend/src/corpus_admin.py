"""
Managing the corpus from the Database tab (issue #114): owners replace it with a dump made by localrag.export, roll it
back to the previous version, or download it. The corpus lives in Postgres schema `corpus` (localrag.pg_store); a
replace restores the dump into `corpus_next` beside it, validates it, then swaps in one transaction:

    DROP SCHEMA corpus_prev CASCADE; ALTER SCHEMA corpus RENAME TO corpus_prev; ALTER SCHEMA corpus_next RENAME TO corpus

so exactly one previous version is kept and a roll back is three renames. Open connections read the new corpus at
their next query; the app's caches are refreshed (localrag.service.refresh_corpus). No user is notified.

    upload     CORPUS_UPLOAD_DIR/<id>/{state.json, dump}: parts of PART_MB at an offset, resumable (the received
               size is the file's size), one upload at a time, sha256 checked against the manifest before the restore
    job        a corpus_versions row (status, progress), run in a thread under a Postgres advisory lock (one at a
               time across processes): sha256, dump contents, free space, pg_restore -j 4, validation, swap, refresh

The database work goes through PgOps so the job's steps are tested without Postgres (PCR-0011).
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

import models
from corpus.common import BACKEND_DIR
from localrag import corpus_dump
from localrag.pg_store import CORPUS_SCHEMA, NEXT_SCHEMA, PREV_SCHEMA, schema_url

logger = logging.getLogger(__name__)

LOCK_KEY = 114_000_114  # pg_advisory_lock key of the corpus jobs
RESTORE_JOBS = 4  # pg_restore -j
SPACE_MARGIN = 1.15  # a restore needs the dump's size in Postgres plus indexes being built and WAL
DOWNLOAD_TOKEN_MINUTES = 5


class CorpusError(Exception):
    """A refused or failed corpus action. `status` is the HTTP status the router answers with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


# --- settings -------------------------------------------------------------------------------------------------------

def database_url() -> str:
    """The corpus database: CORPUS_DATABASE_URL, else DATABASE_URL (the deployed app has only the one, #110)."""
    url = os.getenv("CORPUS_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise CorpusError("No DATABASE_URL", 503)
    return url


def upload_root() -> Path:
    return Path(os.getenv("CORPUS_UPLOAD_DIR", "").strip() or BACKEND_DIR / "data" / "uploads" / "corpus")


def part_bytes() -> int:
    return int(float(os.getenv("CORPUS_UPLOAD_PART_MB", "50")) * (1 << 20))


def disk_limit_bytes() -> float:
    """The corpus database's disk (CORPUS_DB_DISK_GB, default the 40 GB asked of IT): Postgres can't tell its free
    space, so a restore checks against this."""
    return float(os.getenv("CORPUS_DB_DISK_GB", "40")) * 1e9


def app_model() -> str:
    return os.getenv("LOCAL_RAG_MODEL", "st-arctic-l-v2").strip()


# --- uploads --------------------------------------------------------------------------------------------------------

_UPLOAD_ID = re.compile(r"[0-9a-f]{32}")
_upload_lock = threading.Lock()


def _upload_dir(upload_id: str) -> Path:
    if not _UPLOAD_ID.fullmatch(upload_id or ""):
        raise CorpusError("No such upload", 404)
    path = upload_root() / upload_id
    if not (path / "state.json").is_file():
        raise CorpusError("No such upload", 404)
    return path


def upload_state(upload_id: str) -> dict:
    path = _upload_dir(upload_id)
    state = json.loads((path / "state.json").read_text(encoding="utf-8"))
    received = (path / "dump").stat().st_size if (path / "dump").exists() else 0
    return {**state, "id": upload_id, "received": received, "complete": received == state["size"],
            "part_bytes": part_bytes()}


def list_uploads() -> list[dict]:
    root = upload_root()
    if not root.is_dir():
        return []
    uploads = []
    for path in sorted(root.iterdir()):
        if _UPLOAD_ID.fullmatch(path.name) and (path / "state.json").is_file():
            uploads.append(upload_state(path.name))
    return uploads


def create_upload(file_name: str, size: int, manifest: dict, user: models.User) -> dict:
    """Start an upload, or resume the unfinished one of the same file (same name, size and sha256). Other uploads are
    discarded: one at a time, the volume holds one dump."""
    corpus_dump.check_manifest(manifest, size)
    file_name = Path(file_name).name[:200] or "corpus.dump"
    with _upload_lock:
        for upload in list_uploads():
            if (upload["file_name"], upload["size"], upload["manifest"]["sha256"]) == (file_name, size,
                                                                                         manifest["sha256"]):
                return upload
        for upload in list_uploads():
            shutil.rmtree(upload_root() / upload["id"], ignore_errors=True)
        root = upload_root()
        root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(root).free
        if free < size:
            raise CorpusError(f"The upload volume has {free / 1e9:.1f} GB free, the dump needs {size / 1e9:.1f} GB",
                              507)
        upload_id = uuid.uuid4().hex
        path = root / upload_id
        path.mkdir()
        (path / "dump").touch()
        state = {"file_name": file_name, "size": size, "manifest": manifest, "user_email": user.email,
                 "created": datetime.now(UTC).isoformat(timespec="seconds")}
        (path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return upload_state(upload_id)


def write_part(upload_id: str, offset: int, data: bytes) -> dict:
    """Write one part at `offset`. The offset may repeat bytes already received (a part sent again after a lost
    answer) but never leave a gap. Returns the upload's state."""
    state = upload_state(upload_id)
    if len(data) > part_bytes():
        raise CorpusError(f"A part is at most {part_bytes():,} bytes", 413)
    if offset < 0 or offset > state["received"]:
        raise CorpusError(f"Expected a part at offset {state['received']}, got {offset}", 409)
    if offset + len(data) > state["size"]:
        raise CorpusError("The part goes past the end of the file", 400)
    with (_upload_dir(upload_id) / "dump").open("r+b") as file:
        file.seek(offset)
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    return upload_state(upload_id)


def discard_upload(upload_id: str) -> None:
    if running_job_upload() == upload_id:
        raise CorpusError("This upload is being restored")
    shutil.rmtree(_upload_dir(upload_id), ignore_errors=True)


# --- Postgres -------------------------------------------------------------------------------------------------------

def space_plan(limit: float, database: int, needed: float, next_size: int, prev_size: int | None) -> str:
    """Whether a restore fits on the database disk: "ok", "drop_prev" (it fits once the previous version goes, which
    loses the roll back), or a CorpusError. A leftover corpus_next is dropped anyway, so its space counts as free."""
    free = limit - database + next_size
    if needed <= free:
        return "ok"
    if prev_size is not None and needed <= free + prev_size:
        return "drop_prev"
    raise CorpusError(f"Not enough space on the database disk: the restore needs {needed / 1e9:.1f} GB, "
                      f"{max(free, 0) / 1e9:.1f} GB is free of CORPUS_DB_DISK_GB={limit / 1e9:.0f}")


class PgOps:
    """The database side of the corpus jobs, on the corpus database."""

    def __init__(self, url: str):
        self.url = url

    def _connect(self, url: str | None = None, autocommit: bool = True):
        import psycopg2

        connection = psycopg2.connect(url or self.url, connect_timeout=30)
        connection.autocommit = autocommit
        return connection

    def _rows(self, sql: str, params: tuple = (), url: str | None = None) -> list:
        connection = self._connect(url)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall() if cursor.description else []
        finally:
            connection.close()

    @contextmanager
    def lock(self) -> Iterator[bool]:
        """The corpus job lock, held while the block runs; yields False when another job holds it."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
                got = cursor.fetchone()[0]
            yield got
        finally:
            connection.close()  # closing the session releases the lock

    def lock_free(self) -> bool:
        with self.lock() as got:
            return got

    def schemas(self) -> set[str]:
        return {row[0] for row in self._rows("SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
                                             ([CORPUS_SCHEMA, NEXT_SCHEMA, PREV_SCHEMA],))}

    def schema_size(self, schema: str) -> int | None:
        """Bytes of a schema's tables with their indexes and TOAST, None when the schema doesn't exist."""
        if not self._rows("SELECT to_regnamespace(%s) IS NOT NULL", (schema,))[0][0]:
            return None
        return int(self._rows("SELECT COALESCE(SUM(pg_total_relation_size(oid)), 0) FROM pg_class "
                              "WHERE relnamespace = %s::regnamespace AND relkind IN ('r', 'm')", (schema,))[0][0])

    def database_size(self) -> int:
        return int(self._rows("SELECT pg_database_size(current_database())")[0][0])

    def meta(self, schema: str) -> dict | None:
        """corpus_meta of a schema, None when the schema or its table is missing."""
        if not self._rows("SELECT to_regclass(%s) IS NOT NULL", (f"{schema}.corpus_meta",))[0][0]:
            return None
        return dict(self._rows(f"SELECT key, value FROM {schema}.corpus_meta"))

    def drop(self, schema: str) -> None:
        self._rows(f"DROP SCHEMA IF EXISTS {schema} CASCADE")

    def toc(self, path: Path) -> str:
        return subprocess.run(["pg_restore", "-l", str(path)], capture_output=True, text=True, check=True).stdout

    def restore(self, path: Path, progress: Callable[[str], None]) -> None:
        """pg_restore -j into the schema the dump holds (corpus_next); progress(line) for every verbose line."""
        self._rows("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
        process = subprocess.Popen(
            ["pg_restore", "-j", str(RESTORE_JOBS), "--no-owner", "--no-privileges", "--exit-on-error", "--verbose",
             "-d", self.url, str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        assert process.stderr is not None
        tail: list[str] = []
        for line in process.stderr:
            progress(line)
            tail = (tail + [line.strip()])[-5:]
        if process.wait() != 0:
            raise CorpusError("pg_restore failed: " + " | ".join(t for t in tail if t), 500)

    def facts(self, schema: str) -> dict:
        """What validation_errors checks, read from the restored schema, and a test query through PgStore."""
        import numpy as np

        from localrag.pg_store import PgStore

        url = schema_url(self.url, schema)
        facts = {"meta": self.meta(schema), "query_error": None}
        facts["chunks"] = self._rows(f"SELECT COUNT(*) FROM {schema}.corpus_chunks")[0][0]
        facts["columns"] = [row[0] for row in self._rows(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = "
            "'corpus_chunks'", (schema,))]
        facts["dim"] = self._rows("SELECT atttypmod FROM pg_attribute WHERE attrelid = to_regclass(%s) AND attname = "
                                  "'embedding'", (f"{schema}.corpus_chunks",))[0][0]
        try:  # the first chunk's own vector must find it: the vectors, the views and the pool filters work
            store = PgStore(self.url, schema)
            rowid, kind, code, vector = self._rows("SELECT rowid, kind, kommun_code, embedding::text FROM corpus_chunks "
                                                   "ORDER BY rowid LIMIT 1", url=url)[0]
            pool, kommuner = ("law", None) if kind == "law" else ("local", [code])
            found = store.dense_top(np.array(json.loads(vector), dtype=np.float32), pool, kommuner, 5)
            if rowid not in found:
                facts["query_error"] = f"chunk {rowid} not found by its own vector"
            elif not store.query("SELECT chunk_id FROM chunks WHERE rowid = ?", (rowid,)):
                facts["query_error"] = "the chunks view is empty"
        except Exception as error:  # noqa: BLE001 - reported as a validation error
            facts["query_error"] = repr(error)
        return facts

    def run(self, statements: list[str], uploaded: dict | None = None) -> None:
        """The statements in one transaction; `uploaded` is first written into corpus_next's corpus_meta (who
        uploaded it, when, which file), so each version carries its own."""
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '30s'")
                if uploaded is not None:
                    cursor.execute(f"INSERT INTO {NEXT_SCHEMA}.corpus_meta VALUES ('uploaded', %s) ON CONFLICT (key) "
                                   "DO UPDATE SET value = EXCLUDED.value", (json.dumps(uploaded),))
                for statement in statements:
                    cursor.execute(statement)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def dump_command(self, schema: str = CORPUS_SCHEMA) -> list[str]:
        return ["pg_dump", "-Fc", "--compress=zstd:3", "--no-owner", "--no-privileges", "-n", schema, "-d", self.url]


def get_ops() -> PgOps:
    return PgOps(database_url())


def refresh_app() -> None:
    """After a swap or a roll back: the retriever's meta and files, the agent tools."""
    from localrag.service import refresh_corpus

    refresh_corpus()


# --- the replace job ------------------------------------------------------------------------------------------------

_job_threads: dict[int, threading.Thread] = {}


def running_job(db: Session, ops: PgOps | None = None) -> models.CorpusVersion | None:
    """The replace job running now. A row left "running" while nobody holds the lock (the backend restarted during
    the job) is marked failed."""
    row = (db.query(models.CorpusVersion).filter(models.CorpusVersion.status == "running")
           .order_by(models.CorpusVersion.id.desc()).first())
    if row is None:
        return None
    thread = _job_threads.get(row.id)
    if thread is not None and thread.is_alive():
        return row
    if time.time() - row.started_at.timestamp() > 60 and (ops or get_ops()).lock_free():
        row.status, row.finished_at = "failed", datetime.now(UTC)
        row.detail = "Interrupted: the backend stopped during the job. The live corpus was not changed"
        db.commit()
        return None
    return row


def running_job_upload() -> str | None:
    for thread in _job_threads.values():
        if thread.is_alive():
            return getattr(thread, "upload_id", None)
    return None


def start_replace(db: Session, upload_id: str, user: models.User, ops: PgOps | None = None,
                  session_factory: Callable[[], Session] | None = None, start: bool = True) -> models.CorpusVersion:
    """Start the replace job of a complete upload; returns its corpus_versions row."""
    state = upload_state(upload_id)
    if not state["complete"]:
        raise CorpusError(f"The upload has {state['received']:,} of {state['size']:,} bytes")
    if running_job(db, ops) is not None:
        raise CorpusError("A corpus job is already running")
    manifest = state["manifest"]
    row = models.CorpusVersion(action="replace", status="running", user_id=user.id, user_email=user.email,
                               file_name=state["file_name"], model=manifest["model"], chunks=manifest["chunks"],
                               kommuner=len(manifest.get("kommuner") or []), built=str(manifest["built"]),
                               progress={"phase": "queued", "percent": 0, "message": "Waiting to start"})
    db.add(row)
    db.commit()
    db.refresh(row)
    if start:
        thread = threading.Thread(target=run_replace, name=f"corpus-replace-{row.id}", daemon=True,
                                  args=(row.id, upload_id, ops or get_ops(), session_factory or _session))
        thread.upload_id = upload_id  # type: ignore[attr-defined]
        _job_threads[row.id] = thread
        thread.start()
    return row


def _session() -> Session:
    from db.database import SessionLocal

    return SessionLocal()


class _Progress:
    """Writes the job's progress to its row, at most once a second (the panel polls every few seconds)."""

    def __init__(self, db: Session, row: models.CorpusVersion):
        self.db, self.row, self.last = db, row, 0.0

    def __call__(self, phase: str, percent: float, message: str, force: bool = False) -> None:
        if not force and time.monotonic() - self.last < 1:
            return
        self.last = time.monotonic()
        self.row.progress = {"phase": phase, "percent": round(min(max(percent, 0), 100), 1), "message": message}
        self.db.commit()


def app_dim(ops: PgOps, model: str) -> int | None:
    """The vector dimension the app's queries have: its model's (models.toml), else the live corpus's when it holds
    the same vectors, else unknown."""
    from localrag.index import load_model_config
    from localrag.pg_store import same_vectors

    try:
        dim = load_model_config(model).dim
    except KeyError:
        dim = None
    if dim:
        return int(dim)
    live = ops.meta(CORPUS_SCHEMA)
    if live and live.get("model") and same_vectors(model, live["model"]):
        return int(live["dim"])
    return None


def run_replace(row_id: int, upload_id: str, ops: PgOps, session_factory: Callable[[], Session],
                refresh: Callable[[], None] = refresh_app) -> None:
    """The replace job (see the module docstring). On any failure corpus_next is dropped and the live corpus stays as
    it was; the upload stays for a retry unless its bytes are wrong."""
    from localrag.pg_store import same_vectors
    from localrag.store import COLUMNS

    db = session_factory()
    row = db.get(models.CorpusVersion, row_id)
    progress = _Progress(db, row)
    holding = False
    try:
        with ops.lock() as got:
            if not got:
                raise CorpusError("Another corpus job is running")
            holding = True
            state = upload_state(upload_id)
            manifest, path = state["manifest"], _upload_dir(upload_id) / "dump"

            progress("checking", 0, "Checking the file's sha256", force=True)
            digest = corpus_dump.sha256_file(path, lambda done: progress(
                "checking", 100 * done / state["size"], f"Checking the file's sha256: {done / 1e9:.1f} GB"))
            if digest != manifest["sha256"]:
                shutil.rmtree(_upload_dir(upload_id), ignore_errors=True)
                raise CorpusError("The file's sha256 is not the manifest's: the upload was damaged. Upload it again")
            try:
                entries = corpus_dump.toc_entries(ops.toc(path))
            except (ValueError, subprocess.CalledProcessError) as error:
                raise CorpusError(f"Not a dump this server restores: {error}") from None

            progress("space", 0, "Checking the database disk", force=True)
            schemas = ops.schemas()
            plan = space_plan(disk_limit_bytes(), ops.database_size(), manifest["database_mb"] * 1e6 * SPACE_MARGIN,
                              (ops.schema_size(NEXT_SCHEMA) or 0) if NEXT_SCHEMA in schemas else 0,
                              ops.schema_size(PREV_SCHEMA) if PREV_SCHEMA in schemas else None)
            notes = []
            if plan == "drop_prev":
                ops.drop(PREV_SCHEMA)
                notes.append("the previous version was deleted to make room, so there is no roll back")
            ops.drop(NEXT_SCHEMA)

            finished = 0

            def restored(line: str) -> None:
                nonlocal finished
                if corpus_dump.restore_progress(line):
                    finished += 1
                progress("restoring", 100 * finished / entries, f"Restoring: {line.strip()[:160]}")

            progress("restoring", 0, f"Restoring {entries} items with pg_restore -j {RESTORE_JOBS}", force=True)
            ops.restore(path, restored)

            progress("validating", 0, "Validating the restored corpus", force=True)
            model = app_model()
            errors = corpus_dump.validation_errors(manifest, ops.facts(NEXT_SCHEMA), model, app_dim(ops, model),
                                                   same_vectors, COLUMNS)
            if errors:
                raise CorpusError("The restored corpus is not valid: " + "; ".join(errors))

            progress("swapping", 0, "Making it live", force=True)
            ops.run(corpus_dump.swap_statements(ops.schemas()),
                    uploaded={"by": row.user_email, "at": datetime.now(UTC).isoformat(timespec="seconds"),
                              "file": row.file_name})
            try:
                refresh()
            except Exception:
                logger.exception("Refreshing the corpus caches after the swap failed")
                notes.append("refreshing the app's caches failed: restart the backend")
            shutil.rmtree(_upload_dir(upload_id), ignore_errors=True)
        row.status, row.finished_at = "done", datetime.now(UTC)
        row.detail = f"Live: {manifest['chunks']:,} chunks of {manifest['model']}" + (
            f" ({'; '.join(notes)})" if notes else "")
        progress("done", 100, "Live", force=True)
    except Exception as error:
        logger.exception("Corpus replace %s failed", row_id)
        if holding:
            try:
                ops.drop(NEXT_SCHEMA)
            except Exception:
                logger.exception("Dropping %s after the failure failed", NEXT_SCHEMA)
        db.rollback()
        row = db.get(models.CorpusVersion, row_id)
        row.status, row.finished_at = "failed", datetime.now(UTC)
        row.detail = str(error) if isinstance(error, CorpusError) else repr(error)
        row.progress = {**(row.progress or {}), "phase": "failed"}
        db.commit()
    finally:
        db.close()


# --- roll back, status, download ------------------------------------------------------------------------------------

def rollback(db: Session, user: models.User, ops: PgOps | None = None,
             refresh: Callable[[], None] = refresh_app) -> models.CorpusVersion:
    """Swap the live and the previous version back (instant). Refused while a job runs, or when the previous version
    holds vectors the app can't query."""
    from localrag.pg_store import same_vectors

    ops = ops or get_ops()
    with ops.lock() as got:
        if not got:
            raise CorpusError("A corpus job is running")
        try:
            statements = corpus_dump.rollback_statements(ops.schemas())
        except ValueError as error:
            raise CorpusError(str(error)) from None
        previous = ops.meta(PREV_SCHEMA) or {}
        if not same_vectors(app_model(), previous.get("model") or "?"):
            raise CorpusError(f"The previous version holds {previous.get('model')} vectors but the app embeds queries "
                              f"with {app_model()}")
        ops.run(statements)
    refresh()
    row = models.CorpusVersion(action="rollback", status="done", user_id=user.id, user_email=user.email,
                               model=previous.get("model"), chunks=previous.get("chunks"),
                               kommuner=len(previous.get("kommuner") or []), built=str(previous.get("built")),
                               detail="The previous version is live again", finished_at=datetime.now(UTC))
    db.add(row)
    db.commit()
    return row


def version(meta: dict | None) -> dict | None:
    if not meta:
        return None
    return {"built": meta.get("built"), "model": meta.get("model"), "dim": meta.get("dim"),
            "chunks": meta.get("chunks"), "kommuner": len(meta.get("kommuner") or []),
            "uploaded": meta.get("uploaded")}


def history_row(row: models.CorpusVersion) -> dict:
    return {"id": row.id, "action": row.action, "status": row.status, "user_email": row.user_email,
            "file_name": row.file_name, "model": row.model, "chunks": row.chunks, "kommuner": row.kommuner,
            "built": row.built, "progress": row.progress, "detail": row.detail,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None}


def status(db: Session, ops: PgOps | None = None) -> dict:
    ops = ops or get_ops()
    job = running_job(db, ops)
    rows = db.query(models.CorpusVersion).order_by(models.CorpusVersion.id.desc()).limit(50).all()
    last_replace = job or next((row for row in rows if row.action == "replace"), None)
    root = upload_root()
    return {
        "active": version(ops.meta(CORPUS_SCHEMA)),
        "previous": version(ops.meta(PREV_SCHEMA)),
        "job": history_row(last_replace) if last_replace is not None else None,
        "uploads": [{key: upload[key] for key in ("id", "file_name", "size", "received", "complete", "user_email",
                                                   "created")} for upload in list_uploads()],
        "history": [history_row(row) for row in rows],
        "serving": os.getenv("LOCAL_RAG_STORE", "disk").strip() == "neon",
        "part_bytes": part_bytes(),
        "upload_free_bytes": shutil.disk_usage(root if root.is_dir() else root.parent if root.parent.is_dir()
                                               else BACKEND_DIR).free,
        "database_bytes": ops.database_size(),
        "disk_limit_bytes": disk_limit_bytes(),
    }


def active_manifest(ops: PgOps | None = None) -> dict:
    """The manifest of the active corpus, for its download: schema `corpus` (restore it locally, re-export it with
    --from-schema corpus to upload it again). No sha256: the dump is streamed as it is made."""
    ops = ops or get_ops()
    meta = ops.meta(CORPUS_SCHEMA)
    if not meta:
        raise CorpusError("There is no active corpus", 404)
    return {"format": corpus_dump.FORMAT, "version": corpus_dump.FORMAT_VERSION, "schema": CORPUS_SCHEMA,
            "model": meta.get("model"), "dim": meta.get("dim"), "chunks": meta.get("chunks"),
            "kommuner": meta.get("kommuner", []), "built": meta.get("built"), "uploaded": meta.get("uploaded"),
            "dump_file": download_name(meta), "created": datetime.now(UTC).isoformat(timespec="seconds")}


def download_name(meta: dict) -> str:
    built = re.sub(r"[^0-9T]", "", str(meta.get("built") or "unknown"))[:15]
    return f"pyrmit-corpus-{built}-active.dump"


def download_token(user: models.User) -> str:
    """A short-lived link for the browser's own download (the bearer token can't ride on a plain link). No session id:
    it is never accepted as a sign-in."""
    import jwt

    from security import ALGORITHM, get_jwt_secret_key

    expires = datetime.now(UTC) + timedelta(minutes=DOWNLOAD_TOKEN_MINUTES)
    return jwt.encode({"sub": f"user:{user.id}", "purpose": "corpus-download", "exp": expires}, get_jwt_secret_key(),
                      algorithm=ALGORITHM)


def download_user(db: Session, token: str) -> models.User:
    """The owner a download link was made for; CorpusError 401/403 otherwise."""
    import jwt

    from security import ALGORITHM, get_jwt_secret_key

    try:
        claims = jwt.decode(token, get_jwt_secret_key(), algorithms=[ALGORITHM],
                            options={"require": ["sub", "purpose", "exp"]})
    except jwt.InvalidTokenError:
        raise CorpusError("The download link expired: start the download again", 401) from None
    if claims["purpose"] != "corpus-download":
        raise CorpusError("Not a download link", 401)
    user = db.get(models.User, str(claims["sub"]).removeprefix("user:"))
    if user is None or user.role != "owner":
        raise CorpusError("Only owners download the corpus", 403)
    return user


def stream_dump(command: list[str]) -> Iterator[bytes]:
    """pg_dump's output as it is made. The download ends early (and the browser reports it failed) if pg_dump fails."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    try:
        while data := process.stdout.read(1 << 20):
            yield data
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
        code = process.wait()
        if code not in (0, -15):
            logger.error("pg_dump of the corpus failed (%s): %s", code,
                         (process.stderr.read() if process.stderr else b"").decode(errors="replace")[-500:])


def migrate_public_corpus() -> list[str]:
    """At startup (LOCAL_RAG_STORE=neon): move an older install's public.corpus_* tables into schema corpus."""
    from localrag.pg_store import move_public_corpus

    connection = get_ops()._connect()
    try:
        with connection.cursor() as cursor:
            return move_public_corpus(cursor)
    finally:
        connection.close()
