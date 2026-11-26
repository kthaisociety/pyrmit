# ADR-0024: A partly supported claim keeps the verdict "unsupported" and gets a level

**Decision:** The claim check MUST say how much of a cited claim its sources back in `Claim.level` ("full" / "partly" / "none") and MUST NOT add a verdict for it: a partly backed claim keeps the verdict `"unsupported"`.

**Reason:** The other option was a fifth verdict, `"partly"`. ADR-0018 tells every reader of the verdicts to treat one it does not know as not flagged, so the chat, the benchmarks and the recheck would stop flagging partly backed claims the day the check started to give the new verdict, before the interface has a way to show them. A field beside the verdict changes nothing for a reader that ignores it.

**Consequence:** Everything that flags on the verdict flags a partly backed claim as before. A reader that wants three levels reads `level`, which is None unless `CheckOptions.levels` is on, and None for an "uncited" or "skipped" claim. The same goes for `Claim.unbacked`, the sentences not backed: new fields of the saved `claim_check` event, absent from answers saved before them. Showing "partly" differently in the chat is interface work on top of these fields, not a new verdict.

**Scope:** `backend/src/agentic/claim_check.py` (`Claim`, `CheckOptions.levels`, `check_claims`)

**Date:** 2026-11-25
