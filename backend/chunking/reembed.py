"""
Re-embed the chunks already stored in the database with the configured EMBEDDING_* model.

The stored `content` is exactly the text that was embedded at ingestion, so no source
files (law TXT, detaljplan PDFs) are needed. Changing model rewrites every vector of the
target DATABASE_URL: point it at a dedicated Neon branch, not the shared database.

    cd backend
    EMBEDDING_PROVIDER=openrouter EMBEDDING_MODEL=baai/bge-m3 EMBEDDING_DIM=1024 \
        python chunking/reembed.py --yes

If the dimension changes, the column is altered (all vectors are dropped first). The
model label is stored as the column comment; main.py warns when it differs from the
app's EMBEDDING_* config. Use --only-missing to resume an interrupted run.
"""

import argparse
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from psycopg2.extras import execute_batch

from db.push_db import PushDB
from embeddings import EmbeddingConfig, Embedder

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

TABLES = {"law": "law_chunks", "document": "document_chunks"}


def column_state(cursor, table: str) -> tuple[int, str | None]:
    cursor.execute(
        "SELECT atttypmod, col_description(attrelid, attnum) FROM pg_attribute "
        "WHERE attrelid = to_regclass(%s) AND attname = 'embedding'",
        (table,),
    )
    return cursor.fetchone()


def reembed_table(push_db: PushDB, embedder: Embedder, table: str, only_missing: bool) -> None:
    config = embedder.config
    with push_db._get_conn() as conn, conn.cursor() as cursor:
        dim, comment = column_state(cursor, table)
        if dim != config.dim:
            logger.info("%s: vector(%d) -> vector(%d), dropping existing vectors", table, dim, config.dim)
            cursor.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({int(config.dim)}) USING NULL")
            only_missing = False
        elif comment and comment != config.label:
            logger.info("%s: re-embedding from %s to %s", table, comment, config.label)
        # Mark the column first: a partially re-embedded table must not look consistent
        cursor.execute(f"COMMENT ON COLUMN {table}.embedding IS %s", (f"{config.label} (in progress)",))
        conn.commit()

        where = "WHERE embedding IS NULL" if only_missing else ""
        cursor.execute(f"SELECT id, content FROM {table} {where} ORDER BY id")
        rows = cursor.fetchall()

    logger.info("%s: embedding %d chunks with %s", table, len(rows), config.label)
    step = config.batch_size * 5
    for start in range(0, len(rows), step):
        batch = rows[start:start + step]
        vectors = embedder.embed_documents([content or "" for _, content in batch])
        with push_db._get_conn() as conn, conn.cursor() as cursor:
            execute_batch(
                cursor,
                f"UPDATE {table} SET embedding = %s::vector WHERE id = %s",
                [(str(vector), chunk_id) for (chunk_id, _), vector in zip(batch, vectors)],
            )
            conn.commit()
        logger.info("%s: %d/%d", table, start + len(batch), len(rows))

    with push_db._get_conn() as conn, conn.cursor() as cursor:
        cursor.execute(f"COMMENT ON COLUMN {table}.embedding IS %s", (config.label,))
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-embed stored chunks with the configured EMBEDDING_* model")
    parser.add_argument("--table", choices=["law", "document", "all"], default="all")
    parser.add_argument("--only-missing", action="store_true", help="only rows whose embedding is NULL (resume)")
    parser.add_argument("--yes", action="store_true", help="required: confirms overwriting the target database")
    args = parser.parse_args()

    config = EmbeddingConfig.from_env()
    push_db = PushDB()
    host = urlparse(push_db.db_url).hostname
    logger.info("Database: %s\nModel:    %s (dim=%s)", host, config.label, config.dim)
    if not args.yes:
        logger.info("Dry run: pass --yes to overwrite the embeddings in this database.")
        return

    embedder = Embedder(config)
    tables = TABLES.values() if args.table == "all" else [TABLES[args.table]]
    for table in tables:
        reembed_table(push_db, embedder, table, args.only_missing)


if __name__ == "__main__":
    main()
