---
name: refactor-ticket
description: Last station on the board. Refactors the green ticket branch, folds the acceptance file into the unit suite, and closes the issue.
disable-model-invocation: true
---

# refactor-ticket

The last station on the board and the refactor leg of **red-green-refactor**. The branch is **green** against its **acceptance file**, the one test file `architect-ticket` wrote for this ticket, and you refactor under that green.

**Refactoring means the behaviour is already right and only the shape changes.**

## 1. Pin the work and the diff

The branch carries its **GitHub issue number** in the name, following the branch-naming convention every ticket publishes. Take the current branch, or the one the user names, extract the number, and fetch the ticket with `gh issue view <number>`.

**The spec is two things.** The ticket's **Expected behaviour** is the user-visible bar. The **acceptance file** is the exact bar. Each test's name and docstring is one criterion. Step 2 asks whether the second is true to the first.

- If the branch name carries no issue number, the convention was skipped. Ask the user which issue this closes, and flag that the branch should be renamed to include the number.
- If the issue doesn't already record which branch implements it, backfill the link with `gh issue comment <number>` and a one-line ``Refactored on branch `<branch>` ``.

The diff is `git diff main...HEAD`, three-dot, against the merge-base, on that branch. Substitute the base the user names if it isn't `main`. Confirm the branch resolves, the diff is non-empty, and the diff adds exactly one acceptance file before going further. Find the runner command for the whole suite.

## 2. True-to-spec

**Make no edits in this step.** Work through the ticket's expected behaviour one item at a time:

- **Is a test true to it?** Find the acceptance test covering it. A test that asserts something weaker, stubs out the behaviour it should exercise, or passes vacuously is **not** true to spec, green or not.
- **Is it covered at all?** A behaviour the ticket asked for with no test behind it is the worst finding here, because a green suite says otherwise.
- **Does the diff meet it?** Where no test can reach the behaviour, read the code against the ticket directly.
- **Did anything arrive the ticket never asked for?** Check it against Out of scope. Scope creep is a spec finding too.

**Don't run the acceptance file here.** The branch is already green against it, and you are reading for true-to-spec, not for a pass.

**Completion criterion:** every expected behaviour in the ticket accounted for, each one either true-to-spec or a named finding.

Zero findings means the spec is settled, so go to step 3. Any finding means **halt**.

### The spec halt

Halt, print the findings as the **True-to-spec** table from step 9 and nothing else, then ask the user whether to fix the acceptance **tests** so they're true to the ticket. Only the tests. The ticket body is the single source of truth and is never edited here, and neither is a signature already settled on the branch.

With their go-ahead, fix the tests and run the acceptance file:

- **Still green.** The implementation was right and the test was merely thin. Continue to step 3.
- **Now red.** The weak test was hiding a real gap. **Halt here.** The branch is red again, and taking it green is `implement-ticket`'s job, not yours. Hand the failing tests back and wait.

## 3. Reconcile the suite

Run the whole suite. `implement-ticket` ran only the acceptance file, so this is the first time the ticket meets every test written before it. Every red test outside the acceptance file is one of two things, and the acceptance file tells them apart:

- **Stale.** An acceptance test asserts the contrary. **The newest requirement is the truth**, so rewrite the old test to it, or delete it where the acceptance test now covers the same thing. No approval needed; the ticket already decided this when the user filed it.
- **A regression.** No acceptance test contradicts it, so the ticket never asked for this behaviour to change and the implementer broke it. Fix it inline when the fix stays behind the settled interface, no signature touched, and commit it on its own as `Fix #<N>: <what broke>` so the refactor commit stays shape-only. **Halt** when the fix would need a signature change or a behaviour the ticket doesn't cover. That is a contract problem, and taking it back through `/architect-ticket` is the user's call.

**Completion criterion:** the whole suite is green, and every test that was red has a Reconciled row naming it stale or a regression.

## 4. Refactor

Edit the code directly. This step produces changes, not a list of suggestions.

Three tiers, read per `../architect-ticket/RECORD-FORMAT.md`, from that skill's directory, never from the repo:

1. **PCRs in `docs/pcr/`** hold the project conventions. A breach is a **hard violation**. Fix the code, cite `PCR-NNNN` in the report, and never touch the file. A PCR you disagree with is not a finding: it binds until a `/challenge-pcr` session says otherwise, so fix the code to comply, say so in one line, and point the user at `/challenge-pcr` as separate work. A PCR overrides any baseline entry it contradicts.
2. **ADRs in `docs/adr/`** hold the design decisions. A breach is a hard violation too. Fix it and cite `ADR-NNNN`. Nothing pre-selects them, so take the **whole set** and judge yourself which the changed files fall under. Read each one's **Decision** for what's required and its **Consequence** for what a breach looks like in a diff.
   - **Amend an ADR only when it contradicts a signature already settled on this branch.** The architect settled that signature with the user and it is frozen, so the record is what moves. Keep the number, rewrite Decision, Reason, and Consequence together, bump the Date. The reason goes to the user in one line and into the commit message, never into the file. Any other disagreement with an ADR is fixed in the code and reported, not amended.
   - **Write a new ADR when the diff introduces a shape neighbouring code will copy** and no record names it: a new layer, a new kind of module, a dependency direction the first of its kind establishes. Run it through the ADR tests in the format file. Most refactors write none.
   - If the diff itself adds a file under `docs/adr/` or `docs/pcr/`, it is the architect's and you leave it alone.
   - If neither directory exists, this step runs on the baseline alone, and the Records table collapses to `**Records** no docs/pcr/ or docs/adr/`.
3. **The baseline in `code-standards.md`** applies everywhere no record covers. It ships with this skill, so read it from the skill's own directory, the file sitting beside this `SKILL.md`. Never search the repo for it, and if the repo holds a file by that name, it is not this one. It carries its own gates for deciding which entries a given codebase has, and applying them is yours.

Two standing exemptions, over all three tiers:

- **Tests are exempt.** A test that is true to the ticket stays as written, duplication, long setup and all. Only a record that explicitly governs tests touches them.
- **A refactor never changes behaviour.** If a fix would alter what the code does, leave the code alone and report it as a finding for the user.

**Completion criterion:** every changed non-test file has been read against the whole `docs/pcr/` and `docs/adr/` sets and every applicable entry in `code-standards.md`, and each finding is either fixed or recorded as a deliberate non-fix with a reason.

## 5. Update the docs

1. **`CONTEXT.md`** at the project root, if it exists. Skip if not, and never create one. Revise the Language and Relationships entries where the branch introduced or shifted a domain term. Match the file's existing style.
2. **`README.md`** only if the branch alters something a new contributor needs to run or use the project: a new entry point, a new install or run command, changed configuration. Skip internal-only changes and invent nothing.

Judge both against the whole branch diff, not just your refactor edits.

**Completion criterion:** both files checked, each either edited or recorded unchanged in the report.

## 6. Re-run and commit

Run the whole suite:

- **All green.** Commit the refactor, the docs, and any record together as one commit on the branch, so the refactor stays separately readable from the rest of the branch. Subject: `Refactor: <ticket title>`. An amended ADR adds one line under the body, `Amends ADR-0003: <why, one line>`, since the file carries no history. Don't push unless the user asks.
- **Back to red.** The break is yours. Fix or revert it, then re-run. Never amend a test to accommodate a refactor edit.

## 7. Fold the acceptance file

Only now, with the refactor verified against the untouched acceptance file. Move each test into the test file for the module its entry point lives in, in that file's naming and fixture style, creating the module test file if none exists. Where an existing test already asserts the same thing, keep the acceptance version and drop the other. Then delete the acceptance file, run the whole suite, and commit as `Tests #<N>: fold acceptance file`.

**Completion criterion:** the acceptance file is gone, every test it held exists exactly once in a module test file, the suite is green, one commit.

## 8. Close

`gh issue comment <N>` with the branch name and one line per acceptance test naming its new file. Then `gh issue close <N>`.

## 9. Report

Eight tables, in this order, same shape throughout.

- **Findings only.** No hit, no row. Never narrate what you checked, never wrap a table in prose.
- **Empty collapses.** A table with no rows becomes one line, `**Code smells** none`. Nothing follows it.
- **Cap every cell.** Middle column 6 words, last column 8. No sentences, no trailing periods. Truncate a deep path from the left, `.../handlers/order.ts:17`.

**True-to-spec**

| Behaviour | Test | Problem |
|---|---|---|
| discount shown per line | `test_discount_rate` | asserts total, not rate |
| refunds partial orders | none | uncovered |

**Reconciled**

| Test | Verdict | Change |
|---|---|---|
| `test_discount_flat` | stale, contra `test_discount_rate` | rewritten to rate |
| `test_tax_rounding` | regression | fixed `src/tax.py:40` |

**Records**

| File | Record | Fix |
|---|---|---|
| `src/order.ts:17` | ADR-0004, no DB in handlers | query moved to `OrderRepository` |
| `src/order.ts:3` | PCR-0002, no ORM imports | rewritten to `db.query` |
| `src/repos/` | none | ADR-0009 written, repositories own SQL |

**Code smells**

| File | Smell | Fix |
|---|---|---|
| `src/pricing.ts:42` | duplicated code (6.4) | extracted `applyDiscount`, 2 call sites |

**Architecture**

| File | Issue | Fix |
|---|---|---|
| `src/ui/cart.ts:8` | presentation past controller (5.3) | data returned from `CartController` |

**Tests**

Report only, never fixed.

| File | Rule | Note |
|---|---|---|
| `test_order.py:30` | too many assertions (7.5) | 5 asserts, split |

**Found, not fixed**

| File | Issue | Why |
|---|---|---|
| `src/tax.ts:60` | feature envy (6.4) | fix changes behaviour |

**Spec fixes**

| Behaviour | Test | Change |
|---|---|---|
| discount shown per line | `test_discount_rate` | added rate assertion, user approved |

Close with six lines, nothing after them:

```
Changes  7 across 4 files
Records  ADR-0009 written, ADR-0003 amended
Docs     CONTEXT.md updated, README.md unchanged
Commits  fix b0c1d2e, refactor a1b2c3d, fold e3f4a5b
Tests    suite green, acceptance folded into tests/test_order.py, tests/test_pricing.py
Issue    closed #42
```
