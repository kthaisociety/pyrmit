# ADR-0013: The backend writes the place card's texts in the page language

**Decision:** The place profile's user-facing texts (notes, strandskydd reason and note, permit titles and reasons) MUST be written by the backend in the language the frontend passes as `language` to `GET /api/place/profile`; the frontend MUST NOT translate them.

**Reason:** Returning codes for the frontend to translate was weighed and lost: the texts weave in registry values (kommun names, plan refs, area names, legal bases) and follow fixed rules in `place/permits.py`, so moving their wording to the frontend would split each rule from its text and duplicate the formatting in TypeScript.

**Consequence:** A new note or permit gets both wordings in `backend/src/place/` and is checked in both languages by the backend tests. Registry values and keys never change with the language. A switch of page language fetches the profile again. The texts stay deterministic (ADR-0003): no model translates them.

**Scope:** `backend/src/place/profile.py` `build_profile`, `backend/src/place/permits.py` `likely_permits`, `backend/src/routers/place.py` `place_profile`, `frontend/lib/place.ts` `fetchPlaceProfile`

**Date:** 2026-11-07
