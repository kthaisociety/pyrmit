# ADR-0005: Plan-layer snapshots carry a normalised plan block

**Decision:** A plan-layer snapshot written by `place.plan_layers` MUST keep the provider's raw attributes and MUST add the normalised plan (`_plan`: aktbeteckning, name, date, type, page, documents, dropped links) to every feature when the snapshot is written; the place profile MUST read plans of such a kommun from that block only.

**Scope:** `backend/place/plan_layers.py`, `backend/place/profile.py` (plan rows of a kommun that is not a pilot)

**Reason:** Mapping the 180 kommuner's attributes at read time, the way `place.sources.feature` maps Uppsala's, was weighed and lost. Link normalisation (bare file names made absolute, HTML unwrapped, internal paths dropped and counted) belongs to the fetch, where the coverage report counts what was dropped, and a profile row then reads the same for every kommun whatever the provider's attribute names. The raw attributes stay so that a later rule (a new attribute name, a better date) can be applied by fetching again, without losing what the provider said.

**Consequence:** A profile row of a plan-layer kommun never reaches past `_plan` into the raw attributes, and a change to the normalisation rules means a new fetch. Reading raw attributes in `place.profile` for such a kommun, or writing a snapshot without the block, breaches this record.

**Date:** 2026-11-03
