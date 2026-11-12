# PCR-0002: Frontend is Next.js in TypeScript

**Decision:** Frontend code MUST be TypeScript in the Next.js app under `frontend/`.

**Reason:** TODO(owner): name the alternative that was weighed and why it lost.

**Exceptions:** Tool config files at the root of `frontend/` (`*.config.js`, `*.config.mjs`).

**Consequence:** UI lives in `frontend/app/` and `frontend/components/` and talks to the backend only over its REST API. Plain JavaScript files and a second UI framework are breaches.

**Date:** 2026-10-01
