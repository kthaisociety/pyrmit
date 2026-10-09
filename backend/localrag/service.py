"""
Local retrieval for the chat (RETRIEVAL_BACKEND=local): same output shape as the pgvector
agents' debug rows, so chat.py and the pipeline inspector work unchanged.

    RETRIEVAL_BACKEND=local          # default "pgvector"
    LOCAL_RAG_MODEL=st-arctic-l-v2   # a model from localrag/models.toml, already indexed
    LOCAL_RAG_MODE=dense             # dense | hybrid (dense + Swedish BM25, RRF) | bm25
    LOCAL_RAG_DENSE_QUERY=sv         # which query the dense model embeds: en | sv | both
    LOCAL_RAG_RERANKER=              # e.g. BAAI/bge-reranker-v2-m3 (in-memory store only)
    LOCAL_RAG_STORE=disk             # disk: SQLite + memmap built by `python -m localrag.store`; memory: load
                                     # chunks.jsonl in RAM (needed for the compound BM25 analyzer / reranker)

Defaults follow localrag/eval.py (45 questions): the Swedish query beats the English one by
~25 points of recall@5; neither BM25 fusion nor the reranker improved on dense-sv.
"""

import logging
import os
import threading
import time
from typing import Any

# The retriever (numpy, bm25s, torch) is imported lazily: the default pgvector backend doesn't need it

# Appended to the chat's rewrite prompt so one LLM call returns both queries
SWEDISH_QUERY_SUFFIX = (
    "Then, on a new line starting with 'SV:', write the same query in Swedish as a search query for Swedish "
    "laws and municipal planning documents, using the Swedish legal and planning terms (bygglov, detaljplan, "
    "planbesked, strandskydd, enskilt avlopp, förhandsbesked, ...) and keeping place names."
)


def split_rewrite(output: str, fallback: str) -> tuple[str, str | None]:
    """Split the rewrite output "<English query> SV: <Swedish query>" into (english, swedish)."""
    english, _, swedish = output.partition("SV:")
    return english.strip() or fallback, swedish.strip() or None

logger = logging.getLogger(__name__)

_retriever = None
_lock = threading.Lock()


def _agent_mode() -> bool:
    return os.getenv("CHAT_MODE", "rag").strip().lower() == "agent"


def local_backend_enabled() -> bool:
    return os.getenv("RETRIEVAL_BACKEND", "pgvector").strip().lower() == "local"


def get_retriever():
    from localrag.index import VectorStore, load_chunks
    from localrag.retriever import LocalRetriever

    global _retriever
    with _lock:
        if _retriever is None:
            model = os.getenv("LOCAL_RAG_MODEL", "st-arctic-l-v2").strip()
            from localrag.store import DiskRetriever, store_dir

            # Disk store (SQLite + memmap, `python -m localrag.store`): a few hundred MB of RAM instead of GBs
            if os.getenv("LOCAL_RAG_STORE", "disk").strip() == "disk" and (store_dir(model) / "corpus.sqlite").exists():
                _retriever = DiskRetriever(model)
                logger.info("Local retrieval: disk store %s", store_dir(model))
                return _retriever
            # Serve only what `localrag.index` has embedded: embedding a whole corpus inside a request would block
            # the server for an hour. Re-run the index and restart to pick up new chunks.
            indexed = VectorStore(model).position
            chunks = [chunk for chunk in load_chunks() if chunk["chunk_id"] in indexed]
            logger.info("Local retrieval: %d indexed chunks with %s", len(chunks), model)
            mode = os.getenv("LOCAL_RAG_MODE", "dense").strip()
            _retriever = LocalRetriever(
                chunks,
                model=model,
                # The agent's search tool is hybrid (BM25 "stem": lighter than "compound" on the full corpus)
                bm25_modes=("compound",) if mode in ("hybrid", "bm25") else (("stem",) if _agent_mode() else ()),
                reranker=os.getenv("LOCAL_RAG_RERANKER", "").strip() or None,
            )
        return _retriever


def _row(hit) -> dict[str, Any]:
    from localrag.index import chunk_text

    chunk = hit.chunk
    if chunk["kind"] == "law":
        source = f"{chunk['title']}, {chunk['section']}"
    else:
        source = f"{chunk['kommun']} – {chunk['title']}" if chunk.get("kommun") else chunk["title"]
    content = chunk_text(chunk)
    return {
        "source": source,
        "chunk_index": chunk.get("chunk_index"),
        "distance": None,
        "score": round(hit.score, 6),
        "url": chunk.get("url"),
        "content": content,
        "preview": content[:220].replace("\n", " "),
    }


def retrieve(query: str, query_sv: str | None, k: int = 5, recorder=None) -> tuple[list[dict], list[dict], list[str]]:
    """(law rows, local rows, detected kommun codes) for the English query and its Swedish rewrite."""
    retriever = get_retriever()
    started = time.perf_counter()
    rerank = retriever.reranker is not None
    dense_lang = os.getenv("LOCAL_RAG_DENSE_QUERY", "sv").strip() if query_sv else "en"
    mode = os.getenv("LOCAL_RAG_MODE", "dense").strip()
    result = retriever.search(query, query_sv=query_sv, k=k, mode=mode, rerank=rerank, dense_lang=dense_lang)
    if recorder is not None:
        recorder.record(
            kind="db",
            name="Local retrieval",
            table="data/corpus/chunks.jsonl",
            k=k,
            matches=len(result["law"]) + len(result["local"]),
            query=(f"{mode} ({retriever.model}, dense query: {dense_lang}){', reranked' if rerank else ''}; "
                   f"kommun filter: {result['kommuner'] or 'none'}"),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
    return [_row(h) for h in result["law"]], [_row(h) for h in result["local"]], result["kommuner"]
