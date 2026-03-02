"""
RAG Agent for historical case research.
"""

from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
import json


class CaseAgent:
    """Agent that retrieves and analyzes historical permit cases."""

    def __init__(self, vector_store):
        self.vector_store = vector_store
        self.llm = Ollama(model="mistral", temperature=0)

        self.prompt_template = PromptTemplate(
            input_variables=["context", "location", "project_type", "units"],
            template="""You are a permit analyst specializing in development project outcomes.

Based ONLY on the following historical cases:

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

Focus on patterns and insights. If no similar cases found, state that clearly.
""",
        )

    def query(self, location: str, project_type: str, units: int) -> dict:
        """
        Query the case database for similar past projects.

        Args:
            location: City/jurisdiction
            project_type: Type of development
            units: Number of units

        Returns:
            Dictionary with historical findings
        """
        print(
            f"[Case Agent] Searching historical cases for {units} {project_type} units in {location}..."
        )

        # Retrieve relevant documents
        search_query = (
            f"{location} {project_type} {units} units approved denied outcome"
        )
        docs = self.vector_store.similarity_search(search_query, k=5)

        # Format context
        context = "\n\n".join(
            [f"Case {i + 1}:\n{doc.page_content}" for i, doc in enumerate(docs)]
        )

        # Generate response
        prompt = self.prompt_template.format(
            context=context, location=location, project_type=project_type, units=units
        )

        response = self.llm.invoke(prompt)

        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks safely)
            content = response if isinstance(response, str) else response.content
            if "```json" in content:
                parts = content.split("```json")
                if len(parts) > 1:
                    json_part = parts[1].split("```")
                    if len(json_part) > 0:
                        content = json_part[0]
            elif "```" in content:
                parts = content.split("```")
                if len(parts) > 1:
                    content = parts[1]

            result = json.loads(content.strip())
            print(
                f"[Case Agent] Found {len(result.get('similar_cases', []))} similar cases"
            )
            return result

        except (json.JSONDecodeError, IndexError) as e:
            print(f"[Case Agent] Error parsing response: {e}")
            # Fallback response
            return {
                "similar_cases": [],
                "approval_rate": "unknown",
                "common_requirements": [],
                "typical_timeline_months": None,
                "political_climate": response if isinstance(response, str) else (response.content if hasattr(response, "content") else str(response)),
                "confidence": 0.3,
            }
