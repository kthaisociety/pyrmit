"""
Quick integration test: verifies Supabase connection, RPC functions,
and the PgVectorStore duck-typing.
"""

import os
import sys
from dotenv import load_dotenv

# Load env from both the local .env and the backend .env
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from utils.pg_vector_store import PgVectorStore


def main():
    print("=" * 60)
    print("Integration Test: PgVectorStore")
    print("=" * 60)

    # 1. Check env vars
    for var in ("OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        val = os.getenv(var)
        if not val:
            print(f"FAIL: {var} not set")
            return
        print(f"  {var} = {val[:12]}...")

    # 2. Create store
    print("\nCreating PgVectorStore...")
    try:
        store = PgVectorStore()
        print("  OK: store created")
    except Exception as e:
        print(f"  FAIL: {e}")
        return

    # 3. Test law_db similarity_search
    print("\nTesting store.law_db.similarity_search('zoning regulations', k=3)...")
    try:
        results = store.law_db.similarity_search("zoning regulations", k=3)
        print(f"  OK: got {len(results)} results")
        for i, doc in enumerate(results):
            snippet = doc.page_content[:80].replace("\n", " ")
            print(f"    [{i}] {snippet}...")
    except Exception as e:
        print(f"  FAIL: {e}")

    # 4. Test case_db similarity_search (queries document_chunks table)
    print("\nTesting store.case_db.similarity_search('building permit approved', k=3)...")
    try:
        results = store.case_db.similarity_search("building permit approved", k=3)
        print(f"  OK: got {len(results)} results")
        for i, doc in enumerate(results):
            snippet = doc.page_content[:80].replace("\n", " ")
            print(f"    [{i}] {snippet}...")
    except Exception as e:
        print(f"  FAIL: {e}")
        print("  (Run match_functions.sql in Supabase SQL Editor if RPC not found)")

    # 5. Verify duck-typing
    print("\nDuck-type check:")
    try:
        r = store.law_db.similarity_search("test", k=1)
        if r:
            assert hasattr(r[0], "page_content"), "Missing .page_content attribute"
            assert isinstance(r[0].page_content, str), ".page_content is not a string"
            print("  OK: .page_content attribute works correctly")
        else:
            print("  WARN: no results returned (law_chunks might be empty)")
    except Exception as e:
        print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print("Integration test complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
