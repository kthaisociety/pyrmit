-- Supabase RPC functions for pgvector similarity search.
-- Run this once in the Supabase SQL Editor.

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
