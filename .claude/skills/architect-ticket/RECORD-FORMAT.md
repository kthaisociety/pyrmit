# Record format

Shared contract. The single source of truth for every ADR and PCR this system writes. Every skill that touches `docs/adr/` or `docs/pcr/` reads this file rather than restating it.

Two kinds of record, one shape, two blast radii:

- **An ADR (Architecture Decision Record)** binds one region of the codebase: a module's purpose and shape, what a future implementation inside it may and may not do, a public interface chosen over a real alternative. Lives in `docs/adr/`.
- **A PCR (Project Convention Record)** binds the whole project: tech stack, allowed libraries, naming, comment convention, OOP or not, test suite. Lives in `docs/pcr/`. Changing one ripples through every file, which is why only a dedicated `/challenge-pcr` session may.

Both are `NNNN-slug.md`, numbered sequentially within their own directory. Create the directory lazily, when the first record is written.

**A record is a decision that binds.** There is no second, softer kind. A recorded choice *is* a rule, so write it as one and let a reviewer cite it by number. Anything too soft to bind is not a record; leave it out rather than filing a preference nobody can enforce.

## Template

```md
# ADR-NNNN: {imperative title, for example "Handlers depend inward"}

**Decision:** {one imperative sentence, phrased as MUST or MUST NOT}. For example: "Code in `handlers/` MUST NOT import from `infra/`; depend on `core/` interfaces instead."

**Reason:** {why this was chosen, and what was chosen against}. Name the alternative that was weighed and why it lost.

**Consequence:** {what this forces on the codebase from here on}. What a future change has to live with, and what breaks if someone works around it.

**Date:** {YYYY-MM-DD}
```

A PCR is identical with the `PCR-` prefix. Four fields, every one required.

- **Decision** is what a reviewer cites. Imperative, one sentence, one thing.
- **Reason** is what stops a future reader undoing it by accident. A record that only says *what* was decided is half a record: the reader sees the shape, sees no argument for it, and "simplifies" it away. Name the road not taken.
- **Consequence** is what makes the decision checkable without a check recipe. A reader who knows what the decision forces can tell compliance from breach in a diff, and a consequence stays true when the tooling changes.
- **Date** is when the decision last changed, not when it was first written.

## Optional lines

Add only when they earn their place:

- **Scope:** the paths, layers, or contexts an ADR covers, when it isn't the whole repo. A PCR never has one; a convention with a scope is an ADR.
- **Exceptions:** narrow, named carve-outs. A decision riddled with exceptions is really two decisions, or none.
- **Status:** `retired`, when the code the decision governed no longer exists. Retired records stay on disk so old review comments and branches still resolve the number. Absent means live.

## What earns an ADR

Three tests, all required:

1. **Imperative.** It can be phrased as MUST or MUST NOT, not "we prefer" or "usually".
2. **Arguable.** You can name what it was chosen *against*. A decision with no losing alternative is a description, and its Reason field will read as filler.
3. **Load-bearing.** A real reader would otherwise get it wrong. Skip anything that restates the language default or the obvious.

Then the spine test. An ADR names something with structure behind it: what a module is for and what shape it takes, what code inside it is and is not allowed to do, which way a dependency points, who owns a piece of data, an interface shape that beat a real alternative. A parameter name, a default value, the order of two arguments, a choice between two equivalent idioms: none of these has a spine, and none gets a record. A ticket's grill touches many topics and settles most of them without argument. Those produce nothing. The one or two that were argued against a named alternative are the ADRs, and a ticket that argued nothing produces none.

## What earns a PCR

A convention that holds across the whole project and that a single ticket must never move: the stack, the libraries a file may import, how identifiers are named, how comments are written, whether the code is object-oriented, which test runner and layout the suite uses. The test is ripple. If changing it means touching every file, it is a PCR. If it only touches one region, it is an ADR.

A PCR that overlaps `refactor-ticket`'s `code-standards.md` baseline wins. A PCR saying the project is not object-oriented switches off every entry marked `(OO only)`.

## One decision per file

Never bundle two. The value is that `ADR-0012` names exactly one thing, so "violates ADR-0012" is unambiguous and the reader loads one short file. A candidate with an "and" in it is two records.

The filename slug is the decision's shorthand. Pick it so the directory reads as an index at a glance: `0012-no-orm-in-domain.md`, not `0012-database.md`.

## Who writes, who changes

**ADRs.** `architect-ticket` writes them at its diff gate, one per argument the grill had. `refactor-ticket` writes one when the diff introduces a shape neighbouring code will copy. No other skill writes one; a station that finds itself weighing an ADR-worthy call is a station that was handed an incomplete contract, and it halts.

Either of those two stations may **amend** an existing ADR when the work in front of it has a reason the record did not anticipate. Keep the number, rewrite Decision, Reason, and Consequence together so the file reads as one current decision, and bump the Date. **The reasoning for the change does not go in the file.** State it to the user in the session and put it in the commit message. The ADR stays a clean statement of what binds now. **Retire** an ADR the same way, by setting `Status: retired` and bumping the Date, when the code it governed is gone. Never delete one.

**PCRs.** `project-planning` seeds them once per project. `architect-ticket` writes a new one when its ticket is the first to settle a project-wide convention, for example the first ticket that picks a test runner. Nothing else writes one.

**Changing or retiring a PCR takes a full `/challenge-pcr` session, and there is no other route.** No skill edits a file in `docs/pcr/` in passing, not to fix drift, not to reword, not to retire, and no skill deletes one. So when a PCR blocks the work in front of you:

1. **Stop at the PCR.** Name it, and name what it blocks, in one line.
2. **Hand it to the user** to run `/challenge-pcr`. You do not run it for them, and you do not run it as part of the current session.
3. **Assume it stands.** Until that session returns a verdict, the convention binds. Never write code, or an interface, on the assumption that the challenge will succeed.
