"""
Shared base class for all RAG agents.
Eliminates duplicated embedding, retrieval, LLM-call, and JSON-parsing logic.
"""

import json
import re

from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy.sql import select

import os

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


class BaseRAGAgent:
    """Base class providing shared embedding, retrieval, LLM, and JSON utilities."""

    _source_label_column: str = ""

    def __init__(self, db: Session, openai_client: OpenAI, model_class, label: str):
        self.db = db
        self.client = openai_client
        self.model_class = model_class
        self.label = label

    def _embed(self, text: str) -> list[float]:
        return self.client.embeddings.create(
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
        source_col = getattr(self.model_class, self._source_label_column)
        stmt = (
            select(self.model_class.content, source_col)
            .where(self.model_class.embedding.is_not(None))
            .order_by(self.model_class.embedding.cosine_distance(embedding))
            .limit(k)
        )
        return [(row[0], row[1] or "unknown") for row in self.db.execute(stmt).fetchall()]

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        completion = self.client.chat.completions.create(
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
