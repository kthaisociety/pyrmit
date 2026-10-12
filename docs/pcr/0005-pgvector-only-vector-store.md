# PCR-0005: Postgres with pgvector is the only vector store

**Decision:** Vector storage and similarity search MUST use PostgreSQL with pgvector, and MUST NOT add a separate vector database.

**Reason:** TODO(owner): name the alternative that was weighed and why it lost.

**Consequence:** Chunks, users and chat history live in one database and one connection string. Retrieval is SQL with cosine distance against `law_chunks` and `document_chunks`.

**Date:** 2026-10-01
