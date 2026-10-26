# PCR-0001: Backend is Python on FastAPI

**Decision:** Backend code MUST be Python served through FastAPI, living under `backend/`.

**Reason:** TODO(owner): name the alternative that was weighed and why it lost.

**Consequence:** Every API endpoint is a FastAPI router registered in `backend/main.py`. A second backend language or framework means a new service, not a new file.

**Date:** 2026-10-01
