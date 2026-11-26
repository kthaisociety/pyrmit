# ADR-0020: New referee labels go beside the frozen ones

**Decision:** Labels for stretches the frozen reference does not hold (a change that cuts answers differently) MUST go into the row's `labels` map {stretch text: label}; a label already on a frozen item, the reference's `check_version` and its date MUST NOT change.

**Reason:** The other options were a `--session` flag on `referee` that re-labels and re-freezes the whole reference, or writing the new labels onto the items. Either rewrites what the frozen agreement was measured on, so the frozen numbers every recheck is set against would move under it. Labelling only the missing stretches, outside the code (`prompts`, then `labels`), costs no API spend and leaves the reference's own labels as they were.

**Consequence:** The recheck looks a stretch's label up in the frozen items first, then in `labels`; a stretch in neither is counted unlabelled and kept out of the agreement, and a change with unlabelled validation stretches is not kept. Replacing a frozen label takes a new reference (`referee` again), not an edit.

**Scope:** `backend/src/agentic/claim_referee.py` (`prompts`, `add_labels`, `recheck`)

**Date:** 2026-11-24
