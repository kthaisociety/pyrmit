"""
Supabase/pgvector-backed vector store that duck-types the ChromaDB
similarity_search interface so LawAgent and CaseAgent work unchanged.
"""

import os
from types import SimpleNamespace

from supabase import create_client, Client
from openai import OpenAI


class TypedVectorStore:
    """Exposes .similarity_search(query, k) returning objects with .page_content,
    matching the interface that LawAgent/CaseAgent already expect from ChromaDB."""

    def __init__(self, supabase_client: Client, openai_client: OpenAI, rpc_name: str):
        self.supabase = supabase_client
        self.openai = openai_client
        self.rpc_name = rpc_name

    def similarity_search(self, query: str, k: int = 5) -> list:
        embedding = self.openai.embeddings.create(
            model="text-embedding-3-large", input=query
        ).data[0].embedding

        result = self.supabase.rpc(
            self.rpc_name,
            {"query_embedding": embedding, "match_count": k},
        ).execute()

        return [
            SimpleNamespace(page_content=row["content"])
            for row in result.data
        ]


class PgVectorStore:
    """Top-level store exposing .law_db and .case_db with identical interfaces."""

    def __init__(self):
        supabase_url = os.environ["SUPABASE_URL"]
        supabase_key = os.environ["SUPABASE_KEY"]

        self.supabase = create_client(supabase_url, supabase_key)
        self.openai = OpenAI()

        self.law_db = TypedVectorStore(self.supabase, self.openai, "match_law_chunks")
        self.case_db = TypedVectorStore(self.supabase, self.openai, "match_document_chunks")
