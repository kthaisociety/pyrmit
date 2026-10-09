"""
Shared base class for all RAG agents.
Eliminates duplicated embedding, retrieval, LLM-call, and JSON-parsing logic.
"""

import json
import logging
import re
import time
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy.sql import select

import os
from embeddings import get_embedder
from llm import get_response_output_text, resolve_model_name
from pipeline_trace import CallRecorder, recorded_chat_completion

# LLM_MODEL overrides the chat model (e.g. "anthropic/claude-sonnet-5.5" with LLM_PROVIDER=openrouter)
OPENAI_CHAT_MODEL = os.getenv("LLM_MODEL", "").strip() or (
    "openai/gpt-5.4-mini"
    if os.getenv("APP_ENV", "development").strip().lower() == "production"
    else "openai/gpt-5.4-nano"
)

_TRANSLATION_INSTRUCTION = (
    "Always respond in English. "
    "When quoting source text that is in Swedish, include the original Swedish verbatim "
    "and follow it with an English translation."
)

logger = logging.getLogger(__name__)


class BaseRAGAgent:
    """Base class providing shared embedding, retrieval, LLM, and JSON utilities."""

    _source_label_column: str = ""

    def __init__(
        self,
        db: Session,
        openai_client: OpenAI,
        model_class,
        label: str,
        recorder: CallRecorder | None = None,
    ):
        self.db = db
        self.client = openai_client
        self.model_class = model_class
        self.label = label
        self.recorder = recorder

    def _embed(self, text: str) -> list[float] | None:
        # Embeddings can be unavailable independently of chat completions (e.g. a
        # missing key for the embedding provider). Degrade to no-retrieval instead
        # of failing the whole request.
        embedder = get_embedder()
        started = time.perf_counter()
        call = {"kind": "embedding", "name": f"{self.label}: embed query", "model": embedder.config.label, "input": text}
        try:
            embedding = embedder.embed_query(text)
        except Exception as exc:
            logger.warning("Embedding call failed; continuing without retrieval", exc_info=True)
            if self.recorder is not None:
                self.recorder.record(**call, error=str(exc), duration_ms=round((time.perf_counter() - started) * 1000))
            return None
        if self.recorder is not None:
            self.recorder.record(
                **call, dimensions=len(embedding), duration_ms=round((time.perf_counter() - started) * 1000)
            )
        return embedding

    def _retrieve(self, query: str, k: int = 5) -> list[str]:
        embedding = self._embed(query)
        if embedding is None:
            return []
        stmt = (
            select(self.model_class.content)
            .where(self.model_class.embedding.is_not(None))
            .order_by(self.model_class.embedding.cosine_distance(embedding))
            .limit(k)
        )
        return [row[0] for row in self.db.execute(stmt).fetchall()]

    def _retrieve_with_meta(self, query: str, k: int = 5) -> list[tuple[str, str]]:
        """Retrieve top-k chunks as (content, source_label) tuples."""
        return self._retrieve_with_meta_from_embedding(self._embed(query), k)

    def _retrieve_with_meta_from_embedding(self, embedding: list[float], k: int = 5) -> list[tuple[str, str]]:
        """Retrieve top-k chunks as (content, source_label) tuples from a pre-computed embedding."""
        rows = self._retrieve_debug_rows_from_embedding(embedding, k)
        return [(row["content"], row["source"]) for row in rows]

    def _retrieve_debug_rows(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        return self._retrieve_debug_rows_from_embedding(self._embed(query), k)

    def _retrieve_debug_rows_from_embedding(self, embedding: list[float] | None, k: int = 5) -> list[dict[str, Any]]:
        """Retrieve top-k chunks with source, chunk index, distance, and preview."""
        if embedding is None:
            return []
        source_attr = self._source_label_column or "source"
        source_col = getattr(self.model_class, source_attr)
        distance_col = self.model_class.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(self.model_class.content, source_col, self.model_class.chunk_index, distance_col)
            .where(self.model_class.embedding.is_not(None))
            .order_by(distance_col)
            .limit(k)
        )
        started = time.perf_counter()
        results = self.db.execute(stmt).fetchall()
        if self.recorder is not None:
            self.recorder.record(
                kind="db",
                name=f"{self.label}: vector search",
                table=self.model_class.__tablename__,
                k=k,
                matches=len(results),
                query="ORDER BY embedding <=> :query_embedding (cosine distance) LIMIT :k",
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
        rows = []
        for content, source, chunk_index, distance in results:
            rows.append(
                {
                    "source": source or "unknown",
                    "chunk_index": chunk_index,
                    "distance": None if distance is None else round(float(distance), 6),
                    "content": content,
                    "preview": content[:220].replace("\n", " "),
                }
            )
        return rows

    @staticmethod
    def _trace_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Debug rows without the preview, for the frontend pipeline inspector."""
        return [{key: value for key, value in row.items() if key != "preview"} for row in rows]

    def _log_retrieval(self, query: str, rows: list[dict[str, Any]]) -> None:
        logger.info("%s retrieval query=%r matches=%d", self.label, query, len(rows))
        for idx, row in enumerate(rows, start=1):
            logger.info(
                "%s match %d source=%s chunk_index=%s distance=%s preview=%r",
                self.label,
                idx,
                row["source"],
                row["chunk_index"],
                row["distance"],
                row["preview"],
            )

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        completion = recorded_chat_completion(
            self.recorder,
            self.client,
            name=f"{self.label}: analysis",
            model=resolve_model_name(OPENAI_CHAT_MODEL),
            instructions=system_prompt,
            input=user_prompt,
            temperature=0,
        )
        return get_response_output_text(completion)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Parse JSON from a response that may be wrapped in markdown code fences."""
        try:
            clean = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            return {}
