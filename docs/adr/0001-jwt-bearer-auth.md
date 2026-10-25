# ADR-0001: Auth uses stateless JWT bearer tokens

**Decision:** Authenticated routes MUST resolve the user from a JWT bearer token through `get_current_user` in `backend/src/dependencies.py`, and MUST NOT look up server-side session rows.

**Scope:** `backend/src/routers/auth.py`, `backend/src/security.py`, `backend/src/dependencies.py`

**Reason:** TODO(owner): name the alternative that was weighed and why it lost.

**Consequence:** Signin and signup return a token and store nothing. Signout only discards the token on the client, so a token stays valid until it expires. The `sessions` table is not part of auth.

**Date:** 2026-10-01
