CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS law_chunks (
    id TEXT PRIMARY KEY,
    law_name TEXT NOT NULL,
    source_file TEXT,
    chapter TEXT,
    chapter_title TEXT,
    section TEXT,
    chunk_index INTEGER,
    content TEXT,
    embedding vector(3072),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_law_chunks_law_name ON law_chunks (law_name);
CREATE INDEX IF NOT EXISTS idx_law_chunks_section ON law_chunks (section);
