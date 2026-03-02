"""Quick test of the RAG system"""

import os
from dotenv import load_dotenv

load_dotenv()

from utils.vector_store import VectorStoreManager
from agents.law_agent import LawAgent
from agents.case_agent import CaseAgent
from agents.orchestrator import Orchestrator
from utils.parsers import parse_query, format_response

# Initialize
print("Loading databases...")
manager = VectorStoreManager()
law_db = manager.load_law_db()
case_db = manager.load_case_db()
print("✓ Databases loaded")

# Initialize agents
print("\nInitializing agents...")
law_agent = LawAgent(law_db)
case_agent = CaseAgent(case_db)
orchestrator = Orchestrator(law_agent, case_agent)
print("✓ All agents ready")

# Test query
test_query = "Can I build 20 residential units in Palo Alto?"
print(f"\nTest query: {test_query}")
print("\nProcessing...")

# Parse query
parsed = parse_query(test_query)
print(f"Parsed: {parsed}")

# Run analysis
result = orchestrator.analyze(
    location=parsed.get("location", "Unknown"),
    project_type=parsed.get("project_type", "residential"),
    units=parsed.get("units", 0),
)

# Format and display
print("\n" + "=" * 60)
print("RESULT:")
print("=" * 60)
formatted = format_response(result)
print(formatted)
