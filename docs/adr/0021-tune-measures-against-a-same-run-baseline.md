# ADR-0021: Tuning measures each change against the check rechecked in the same run

**Decision:** `claim_referee.tune` MUST judge each change of the claim check against the current check rechecked in the same run on the same reference, and only on the validation split; it MUST NOT compare with the frozen agreement or let the tuning split decide.

**Reason:** Comparing with the frozen agreement was the cheaper option (one recheck fewer). But Jev's answers are not fixed over time, so a change would be credited with drift that happened since the reference was frozen; the same-run baseline cancels it. The tuning split is where the changes were chosen, so its numbers flatter them; validation is what they were not fitted on.

**Consequence:** A tune run costs one more recheck (about 316 Jev calls) for the baseline. The report shows the frozen and tuning numbers for reading, never as the rule. A change is kept only when validation agreement over all items rises and the share of the referee's "no" claims still flagged does not fall.

**Scope:** `backend/src/agentic/claim_referee.py` (`tune`, `keeps`)

**Date:** 2026-11-24
