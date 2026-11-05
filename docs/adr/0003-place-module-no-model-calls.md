# ADR-0003: The place module makes no model calls

**Decision:** Code in `backend/place/` MUST NOT call a language model or import `llm.py`, `agents/` or `agentic/`. The place profile is built from registers only.

**Scope:** `backend/place/`

**Reason:** Letting the agent find the plans and protected areas of a place itself, with tools, was weighed and lost. The user has to be able to tell a registry fact from the model's reading of it: the place card shows the registry, and the answer interprets it. The lookup also has to be testable and scorable without keys or credits.

**Consequence:** The chat receives the profile as input and may interpret it, but the profile itself is deterministic. Anything that needs judgement, such as sammanhållen bebyggelse or lämplighet, belongs in the answer, not in the profile. Code in `agentic/` or `routers/` may import `place/`; an import in the other direction breaches this record.

**Date:** 2026-10-25
