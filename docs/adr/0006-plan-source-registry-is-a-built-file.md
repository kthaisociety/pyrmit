# ADR-0006: The plan source registry is a built file, not code

**Decision:** The kommun plan sources MUST live in `backend/place/plan_sources.json`, built from the survey in `docs/research/` by `python -m place.registry` and edited by hand only for what the survey cannot tell (base pattern, licence); code MUST NOT hold a kommun's plan source as a constant, and a rebuild MUST keep those hand edits.

**Scope:** `backend/place/registry.py`, `backend/place/plan_sources.json`

**Reason:** Listing the sources in Python like `place.sources.PILOTS` was weighed and lost: 180 entries of attribute names are data, an operator fixes a wrong attribute or adds a base pattern without a code change, and the survey is the record of where each entry came from. Reading the survey CSV at run time was weighed and lost too: it lives outside the backend package, and an operator's corrections would have nowhere to go.

**Consequence:** A kommun is added by adding it to the survey and rebuilding, or by editing the file; the pilot kommuner stay in `place.sources` because they carry more than a plan layer. A plan source hard-coded in Python, or a rebuild that drops an operator's base pattern, breaches this record.

**Date:** 2026-11-03
