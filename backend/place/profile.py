"""The place profile of a point: what the place card shows and what the chat answers from."""

import json
import re
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from shapely.errors import GEOSException
from shapely.geometry import Point, mapping, shape
from shapely.validation import make_valid

from place import live
from place.sources import PILOTS, Layer
from place.sources import feature as layer_feature
from place.store import PlaceStore

NOT_A_DECISION = ("Registry data, not a decision: the adopted plan documents and the authorities' decisions are "
                  "binding.")

MIN_SHARE = 0.02                     # a feature covering less of the property only touches its boundary
FINISHED_STAGES = {"avslutat", "avbrutet", "avbruten"}  # still in the kommun's "pågående" layer, no longer in progress
PLAN_KINDS = ("plan", "plan_addition", "area_regulations")
CORPUS_PLANS = Path(__file__).resolve().parent.parent / "data" / "corpus" / "plans.jsonl"

_store: PlaceStore | None = None
_store_lock = threading.Lock()


def default_store() -> PlaceStore:
    """The shared store over data/geo/ (snapshots are read once per process)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = PlaceStore()
        return _store


@lru_cache(maxsize=1)
def _corpus_plans_by_kommun() -> dict[str, list[dict]]:
    by_kommun: dict[str, list[dict]] = {}
    if CORPUS_PLANS.exists():
        with CORPUS_PLANS.open(encoding="utf-8") as lines:
            for line in lines:
                plan = json.loads(line)
                by_kommun.setdefault(plan["kommun_code"], []).append(plan)
    return by_kommun


def corpus_plans(code: str) -> list[dict]:
    """The corpus registry's plans of a kommun (data/corpus/plans.jsonl, built by corpus.plans)."""
    return _corpus_plans_by_kommun().get(code, [])


def _plan_key(name: str | None, kommun: str) -> str:
    """Plan names as the registry and the kommun's map both spell them: no '- <kommun> kommun' suffix, no
    'Detaljplan för' prefix, lower case, punctuation as spaces."""
    text = (name or "").lower()
    text = re.sub(rf"\s*[-–]\s*{re.escape(kommun.lower())} kommun\s*$", "", text)
    text = re.sub(r"^detaljplan för\s+", "", text)
    return " ".join(re.findall(r"[0-9a-zåäöé:]+", text))


def _overlap_area(a, b) -> float:
    try:
        return a.intersection(b).area
    except GEOSException:  # self-intersecting polygons from the providers
        return make_valid(a).intersection(make_valid(b)).area


def _covers_enough(geometry, point, area) -> tuple[bool, float]:
    """Whether a feature counts for the property `area` (contains the pin or covers MIN_SHARE of it), and the
    share of the property it covers. Shares are ratios of areas in degrees: the scale cancels out."""
    if area.area == 0:
        return geometry.intersects(point), 1.0
    share = _overlap_area(geometry, area) / area.area
    return geometry.intersects(point) or share >= MIN_SHARE, share


def _detaljplan(rows: dict[str, list[dict]], plan_layer: dict) -> str:
    """Inside when a plan in force covers the property; outside only when the plan layer is complete."""
    if rows["plan"]:
        return "inside"
    return "outside" if plan_layer.get("complete") and plan_layer.get("status") == "ok" else "unknown"


def _not_covered(lat: float, lon: float) -> dict:
    return {"point": {"lat": lat, "lon": lon}, "kommun": None, "covered": False, "property": None,
            "property_status": "not_covered", "detaljplan": "unknown", "plans": [], "zones": [],
            "pending_plans": [], "layers": [], "notes": [NOT_A_DECISION]}


def _property(code: str, lon: float, lat: float, property_at) -> tuple[dict | None, str]:
    try:
        found = property_at(code, lon, lat)
    except live.PlaceSourceUnavailable:
        return None, "unavailable"
    return found, "found" if found else "none"


def _without_share(row: dict) -> dict:
    """Plans and plans in progress are listed whole: the share of the property only describes zones."""
    return {key: value for key, value in row.items() if key != "share"}


def _corpus_match(key: str, plans_by_key: dict[str, dict]) -> dict:
    match = plans_by_key.get(key)
    return {"corpus_plan_id": match["plan_id"] if match else None,
            "provisions_indexed": bool(match and match.get("provisions"))}


def _layer_rows(store: PlaceStore, code: str, layer: Layer, meta: dict, point, area) -> list[dict]:
    rows = []
    for props, geometry in store.features(code, layer.id, area):
        counts, share = _covers_enough(geometry, point, area)
        if counts:
            rows.append(layer_feature(layer, props) | {"source": meta.get("provider") or layer.provider,
                                                       "fetched": meta.get("fetched"),
                                                       "geometry": mapping(geometry), "share": round(share, 3)})
    return rows


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
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):  # also rejects NaN
        raise ValueError(f"Not a coordinate: lat={lat}, lon={lon}")
    store = store or default_store()
    code = store.kommun_at(lon, lat)
    if code is None or code not in PILOTS:
        return _not_covered(lat, lon)

    kommun = PILOTS[code]["name"]
    found, property_status = _property(code, lon, lat, property_at or live.property_at)
    point = Point(lon, lat)
    area = shape(found["geometry"]) if found else point
    meta = {layer["id"]: layer for layer in store.layers(code)}

    rows = {kind: [] for kind in (*PLAN_KINDS, "zone", "plan_pending")}
    consulted = []
    for layer in PILOTS[code]["layers"]:
        layer_meta = meta.get(layer.id, {})
        consulted.append({"id": layer.id, "title": layer.title, "provider": layer.provider,
                          "licence": layer.licence, "fetched": layer_meta.get("fetched"),
                          "status": layer_meta.get("status", "unavailable")})
        rows[layer.kind] += _layer_rows(store, code, layer, layer_meta, point, area)

    plans_by_key = {}
    for plan in (plan_registry or corpus_plans)(code):
        plans_by_key.setdefault(_plan_key(plan.get("name"), kommun), plan)
    plans = [_without_share(row) | _corpus_match(_plan_key(row["name"], kommun), plans_by_key)
             for kind in PLAN_KINDS for row in rows[kind]]
    plans.sort(key=lambda row: row["date"] or "", reverse=True)

    zones = sorted(rows["zone"], key=lambda row: row["share"], reverse=True)
    return {"point": {"lat": lat, "lon": lon}, "kommun": {"code": code, "name": kommun}, "covered": True,
            "property": found, "property_status": property_status, "detaljplan": _detaljplan(rows, meta.get("plans", {})), "plans": plans,
            "zones": zones, "pending_plans": [_without_share(row) for row in rows["plan_pending"]
                                              if (row["status"] or "").lower() not in FINISHED_STAGES],
            "layers": consulted, "notes": [NOT_A_DECISION]}
