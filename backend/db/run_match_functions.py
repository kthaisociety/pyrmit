"""Run match_functions.sql against the Postgres DB."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DB_URL = os.environ["DATABASE_URL"]

SQL = """
CREATE OR REPLACE FUNCTION match_law_chunks(query_embedding vector(3072), match_count int)
RETURNS TABLE (content text) AS $$
  SELECT content FROM law_chunks
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION match_document_chunks(query_embedding vector(3072), match_count int)
RETURNS TABLE (content text) AS $$
  SELECT content FROM document_chunks
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$ LANGUAGE sql;
"""

conn = psycopg2.connect(DB_URL)
conn.autocommit = True
cur = conn.cursor()
cur.execute(SQL)
print("RPC functions created successfully:")
print("  - match_law_chunks")
print("  - match_document_chunks")
cur.close()
conn.close()
