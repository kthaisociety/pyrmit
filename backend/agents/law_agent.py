"""
RAG Agent for legal/regulatory research.
Uses OpenAI GPT + SQLAlchemy pgvector queries on law_chunks.
"""

from openai import OpenAI
from sqlalchemy.orm import Session

from agents.base import BaseRAGAgent
from models import LawChunk

_SYSTEM_PROMPT = "You are a legal expert specializing in zoning and land use law."

_USER_TEMPLATE = """Based ONLY on the following legal documents:

{context}

Answer this question:
What are the legal requirements for building {units} units of {project_type} in {location}?

Provide your answer in JSON format:
{{
    "max_units_allowed": <number or "varies">,
    "base_zoning": "<description>",
    "applicable_laws": ["<law1>", "<law2>"],
    "conditions": ["<condition1>", "<condition2>"],
    "special_provisions": "<any density bonuses, exemptions, etc>",
    "confidence": <0.0 to 1.0>
}}

Be specific and cite the actual code sections. If information is missing, state that clearly."""


class LawAgent(BaseRAGAgent):
    """Agent that retrieves and interprets legal regulations."""

    def __init__(self, db: Session, openai_client: OpenAI):
        super().__init__(db, openai_client, LawChunk, "Law Agent")

    def query(self, location: str, project_type: str, units: int) -> dict:
        print(f"[{self.label}] Searching regulations for {units} {project_type} units in {location}...")

        search_query = f"{location} zoning {project_type} density {units} units maximum allowed"
        docs = self._retrieve(search_query)
        context = "\n\n".join(f"Document {i + 1}:\n{doc}" for i, doc in enumerate(docs))

        user_prompt = _USER_TEMPLATE.format(
            context=context, location=location, project_type=project_type, units=units
        )
        response_text = self._call_llm(_SYSTEM_PROMPT, user_prompt)

        try:
            result = self._extract_json(response_text)
            print(f"[{self.label}] Found {len(result.get('applicable_laws', []))} applicable laws")
            return result
        except Exception as e:
            print(f"[{self.label}] Error parsing response: {e}")
            return {
                "max_units_allowed": "unknown",
                "base_zoning": "Could not determine",
                "applicable_laws": [],
                "conditions": [],
                "special_provisions": response_text,
                "confidence": 0.3,
            }
