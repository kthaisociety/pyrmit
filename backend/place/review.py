"""
The review of the plan coverage on the map (GET /api/place/review/*): which kommuner have plan polygons in a snapshot
and which of those polygons have a matched document (place.plan_links). Read from the snapshots, the coverage rows of
place.plan_layers and the link tables; no provider or model call (ADR-0002, ADR-0003). The polygons are served by
viewport, never for the whole country (ADR-0008).
"""

from collections.abc import Iterable

from place.registry import PlanSource
from place.store import PlaceStore

MAX_SPAN = (2.0, 1.0)       # the widest box plans_in_view serves, degrees of longitude and latitude (about a kommun)
MAX_PLANS = 4000            # the most polygons one view gets; beyond it the collection is truncated
PLAN_TOLERANCE = 0.00002    # degrees (about 2 m): the polygons are simplified this much before they are served
OUTLINE_TOLERANCE = 0.001   # degrees (about 100 m): the kommun outlines of the coverage view
NOT_FETCHED_YET = "not fetched yet"
MATCH_LEVELS = ("link", "akt", "name")


def coverage(store: PlaceStore, sources: Iterable[PlanSource]) -> dict:
    """The coverage of every kommun as a GeoJSON FeatureCollection: one Feature per kommun of `sources` (the plan
    source registry) and per kommun with a snapshot that is not in it (a pilot kommun), in kommun code order, each
    once.

    A feature's geometry is the kommun outline (store.outline, simplified to OUTLINE_TOLERANCE), or None when no
    boundary was ever fetched. Its properties: {"code", "name", "covered" (True when the kommun has a plans
    snapshot), "polygons" (the snapshot's plan count, 0 when not covered), "matched" (polygons with at least one
    plan-document link, 0 when none), "fetched" (the snapshot date, None when not covered), "reason" (None when
    covered; else the coverage row's reason for the last failed fetch, or NOT_FETCHED_YET when the fetch never ran
    for the kommun)}.

    A snapshot the coverage report flags as doubtful (a low share of aktbeteckningar or links) counts as covered
    like any other: nothing is filtered out here."""
    raise NotImplementedError


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
    raise NotImplementedError
