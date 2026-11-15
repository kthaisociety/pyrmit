# ADR-0017: Demoting an owner locks the owner rows

**Decision:** `set_role` in `backend/src/roles.py` MUST read the owner rows with `SELECT ... FOR UPDATE` before it demotes an owner, and MUST count the owners from that locked read.

**Reason:** Unknown. Found as a comment in `backend/src/roles.py`, quoted:

> Lock the owner rows, so two owners demoting each other at once can't leave none (Postgres; SQLite ignores it)

**Consequence:** Two owners demoting each other at the same moment can't both pass the last-owner check, so the app never ends with zero owners. Removing the lock, or counting owners without it, brings that race back. The tests run on SQLite, which ignores the lock, so they can't catch its removal.

**Scope:** `backend/src/roles.py`, `set_role`

**Status:** found

**Date:** 2026-11-15
