# ADR-0011: The model decides the answer language, the code only reads its decision

**Decision:** The answer language MUST be decided by the model from the user's own words, through the shared rule in `answer_language.LANGUAGE_RULE`; code MUST NOT detect the language itself, and a path that writes answer text in code MUST take the language from the chat's rewrite call (its `LANG:` line, read by `answer_language.split_language`).

**Reason:** The alternative was a rule in code (å/ä/ö and common Swedish words, then earlier messages, then the share of Swedish words) deciding before any model call. It lost because the model reads the question anyway and handles the cases a word list gets wrong (a lone domain term, a mixed sentence, a one-word reply), and the rewrite call that runs first already carries the decision at no extra call.

**Consequence:** Prompts carry the rule and the user's question as written, never only its English rewrite, and the agent's prompt marks the place context as not deciding the language. The templates in code (`agents/parsers.format_response`, the orchestrator's texts, the clarifying prompt) take a `language` argument and never guess one. How often the model decides right is measured by the bilingual eval (`agentic/cases_bilingual.jsonl`), not by unit tests.

**Scope:** `backend/src/answer_language.py`; the answer prompts in `routers/chat.py`, `agentic/agent.py` and `agents/`

**Date:** 2026-11-07
