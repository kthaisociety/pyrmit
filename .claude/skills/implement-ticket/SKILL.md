---
name: implement-ticket
description: Fills in the stub bodies on a red branch until the acceptance file passes, then commits.
disable-model-invocation: true
---

# implement-ticket

You are the green leg of red-green-refactor. `architect-ticket` committed the public interface as stubs and an **acceptance file**, one test file holding this ticket's tests, every one failing against those stubs, leaving the branch red. You fill in the bodies until the acceptance file passes.

**The acceptance file is the only bar.** The rest of the suite reflects requirements as they stood before this ticket, and where the ticket changed them, old tests are now wrong. Reconciling the suite is `refactor-ticket`'s job. Never run it to decide whether you are done, and never shape the implementation to keep an old test green.

**Two things on that diff are frozen: the signatures and the tests.** Never rename a parameter, change a return type, loosen an assertion, or delete a test to get green. Both were settled with the user, and quietly editing either turns a passing suite into a lie.

**Behind the signatures you have full freedom.** No implementation choice needs approval. `refactor-ticket` refactors what's behind the signatures afterwards, so don't polish here and don't ask permission.

---

## Pin the work

1. **The branch.** Take the current branch, or the one the user names. Its name carries the issue number, as in `42-oauth-admin-login`. If the branch name has no number, ask which issue this implements before reading anything.
2. **The ticket.** `gh issue view <number> --json title,body`. Read Goal, Expected behaviour, and Out of scope. It tells you whether a green test actually shipped the feature.
3. **The diff.** `git diff main...HEAD`, three-dot, against the merge-base. Substitute the base the user names if it isn't `main`.

Confirm the branch and issue with the user in one line before writing code.

### Precondition

The diff must carry both interface stubs and the acceptance file. If it carries one without the other, or is empty, halt:

> This branch isn't red. `implement-ticket` starts from a committed interface plus a failing acceptance file. Run `/architect-ticket <issue>` first.

Then run the acceptance file, once, and confirm it fails. A branch that is already green has nothing to implement, and a test that **errors** rather than fails points at a missing dependency the architect should have caught. Either way, stop and say what you saw.

---

## Read the diff as the spec

Read it once, in full, before writing anything. Three things come out of it, and nothing else should:

- **The stubs.** Every signature and docstring. The docstring is the contract: the errors it names, the invariants it promises, the edge cases it describes. All of that is work you owe, whether or not a test covers it.
- **The tests.** Each test's name and docstring is one acceptance criterion. The assertions are the exact bar.
- **The surrounding code.** Read the region you're about to change, not the whole file. Grep to locate, then read with an offset and a limit.

**Point, don't paste.** Never paste the stubs, the tests, or the ticket body back into your own response. You already read them.

---

## The green loop

1. **Implement.** Fill in the stub bodies, plus whatever private code they need.
2. **Run the acceptance file.** Not the whole suite.
3. **Read every failure before fixing any of them.** Fixing one at a time invites a fix that breaks a sibling.
4. **Repeat until green.**

**Track the pass number and report it**, as in "pass 3: 2 of 6 still red", so a loop that isn't converging shows itself.

**Terse verdicts only.** One line per pass. The edit itself is the record, so name the files touched and move on.

**Completion criterion:** every test in the acceptance file passes, and no signature or assertion on the diff was edited.

### Loop exits

Four things stop the loop and go to the user, because none is yours to fix:

- **The contract is wrong.** A signature can't express the behaviour, or two parts of it contradict each other. Say which stub and why. Do not fix it in code.
- **A test is wrong.** It asserts something the ticket never asked for, or contradicts the docstring it sits under. Say which test and quote the conflict. Do not weaken it.
- **No progress.** The same test fails with the same evidence two passes running. A third would spin.
- **A record blocks the implementation.** The contract was architected against `docs/pcr/` and `docs/adr/`, so a PCR or ADR that the only workable implementation would breach means the contract has a gap. Name the record and what it blocks. Do not code around it, and never edit one; this station writes no records.
- **You are weighing a decision.** A module boundary, a dependency direction, a data owner, anything a future reader could undo by accident. Those were the architect's to settle, and one left open is a contract gap. Name it. Do not settle it in code.

On any exit, describe the failure in plain English: which test, the evidence, and your best guess at the cause, stated as a guess. Then ask what should happen next and offer the real options: a hint from them, a contract amendment back through `/architect-ticket`, a `/challenge-pcr` session when a PCR is the block, or stopping here.

---

## Finalization

Bookkeeping, once the acceptance file is green. It runs no tests. In order:

1. **Comment on the issue** with `gh issue comment <N>`: the branch name, and one line per acceptance test naming it and confirming it green. Don't close the issue.
2. **Commit** on the branch, as a separate commit from the architect's.

   ```
   Implement #<N>: <ticket title>

   Green.
   Issue: #<N>
   ```

   Don't push unless the user asks.

## Report

Close with these lines, then the two notes below and nothing else:

```
Tests     tests/test_acceptance.py, 6 green
Files     src/auth/oauth.py, src/auth/session.py
Issue     commented #42
Commit    d4e5f6a
```

Then say `/refactor-ticket` reconciles the suite, refactors, folds the acceptance file in, and closes the issue.
