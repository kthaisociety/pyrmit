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
from llm import get_response_output_text, resolve_model_name
from pipeline_trace import CallRecorder, recorded_chat_completion, recorded_embedding

OPENAI_EMBEDDING_MODEL = "openai/text-embedding-3-large"
OPENAI_CHAT_MODEL = (
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

_direct_openai_client: OpenAI | None = None


def _get_direct_openai_client() -> OpenAI:
    # Embeddings go straight to OpenAI regardless of AI_GATEWAY_API_KEY: the
    # Gateway's free tier doesn't offer embedding models, so chat completions
    # can stay on the Gateway while embeddings use a funded OpenAI key.
    global _direct_openai_client
    if _direct_openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for embeddings")
        _direct_openai_client = OpenAI(api_key=api_key)
    return _direct_openai_client


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
        # Vercel AI Gateway free-tier account that only allows certain chat models).
        # Degrade to no-retrieval instead of failing the whole request.
        try:
            return recorded_embedding(
                self.recorder,
                _get_direct_openai_client(),
                name=f"{self.label}: embed query",
                model=OPENAI_EMBEDDING_MODEL.removeprefix("openai/"),
                input=text,
            ).data[0].embedding
        except Exception:
            logger.warning("Embedding call failed; continuing without retrieval", exc_info=True)
            return None

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
