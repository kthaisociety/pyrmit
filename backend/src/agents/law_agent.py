"""
RAG Agent for legal/regulatory research.
Uses OpenAI GPT + SQLAlchemy pgvector queries on law_chunks.
"""

import logging

from openai import OpenAI
from sqlalchemy.orm import Session

from agents.base import BaseRAGAgent, _TRANSLATION_INSTRUCTION
from models import LawChunk
from observability import start_observation

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a legal expert specializing in zoning and land use law. "
    + _TRANSLATION_INSTRUCTION
)

_USER_TEMPLATE = """Based ONLY on the following legal documents (which may be in Swedish):

{context}

Answer this question in English:
What are the legal requirements for building {units} units of {project_type} in {location}?

When citing Swedish source text, use this format:
> **English:** [your English interpretation]
> **Original (Swedish):** [exact Swedish text from the source]

Provide your answer in JSON format:
{{
    "max_units_allowed": <number or "varies">,
    "base_zoning": "<description in English>",
    "applicable_laws": ["<law1>", "<law2>"],
    "conditions": ["<condition1 in English>", "<condition2 in English>"],
    "special_provisions": "<any density bonuses, exemptions, etc — in English>",
    "confidence": <0.0 to 1.0>
}}

Be specific and cite the actual code sections. If information is missing, state that clearly."""


class LawAgent(BaseRAGAgent):
    """Agent that retrieves and interprets legal regulations."""

    _source_label_column = "law_name"

    def __init__(self, db: Session, openai_client: OpenAI):
        super().__init__(db, openai_client, LawChunk, "Law Agent")

    def query(self, location: str, project_type: str, units: int) -> dict:
        logger.debug("Searching regulations for %d %s units in %s", units, project_type, location)

        search_query = f"{location} zoning {project_type} density {units} units maximum allowed"
        debug_rows = self._retrieve_debug_rows(search_query)
        self._log_retrieval(search_query, debug_rows)
        sources = list(dict.fromkeys(row["source"] for row in debug_rows))
        with start_observation(
            "law_agent.retrieval",
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
            logger.info("Found %d applicable laws", len(result.get("applicable_laws", [])))
            result["sources"] = sources
            return result
        except Exception as e:
            logger.error("Error parsing LLM response", exc_info=True)
            return {
                "max_units_allowed": "unknown",
                "base_zoning": "Could not determine",
                "applicable_laws": [],
                "conditions": [],
                "special_provisions": response_text,
                "confidence": 0.3,
                "sources": sources,
            }
