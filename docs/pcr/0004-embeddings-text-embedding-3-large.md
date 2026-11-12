# PCR-0004: Each vector store is searched with the model that embedded it

**Decision:** Every embedding MUST come from the model configured for the store it is compared with: the pgvector tables `law_chunks` and `document_chunks` use `EMBEDDING_*` (default `text-embedding-3-large` at 3072 dimensions), and the local corpus uses the model it was indexed with (`LOCAL_RAG_MODEL`). A store MUST record that model, and the app MUST refuse or flag a query model that differs from it.

**Reason:** One model for every store was weighed and lost. On the retrieval evaluation of Swedish planning and statute questions (`localrag.eval`, `data/eval/`), `Snowflake/snowflake-arctic-embed-l-v2.0` on the Swedish query led (recall@5 0.92, `bge-m3` 0.91), runs locally on the GPU, and embeds the 1.9 million local chunks at no API cost on every rebuild. The hosted corpus uses `bge-m3`, which OpenRouter serves with the same vectors as the local model, so an install without a GPU can query it.

**Consequence:** Query and chunk vectors stay comparable within a store. Changing a store's model means re-embedding that store in one change: `chunking/reembed.py` for the pgvector tables (it stores the model label as the column comment, and `main.py` logs an error on a mismatch), `localrag.index` and `localrag.store` for the local corpus, `localrag.pg_store` for the hosted one, whose `corpus_meta` the app checks at startup.

**Date:** 2026-11-05
