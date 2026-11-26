# ADR-0027: A failed claim check keeps what its retry needs

**Decision:** A claim check that could not run MUST be saved with the raw answer, the chunk ids the agent read and the place data it was given, and a retry MUST check those; a retry MUST NOT rebuild the raw answer from the answer text the chat shows.

**Reason:** The check reads the agent's raw answer, where each citation names one chunk. The shown answer has a number per source, and one number can stand for several chunks. Rebuilding the raw answer from the shown text and the citation list was weighed and lost: a claim would be judged against every chunk under its number, not only those the agent pointed at, so a retry would pass claims the live check flags, and the chunks the agent read, which resolve a miscopied id, would be lost.

**Consequence:** The failed `claim_check` event of a saved answer carries `message_id` and `retry` (`chat._failed_check`); a check that ran carries neither. Only an answer with that data can be retried: one that failed before it was saved keeps its notice without a retry button. The retry data goes to the browser with the trace, so nothing secret may be put in it. A change to what `check_claims` takes has to be saved here too, or a retry checks less than the first check did.

**Scope:** `backend/src/routers/chat.py`, `_failed_check` and `retry_claim_check`

**Date:** 2026-11-26
