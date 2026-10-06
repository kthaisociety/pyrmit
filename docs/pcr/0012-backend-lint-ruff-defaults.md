# PCR-0012: Backend code passes ruff's default rules

**Decision:** Backend code MUST pass `ruff check` with ruff's default rule set for the version pinned in `uv.lock`, and new code MUST NOT add entries to the per-file baseline in `pyproject.toml`.

**Reason:** No backend linter was weighed and lost, because the frontend was already linted and the backend had nothing equivalent. Fixing the 111 existing problems before turning lint on was weighed and lost: it meant edits across `src/` in a platform change. A baseline of existing problems lets lint go live without touching app code.

**Consequence:** CI runs `ruff check` as the required `backend / lint` check. The baseline under `[tool.ruff.lint.per-file-ignores]` may only shrink. Adding a file or rule to it, or a `# noqa` to get a new line past lint, is a breach. Selecting a custom rule set changes this record and needs `/challenge-pcr`.

**Date:** 2026-10-06
