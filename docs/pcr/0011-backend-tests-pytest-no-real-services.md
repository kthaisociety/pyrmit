# PCR-0011: Backend tests run on pytest without a real database or model calls

**Decision:** Backend tests MUST run on pytest from `backend/tests/unit/`, mirroring the layout of `backend/src/`, and MUST NOT connect to a real database or call a real model or OCR API.

**Reason:** Tests against a real Postgres with pgvector in CI were weighed and lost for now: they need a database container and an `init.sql` kept in sync for CI, and they belong with end-to-end tests, which have not been decided. Real model calls would make the suite slow, costly and nondeterministic.

**Consequence:** `uv run pytest` runs the whole backend suite, and CI runs it as the required `backend / test` check with no secrets set. A test that needs `DATABASE_URL`, `OPENAI_API_KEY`, `AI_GATEWAY_API_KEY` or `MISTRAL_API_KEY` to pass is a breach; fake the database session or `llm.py` client instead.

**Date:** 2026-10-06
