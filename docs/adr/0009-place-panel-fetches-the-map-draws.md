# ADR-0009: The place panel fetches, the map draws

**Decision:** `PlaceMap` MUST take everything it draws as props (`outlines`, `review`) and report its state through callbacks (`onMapClick`, `onViewChange`); it MUST NOT call the backend. The fetches of the map panel live in `PlacePanel`.

**Scope:** `frontend/components/place/PlaceMap.tsx`, `frontend/components/place/PlacePanel.tsx`

**Reason:** Letting the map fetch the review layers for itself, since it alone knows the viewport, was weighed and lost. MapLibre needs WebGL, which jsdom has not, so `PlaceMap` cannot run under the unit tests (PCR-0007) and is replaced by a stand-in in them; a fetch inside it would be a fetch no test reaches, and the fake backend (PCR-0008) would never see the request. With the panel fetching and the map reporting its view, every request, threshold and error path is testable through the stand-in, and the map stays a drawing of props that a later map library could replace behind the same interface.

**Consequence:** A new map layer that needs data adds a prop to `PlaceMap` and a fetch to `PlacePanel`, never an `authFetch` inside the map. What the map draws from its props (colours, popups, zoom behaviour) is checked by hand in the browser and is listed as a manual check in the ticket's work, not faked as a test.

**Date:** 2026-11-05
