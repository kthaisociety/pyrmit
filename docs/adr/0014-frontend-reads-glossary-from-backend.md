# ADR-0014: The frontend reads the glossary from the backend

**Decision:** The frontend MUST take Swedish domain terms' English explanations from `GET /api/glossary` (`backend/src/glossary.py`), shown through `components/Term.tsx`; it MUST NOT keep its own copy of an explanation.

**Reason:** Writing the explanations into the English dictionary by hand was weighed and lost: the chat answers and the place card already explain terms from `glossary.GLOSSARY`, and a second copy in the frontend would drift from it, so the same term would be explained differently in the answer and on the page.

**Consequence:** A term is added or reworded in `glossary.py` only, and the page picks it up. A domain term on the page is wrapped in `Term`, which in English shows the explanation as a tooltip, never inline. An English explanation of a glossary term typed into `frontend/lib/messages.ts` is a breach.

**Scope:** `frontend/components/Term.tsx`, `frontend/lib/i18n.tsx` `LanguageProvider`, `backend/src/routers/glossary.py`

**Date:** 2026-11-07
