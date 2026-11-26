# ADR-0023: A known-answer case is wrong by construction, never by judgement

**Decision:** `claim_referee.known_cases` MUST build a changed case only by a rule that makes it wrong whatever a model would say: a number that stands in the claim's cited chunk replaced by one that stands in none of its sources, or the claim's citation replaced by a chunk cited only in answers of another case, and only for a row without place data. It MUST NOT use a model to write or to pick a case.

**Reason:** The cases exist because the referee's labels are themselves uncertain; a case made or checked by a model would bring that uncertainty back. The alternatives were sentences rewritten to their opposite by a model (the rewrite can itself be wrong, and someone would have to check it), a source swapped for another chunk of the same answer (two chunks of one statute often back the same claim), and changing any number of the claim (a number from the user's question, such as their own "25 kvm", is not stated by the source, so changing it does not make the claim unsupported).

**Consequence:** Fewer cases than claims: a claim without a number from its source gives no number case, a row with place data gives no source case. The cases cover two kinds of error only (a wrong figure, a wrong source) and say nothing about a claim that adds an inference. The same reference always gives the same cases, so two checks can be compared on them.

**Scope:** `backend/src/agentic/claim_referee.py` (`known_cases`)

**Date:** 2026-11-25
