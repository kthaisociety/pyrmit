# ADR-0002: Place lookups read area layers from dated snapshots

**Decision:** The place profile MUST read plans, land-use zones, protected areas and national interests from the dated snapshots under `backend/data/geo/` that `place.fetch` writes, and MUST NOT query those providers for each pin.

**Scope:** `backend/place/`, `backend/routers/place.py`

**Reason:** Querying the providers' services for each pin was weighed and lost: the evaluations need the same answer for the same pin over time, the free services have rate limits and outages, and a pin would wait on four services at once. Storing the layers in Postgres with PostGIS on Neon was weighed and lost: it adds an extension and tables to the team's shared database for data that is read-only and per kommun. The property and the ancient remains stay live, because properties change with every subdivision and the ancient-remains register has no working bulk download.

**Consequence:** Adding or refreshing a kommun means running `python -m place.fetch` and restarting the backend. The snapshots are not versioned, so every profile row carries its snapshot date. A provider call in the request path for an area layer breaches this record.

**Date:** 2026-10-25
