"""
How well the place snapshots agree with their sources today. For sample points of a pilot kommun, the features of
each snapshot layer that contain the point are compared with the provider's own answer for that point (ArcGIS
identify, a WFS Intersects filter): a snapshot that misses features, keeps removed ones or reads the geometry wrong
shows up as "missing" / "extra". The same points time a whole place profile, with its live lookups. No model calls
(ADR-0003).

Not a facit: the providers only check the snapshots' copy of their own data. Whether the data is right for the place
is the hand-made facit's job (place.bench).

    cd backend && python -m place.check_sources --kommun 0380 --n 300   # -> data/agentic/place-sources-<time>.json
"""

import argparse
import json
import random
import re
import statistics
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx
from shapely.geometry import Point

from place.bench import RESULTS_DIR, load_cases, sample_points
from place.fetch import get_json, new_client
from place.sources import SWEDEN_TZ, Layer, layers_for

DRAFT_CASES = Path(__file__).resolve().parent / "cases_draft_{code}.jsonl"
KEY_FIELDS = {"protected_areas": "NVRID", "natura2000": "OMRADESKOD"}  # WFS layers; ArcGIS layers by object id
IDENTIFY_EXTENT_DEG = 0.01  # identify needs a map extent; with tolerance 0 only the point counts
WORKERS = 4
# The WFS answers "geometry": {"type": "MultiPolygon",} when the geometry is left out of propertyName
_EMPTY_GEOMETRY = re.compile(r'"geometry"\s*:\s*\{\s*"type"\s*:\s*"\w+"\s*,?\s*\}')


def feature_key(layer: Layer, properties: dict, oid_field: str = "OBJECTID") -> str | None:
    """The id a feature of `layer` is compared by: the NVRID / site code for Naturvårdsverket's layers, else the
    ArcGIS object id (as a string)."""
    value = properties.get(KEY_FIELDS.get(layer.id, oid_field))
    return None if value in (None, "") else str(value)


def snapshot_keys(store, code: str, layer: Layer, lon: float, lat: float) -> list[str]:
    """The keys of the snapshot features of `layer` that contain the point."""
    return sorted({key for props, _ in store.features(code, layer.id, Point(lon, lat))
                   if (key := feature_key(layer, props))})


def _oid_aliases(client: httpx.Client, layers: list[Layer]) -> dict[int, str]:
    """Identify names attributes by their alias ("OBJEKTID" on some Uppsala layers): the object id field's alias
    per layer id, from the layers' metadata."""
    aliases = {}
    for layer in layers:
        meta = get_json(client, f"{layer.url}/{layer.layer_id}", {"f": "json"})
        oid = next((field for field in meta.get("fields") or [] if field.get("type") == "esriFieldTypeOID"), None)
        aliases[layer.layer_id] = (oid or {}).get("alias") or (oid or {}).get("name") or "OBJECTID"
    return aliases


def identify_keys(client: httpx.Client, url: str, layers: list[Layer], aliases: dict[int, str], lon: float,
                  lat: float) -> dict[str, list[str]]:
    """The provider's answer for the point: {layer id: keys of the features containing it}, one identify call for
    every layer of one MapServer."""
    half = IDENTIFY_EXTENT_DEG / 2
    data = get_json(client, f"{url}/identify", {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": 4326, "tolerance": 0,
        "layers": "all:" + ",".join(str(layer.layer_id) for layer in layers), "returnGeometry": "false",
        "mapExtent": f"{lon - half},{lat - half},{lon + half},{lat + half}", "imageDisplay": "400,400,96",
        "f": "json"})
    by_id = {layer.layer_id: layer for layer in layers}
    found: dict[str, set[str]] = {layer.id: set() for layer in layers}
    for result in data.get("results") or []:
        layer = by_id.get(result.get("layerId"))
        if layer:
            key = feature_key(layer, result.get("attributes") or {}, aliases.get(layer.layer_id, "OBJECTID"))
            if key:
                found[layer.id].add(key)
    return {layer_id: sorted(keys) for layer_id, keys in found.items()}


def wfs_keys(client: httpx.Client, layer: Layer, lon: float, lat: float) -> list[str]:
    """The keys of the WFS features whose geometry contains the point (an OGC Intersects filter, run by the
    provider)."""
    point_filter = (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" xmlns:gml="http://www.opengis.net/gml/3.2">'
        '<fes:Intersects><fes:ValueReference>SHAPE</fes:ValueReference>'
        f'<gml:Point gml:id="pin" srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>{lat} {lon}</gml:pos></gml:Point>'
        '</fes:Intersects></fes:Filter>')
    response = client.get(layer.url, params={
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": layer.type_name,
        "outputFormat": "GEOJSON", "srsName": "urn:ogc:def:crs:EPSG::4326", "FILTER": point_filter,
        "propertyName": KEY_FIELDS[layer.id]})
    response.raise_for_status()
    data = json.loads(_EMPTY_GEOMETRY.sub('"geometry": null', response.text))
    return sorted({key for feature in data.get("features") or []
                   if (key := feature_key(layer, feature.get("properties") or {}))})


def compare(ours: list[str], theirs: list[str]) -> dict:
    """{"ours", "theirs", "missing": in the source but not the snapshot, "extra": in the snapshot only, "agree"}."""
    missing, extra = sorted(set(theirs) - set(ours)), sorted(set(ours) - set(theirs))
    return {"ours": ours, "theirs": theirs, "missing": missing, "extra": extra, "agree": not missing and not extra}


class SourceChecker:
    """Checks points of one kommun: `live` maps (lon, lat) to the providers' answers {layer id: keys}; defaults to
    the real services."""

    def __init__(self, code: str, store, *, client: httpx.Client | None = None,
                 live: Callable[[float, float], dict[str, list[str]]] | None = None):
        self.code, self.store = code, store
        self.layers = [layer for layer in layers_for(code) if layer.id in {row["id"] for row in store.layers(code)}]
        self.client = client
        self.live = live or self._live
        self._aliases: dict[int, str] | None = None
        self._lock = threading.Lock()

    def _live(self, lon: float, lat: float) -> dict[str, list[str]]:
        arcgis: dict[str, list[Layer]] = {}
        for layer in self.layers:
            if layer.service == "arcgis":
                arcgis.setdefault(layer.url, []).append(layer)
        with self._lock:  # one client and one metadata read, shared by the worker threads
            self.client = self.client or new_client()
            if self._aliases is None:
                self._aliases = _oid_aliases(self.client, [layer for group in arcgis.values() for layer in group])
        answers: dict[str, list[str]] = {}
        for url, group in arcgis.items():
            answers |= identify_keys(self.client, url, group, self._aliases, lon, lat)
        for layer in self.layers:
            if layer.service == "wfs":
                answers[layer.id] = wfs_keys(self.client, layer, lon, lat)
        return answers

    def check(self, lat: float, lon: float) -> dict:
        """{"layers": {layer id: compare(...)}, "error"}: the providers' answers against the snapshot at the point."""
        try:
            answers = self.live(lon, lat)
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            return {"layers": {}, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return {"layers": {layer.id: compare(snapshot_keys(self.store, self.code, layer, lon, lat),
                                             answers.get(layer.id, []))
                           for layer in self.layers if layer.id in answers},
                "error": None}


def timed_profile(build: Callable[[float, float], dict], lat: float, lon: float) -> dict:
    """How long a place profile takes and what its live parts did: {"seconds", "property_status",
    "remains_status", "detaljplan", "error"}."""
    started = time.perf_counter()
    try:
        profile = build(lat, lon)
    except Exception as exc:  # a failing lookup is a result here, not a crash
        return {"seconds": round(time.perf_counter() - started, 3), "property_status": None,
                "remains_status": None, "detaljplan": None, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"seconds": round(time.perf_counter() - started, 3), "property_status": profile.get("property_status"),
            "remains_status": (profile.get("section_status") or {}).get("ancient_remains"),
            "detaljplan": profile.get("detaljplan"), "error": None}


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def summarise(points: list[dict]) -> dict:
    """Per layer: points where the snapshot and the source agree, the points where either has a feature
    ("present"), and precision / recall of the snapshot's features against the source's. Plus the share of points
    where every layer agrees, and the profile times."""
    checked = [point for point in points if not point["sources"]["error"]]
    layers = {}
    for layer_id in dict.fromkeys(key for point in checked for key in point["sources"]["layers"]):
        rows = [point["sources"]["layers"][layer_id] for point in checked if layer_id in point["sources"]["layers"]]
        ours, theirs = sum(len(row["ours"]) for row in rows), sum(len(row["theirs"]) for row in rows)
        both = sum(len(set(row["ours"]) & set(row["theirs"])) for row in rows)
        layers[layer_id] = {"points": len(rows), "present": sum(bool(row["ours"] or row["theirs"]) for row in rows),
                            "agree": sum(row["agree"] for row in rows),
                            "precision": both / ours if ours else None, "recall": both / theirs if theirs else None,
                            "missing": sum(len(row["missing"]) for row in rows),
                            "extra": sum(len(row["extra"]) for row in rows)}
    seconds = [point["profile"]["seconds"] for point in points if point.get("profile") and not point["profile"]["error"]]
    profiles = [point["profile"] for point in points if point.get("profile")]
    return {
        "points": len(points), "checked": len(checked), "source_errors": len(points) - len(checked),
        "all_agree": sum(all(row["agree"] for row in point["sources"]["layers"].values()) for point in checked),
        "layers": layers,
        "profile": {"timed": len(seconds), "p50_s": _percentile(seconds, 0.5), "p90_s": _percentile(seconds, 0.9),
                    "max_s": max(seconds, default=None),
                    "mean_s": round(statistics.fmean(seconds), 3) if seconds else None,
                    "errors": sum(bool(p["error"]) for p in profiles),
                    "property_unavailable": sum(p["property_status"] == "unavailable" for p in profiles),
                    "remains_unavailable": sum(p["remains_status"] == "unavailable" for p in profiles),
                    "detaljplan": {state: sum(p["detaljplan"] == state for p in profiles)
                                   for state in ("inside", "outside", "unknown")}},
    }


def run_check(code: str, n: int = 300, *, seed: int = 25, store=None, checker: SourceChecker | None = None,
              build: Callable[[float, float], dict] | None = None, drafts: Path | None = None,
              out_dir: Path = RESULTS_DIR, workers: int = WORKERS) -> dict:
    """Check `n` seeded sample points of kommun `code` (half inside its plans, see place.bench.sample_points) plus
    the proposed facit places of `drafts` (default place/cases_draft_<code>.jsonl, when it exists), save the result
    as `out_dir`/place-sources-<YYYYmmdd-HHMMSS>.json and return it: {"date", "kommun", "seed", "points": [{"lat",
    "lon", "origin": "sample" | <draft id>, "sources", "profile"}], "summary", "path"}. `build` (lat, lon -> profile,
    default place.profile.build_profile) is timed per point; build=False skips the profiles."""
    from place.profile import build_profile, default_store

    store = store or default_store()
    checker = checker or SourceChecker(code, store)
    build = build_profile if build is None else build
    places = [(lat, lon, "sample") for lat, lon in sample_points(store, code, n, random.Random(seed))]
    drafts = Path(str(DRAFT_CASES).format(code=code)) if drafts is None else drafts
    if drafts and Path(drafts).exists():
        places += [(case["pin"]["lat"], case["pin"]["lon"], case["id"]) for case in load_cases(drafts)]

    def one(place: tuple[float, float, str]) -> dict:
        lat, lon, origin = place
        return {"lat": lat, "lon": lon, "origin": origin, "sources": checker.check(lat, lon),
                "profile": timed_profile(build, lat, lon) if build else None}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        points = list(pool.map(one, places))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"place-sources-{datetime.now(SWEDEN_TZ).strftime('%Y%m%d-%H%M%S')}.json"
    result = {"date": datetime.now(SWEDEN_TZ).isoformat(timespec="seconds"), "kommun": code, "seed": seed,
              "snapshot": {row["id"]: row.get("fetched") for row in store.layers(code)},
              "points": points, "summary": summarise(points), "path": str(path)}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the place snapshots against their sources at sample points")
    parser.add_argument("--kommun", default="0380")
    parser.add_argument("--n", type=int, default=300, help="sample points (plus the draft facit places)")
    parser.add_argument("--seed", type=int, default=25)
    parser.add_argument("--no-profile", action="store_true", help="skip timing the place profiles")
    args = parser.parse_args()
    result = run_check(args.kommun, args.n, seed=args.seed, build=False if args.no_profile else None)
    summary = result["summary"]
    print(f"{summary['checked']}/{summary['points']} points checked, every layer agrees at {summary['all_agree']}"
          f" -> {result['path']}")
    for layer_id, stats in summary["layers"].items():
        if stats["present"]:
            print(f"  {layer_id:28} agree {stats['agree']}/{stats['points']}  present {stats['present']}"
                  f"  precision {stats['precision']}  recall {stats['recall']}")
    print("  profile:", summary["profile"])


if __name__ == "__main__":
    main()
