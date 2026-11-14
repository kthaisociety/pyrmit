"""
Export the corpus for the server (issue #114): a disk store (localrag.store) loaded into a local Postgres in schema
`corpus_next` (localrag.pg_store.load), dumped with pg_dump, plus its manifest. An owner uploads both files in the
Database tab's Corpus panel; the server restores the dump beside the live corpus and swaps (corpus_admin.py). The
heavy work (Swedish stems, vectors as text) stays here: the server only copies rows and rebuilds indexes.

    docker run -d --name pyrmit-export -e POSTGRES_PASSWORD=export -p 5440:5432 pgvector/pgvector:pg17
    cd backend && python -m localrag.export --model st-bge-m3 \\
        --url postgresql://postgres:export@localhost:5440/postgres \\
        --pg-dump "docker exec -i pyrmit-export pg_dump" --dump-url postgresql://postgres:export@localhost/postgres

    -> data/export/pyrmit-corpus-<built>.dump and .manifest.json

pg_dump must be version 17 (the server's Postgres). Without it on the PC, --pg-dump runs the one inside the
Postgres container; --dump-url is then the URL as seen from inside the container. --skip-load dumps the corpus_next
already loaded; --from-schema corpus re-exports a downloaded dump restored locally (its schema is `corpus`).
"""

import argparse
import hashlib
import inspect
import json
import os
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from corpus.common import BACKEND_DIR
from localrag import pg_store
from localrag.corpus_dump import FORMAT, FORMAT_VERSION, label_schema_version
from localrag.pg_store import NEXT_SCHEMA

EXPORT_DIR = BACKEND_DIR / "data" / "export"
DUMP_OPTIONS = ("-Fc", "--compress=zstd:3", "--no-owner", "--no-privileges")


def schema_facts(url: str, schema: str) -> dict:
    """What the manifest says of a loaded schema: corpus_meta, the chunk columns and the size on disk."""
    import psycopg2

    connection = psycopg2.connect(url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT key, value FROM {schema}.corpus_meta")
            meta = dict(cursor.fetchall())
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                           "AND table_name = 'corpus_chunks'", (schema,))
            columns = [row[0] for row in cursor.fetchall()]
            cursor.execute(f"SELECT COUNT(*) FROM {schema}.corpus_chunks")
            chunks = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
                           "WHERE c.relnamespace = %s::regnamespace AND c.relkind IN ('r', 'm')", (schema,))
            size = int(cursor.fetchone()[0])
    finally:
        connection.close()
    return {"meta": meta, "columns": columns, "chunks": chunks, "database_mb": round(size / 1e6, 1)}


def rename_schema(url: str, old: str, new: str) -> None:
    import psycopg2

    connection = psycopg2.connect(url)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER SCHEMA {old} RENAME TO {new}")
    finally:
        connection.close()


def dump(pg_dump: list[str], dump_url: str, target: Path) -> tuple[int, str]:
    """pg_dump of corpus_next into `target`, hashed while it is written. Returns (bytes, sha256)."""
    digest, size = hashlib.sha256(), 0
    partial = target.with_suffix(".partial")
    with partial.open("wb") as file:
        process = subprocess.Popen([*pg_dump, *DUMP_OPTIONS, "-n", NEXT_SCHEMA, "-d", dump_url],
                                   stdout=subprocess.PIPE)
        assert process.stdout is not None
        while data := process.stdout.read(8 << 20):
            file.write(data)
            digest.update(data)
            size += len(data)
        process.stdout.close()
        code = process.wait()
    if code != 0:  # after the file is closed: Windows refuses to delete an open file
        partial.unlink(missing_ok=True)
        raise SystemExit(f"pg_dump failed (exit {code})")
    partial.replace(target)
    return size, digest.hexdigest()


def pg_dump_version(pg_dump: list[str]) -> str:
    result = subprocess.run([*pg_dump, "--version"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def manifest_for(facts: dict, dump_file: str, size: int, sha256: str, pg_version: str) -> dict:
    meta = facts["meta"]
    return {
        "format": FORMAT, "version": FORMAT_VERSION, "schema": NEXT_SCHEMA,
        "model": meta["model"], "dim": int(meta["dim"]), "chunks": int(facts["chunks"]),
        "kommuner": meta.get("kommuner", []), "label_schema_version": label_schema_version(facts["columns"]),
        "built": meta["built"], "database_mb": facts["database_mb"],
        "dump_file": dump_file, "dump_bytes": size, "sha256": sha256,
        "pg_dump": pg_version, "created": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump a disk store as schema corpus_next, for the Corpus panel")
    parser.add_argument("--model", help="disk store to load (localrag.store), e.g. st-bge-m3")
    parser.add_argument("--url", default=os.getenv("EXPORT_DATABASE_URL"),
                        help="a local Postgres 17 with pgvector (default: EXPORT_DATABASE_URL). Never the server's")
    parser.add_argument("--out", type=Path, default=EXPORT_DIR, help="folder for the dump and its manifest")
    parser.add_argument("--skip-load", action="store_true", help="dump the corpus_next already loaded")
    parser.add_argument("--from-schema", help="dump this schema instead (renamed to corpus_next for the dump, then "
                                              "back), e.g. corpus for a downloaded dump restored locally")
    parser.add_argument("--workers", type=int, default=1, help="processes copying the chunks, if pg_store supports it")
    parser.add_argument("--pg-dump", default="pg_dump",
                        help='pg_dump 17 command, e.g. "docker exec -i pyrmit-export pg_dump"')
    parser.add_argument("--dump-url", help="the database URL as pg_dump sees it (default: --url)")
    args = parser.parse_args()
    if not args.url:
        parser.error("give --url (or EXPORT_DATABASE_URL): a local Postgres to load the store into")
    if not (args.model or args.skip_load or args.from_schema):
        parser.error("give --model (load a disk store), --skip-load or --from-schema")
    pg_dump = shlex.split(args.pg_dump)
    started = time.perf_counter()

    renamed = False
    if args.from_schema:
        rename_schema(args.url, args.from_schema, NEXT_SCHEMA)
        renamed = True
    elif not args.skip_load:
        options = {"workers": args.workers} if "workers" in inspect.signature(pg_store.load).parameters else {}
        pg_store.load(args.model, args.url, schema=NEXT_SCHEMA, **options)
    try:
        facts = schema_facts(args.url, NEXT_SCHEMA)
        built = str(facts["meta"]["built"]).replace(":", "").replace("-", "")[:15]
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"pyrmit-corpus-{built}.dump"
        print(f"Dumping {facts['chunks']:,} chunks ({facts['database_mb']} MB in Postgres) to {target}", flush=True)
        size, sha256 = dump(pg_dump, args.dump_url or args.url, target)
        manifest = manifest_for(facts, target.name, size, sha256, pg_dump_version(pg_dump))
    finally:
        if renamed:
            rename_schema(args.url, NEXT_SCHEMA, args.from_schema)
    manifest_path = target.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{target.name}: {size / 1e9:.2f} GB, sha256 {sha256[:12]}…; manifest {manifest_path.name} "
          f"({time.perf_counter() - started:.0f}s)")


if __name__ == "__main__":
    main()
