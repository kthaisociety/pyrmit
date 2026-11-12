# PCR-0009: Each package has exactly one package manager and lockfile

**Decision:** `frontend/` MUST install dependencies with Bun from `bun.lock`, and `backend/` MUST install with uv from `pyproject.toml` and `uv.lock`, in development, CI and Docker alike.

**Reason:** Two lists per package were in use: CI installed the frontend with Bun while Docker used npm and `package-lock.json`, and the backend Docker image installed from a `requirements.txt` that was missing eight packages listed in `pyproject.toml`. npm and `requirements.txt` were weighed and lost: Bun was already what CI and the README used, and only `uv.lock` pins every backend package to an exact version.

**Consequence:** `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` and `requirements.txt` are breaches. A dependency change commits the updated lockfile in the same PR, and CI installs with `--frozen-lockfile` or `--frozen`, so a stale lockfile fails the build. The frontend still builds and runs on Node; Bun only installs.

**Date:** 2026-10-06
