"""
The review of the plan coverage on the map (GET /api/place/review/*): which kommuner have plan polygons in a snapshot
and which of those polygons have a matched document (place.plan_links). Read from the snapshots, the coverage rows of
place.plan_layers and the link tables; no provider or model call (ADR-0002, ADR-0003). The polygons are served by
viewport, never for the whole country (ADR-0008).
"""

import math
from collections.abc import Iterable

from shapely.geometry import box, mapping, shape

from place import plan_layers
from place.plan_links import polygon_key
from place.registry import PlanSource
from place.sources import PILOTS, layer_by_id, plan_layer_definitions
from place.sources import feature as pilot_feature
from place.store import PlaceStore

MAX_SPAN = (2.0, 1.0)       # the widest box plans_in_view serves, degrees of longitude and latitude (about a kommun)
MAX_PLANS = 4000            # the most polygons one view gets; beyond it the collection is truncated
PLAN_TOLERANCE = 0.00002    # degrees (about 2 m): the polygons are simplified this much before they are served
OUTLINE_TOLERANCE = 0.001   # degrees (about 100 m): the kommun outlines of the coverage view
NOT_FETCHED_YET = "not fetched yet"


def _simplified(geometry: dict | None, tolerance: float) -> dict | None:
    return mapping(shape(geometry).simplify(tolerance, preserve_topology=True)) if geometry else None


def _plans_layer(store: PlaceStore, code: str) -> dict | None:
    """The plans layer's manifest entry of a kommun with a snapshot file for it, else None."""
    layer = next((layer for layer in store.layers(code) if layer["id"] == plan_layers.LAYER_ID), None)
    return layer if layer and layer["status"] == "ok" else None


def _polygons(store: PlaceStore, code: str, layer: dict) -> int:
    """The polygons the link table can hold keys of: a pilot kommun's plan layers together, else the plans layer."""
    if code not in PILOTS:
        return layer.get("count") or 0
    ids = {definition.id for definition in plan_layer_definitions(code)}
    return sum(entry.get("count") or 0 for entry in store.layers(code) if entry["id"] in ids)


def coverage(store: PlaceStore, sources: Iterable[PlanSource]) -> dict:
    """The coverage of every kommun as a GeoJSON FeatureCollection: one Feature per kommun of `sources` (the plan
    source registry) and per kommun with a snapshot that is not in it (a pilot kommun), in kommun code order, each
    once.

    A feature's geometry is the kommun outline (store.outline, simplified to OUTLINE_TOLERANCE), or None when no
    boundary was ever fetched. Its properties: {"code", "name", "covered" (True when the kommun has a plans
    snapshot), "polygons" (the snapshot's plan count, a pilot kommun's plan layers together, 0 when not covered), "matched" (the plans with at least one
    plan-document link, by polygon key: polygons sharing an aktbeteckning count once; 0 when none), "fetched" (the
    snapshot date, None when not covered), "reason" (None when covered; else the coverage row's reason for the last
    failed fetch, or NOT_FETCHED_YET when the fetch never ran for the kommun)}.

    A snapshot the coverage report flags as doubtful (a low share of aktbeteckningar or links) counts as covered
    like any other: nothing is filtered out here."""
    names = {source.code: source.name for source in sources}
    snapshots = {kommun["code"]: kommun for kommun in store.kommuner()}
    rows = plan_layers.load_coverage(store.root)
    features = []
    for code in sorted(set(names) | set(snapshots)):
        layer = _plans_layer(store, code) if code in snapshots else None
        if layer:
            properties = {"covered": True, "polygons": _polygons(store, code, layer), "matched": len(store.plan_links(code)),
                          "fetched": layer.get("fetched"), "reason": None}
        else:
            properties = {"covered": False, "polygons": 0, "matched": 0, "fetched": None,
                          "reason": (rows.get(code) or {}).get("reason") or NOT_FETCHED_YET}
        features.append({"type": "Feature", "geometry": _simplified(store.outline(code), OUTLINE_TOLERANCE),
                         "properties": {"code": code, "name": names.get(code) or snapshots[code]["name"], **properties}})
    return {"type": "FeatureCollection", "features": features}


def _checked(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """The box as four floats, or ValueError with the reason."""
    if len(bbox) != 4 or not all(isinstance(value, int | float) and math.isfinite(value) for value in bbox):
        raise ValueError("The box must be four coordinates: west, south, east, north.")
    west, south, east, north = (float(value) for value in bbox)
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError("The box must be in WGS84 degrees.")
    if west >= east or south >= north:
        raise ValueError("The box must have west left of east and south below north.")
    if east - west > MAX_SPAN[0] or north - south > MAX_SPAN[1]:
        raise ValueError(f"The box is wider than a kommun: at most {MAX_SPAN[0]}° by {MAX_SPAN[1]}° is served at once.")
    return west, south, east, north


def plans_in_view(store: PlaceStore, bbox: tuple[float, float, float, float]) -> dict:
    """The plan polygons meeting `bbox` (west, south, east, north, WGS84) as a GeoJSON FeatureCollection with one
    extra member, "truncated".

    The features come from every kommun whose snapshot holds a plans layer meeting the box, pilot and plan-layer
    kommuner alike, in kommun code order and the layer's order within a kommun. Each feature's geometry is the
    polygon simplified to PLAN_TOLERANCE (topology kept); its properties: {"code" (kommun code), "kommun" (kommun
    name), "ref" (aktbeteckning, or None), "name", "date" (ISO, or None), "match" (the level of the polygon's
    plan-document links, "link", "akt" or "name", or None when no document is matched)}.

    At most MAX_PLANS features are served; "truncated" is True when more met the box, else False. Raises ValueError
    when the box is wider than MAX_SPAN in longitude or latitude, when west >= east or south >= north, or when a
    bound is not a coordinate."""
    view = box(*_checked(bbox))
    features: list[dict] = []
    for kommun in store.kommuner():
        if not box(*kommun["bbox"]).intersects(view):
            continue
        code = kommun["code"]
        layer = layer_by_id(code, plan_layers.LAYER_ID) if code in PILOTS else None
        links = store.plan_links(code)
        for props, geometry in store.features(code, plan_layers.LAYER_ID, view):
            if len(features) == MAX_PLANS:
                return {"type": "FeatureCollection", "features": features, "truncated": True}
            row = pilot_feature(layer, props) if layer else plan_layers.feature(props)
            matched = links.get(polygon_key(row) or "", [])
            features.append({"type": "Feature",
                             "geometry": mapping(geometry.simplify(PLAN_TOLERANCE, preserve_topology=True)),
                             "properties": {"code": code, "kommun": kommun["name"], "ref": row["ref"],
                                            "name": row["name"], "date": row["date"],
                                            "match": matched[0]["level"] if matched else None}})
    return {"type": "FeatureCollection", "features": features, "truncated": False}
