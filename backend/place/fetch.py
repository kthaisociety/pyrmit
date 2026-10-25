"""
Snapshot the area layers of pilot kommuner (place.sources.PILOTS) for the place profile:

    cd backend && python -m place.fetch --kommun 0380            # all layers, ~1-2 min
    python -m place.fetch --kommun 0380 --only plans,natura2000  # some layers again

-> data/geo/<code>/kommun.geojson (boundary: OpenStreetMap via Nominatim, ODbL), <layer>.geojson (raw attributes,
WGS84) and manifest.json (fetch date, source, licence and count per layer), the format place.store.PlaceStore
reads. Restart the backend after fetching.
"""

import argparse
import json
import logging
import time
from pathlib import Path

import httpx
from shapely.geometry import shape

from place.sources import NOMINATIM, PILOTS, USER_AGENT, Layer, layers_for, today
from place.store import GEO_DIR

logger = logging.getLogger(__name__)

ARCGIS_IDS_PER_REQUEST = 500
WFS_PAGE = 1000
WFS_MAX_FEATURES = 200_000
ATTEMPTS = 2
RETRY_DELAY_S = 1.0


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=90, follow_redirects=True)


def _get_json(client: httpx.Client, url: str, params: dict):
    """GET a JSON payload, once more after a short pause if it fails. ArcGIS reports errors with HTTP 200."""
    for attempt in range(ATTEMPTS):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(f"{url}: {data['error']}")
            return data
        except (httpx.HTTPError, ValueError, RuntimeError):
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(RETRY_DELAY_S)


def kommun_boundary(client: httpx.Client, code: str) -> dict:
    """The kommun's boundary from OpenStreetMap (one Nominatim request), as a GeoJSON geometry."""
    name = PILOTS[code]["name"]
    results = _get_json(client, f"{NOMINATIM}/search", {
        "q": f"{name} kommun", "countrycodes": "se", "polygon_geojson": 1, "polygon_threshold": 0.0005,
        "format": "jsonv2", "limit": 5})
    for result in results:
        if result.get("addresstype") == "municipality" and result.get("geojson", {}).get("type") in (
                "Polygon", "MultiPolygon"):
            return result["geojson"]
    raise RuntimeError(f"No municipality boundary for {name} kommun in Nominatim")


def fetch_arcgis(client: httpx.Client, layer: Layer, envelope: tuple | None) -> list[dict]:
    """Every feature of a MapServer layer (in the envelope, for national layers): the ids first, then the
    features by batches of ids, which works whether or not the layer supports paging."""
    url = f"{layer.url}/{layer.layer_id}/query"
    where: dict = {"where": "1=1"}
    if envelope:
        where.update(geometry=",".join(map(str, envelope)), geometryType="esriGeometryEnvelope", inSR=4326,
                     spatialRel="esriSpatialRelIntersects")
    ids = _get_json(client, url, {**where, "returnIdsOnly": "true", "f": "json"}).get("objectIds") or []
    features = []
    for start in range(0, len(ids), ARCGIS_IDS_PER_REQUEST):
        batch = ids[start:start + ARCGIS_IDS_PER_REQUEST]
        data = _get_json(client, url, {"objectIds": ",".join(map(str, batch)), "outFields": "*", "outSR": 4326,
                                       "f": "geojson"})
        features += data.get("features") or []
    return features


def fetch_wfs(client: httpx.Client, layer: Layer, envelope: tuple) -> list[dict]:
    """A WFS 2.0 feature type in the envelope, as GeoJSON in WGS84 (the bbox in lat,lon order for EPSG:4326)."""
    west, south, east, north = envelope
    features, seen = [], set()
    for start in range(0, WFS_MAX_FEATURES, WFS_PAGE):
        data = _get_json(client, layer.url, {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": layer.type_name,
            "outputFormat": "GEOJSON", "srsName": "urn:ogc:def:crs:EPSG::4326", "count": WFS_PAGE,
            "startIndex": start, "bbox": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326"})
        page = [f for f in data.get("features") or [] if f.get("id") not in seen]
        seen.update(f.get("id") for f in page)
        features += page
        if len(data.get("features") or []) < WFS_PAGE or not page:
            break
    return features


def fetch_layer(client: httpx.Client, layer: Layer, kommun) -> list[dict]:
    """The layer's area features: national layers keep those that meet the kommun boundary."""
    envelope = kommun.bounds if layer.national else None
    raw = fetch_arcgis(client, layer, envelope) if layer.service == "arcgis" else fetch_wfs(client, layer, envelope)
    kept = []
    for item in raw:
        if not item.get("geometry"):
            continue
        geometry = shape(item["geometry"])
        if geometry.geom_type not in ("Polygon", "MultiPolygon"):
            continue  # points and lines (e.g. roads of national interest) are not area constraints
        if layer.national and not geometry.intersects(kommun):
            continue
        kept.append({"type": "Feature", "geometry": item["geometry"], "properties": item.get("properties") or {}})
    return kept


def _boundary(client: httpx.Client, code: str, out: Path, manifest: dict, refresh: bool):
    path = out / "kommun.geojson"
    if refresh or not path.exists():
        geometry = kommun_boundary(client, code)
        path.write_text(json.dumps({"type": "Feature", "geometry": geometry, "properties": {
            "code": code, "name": PILOTS[code]["name"], "source": "OpenStreetMap (Nominatim)", "licence": "ODbL"}}),
            encoding="utf-8")
        manifest["kommun"] = {"code": code, "name": PILOTS[code]["name"], "fetched": today(),
                              "source": "OpenStreetMap via Nominatim", "licence": "ODbL"}
    return shape(json.loads(path.read_text(encoding="utf-8"))["geometry"])


def _layer_entry(layer: Layer, count: int) -> dict:
    return {"title": layer.title, "provider": layer.provider, "licence": layer.licence, "url": layer.url,
            "layer_id": layer.layer_id, "type_name": layer.type_name or None, "count": count,
            "fetched": today(), "complete": layer.complete}


def fetch_kommun(code: str, only: set[str] | None = None, *, client: httpx.Client | None = None,
                 out_dir: Path = GEO_DIR) -> dict:
    """Snapshot pilot kommun `code` (every layer, or the layer ids in `only`) into `out_dir`/<code>/ and return
    its manifest. National layers keep only the features that meet the kommun boundary. A layer whose fetch fails
    keeps its previous snapshot and gets "last_error" in the manifest; the others are still written.
    Raises KeyError for a kommun that is not a pilot."""
    layers = [layer for layer in layers_for(code) if not only or layer.id in only]  # KeyError: not a pilot
    out = out_dir / code
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"layers": {}}
    with client or _client() as http:
        kommun = _boundary(http, code, out, manifest, refresh=not only)
        for layer in layers:
            started = time.time()
            try:
                features = fetch_layer(http, layer, kommun)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                logger.error("%s/%s failed, previous snapshot kept: %s", code, layer.id, exc)
                manifest["layers"].setdefault(layer.id, _layer_entry(layer, 0) | {"fetched": None})
                manifest["layers"][layer.id]["last_error"] = f"{today()}: {exc}"
                continue
            (out / f"{layer.id}.geojson").write_text(
                json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")
            manifest["layers"][layer.id] = _layer_entry(layer, len(features))
            logger.info("%s/%s: %d features in %.1f s", code, layer.id, len(features), time.time() - started)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    """CLI: --kommun <code> (repeatable, default every pilot kommun) and --only <layer ids, comma-separated>."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kommun", action="append", help="kommun code (default: every pilot kommun)")
    parser.add_argument("--only", help="comma-separated layer ids")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    only = set(args.only.split(",")) if args.only else None
    for code in args.kommun or list(PILOTS):
        if code not in PILOTS:
            raise SystemExit(f"{code} is not a pilot kommun ({', '.join(PILOTS)})")
        manifest = fetch_kommun(code, only)
        total = sum(layer.get("count", 0) for layer in manifest["layers"].values())
        print(f"{code} {PILOTS[code]['name']}: {total} features in {len(manifest['layers'])} layers -> "
              f"{GEO_DIR / code}")


if __name__ == "__main__":
    main()
