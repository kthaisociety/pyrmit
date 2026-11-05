# PCR-0005: Vectors live in Postgres with pgvector or in the local disk store

**Decision:** Vector storage and similarity search MUST use PostgreSQL with pgvector (the chat's `law_chunks` and `document_chunks`, and the hosted corpus's tables loaded by `localrag.pg_store`) or the local disk store built by `localrag.store` (SQLite for the chunks and BM25, a float16 vector file searched on the GPU). Code MUST NOT add a separate vector database service.

**Reason:** pgvector alone was weighed and lost for the national corpus: 1.9 million chunks and about 3.9 GB of vectors do not fit the 1 GB of Neon's free plan, while the disk store serves them from the machine that built them, a dense search being one GPU matrix product of about 0.1 s. The hosted corpus for outside testers (three kommuner and the statutes, about 115,000 chunks) fits pgvector on its own Neon branch, so an install without the data or a GPU can query it. A separate vector database service would add a server to run beside both.

**Consequence:** `LOCAL_RAG_STORE` picks the disk store (`disk`, the default), the hosted corpus (`neon`) or an in-memory index (`memory`, for the evaluations), and both stores answer the same queries (`localrag.pg_store.PgStore` runs the disk store's SQL). Chunks, users and chat history stay in the database of `DATABASE_URL`; the hosted corpus has its own connection string, `CORPUS_DATABASE_URL`. Rebuilding the corpus means rebuilding the disk store, and reloading the hosted tables when they should follow.

**Date:** 2026-11-05
