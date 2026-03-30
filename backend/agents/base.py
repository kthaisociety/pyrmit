"""
Shared base class for all RAG agents.
Eliminates duplicated embedding, retrieval, LLM-call, and JSON-parsing logic.
"""

import json
import logging
import re
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy.sql import select

from observability import create_chat_completion, create_embedding

OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
OPENAI_CHAT_MODEL = "gpt-3.5-turbo"

_TRANSLATION_INSTRUCTION = (
    "Always respond in English. "
    "When quoting source text that is in Swedish, include the original Swedish verbatim "
    "and follow it with an English translation."
)

logger = logging.getLogger(__name__)


class BaseRAGAgent:
    """Base class providing shared embedding, retrieval, LLM, and JSON utilities."""

    _source_label_column: str = ""

    def __init__(self, db: Session, openai_client: Any, model_class, label: str):
        self.db = db
        self.client = openai_client
        self.model_class = model_class
        self.label = label

    def _embed(self, text: str) -> list[float]:
        return create_embedding(
            self.client,
            model=OPENAI_EMBEDDING_MODEL, input=text
        ).data[0].embedding

    def _retrieve(self, query: str, k: int = 5) -> list[str]:
        embedding = self._embed(query)
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

    def _retrieve_debug_rows_from_embedding(self, embedding: list[float], k: int = 5) -> list[dict[str, Any]]:
        """Retrieve top-k chunks with source, chunk index, distance, and preview."""
        source_col = getattr(self.model_class, self._source_label_column)
        distance_col = self.model_class.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(self.model_class.content, source_col, self.model_class.chunk_index, distance_col)
            .where(self.model_class.embedding.is_not(None))
            .order_by(distance_col)
            .limit(k)
        )
        rows = []
        for content, source, chunk_index, distance in self.db.execute(stmt).fetchall():
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
        completion = create_chat_completion(
            self.client,
            model=OPENAI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        return completion.choices[0].message.content

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Parse JSON from a response that may be wrapped in markdown code fences."""
        try:
            clean = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            return {}
