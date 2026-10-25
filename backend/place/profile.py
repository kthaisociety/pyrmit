"""The place profile of a point: what the place card shows and what the chat answers from."""

from typing import Callable

from place.store import PlaceStore

NOT_A_DECISION = ("Registry data, not a decision: the adopted plan documents and the authorities' decisions are "
                  "binding.")


def build_profile(lat: float, lon: float, *, store: PlaceStore | None = None,
                  property_at: Callable[[str, float, float], dict | None] | None = None,
                  plan_registry: Callable[[str], list[dict]] | None = None) -> dict:
    """Place profile of a point in WGS84. `store`, `property_at` (code, lon, lat) and `plan_registry` (kommun code
    -> plan records of data/corpus/plans.jsonl) default to the snapshots, the live property service and the
    corpus registry.

    Returns:
    - "point": {"lat", "lon"}
    - "kommun": {"code", "name"} of the pilot kommun the point lies in, or None
    - "covered": True when the point lies in a pilot kommun with a snapshot
    - "property": {"designation", "geometry", "source", "fetched"}, or None
    - "property_status": "found", "none" (no property at the point: a street, park or water), "unavailable"
      (the property service failed) or "not_covered"
    - "detaljplan": "inside", "outside" or "unknown". "outside" only when the kommun's plan layer is complete;
      with an incomplete layer and no plan found it is "unknown"
    - "plans": plans in force, tillägg and områdesbestämmelser covering the property (or the point when there is
      no property), newest laga kraft date first
    - "zones": land-use zones (användning) on the property
    - "pending_plans": plans in progress covering the property (not binding)
    - "layers": [{"id", "title", "provider", "licence", "fetched", "status"}] for every layer consulted
    - "notes": user-facing caveats, the first one NOT_A_DECISION

    Every row of plans, zones and pending_plans is a feature of `place.sources.feature` plus "source" (provider),
    "fetched" (snapshot date) and "geometry" (GeoJSON). Plans also carry "corpus_plan_id" (the matching plan of
    the corpus registry, or None) and "provisions_indexed" (True when that plan has provisions); zones carry
    "share", the fraction of the property they cover (1.0 without a property). A feature counts when it contains
    the pin or covers at least 2 % of the property, so neighbours that only touch its boundary are left out.

    Outside the pilot kommuner, kommun is None, covered False, property_status "not_covered", detaljplan
    "unknown" and the lists are empty. Raises ValueError when lat or lon is not a coordinate."""
    raise NotImplementedError
