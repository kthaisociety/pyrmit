# ADR-0008: The review map gets plan polygons by viewport from the backend

**Decision:** The map's review mode MUST get plan polygons through `place.review.plans_in_view` (GET `/api/place/review/plans?bbox=`), which serves the polygons meeting one box no wider than `MAX_SPAN` and at most `MAX_PLANS` of them, and MUST NOT load a kommun's or the country's polygons as one file or one request.

**Scope:** `backend/place/review.py`, `backend/routers/place.py` (`review_plans`), `frontend/components/place/PlacePanel.tsx` (the review mode's fetches)

**Reason:** Serving the snapshots as static GeoJSON files (one per kommun, 17 MB for Göteborg, about 230 MB for the registry) was weighed and lost: the browser would hold a kommun's whole layer to show a street, and the country never fits. Building vector tiles (tippecanoe, PMTiles) was weighed and lost for now: it adds a build step and a tile host beside the snapshots, while the polygons move to the corpus database next (#57) and the viewport query then moves with them unchanged. A query by box over the spatial index the store already keeps (`PlaceStore.features`) needs nothing new and keeps every answer under a bound.

**Consequence:** The frontend fetches again after every move once zoomed in past `REVIEW_PLANS_ZOOM`, and shows nothing but the coverage colours below it; a view with more polygons than the cap is told so (`truncated`) and the reviewer zooms in. Any new map layer over the plan polygons reads them the same way. A request for a box wider than a kommun is refused (422), never served in pieces.

**Date:** 2026-11-05
