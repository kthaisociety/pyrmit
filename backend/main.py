import logging
import os
import threading
from dotenv import load_dotenv

# Must run before any module that reads env vars at import time
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from db.database import engine, Base
from dev_access import (
    is_access_gate_exempt_path,
    is_dev_access_enabled,
    request_has_dev_access,
)
from embeddings import EmbeddingConfig
from routers import access_gate, chat, auth, chunks, agents, db_browser, docs, benchmark
from logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

# create_all never alters existing tables: add columns introduced after a table was created
_message_columns = {column["name"] for column in inspect(engine).get_columns("chat_messages")}
for _column, _type in (("trace", "JSONB"), ("status", "VARCHAR")):
    if _column not in _message_columns:
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS {_column} {_type}"))


def _check_embedding_config() -> None:
    """Vectors from different models are not comparable: flag a DB embedded with another model."""
    config = EmbeddingConfig.from_env()
    with engine.connect() as connection:
        for table in ("law_chunks", "document_chunks"):
            dim, comment = connection.execute(
                text(
                    "SELECT atttypmod, col_description(attrelid, attnum) FROM pg_attribute "
                    "WHERE attrelid = to_regclass(:table) AND attname = 'embedding'"
                ),
                {"table": table},
            ).one()
            if dim > 0 and dim != config.dim:
                logger.error("%s.embedding is vector(%d) but EMBEDDING_DIM=%s", table, dim, config.dim)
            # The column comment is written by chunking/reembed.py
            if comment and comment != config.label:
                logger.error("%s was embedded with %s but the app uses %s", table, comment, config.label)


_check_embedding_config()

app = FastAPI()


def _preload_local_corpus() -> None:
    """Load the local index (~1 min on the full corpus) at startup rather than on the first question."""
    from agentic.service import agent_enabled, get_tools
    from localrag.service import get_retriever, local_backend_enabled

    try:
        if agent_enabled():
            get_tools()
        elif local_backend_enabled():
            get_retriever()
    except Exception:
        logger.error("Preloading the local corpus failed", exc_info=True)


threading.Thread(target=_preload_local_corpus, name="preload-local-corpus", daemon=True).start()


@app.middleware("http")
async def development_access_middleware(request, call_next):
    if (
        request.method != "OPTIONS"
        and is_dev_access_enabled()
        and not is_access_gate_exempt_path(request.url.path)
        and not request_has_dev_access(request)
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Access password required"},
        )

    return await call_next(request)

cors_allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(access_gate.router, prefix="/api/access-gate", tags=["access-gate"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(chunks.router, prefix="/api", tags=["chunks"])
app.include_router(agents.router, prefix="/api", tags=["agents"])
app.include_router(db_browser.router, prefix="/api", tags=["db-browser"])
app.include_router(docs.router, prefix="/api", tags=["docs"])
app.include_router(benchmark.router, prefix="/api", tags=["benchmark"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the Building Permit Agent API"}
