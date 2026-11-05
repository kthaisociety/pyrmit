"""The place profile of a point: what the place card shows and what the chat answers from."""

import json
import logging
import math
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from shapely.affinity import scale
from shapely.errors import GEOSException
from shapely.geometry import Point, mapping, shape
from shapely.validation import make_valid

from place import live, plan_layers
from place.permits import likely_permits
from place.plan_links import polygon_key
from place.sources import (
    ANCIENT_REMAINS,
    METRES_PER_DEGREE_LAT,
    NATIONAL_LAYERS,
    PILOTS,
    PLAN_KINDS,
    SECTION_KINDS,
    Layer,
    today,
)
from place.sources import feature as layer_feature
from place.store import PlaceStore

logger = logging.getLogger(__name__)

# The wait for the corpus on a pin: past Neon waking from suspend (a few seconds), short of a pin that seems to hang.
# One worker keeps PgStore's connection, which is per thread
CORPUS_LOOKUP_SECONDS = 8
_corpus_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="corpus-documents")
ROLE_ORDER = {"plankarta": 0, "planbeskrivning": 1}
DOCUMENTS_UNAVAILABLE = "The plan documents could not be read from the corpus right now: the plans are listed without them."
NOT_A_DECISION = ("Registry data, not a decision: the adopted plan documents and the authorities' decisions are "
                  "binding.")
STRANDSKYDD = {
    "status": "not_checked",
    "reason": "Not checked: the länsstyrelser's strandskydd services could not be reached, and the general 100 m "
              "strandskydd is not published as data.",
    "note": "A strandskyddsdispens (MB 7 kap. 18 b §) may be needed within 100 m of a shoreline, unless the "
            "detaljplan lifts the strandskydd.",
}
SECTIONS = (*SECTION_KINDS, "ancient_remains")

ANCIENT_REMAINS_RADIUS_M = 30         # without a property: remains this close to the pin
MIN_SHARE = 0.02                     # a feature covering less of the property only touches its boundary
FINISHED_STAGES = {"avslutat", "avbrutet", "avbruten"}  # still in the kommun's "pågående" layer, no longer in progress
CORPUS_PLANS = Path(__file__).resolve().parents[2] / "data" / "corpus" / "plans.jsonl"

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


def _detaljplan(plans_in_force: list[dict], plan_layer: dict) -> str:
    """Inside when a plan in force covers the property; outside only when the plan layer is complete."""
    if plans_in_force:
        return "inside"
    return "outside" if plan_layer.get("complete") and plan_layer.get("status") == "ok" else "unknown"


def _section_status(status_of: dict[str, str]) -> dict[str, str]:
    """A section is "ok" when every national layer it is built from has its snapshot, else "unavailable"."""
    return {section: "ok" if all(status_of[layer.id] == "ok" for layer in NATIONAL_LAYERS if layer.kind == kind)
            else "unavailable" for section, kind in SECTION_KINDS.items()}


def _not_covered(lat: float, lon: float) -> dict:
    return {"point": {"lat": lat, "lon": lon}, "kommun": None, "covered": False, "property": None,
            "property_status": "not_covered", "detaljplan": "unknown", "plans": [], "zones": [],
            "pending_plans": [], **{section: [] for section in SECTIONS},
            "strandskydd": STRANDSKYDD | {"reason": "This place is not covered yet."}, "permits": [],
            "section_status": dict.fromkeys(SECTIONS, "not_covered"), "layers": [], "notes": [NOT_A_DECISION]}


def _around_pin(point, lat: float):
    """A circle of ANCIENT_REMAINS_RADIUS_M around the pin (an ellipse in degrees)."""
    radius = ANCIENT_REMAINS_RADIUS_M / METRES_PER_DEGREE_LAT
    return scale(point.buffer(radius), xfact=1 / math.cos(math.radians(lat)), yfact=1, origin=point)


def _ancient_remains(lookup, area) -> tuple[list[dict], dict]:
    """The remains on `area` as profile rows, and the register's entry in the layers list."""
    entry = {"id": ANCIENT_REMAINS.id, "title": ANCIENT_REMAINS.title, "provider": ANCIENT_REMAINS.provider,
             "licence": ANCIENT_REMAINS.licence, "fetched": today()}
    try:
        found = lookup(mapping(area))
    except live.PlaceSourceUnavailable:
        return [], entry | {"status": "unavailable"}
    rows = [layer_feature(ANCIENT_REMAINS, remain["properties"])
            | {"source": ANCIENT_REMAINS.provider, "fetched": entry["fetched"], "geometry": remain["geometry"]}
            for remain in found]
    return rows, entry | {"status": "ok"}


def _property(code: str, lon: float, lat: float, property_at) -> tuple[dict | None, str]:
    try:
        found = property_at(code, lon, lat)
    except live.PlaceSourceUnavailable:
        return None, "unavailable"
    return found, "found" if found else "none"


def _without_share(row: dict) -> dict:
    """Plans and plans in progress are listed whole: the share of the property only describes zones."""
    return {key: value for key, value in row.items() if key != "share"}


def _corpus_match(key: str, plans_by_key: dict[str, dict], page: str | None = None,
                  plans_by_page: dict[str, dict] | None = None) -> dict:
    """The corpus plan of a snapshot plan: the one built from the plan's own page (place.plan_documents), else the
    one with the same name."""
    match = (plans_by_page or {}).get(page) if page else None
    match = match or plans_by_key.get(key)
    return {"corpus_plan_id": match["plan_id"] if match else None,
            "provisions_indexed": bool(match and match.get("provisions"))}


def _by_date_newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: row["date"] or "", reverse=True)


class CorpusUnavailable(RuntimeError):
    """The corpus the plan documents are read from cannot be reached."""


def _read_documents(doc_ids: list[str]) -> dict[str, dict]:
    from localrag.service import get_retriever

    store = getattr(get_retriever(), "store", None)
    if store is None:
        raise CorpusUnavailable("the app's corpus is not in a store")
    marks = ",".join("?" * len(doc_ids))
    return {row["doc_id"]: {"title": row["title"], "url": row["url"]} for row in store.query(
        f"SELECT DISTINCT doc_id, title, url FROM chunks WHERE doc_id IN ({marks})", tuple(doc_ids))}


def hosted_documents(doc_ids: list[str]) -> dict[str, dict]:
    """{doc_id: {"title", "url"}} of the documents in the corpus the app serves from (LOCAL_RAG_STORE), those it does
    not hold left out. Waits at most CORPUS_LOOKUP_SECONDS. Raises CorpusUnavailable when the corpus cannot be reached
    in that time, or when the app has no local corpus."""
    from localrag.service import local_backend_enabled

    if not local_backend_enabled():
        raise CorpusUnavailable("the app has no local corpus")
    try:
        return _corpus_worker.submit(_read_documents, doc_ids).result(timeout=CORPUS_LOOKUP_SECONDS)
    except Exception as exc:  # a timeout, or the driver's own errors: psycopg2 is only imported with the hosted store
        logger.warning("Plan documents not read from the corpus: %s", type(exc).__name__)
        raise CorpusUnavailable(type(exc).__name__) from exc


def _read_with(row: dict, rows: list[dict]) -> list[str]:
    """The aktbeteckningar of the plans to read `row` with, of `rows` at the point: see build_profile's "read_with"."""
    others = [other for other in rows if other is not row and other.get("ref")]
    named = [ref for ref in row.get("named_plans") or [] if ref != row.get("ref")]
    if row["kind"] != "plan_addition":
        return [ref for ref in named if any(other["ref"] == ref for other in others)]
    return named or [other["ref"] for other in others
                     if other["kind"] == "plan" and (other["date"] or "") < (row["date"] or "9999")]


def _documents_of(matched: list[dict], found: dict[str, dict]) -> list[dict]:
    """The linked documents the corpus holds, plan maps first."""
    return sorted(({"doc_id": link["doc_id"], "role": link.get("role"), **found[link["doc_id"]]}
                   for link in matched if link["doc_id"] in found),
                  key=lambda document: ROLE_ORDER.get(document["role"], len(ROLE_ORDER)))


def _with_documents(rows: list[dict], links: dict[str, list[dict]],
                    corpus_documents: Callable[[list[str]], dict[str, dict]]) -> tuple[list[dict], list[str]]:
    """The plan rows with their documents (place.plan_links) as the corpus holds them, and the notes that go with them:
    one when the corpus could not be reached, which leaves the rows without documents."""
    matched_of = [links.get(polygon_key(row) or "", []) for row in rows]
    read_with_of = [_read_with(row, rows) for row in rows]
    doc_ids = sorted({link["doc_id"] for matched in matched_of for link in matched}
                     | {link["doc_id"] for refs in read_with_of for ref in refs for link in links.get(ref, [])})
    found, unavailable = {}, False
    if doc_ids:
        try:
            found = corpus_documents(doc_ids)
        except CorpusUnavailable:
            unavailable = True
    out = []
    for row, matched, read_with in zip(rows, matched_of, read_with_of, strict=True):
        documents = _documents_of(matched, found)
        status = "read" if documents else "unavailable" if unavailable and matched else "none"
        out.append(row | {"document_ids": [link["doc_id"] for link in matched],
                          "document_match": matched[0]["level"] if matched else None,
                          "corpus_documents": documents, "text_status": status,
                          "read_with": [{"ref": ref, "corpus_documents": _documents_of(links.get(ref, []), found)}
                                        for ref in read_with]})
    return out, [DOCUMENTS_UNAVAILABLE] if unavailable else []


def _plan_layer_profile(lat: float, lon: float, code: str, store: PlaceStore,
                        corpus_documents: Callable[[list[str]], dict[str, dict]]) -> dict:
    """The profile of a point in a kommun whose plan layer place.plan_layers snapshotted: the plans at the point
    from that layer, nothing else looked up."""
    name = next(kommun["name"] for kommun in store.kommuner() if kommun["code"] == code)
    meta = next((layer for layer in store.layers(code) if layer["id"] == plan_layers.LAYER_ID), {})
    point = Point(lon, lat)
    plans, document_notes = _with_documents(_by_date_newest_first([
        plan_layers.feature(props) | {"source": meta.get("provider"), "fetched": meta.get("fetched"),
                                      "licence": meta.get("licence"), "geometry": mapping(geometry),
                                      "corpus_plan_id": None, "provisions_indexed": False}
        for props, geometry in store.features(code, plan_layers.LAYER_ID, point)]), store.plan_links(code),
        corpus_documents)
    notes = [NOT_A_DECISION, (f"Only {name} kommun's plan layer is checked here: no property, land-use zones or plans "
                              "in progress."), *document_notes]
    if not plans:
        notes.append(f"No plan was found in {name} kommun's plan layer at this point. The layer is not known to hold "
                     "every plan in force, so an older plan may still apply.")
    profile = {"point": {"lat": lat, "lon": lon}, "kommun": {"code": code, "name": name}, "covered": True,
               "property": None, "property_status": "not_covered",
               "detaljplan": "inside" if plans else "unknown", "plans": plans, "zones": [], "pending_plans": [],
               **{section: [] for section in SECTIONS}, "strandskydd": dict(STRANDSKYDD),
               "section_status": dict.fromkeys(SECTIONS, "not_covered"),
               "layers": [{"id": plan_layers.LAYER_ID, "title": meta.get("title"), "provider": meta.get("provider"),
                           "licence": meta.get("licence"), "fetched": meta.get("fetched"),
                           "status": meta.get("status", "unavailable")}],
               "notes": notes}
    return profile | {"permits": likely_permits(profile)}


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
                  corpus_documents: Callable[[list[str]], dict[str, dict]] | None = None,
                  property_at: Callable[[str, float, float], dict | None] | None = None,
                  plan_registry: Callable[[str], list[dict]] | None = None,
                  ancient_remains_at: Callable[[dict], list[dict]] | None = None) -> dict:
    """Place profile of a point in WGS84. `store`, `property_at` (code, lon, lat), `plan_registry` (kommun code
    -> plan records of data/corpus/plans.jsonl) and `ancient_remains_at` (GeoJSON geometry -> register features,
    see place.live) default to the snapshots, the live property service, the corpus registry and Riksantikvarieämbetet.

    A point is covered when it lies in a kommun with a snapshot: a pilot kommun (place.sources.PILOTS, with
    property, zones, pending plans and the national layers) or a kommun whose plan layer place.plan_layers
    snapshotted (plans only: no property lookup, so the plans are those at the point).

    Returns:
    - "point": {"lat", "lon"}
    - "kommun": {"code", "name"} of the kommun the point lies in, or None
    - "covered": True when the point lies in a kommun with a snapshot
    - "property": {"designation", "geometry", "source", "fetched"}, or None
    - "property_status": "found", "none" (no property at the point: a street, park or water), "unavailable"
      (the property service failed) or "not_covered" (outside the snapshots, or a plan-layer kommun)
    - "detaljplan": "inside", "outside" or "unknown". "outside" only when the kommun's plan layer is complete
      (Uppsala); with an incomplete layer and no plan found it is "unknown", and a plan-layer kommun then adds a
      note that no plan was found in the kommun's layer
    - "plans": plans in force, tillägg and områdesbestämmelser covering the property (or the point when there is
      no property), newest laga kraft date first, every polygon that covers the point listed
    - "zones": land-use zones (användning) on the property
    - "pending_plans": plans in progress covering the property (not binding)
    - "protected_areas": protected areas covering the property (naturreservat, biotopskyddsområde, ...): type,
      name, deciding authority, decision date and a link to the decision; "permit_authority" is the authority that
      decides dispens
    - "natura2000": Natura 2000 sites covering the property, with their site code and a link to the site
    - "national_interests": riksintressen (miljöbalken 3 and 4 kap.) covering the property, with their kind, name,
      legal basis ("law") and a link to the description where there is one
    - "ancient_remains": ancient remains on the property (or within ANCIENT_REMAINS_RADIUS_M of the pin when there
      is no property): ref = RAÄ number, type = kind of remain, status = antikvarisk bedömning, url = Fornsök
    - "strandskydd": {"status": "not_checked", "reason", "note"}: the reason it was not checked and the reminder
      that a strandskyddsdispens may be needed within 100 m of a shoreline
    - "permits": place.permits.likely_permits of this profile
    - "section_status": {"protected_areas", "natura2000", "national_interests", "ancient_remains"}: "ok" when every
      source of the section answered (an empty list then means none was found), "unavailable" when one did not,
      "not_covered" outside the pilot kommuner
    - "layers": [{"id", "title", "provider", "licence", "fetched", "status"}] for every layer consulted
    - "notes": user-facing caveats, the first one NOT_A_DECISION

    Every row of plans, zones, pending_plans, protected_areas, natura2000, national_interests and ancient_remains
    is a feature of `place.sources.feature` (`place.plan_layers.feature` in a plan-layer kommun) plus "source"
    (provider), "fetched" (snapshot date) and "geometry" (GeoJSON). Plans also carry "page" (the plan's page link,
    or None), "documents" (absolute document links, [] when the layer has none), "licence" (the layer's),
    "document_ids" (the document store's documents place.plan_links matched to the polygon, [] when none is matched
    yet), "document_match" (the level that matched them: "link", "akt" or "name", None when no document is matched
    yet), "corpus_documents" (those of them in the corpus: [{"doc_id", "role" (the plan registry's, or None), "title",
    "url"}], plan maps first, then plan descriptions, then the rest), "text_status" ("read" when corpus_documents has
    any; "none" when it has none; "unavailable" when the polygon has matched documents but the corpus could not be
    reached, which also adds a note), "read_with" (the plans to read together with this one: [{"ref",
    "corpus_documents"}], [] when none. An amendment (kind "plan_addition") reads with the plans its layer row names,
    at the point or not, else with the older plans of kind "plan" at the point; any other plan reads with those its row
    names that are also at the point, so a plan naming an amendment elsewhere does not bring it in), "corpus_plan_id" (the matching plan of the corpus registry, or None) and
    "provisions_indexed" (True when that plan has provisions); zones carry
    "share", the fraction of the property they cover (1.0 without a property). A feature counts when it contains
    the pin or covers at least 2 % of the property, so neighbours that only touch its boundary are left out.

    In a plan-layer kommun, property is None, zones, pending_plans and the sections are empty with every
    section_status "not_covered", layers holds the plan layer, and the permits are those of the plans found.
    Outside every snapshot, kommun is None, covered False, property_status "not_covered", detaljplan "unknown",
    the lists are empty, every section_status is "not_covered" and there are no permits. Raises ValueError when
    lat or lon is not a coordinate."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):  # also rejects NaN
        raise ValueError(f"Not a coordinate: lat={lat}, lon={lon}")
    store = store or default_store()
    code = store.kommun_at(lon, lat)
    if code is None:
        return _not_covered(lat, lon)
    if code not in PILOTS:
        return _plan_layer_profile(lat, lon, code, store, corpus_documents or hosted_documents)

    kommun = PILOTS[code]["name"]
    found, property_status = _property(code, lon, lat, property_at or live.property_at)
    point = Point(lon, lat)
    area = shape(found["geometry"]) if found else point
    meta = {layer["id"]: layer for layer in store.layers(code)}

    rows: dict[str, list[dict]] = {}
    consulted = []
    for layer in PILOTS[code]["layers"] + NATIONAL_LAYERS:
        layer_meta = meta.get(layer.id, {})
        consulted.append({"id": layer.id, "title": layer.title, "provider": layer.provider,
                          "licence": layer.licence, "fetched": layer_meta.get("fetched"),
                          "status": layer_meta.get("status", "unavailable")})
        rows.setdefault(layer.kind, []).extend(_layer_rows(store, code, layer, layer_meta, point, area))
    status_of = {entry["id"]: entry["status"] for entry in consulted}

    plans_by_key, plans_by_page = {}, {}
    for plan in (plan_registry or corpus_plans)(code):
        plans_by_key.setdefault(_plan_key(plan.get("name"), kommun), plan)
        if plan.get("page"):
            plans_by_page.setdefault(plan["page"]["url"], plan)
    pages = store.plan_pages(code)
    plans, document_notes = _with_documents(_by_date_newest_first([
        _without_share(row) | {"page": row["url"], "documents": [], "licence": meta.get(row["layer"], {}).get("licence")}
        | _corpus_match(_plan_key(row["name"], kommun), plans_by_key, pages.get(row["ref"]), plans_by_page)
        for kind in PLAN_KINDS for row in rows.get(kind, [])]), store.plan_links(code),
        corpus_documents or hosted_documents)

    remains, remains_entry = _ancient_remains(ancient_remains_at or live.ancient_remains_at,
                                              area if found else _around_pin(point, lat))
    consulted.append(remains_entry)
    sections = {section: [_without_share(row) for row in rows.get(kind, [])] for section, kind in SECTION_KINDS.items()}
    section_status = _section_status(status_of) | {"ancient_remains": remains_entry["status"]}

    profile = {"point": {"lat": lat, "lon": lon}, "kommun": {"code": code, "name": kommun}, "covered": True,
               "property": found, "property_status": property_status,
               "detaljplan": _detaljplan(rows.get("plan", []), meta.get("plans", {})), "plans": plans,
               "zones": sorted(rows.get("zone", []), key=lambda row: row["share"], reverse=True),
               "pending_plans": [_without_share(row) for row in rows.get("plan_pending", [])
                                 if (row["status"] or "").lower() not in FINISHED_STAGES],
               **sections, "ancient_remains": remains, "strandskydd": dict(STRANDSKYDD),
               "section_status": section_status, "layers": consulted, "notes": [NOT_A_DECISION, *document_notes]}
    return profile | {"permits": likely_permits(profile)}
