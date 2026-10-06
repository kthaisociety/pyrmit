# PCR-0010: PRs into dev and main merge only when every required check is green

**Decision:** A pull request into `dev` or `main` MUST NOT merge until every required CI check passes, and those checks MUST run on every such PR regardless of which files it changes.

**Reason:** Advisory checks were weighed and lost: a red mark nobody has to fix gets ignored, and adding the requirement later, once tests are flaky, is much harder. Building Docker images only locally was weighed and lost: the Dockerfiles once installed from a different lockfile than CI, and nothing noticed. Path-filtered workflows were weighed and lost: GitHub waits forever for a required check that a path filter skipped, so a backend-only PR could never merge.

**Consequence:** The required checks are `frontend / lint`, `frontend / test`, `frontend / docker`, `backend / lint`, `backend / test` and `backend / docker`, enforced by a repository ruleset on `dev` and `main`. Renaming one of those jobs silently drops it from the ruleset, so a rename updates the ruleset in the same change. A known-broken test is marked `xfail` with a linked issue rather than left red or deleted.

**Date:** 2026-10-06
