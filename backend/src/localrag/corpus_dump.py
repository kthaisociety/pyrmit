"""
The corpus as a pg_dump file (issue #114): what localrag.export writes on the developer PC and the Database tab's
Corpus panel restores on the server (corpus_admin.py). No database here: the manifest, the check of a dump's table of
contents, the validation rules and the swap SQL, so the unit tests cover them without Postgres (PCR-0011).

    pyrmit-corpus-<built>.dump            pg_dump -Fc --compress=zstd:3 -n corpus_next
    pyrmit-corpus-<built>.manifest.json   MANIFEST_KEYS: model, dim, chunks, kommuner, label schema version, sha256...
"""

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from localrag.pg_store import CORPUS_SCHEMA, NEXT_SCHEMA, PREV_SCHEMA

FORMAT = "pyrmit-corpus-dump"
FORMAT_VERSION = 1
MANIFEST_KEYS = ("format", "version", "schema", "model", "dim", "chunks", "kommuner", "label_schema_version", "built",
                 "database_mb", "dump_file", "dump_bytes", "sha256")
# The labels of docs/source-chunk-schema.md (#107): version 2 when the chunks carry place and fetch date
LABEL_COLUMNS = {2: {"place", "fetched_at"}}
_SHA256 = re.compile(r"[0-9a-f]{64}")


class InvalidManifest(ValueError):
    """A manifest the server can't use; the message says what is wrong."""


def label_schema_version(columns: Iterable[str]) -> int:
    """1: the chunks of the first corpus (no labels); 2: with the source-chunk-schema labels (place, fetched_at...)."""
    columns = set(columns)
    return max([1, *(version for version, needed in LABEL_COLUMNS.items() if needed <= columns)])


def sha256_file(path: Path, progress: Callable[[int], None] | None = None, block: int = 8 << 20) -> str:
    """Hex sha256 of a file; progress(bytes read so far) after every block."""
    digest, done = hashlib.sha256(), 0
    with path.open("rb") as file:
        while data := file.read(block):
            digest.update(data)
            done += len(data)
            if progress is not None:
                progress(done)
    return digest.hexdigest()


def check_manifest(manifest: dict, size: int | None = None) -> dict:
    """The manifest of an upload, checked: the keys the restore reads, the schema the swap renames (`corpus_next`),
    and the file size. Raises InvalidManifest. Returns the manifest."""
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise InvalidManifest(f"Not a {FORMAT} manifest (make it with python -m localrag.export)")
    if manifest.get("version") != FORMAT_VERSION:
        raise InvalidManifest(f"Manifest version {manifest.get('version')}: this server reads version {FORMAT_VERSION}")
    missing = [key for key in MANIFEST_KEYS if manifest.get(key) in (None, "")]
    if missing:
        raise InvalidManifest(f"The manifest lacks {', '.join(missing)}")
    if manifest["schema"] != NEXT_SCHEMA:
        raise InvalidManifest(f"The dump holds schema {manifest['schema']}, not {NEXT_SCHEMA}: re-export it with "
                              f"python -m localrag.export --from-schema {manifest['schema']}")
    if not _SHA256.fullmatch(str(manifest["sha256"])):
        raise InvalidManifest("The manifest's sha256 is not a hex SHA-256")
    for key in ("dim", "chunks", "dump_bytes"):
        if not isinstance(manifest[key], int) or manifest[key] <= 0:
            raise InvalidManifest(f"The manifest's {key} is not a positive number")
    if size is not None and size != manifest["dump_bytes"]:
        raise InvalidManifest(f"The file is {size:,} bytes, the manifest says {manifest['dump_bytes']:,}")
    return manifest


# --- the dump's table of contents (pg_restore -l) -------------------------------------------------------------------

# What pg_dump -n writes for the corpus tables; anything else (functions, extensions, other schemas) is refused
TOC_TYPES = ("TABLE DATA", "TABLE", "INDEX", "FK CONSTRAINT", "CONSTRAINT", "VIEW", "SCHEMA", "COMMENT", "ACL",
             "SEQUENCE OWNED BY", "SEQUENCE SET", "SEQUENCE", "DEFAULT", "STATISTICS")
_TOC_LINE = re.compile(r"^\d+;\s+\d+\s+\d+\s+(?P<type>" + "|".join(re.escape(t) for t in TOC_TYPES)
                       + r")\s+(?P<schema>\S+)\s+(?P<rest>.*)$")


def toc_entries(toc: str, schema: str = NEXT_SCHEMA) -> int:
    """The number of entries of a `pg_restore -l` listing, after checking that every one belongs to `schema` (its
    own SCHEMA entry included). Raises ValueError naming the first entry that doesn't: a dump of another schema, or
    one carrying other objects, is never restored."""
    entries = 0
    for line in toc.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        match = _TOC_LINE.match(line)
        if match is None:
            raise ValueError(f"The dump holds an object this restore doesn't accept: {line}")
        owner_free = match["rest"].split()
        if match["schema"] == "-":  # the schema itself, or a comment / ACL on it
            if schema not in owner_free:
                raise ValueError(f"The dump holds an object outside schema {schema}: {line}")
        elif match["schema"] != schema:
            raise ValueError(f"The dump holds schema {match['schema']}, not {schema}: {line}")
        entries += 1
    if not entries:
        raise ValueError("The dump is empty")
    return entries


_FINISHED = re.compile(r"finished item (\d+)")


def restore_progress(line: str) -> bool:
    """A `pg_restore --verbose` line that marks one more entry done (with -j: "finished item 1234 ...")."""
    return _FINISHED.search(line) is not None


# --- validation of the restored corpus_next -------------------------------------------------------------------------

def validation_errors(manifest: dict, facts: dict, app_model: str, app_dim: int | None,
                      same_vectors: Callable[[str, str], bool], required_columns: Iterable[str]) -> list[str]:
    """Why the restored corpus can't go live (empty: it can). `facts` come from the restored schema:
    meta (corpus_meta), chunks (COUNT(*) of corpus_chunks), dim (the embedding column's dimension), columns (of
    corpus_chunks), query_error (None when a test query answered). app_dim: the dimension the app's queries have (the
    model's, else the live corpus's), None when unknown."""
    errors, meta = [], facts.get("meta") or {}
    if not meta:
        return ["The restored schema has no corpus_meta"]
    stored = meta.get("model")
    if not stored or not same_vectors(app_model, stored):
        errors.append(f"The corpus holds {stored} vectors but the app embeds queries with {app_model} (LOCAL_RAG_MODEL)")
    if stored != manifest.get("model"):
        errors.append(f"corpus_meta says model {stored}, the manifest {manifest.get('model')}")
    dims = {"corpus_meta": meta.get("dim"), "the embedding column": facts.get("dim"), "the manifest": manifest.get("dim")}
    if app_dim is not None:
        dims["the app's model"] = app_dim
    if len(set(dims.values())) != 1:
        errors.append("Vector dimensions differ: " + ", ".join(f"{name} {dim}" for name, dim in dims.items()))
    counts = {"rows": facts.get("chunks"), "corpus_meta": meta.get("chunks"), "the manifest": manifest.get("chunks")}
    if len(set(counts.values())) != 1:
        errors.append("Chunk counts differ: " + ", ".join(f"{name} {count}" for name, count in counts.items()))
    missing = sorted(set(required_columns) - set(facts.get("columns") or ()))
    if missing:
        errors.append(f"corpus_chunks lacks the columns this app reads: {', '.join(missing)}")
    if facts.get("query_error"):
        errors.append(f"The test query failed: {facts['query_error']}")
    return errors


# --- the swap and the roll back -------------------------------------------------------------------------------------

def swap_statements(schemas: set[str]) -> list[str]:
    """The renames that make corpus_next live, in one transaction, given the schemas that exist now: the old previous
    version goes, the live one becomes the previous one."""
    if NEXT_SCHEMA not in schemas:
        raise ValueError(f"No {NEXT_SCHEMA} to make live")
    statements = []
    if PREV_SCHEMA in schemas:
        statements.append(f"DROP SCHEMA {PREV_SCHEMA} CASCADE")
    if CORPUS_SCHEMA in schemas:
        statements.append(f"ALTER SCHEMA {CORPUS_SCHEMA} RENAME TO {PREV_SCHEMA}")
    statements.append(f"ALTER SCHEMA {NEXT_SCHEMA} RENAME TO {CORPUS_SCHEMA}")
    return statements


ROLLBACK_TMP = "corpus_rollback"


def rollback_statements(schemas: set[str]) -> list[str]:
    """The renames that swap the live and the previous version back, in one transaction."""
    if CORPUS_SCHEMA not in schemas or PREV_SCHEMA not in schemas:
        raise ValueError("There is no previous version to roll back to")
    return [f"ALTER SCHEMA {CORPUS_SCHEMA} RENAME TO {ROLLBACK_TMP}",
            f"ALTER SCHEMA {PREV_SCHEMA} RENAME TO {CORPUS_SCHEMA}",
            f"ALTER SCHEMA {ROLLBACK_TMP} RENAME TO {PREV_SCHEMA}"]


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
