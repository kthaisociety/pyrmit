"""Live lookups at a point: the property (fastighet) from the pilot kommun's own map service."""

import math
from functools import lru_cache

import httpx
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from place.sources import (
    METRES_PER_DEGREE_LAT,
    PILOTS,
    RAA_WMS,
    UPPSALA_MAP,
    USER_AGENT,
    today,
)

UPPSALA_PROPERTY_LAYER = 51  # Fastighetsgränser: one polygon per part of a property, "fastighet" = "TRAKT 7:8"
TIMEOUT_S = 15
COORDINATE_DECIMALS = 6      # ~0.1 m: pins closer than that share a cached lookup
# Every kind of lämning in the register, from fornlämning to "ingen antikvarisk bedömning"
RAA_LAYERS = "fornlamning,mojligfornlamning,ovrkulthistlamning,ingenantikvariskbedomning,ejkulthistlamning"
RAA_IMAGE_PX = 256           # GetFeatureInfo searches a circle of RAA_IMAGE_PX / 2 around the image centre
RAA_MAX_FEATURES = 100


class PlaceSourceUnavailable(Exception):
    """A live source did not answer: network error, HTTP error or an unreadable payload."""


def _query(params: dict) -> list[dict]:
    try:
        response = httpx.get(f"{UPPSALA_MAP}/{UPPSALA_PROPERTY_LAYER}/query", timeout=TIMEOUT_S,
                             headers={"User-Agent": USER_AGENT},
                             params={"outFields": "fastighet", "outSR": 4326, "f": "geojson", **params})
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PlaceSourceUnavailable(f"Uppsala property service: {exc}") from exc
    if "error" in data:
        raise PlaceSourceUnavailable(f"Uppsala property service: {data['error']}")
    return data.get("features") or []


def _designation(kommun: str, fastighet: str) -> str:
    """'KUNGSÄNGEN 7:8' -> 'Uppsala Kungsängen 7:8' (the kommun name, then the trakt in title case)."""
    trakt, _, number = fastighet.strip().rpartition(" ")
    return f"{kommun} {trakt.title()} {number}" if trakt else f"{kommun} {fastighet.strip()}"


@lru_cache(maxsize=2048)
def _uppsala_property(kommun: str, lon: float, lat: float) -> dict | None:
    hits = _query({"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
                   "spatialRel": "esriSpatialRelIntersects"})
    if not hits:
        return None
    fastighet = hits[0]["properties"]["fastighet"]
    escaped = fastighet.replace("'", "''")
    parts = _query({"where": f"fastighet = '{escaped}'"}) or hits
    geometry = unary_union([shape(part["geometry"]) for part in parts])
    return {"designation": _designation(kommun, fastighet), "geometry": mapping(geometry),
            "source": "Uppsala kommun", "fetched": today()}


def _search_square(area) -> tuple[float, float, float, float]:
    """(south, west, north, east) of a square around `area` whose inscribed circle covers all of it: the circle
    GetFeatureInfo searches with a buffer of half the image."""
    west, south, east, north = area.bounds
    lon0, lat0 = (west + east) / 2, (south + north) / 2
    metres_per_degree_lon = METRES_PER_DEGREE_LAT * math.cos(math.radians(lat0))
    radius_m = math.hypot((east - west) / 2 * metres_per_degree_lon, (north - south) / 2 * METRES_PER_DEGREE_LAT)
    half_lat, half_lon = radius_m / METRES_PER_DEGREE_LAT, radius_m / metres_per_degree_lon
    return lat0 - half_lat, lon0 - half_lon, lat0 + half_lat, lon0 + half_lon


@lru_cache(maxsize=512)
def _remains_in(square: tuple[float, float, float, float]) -> tuple[dict, ...]:
    try:
        response = httpx.get(RAA_WMS, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}, params={
            "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo", "layers": RAA_LAYERS,
            "query_layers": RAA_LAYERS, "crs": "EPSG:4326", "bbox": ",".join(map(str, square)),
            "width": RAA_IMAGE_PX, "height": RAA_IMAGE_PX, "i": RAA_IMAGE_PX // 2, "j": RAA_IMAGE_PX // 2,
            "buffer": RAA_IMAGE_PX // 2, "feature_count": RAA_MAX_FEATURES, "info_format": "application/json"})
        response.raise_for_status()
        features = response.json().get("features") or []
    except (httpx.HTTPError, ValueError) as exc:
        raise PlaceSourceUnavailable(f"Riksantikvarieämbetet: {exc}") from exc
    return tuple({"properties": f.get("properties") or {}, "geometry": f["geometry"]} for f in features
                 if f.get("geometry"))


def ancient_remains_at(geometry: dict) -> list[dict]:
    """The ancient remains (lämningar) of Riksantikvarieämbetet's register that meet `geometry` (GeoJSON in WGS84:
    the property, or a small circle around the pin): [{"properties": <the register's attributes: lamningsnummer,
    raa_nummer, lamningstyp, antikvarisk_bedomning, url, ...>, "geometry": <GeoJSON>}].

    Raises PlaceSourceUnavailable when the register does not answer."""
    area = shape(geometry)
    square = tuple(round(value, COORDINATE_DECIMALS) for value in _search_square(area))
    hits = [remain for remain in _remains_in(square) if shape(remain["geometry"]).intersects(area)]
    # A remain with several geometry parts comes once per part: keep one per lämningsnummer
    return list({remain["properties"].get("lamningsnummer") or id(remain): remain for remain in hits}.values())


def property_at(code: str, lon: float, lat: float) -> dict | None:
    """The property at the point in pilot kommun `code`: {"designation" (e.g. "Uppsala Kungsängen 7:8"),
    "geometry" (GeoJSON in WGS84, every part of the property), "source", "fetched" (ISO date)}.

    None when no property covers the point (a street, park or water) or the kommun has no property service.
    Raises PlaceSourceUnavailable when the service fails."""
    if PILOTS.get(code, {}).get("property_service") != "uppsala":
        return None
    return _uppsala_property(PILOTS[code]["name"], round(lon, COORDINATE_DECIMALS), round(lat, COORDINATE_DECIMALS))
