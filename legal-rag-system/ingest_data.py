"""
Script to ingest documents into vector databases.
"""

from utils.vector_store import VectorStoreManager
import os
from dotenv import load_dotenv

load_dotenv()


def main():
    """Ingest law and case documents into vector stores."""

    # Check for data directories
    if not os.path.exists("./data/laws"):
        os.makedirs("./data/laws")
        print("Created ./data/laws directory")
        print("Please add law documents (as .txt files) to this directory")

    if not os.path.exists("./data/cases"):
        os.makedirs("./data/cases")
        print("Created ./data/cases directory")
        print("Please add case documents (as .txt files) to this directory")

    # Check if data files exist
    law_files = [f for f in os.listdir("./data/laws") if f.endswith(".txt")]
    case_files = [f for f in os.listdir("./data/cases") if f.endswith(".txt")]

    if not law_files:
        print("\n⚠️  WARNING: No .txt files found in ./data/laws/")
        print("Please add some law documents before running ingestion.")
        return

    if not case_files:
        print("\n⚠️  WARNING: No .txt files found in ./data/cases/")
        print("Please add some case documents before running ingestion.")
        return

    print(
        f"\nFound {len(law_files)} law documents and {len(case_files)} case documents"
    )

    # Check for Google API key before creating vector store manager
    if not os.getenv("GOOGLE_API_KEY"):
        print("\n✗ ERROR: GOOGLE_API_KEY not found in environment")
        print("Please create a .env file with your Google API key:")
        print("GOOGLE_API_KEY=your-api-key-here")
        print("\nGet your API key from: https://makersuite.google.com/app/apikey")
        return

    # Initialize vector store manager
    manager = VectorStoreManager()

    # Create law database
    print("\n" + "=" * 60)
    print("Creating Law Database")
    print("=" * 60)
    try:
        law_db = manager.create_law_db()
        print("✓ Law database created successfully")
    except Exception as e:
        print(f"✗ Error creating law database: {e}")
        return  # Exit early if database creation fails

    # Create case database
    print("\n" + "=" * 60)
    print("Creating Case Database")
    print("=" * 60)
    try:
        case_db = manager.create_case_db()
        print("✓ Case database created successfully")
    except Exception as e:
        print(f"✗ Error creating case database: {e}")
        return  # Exit early if database creation fails

    # Create case database
    print("\n" + "=" * 60)
    print("Creating Case Database")
    print("=" * 60)
    try:
        case_db = manager.create_case_db()
        print("✓ Case database created successfully")
    except Exception as e:
        print(f"✗ Error creating case database: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Data ingestion complete!")
    print("You can now run: python main.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
