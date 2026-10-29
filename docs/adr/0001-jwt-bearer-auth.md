# ADR-0001: Auth uses JWT bearer tokens backed by revocable login sessions

**Decision:** Authenticated routes MUST resolve the user through `get_current_session` in `backend/src/dependencies.py`, which MUST accept a JWT bearer token only when its `sid` claim names an unexpired `sessions` row owned by the token's `sub` user.

**Scope:** `backend/src/routers/auth.py`, `backend/src/security.py`, `backend/src/dependencies.py`

**Reason:** Stateless JWTs were weighed and lost. They need no lookup per request, but signout can only discard the token on the client, so a copied token stays valid until it expires. A session row per login lets signout revoke that token on the server immediately, at the cost of one database lookup per authenticated request.

**Consequence:** Signin, signup and the token route each create one `sessions` row whose expiry equals the JWT's `exp`. Signout deletes only the current row, so other logins and chat history are untouched. A token without `sid`, or whose row is gone or expired, gets a 401 and the frontend sends the user back to sign in. Expired rows are not deleted automatically, and the legacy `sessions.token` column is unused. A chat stream already authorized keeps running after signout.

**Date:** 2026-10-26
