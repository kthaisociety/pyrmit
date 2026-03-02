"""
RAG Agent for legal/regulatory research.
"""

from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
import json


class LawAgent:
    """Agent that retrieves and interprets legal regulations."""

    def __init__(self, vector_store):
        self.vector_store = vector_store
        self.llm = Ollama(model="mistral", temperature=0)

        self.prompt_template = PromptTemplate(
            input_variables=["context", "location", "project_type", "units"],
            template="""You are a legal expert specializing in zoning and land use law.

Based ONLY on the following legal documents:

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

Be specific and cite the actual code sections. If information is missing, state that clearly.
""",
        )

    def query(self, location: str, project_type: str, units: int) -> dict:
        """
        Query the law database for relevant regulations.

        Args:
            location: City/jurisdiction
            project_type: Type of development
            units: Number of units

        Returns:
            Dictionary with legal findings
        """
        print(
            f"[Law Agent] Searching regulations for {units} {project_type} units in {location}..."
        )

        # Retrieve relevant documents
        search_query = (
            f"{location} zoning {project_type} density {units} units maximum allowed"
        )
        docs = self.vector_store.similarity_search(search_query, k=5)

        # Format context
        context = "\n\n".join(
            [f"Document {i + 1}:\n{doc.page_content}" for i, doc in enumerate(docs)]
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
                f"[Law Agent] Found {len(result.get('applicable_laws', []))} applicable laws"
            )
            return result

        except (json.JSONDecodeError, IndexError) as e:
            print(f"[Law Agent] Error parsing response: {e}")
            # Fallback response
            return {
                "max_units_allowed": "unknown",
                "base_zoning": "Could not determine",
                "applicable_laws": [],
                "conditions": [],
                "special_provisions": response if isinstance(response, str) else (response.content if hasattr(response, "content") else str(response)),
                "confidence": 0.3,
            }
