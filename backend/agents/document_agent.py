"""
RAG Agent for detaljplan / planning document research.
Uses OpenAI GPT + SQLAlchemy pgvector queries on document_chunks.
"""

from openai import OpenAI
from sqlalchemy.orm import Session

from agents.base import BaseRAGAgent
from models import DocumentChunk

_SYSTEM_PROMPT = "You are a permit analyst specializing in development project outcomes."

_USER_TEMPLATE = """Based ONLY on the following historical documents:

{context}

Answer this question:
What happened when people tried to build similar {project_type} projects (around {units} units) in {location}?

Provide your answer in JSON format:
{{
    "similar_cases": [
        {{
            "address": "<address>",
            "units": <number>,
            "outcome": "APPROVED" or "DENIED",
            "year": <year>,
            "conditions": ["<condition1>", "<condition2>"]
        }}
    ],
    "approval_rate": "<percentage>",
    "common_requirements": ["<requirement1>", "<requirement2>"],
    "typical_timeline_months": <number>,
    "political_climate": "<assessment>",
    "confidence": <0.0 to 1.0>
}}

Focus on patterns and insights. If no similar cases found, state that clearly."""


class DocumentAgent(BaseRAGAgent):
    """Agent that retrieves and analyzes detaljplan / planning documents."""

    def __init__(self, db: Session, openai_client: OpenAI):
        super().__init__(db, openai_client, DocumentChunk, "Document Agent")

    def query(self, location: str, project_type: str, units: int) -> dict:
        print(f"[{self.label}] Searching documents for {units} {project_type} units in {location}...")

        search_query = f"{location} {project_type} {units} units approved denied outcome"
        docs = self._retrieve(search_query)
        context = "\n\n".join(f"Document {i + 1}:\n{doc}" for i, doc in enumerate(docs))

        user_prompt = _USER_TEMPLATE.format(
            context=context, location=location, project_type=project_type, units=units
        )
        response_text = self._call_llm(_SYSTEM_PROMPT, user_prompt)

        try:
            result = self._extract_json(response_text)
            print(f"[{self.label}] Found {len(result.get('similar_cases', []))} similar cases")
            return result
        except Exception as e:
            print(f"[{self.label}] Error parsing response: {e}")
            return {
                "similar_cases": [],
                "approval_rate": "unknown",
                "common_requirements": [],
                "typical_timeline_months": None,
                "political_climate": response_text,
                "confidence": 0.3,
            }
