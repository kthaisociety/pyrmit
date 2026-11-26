# ADR-0022: A stretch the two referees dispute stays out of every agreement figure

**Decision:** Once a row has a second referee, every agreement figure of `claim_referee` (`summary`, `report`, `recheck`, `tune`, `measure`) MUST leave out the stretches the two referees dispute, and two referees MUST count as agreeing on two levels: for a cited claim "yes" against "partly" or "no", for an uncited sentence the same `needed`.

**Reason:** Two alternatives lost. Letting the first referee decide and using the second only to count differences keeps every stretch, but then the check is graded against labels another model family rejects, and nobody is in the loop to say who is right. Requiring the exact same label ("partly" against "no" disputed) drops many more stretches for a difference that never decides anything: a change to the check wins on two levels, supported against everything else. Leaving disputed stretches out only in the new `measure` would give two agreement numbers for the same check, depending on the command.

**Consequence:** The agreement is measured on fewer stretches, and the count of disputed ones is reported beside it as the measure's own uncertainty. A reference without a second referee counts as before, so its numbers are not comparable with those of one that has it. A row whose second referee reply was unreadable twice is disputed whole. The first referee's labels are never changed by the second (ADR-0020).

**Scope:** `backend/src/agentic/claim_referee.py` (`standing`, `summary`, `recheck`, `tune`, `measure`)

**Date:** 2026-11-25
