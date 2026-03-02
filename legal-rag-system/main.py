"""
Main entry point for the legal RAG system.
"""

from agents.law_agent import LawAgent
from agents.case_agent import CaseAgent
from agents.orchestrator import Orchestrator
from utils.pg_vector_store import PgVectorStore
from utils.parsers import parse_query, format_response
from dotenv import load_dotenv
import os

load_dotenv()

REQUIRED_ENV = ["OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]


def main():
    """Run the legal RAG system."""

    print("\n" + "=" * 60)
    print("LEGAL RAG SYSTEM - REGEN VILLAGES")
    print("=" * 60)

    missing = [v for v in REQUIRED_ENV if not os.getenv(v)]
    if missing:
        print(f"\n✗ ERROR: Missing environment variables: {', '.join(missing)}")
        print("Please add them to your .env file.")
        return

    print("\n[System] Connecting to Supabase vector store...")
    try:
        store = PgVectorStore()
        print("[System] ✓ Connected successfully")
    except Exception as e:
        print(f"[System] ✗ Error connecting to vector store: {e}")
        return

    # Initialize agents
    print("[System] Initializing agents...")
    law_agent = LawAgent(store.law_db)
    case_agent = CaseAgent(store.case_db)
    orchestrator = Orchestrator(law_agent, case_agent)
    print("[System] ✓ All agents ready\n")

    # Interactive loop
    while True:
        print("\n" + "─" * 60)
        print("Enter your question (or 'quit' to exit):")
        print("Example: Can I build 20 units in Palo Alto?")
        query = input("> ")

        if query.lower() in ["quit", "exit", "q"]:
            print("\nGoodbye!")
            break

        if not query.strip():
            continue

        # Parse query
        parsed = parse_query(query)
        print(f"\n[System] Parsed query:")
        print(f"  Location: {parsed['location']}")
        print(f"  Project: {parsed['project_type']}")
        print(f"  Units: {parsed['units']}")

        # Validate parsed data
        if not parsed["location"] or not parsed["units"]:
            print("\n[System] ✗ Could not parse location or unit count from query")
            print("Please try rephrasing, e.g.: 'Can I build 20 units in Palo Alto?'")
            continue

        # Run analysis
        try:
            result = orchestrator.analyze(
                location=parsed["location"],
                project_type=parsed["project_type"],
                units=parsed["units"],
            )

            # Display results
            print("\n" + format_response(result))

        except Exception as e:
            print(f"\n[System] ✗ Error during analysis: {e}")
            print(
                "Please try again with a different query or check the system configuration."
            )


if __name__ == "__main__":
    main()
