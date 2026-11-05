# ADR-0007: Plan-document links live beside the snapshot, keyed by the polygon

**Decision:** The links between plan polygons and the document store's documents MUST be written by `place.plan_links` as `data/geo/<code>/plan_links.jsonl`, one row per polygon and document with the match level, the document's role and the date, keyed by `place.plan_links.polygon_key`; neither the snapshot features nor the corpus registry (`data/corpus/plans.jsonl`) MUST carry them.

**Scope:** `backend/place/plan_links.py`, `backend/place/store.py` (`plan_links`), `backend/place/profile.py` (plan rows)

**Reason:** Writing the match into each snapshot feature was weighed and lost: a match run would then rewrite every snapshot, and a new fetch would lose the links. Writing it into the corpus registry was weighed and lost too: the registry groups documents into plans by file name and is rebuilt by `corpus.plans`, so a link keyed by its plan ids would not survive that rebuild, and a plan-layer kommun's polygons are not registry plans. A table of its own beside the snapshot is rebuilt by one command, diffed by one file, and read by the profile through the store like `plan_pages.json`.

**Consequence:** A run of `place.plan_links`, against the document store or with `--hosted` against the hosted corpus, replaces a kommun's table whole, so the last run decides which document ids it holds; a fetch of the kommun leaves it in place, and the profile shows a stale link until the matcher runs again. A profile row that reads a document id from anywhere but this table, or a snapshot feature that carries one, breaches this record.

**Date:** 2026-11-05
