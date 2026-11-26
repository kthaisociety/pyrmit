# ADR-0018: A claim the check skips stays in its result

**Decision:** A claim or sentence the claim check leaves unjudged on purpose (a hedge under `CheckOptions.skip_hedges`) MUST stay in `ClaimCheck.claims` and the `claim_check` event with verdict `"skipped"`; it MUST NOT be dropped or kept in a separate list.

**Reason:** The other option was a separate list of skipped texts beside `claims`, or leaving them out. Leaving them out makes a skipped hedge look like a claim whose call failed, which the referee's recheck counts as "not_checked" and leaves out of the agreement; a separate list adds a second shape to the event every reader of `claim_check` (chat, benchmarks, recheck) would have to merge back. One more verdict keeps one list.

**Consequence:** Every reader of the verdicts handles `"skipped"`: agreement counts it as not flagged, like `"supported"`; the chat marks nothing for it, as it marks nothing for a supported claim. A new reader that only knows the three older verdicts must treat an unknown one as not flagged.

**Scope:** `backend/src/agentic/claim_check.py` (`Claim`, `check_claims`), `backend/src/agentic/claim_referee.py`

**Date:** 2026-11-24
