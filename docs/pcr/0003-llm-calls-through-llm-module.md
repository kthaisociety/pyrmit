# PCR-0003: All model calls go through backend/llm.py

**Decision:** Code MUST get its OpenAI client and model names from `backend/llm.py` and MUST NOT construct an `OpenAI` client anywhere else.

**Reason:** TODO(owner): name the alternative that was weighed and why it lost.

**Consequence:** `llm.py` decides whether a call goes through the Vercel AI Gateway or straight to OpenAI, and normalizes model names to match. Importing `OpenAI` elsewhere for type hints is fine. Calling `OpenAI(...)` elsewhere bypasses the gateway and is a breach.

**Date:** 2026-10-01
