# ADR-0025: A change to the claim check wins only on both measures

**Decision:** `claim_referee.wins` MUST let a change of the check win only when, on the validation split and against the current check measured in the same run, both its agreement on the agreed stretches and its share of known-answer cases right, over the three kinds together, are higher; neither measure alone, nor the tuning split, MUST decide.

**Reason:** The agreement alone is what #126 used: it rests on referee labels that two model families dispute for 30 % of the stretches, and it credited a change (`per_sentence`) that gained 2 points on validation and lost 4 on tuning. The known-answer cases alone are right by construction but cover two kinds of error only, a wrong number and a wrong source, and say nothing about a claim that adds an inference. Requiring both lets each cover the other's blind spot. Counting the cases per kind ("no kind worse, one better") was the other reading; it rejects a change that catches every wrong number and flags one more untouched claim, while the share over all kinds weighs a missed error against a needless flag.

**Consequence:** Fewer changes win, and "no change wins" is a normal outcome that leaves the live check as it is. A change that only helps one measure is reported with the measure it missed. The combination of winning changes is measured by the same rule and goes live only when it also agrees more than each winner alone (as in ADR-0021's tune).

**Scope:** `backend/src/agentic/claim_referee.py` (`wins`, `improve`)

**Date:** 2026-11-25
