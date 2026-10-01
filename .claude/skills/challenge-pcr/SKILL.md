---
name: challenge-pcr
description: Test whether a project convention record still stands, and amend or retire it only if the challenge wins.
disable-model-invocation: true
---

# challenge-pcr

**A PCR stands until a challenge beats it.** You are not here to update a document, you are here to find out whether a project-wide convention someone chose still holds, and most of the time it does.

This is the only way a PCR in `docs/pcr/` changes or retires, and it takes a whole session to do it. Read [`../architect-ticket/RECORD-FORMAT.md`](../architect-ticket/RECORD-FORMAT.md) before writing anything.

**The burden is on the challenge, and it is heavy.** A PCR binds every file in the project, so moving one is a project adaption, not an edit: swapping a stack for a better fit, a comment convention that has proven unreadable, a naming rule the whole team trips on. "This is inconvenient", "the current code doesn't do this", and "I'd have chosen differently" are not arguments, they are the friction the PCR was written to create. Overturning one takes a case that the whole project gets better and that the ripple is worth paying. Anything else and the PCR stands.

ADRs are not challenged here. `architect-ticket` and `refactor-ticket` amend those in-session when the work gives them a reason.

---

## 1. Pin the challenge

Settle two things before reading any code:

- **Which PCR.** By number, or by describing the convention. Resolve it in `docs/pcr/` and read the file in full.
- **What the user wants**, in one sentence, and **why**. If the invocation came from a station hitting a blocker, the challenge is whatever that station wanted to do and couldn't.

If the challenge is really "I don't want to follow this right now", say so plainly and stop. That's an answer, and it takes one line.

## 2. Investigate

Read, don't ask, for anything the code can answer:

- **The ripple.** Grep the whole project for what the convention touches. Count the files. That number is what a change costs, and the user hears it before anything else.
- **Compliance today.** Does the code follow the PCR? Drifted code is a finding either way, and it changes what the challenge means.
- **Neighbouring records.** A PCR rarely stands alone: a "no ORM" PCR and an ADR on repository shape lean on each other. Overturning one reaches further than one file, so list the ADRs that would need amending.
- **What the Reason field names.** The alternative that lost. Ask what changed since: did the trade-off actually shift, or does the user just not know the argument?

Emit a short **"What I found"**: the file count, whether the code complies, which records are entangled, and whether the original trade-off still applies. Wait for the user to correct misreads.

## 3. Judge

Weigh the challenge against the recorded convention, out loud, and lead with your own verdict. Three outcomes:

**Stands.** The default, and the most common. The Reason still holds, or the challenge is convenience rather than a project adaption. Say which and stop. Nothing is written.

- If the **code** has drifted from a convention that stands, the code is what's wrong. Report the breach and hand it to the user or to `refactor-ticket`. Never amend a PCR to match code that wandered off.

**Amend.** The convention changes, and the project is better for it. Grill the user into the new Decision, Reason, and Consequence before touching the file. Then edit in place:

- **Keep the number.** Review comments, commits, and open branches cite it.
- **Rewrite Decision, Reason, and Consequence together.** A Reason left describing the old trade-off is worse than no Reason.
- **Bump the Date** to today.
- **The reasoning for the change goes in the commit message**, not the file. The record reads as one current convention.

**Retire.** The thing the convention governed no longer exists in the project, so there is nothing left to bind. Set `**Status:** retired`, bump the Date, and leave the file on disk. Never delete a PCR.

Retire is for a convention with no subject left. A convention that is now *wrong* is an amendment, not a retirement.

**Completion criterion:** a stated verdict with its reasoning, and for an amendment or retirement, the file edited, the Date bumped, and every entangled ADR named for the user to route.

## 4. Report

Three lines, nothing after:

```
PCR-0002  no-orm
Verdict   amended, ORM allowed in reporting/ only
Ripple    41 files, ADR-0009 needs amending, handed to refactor-ticket
```

If the verdict is **stands**, the Ripple line names what the user has to do instead.
