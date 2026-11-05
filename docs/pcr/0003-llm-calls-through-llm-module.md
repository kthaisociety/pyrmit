# PCR-0003: Model clients come from backend/src/llm.py and backend/src/embeddings.py

**Decision:** Code MUST get its chat client and model names from `backend/src/llm.py`, and its embedding client from `backend/src/embeddings.py` (`get_embedder()`). It MUST NOT construct an `OpenAI` client anywhere else.

**Reason:** The chat and the embeddings reach different providers. `llm.py` picks the Vercel AI Gateway, OpenAI or OpenRouter (`LLM_PROVIDER`) and normalises model names, timeouts and retries. `embeddings.py` serves OpenAI, OpenRouter, a local OpenAI-compatible server or an in-process sentence-transformers model, each with its own endpoint, key and dimension (`EMBEDDING_*`). Folding the embedding client into `llm.py` was weighed and lost: the embedding provider is chosen independently of the chat provider, and the local models need no client at all.

**Consequence:** A new chat provider or setting goes into `llm.py`, a new embedding provider into `embeddings.py`. Importing `OpenAI` elsewhere for type hints is fine. Calling `OpenAI(...)` outside these two modules bypasses the provider choice and is a breach.

**Date:** 2026-11-05
