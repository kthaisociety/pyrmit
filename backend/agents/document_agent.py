"""
RAG Agent for detaljplan / planning document research.
Uses OpenAI GPT + SQLAlchemy pgvector queries on document_chunks.
"""

import logging

from openai import OpenAI
from sqlalchemy.orm import Session

from agents.base import BaseRAGAgent, _TRANSLATION_INSTRUCTION
from models import DocumentChunk
from observability import start_observation

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a permit analyst specializing in development project outcomes. "
    + _TRANSLATION_INSTRUCTION
)

_USER_TEMPLATE = """Based ONLY on the following historical documents (which may be in Swedish):

{context}

Answer this question in English:
What happened when people tried to build similar {project_type} projects (around {units} units) in {location}?

When citing Swedish source text, use this format:
> **English:** [your English interpretation]
> **Original (Swedish):** [exact Swedish text from the source]

Provide your answer in JSON format:
{{
    "similar_cases": [
        {{
            "address": "<address>",
            "units": <number>,
            "outcome": "APPROVED" or "DENIED",
            "year": <year>,
            "conditions": ["<condition1 in English>", "<condition2 in English>"]
        }}
    ],
    "approval_rate": "<percentage>",
    "common_requirements": ["<requirement1 in English>", "<requirement2 in English>"],
    "typical_timeline_months": <number>,
    "political_climate": "<assessment in English>",
    "confidence": <0.0 to 1.0>
}}

Focus on patterns and insights. If no similar cases found, state that clearly."""


class DocumentAgent(BaseRAGAgent):
    """Agent that retrieves and analyzes detaljplan / planning documents."""

    _source_label_column = "document_name"

    def __init__(self, db: Session, openai_client: OpenAI):
        super().__init__(db, openai_client, DocumentChunk, "Document Agent")

    def query(self, location: str, project_type: str, units: int) -> dict:
        logger.debug("Searching documents for %d %s units in %s", units, project_type, location)

        search_query = f"{location} {project_type} {units} units approved denied outcome"
        debug_rows = self._retrieve_debug_rows(search_query)
        self._log_retrieval(search_query, debug_rows)
        sources = list(dict.fromkeys(row["source"] for row in debug_rows))
        with start_observation(
            "document_agent.retrieval",
            input={"query": search_query},
            metadata={
                "location": location,
                "project_type": project_type,
                "units": units,
                "matches": [
                    {key: value for key, value in row.items() if key != "content"} for row in debug_rows
                ],
            },
        ):
            pass
        docs = [(row["content"], row["source"]) for row in debug_rows]
        context = "\n\n".join(f"Document {i + 1}:\n{content}" for i, (content, _) in enumerate(docs))

        user_prompt = _USER_TEMPLATE.format(
            context=context, location=location, project_type=project_type, units=units
        )
        response_text = self._call_llm(_SYSTEM_PROMPT, user_prompt)

        try:
            result = self._extract_json(response_text)
            logger.info("Found %d similar cases", len(result.get("similar_cases", [])))
            result["sources"] = sources
            return result
        except Exception as e:
            logger.error("Error parsing LLM response", exc_info=True)
            return {
                "similar_cases": [],
                "approval_rate": "unknown",
                "common_requirements": [],
                "typical_timeline_months": None,
                "political_climate": response_text,
                "confidence": 0.3,
                "sources": sources,
            }
