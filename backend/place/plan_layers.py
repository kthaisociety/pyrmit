"""
Snapshot the plan layers of the kommun plan sources (place.registry) for the place profile, in the format
place.fetch writes for the pilot kommuner, and report the coverage:

    cd backend && python -m place.plan_layers                      # every kommun in place/plan_sources.json
    python -m place.plan_layers --kommun 0182 --kommun 0120        # some of them

-> data/geo/<code>/kommun.geojson, plans.geojson, manifest.json per kommun, and data/geo/plan_coverage.md.
Restart the backend after fetching. Each snapshot feature keeps the provider's raw attributes and gets the
normalised plan under PLAN_KEY (ADR-0005).
"""

import argparse
import json
import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

import httpx
from shapely.geometry import shape

from place.fetch import fetch_arcgis, get_json, kommun_boundary, new_client
from place.registry import PlanSource, load_registry
from place.sources import Layer, first_value, iso_date, today
from place.store import GEO_DIR

logger = logging.getLogger(__name__)

PLAN_KEY = "_plan"                  # the block with the normalised plan in a snapshot feature's properties
LAYER_ID = "plans"                  # the snapshot file and manifest key, as for the pilot kommuner
LAYER_TITLE = "Gällande detaljplaner"
MIN_SHARE_OF_SURVEY = 0.5           # fewer polygons than this share of the survey's count flags the fetch
COVERAGE_REPORT = "plan_coverage.md"
BOUNDARY_SOURCE = "OpenStreetMap via Nominatim"
BOUNDARY_LICENCE = "ODbL"

WFS_PAGE = 1000
WFS_MAX_FEATURES = 200_000
WFS_OUTPUT_FORMATS = ("application/json", "GeoJSON", "GEOJSON", "json")
WFS_OWN_PARAMETERS = {"service", "version", "request", "typename", "typenames", "outputformat", "srsname", "count",
                      "maxfeatures", "startindex"}
SWEDEN_LON = (10.0, 25.0)
SWEDEN_LAT = (54.0, 70.0)
FILE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".djvu", ".ecw", ".dwg", ".dxf", ".zip",
                   ".doc", ".docx")
INTERNAL_PATH = re.compile(r"^(\\\\|[A-Za-z]:[\\/]|file:)", re.IGNORECASE)
WEB_ADDRESS = re.compile(r"^https?://", re.IGNORECASE)
OTHER_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
LINK_SEPARATORS = re.compile(r"[\s;,|]+")
REASON_LENGTH = 200


# --- links --------------------------------------------------------------------------------------------------------

def _candidates(value) -> list[str]:
    """The links a link attribute holds: the hrefs of its anchors, the addresses it lists, or the value itself."""
    text = str(value).strip() if value is not None else ""
    if not text:
        return []
    if "<a" in text.lower():
        return HREF.findall(text)
    if text.lower().count("http") > 1 or "\n" in text:
        return [part for part in LINK_SEPARATORS.split(text) if part]
    return [text]


def _absolute(link: str, base_url: str | None) -> str | None:
    """The link as an address, or None for an internal path or a bare name without a base pattern."""
    if INTERNAL_PATH.match(link):
        return None
    if WEB_ADDRESS.match(link):
        return link
    if link.lower().startswith("www."):
        return f"https://{link}"
    if OTHER_SCHEME.match(link):
        return link
    if not base_url:
        return None
    name = quote(link, safe="/:()")
    if "{file}" in base_url:
        return base_url.replace("{file}", name)
    return urljoin(base_url.rstrip("/") + "/", name)


def _links(values: list, base_url: str | None) -> tuple[list[str], int]:
    """(absolute links, each once, in order; links dropped)."""
    links, dropped = [], 0
    for value in values:
        for candidate in _candidates(value):
            link = _absolute(candidate, base_url)
            if link is None:
                dropped += 1
            elif link not in links:
                links.append(link)
    return links, dropped


def _is_file(link: str) -> bool:
    return urlsplit(link).path.lower().endswith(FILE_EXTENSIONS)


def _text(value) -> str | None:
    return str(value).strip() if value not in (None, "") and str(value).strip() else None


def _plan_properties(source: PlanSource, props: dict) -> dict:
    """The PLAN_KEY block of a feature: the normalised plan read with the source's attribute names."""
    lowered = {key.lower(): value for key, value in props.items()}
    links, dropped = _links([lowered.get(field.lower()) for field in source.url_fields], source.base_url)
    return {"ref": _text(first_value(props, *source.akt_fields)), "name": _text(first_value(props, *source.name_fields)),
            "date": iso_date(first_value(props, *source.date_fields)),
            "type": _text(first_value(props, *source.type_fields)),
            "page": next((link for link in links if not _is_file(link)), None),
            "documents": [link for link in links if _is_file(link)], "dropped_links": dropped}


def feature(props: dict) -> dict:
    """The profile row of a snapshot plan from its properties, read from their PLAN_KEY block: {"layer": LAYER_ID,
    "kind": "plan", "layer_title": LAYER_TITLE, "name", "ref" (aktbeteckning), "type", "date" (ISO), "url" (the
    plan page, else the first document link, else None), "page", "documents" (absolute links, in the layer's
    order), "status", "authority", "law", "text", "note" (all None)}."""
    plan = props.get(PLAN_KEY) or {}
    documents = list(plan.get("documents") or [])
    return {"layer": LAYER_ID, "kind": "plan", "layer_title": LAYER_TITLE, "name": plan.get("name"),
            "ref": plan.get("ref"), "type": plan.get("type"), "date": plan.get("date"), "status": None,
            "authority": None, "law": None, "text": None,
            "url": plan.get("page") or (documents[0] if documents else None), "note": None,
            "page": plan.get("page"), "documents": documents}


# --- the services ---------------------------------------------------------------------------------------------------

def _arcgis_layer(source: PlanSource) -> Layer:
    base, _, layer_id = source.url.rstrip("/").rpartition("/")
    return Layer(id=LAYER_ID, kind="plan", title=source.layer, provider=f"{source.name} kommun", licence=source.licence,
                 service="arcgis", url=base, layer_id=int(layer_id))


def _wfs_pages(client: httpx.Client, url: str, params: dict, version: str, output_format: str) -> list[dict]:
    """Every feature of the type, page by page. ValueError when the service does not answer with GeoJSON."""
    page_key = "count" if version.startswith("2") else "maxFeatures"
    features, seen = [], set()
    for start in range(0, WFS_MAX_FEATURES, WFS_PAGE):
        data = get_json(client, url, {**params, "outputFormat": output_format, "srsName": "EPSG:4326",
                                      page_key: WFS_PAGE, "startIndex": start})
        if not isinstance(data, dict) or "features" not in data:
            raise ValueError(f"{url}: no GeoJSON for outputFormat {output_format}")
        page = [f for f in data["features"] or [] if f.get("id") not in seen or f.get("id") is None]
        seen.update(f.get("id") for f in page)
        features += page
        if len(data["features"] or []) < WFS_PAGE or not page:
            break
    return features


def _fetch_wfs(client: httpx.Client, source: PlanSource) -> list[dict]:
    """The whole feature type, with the version, type name and output format the endpoint's own query carries,
    its other parameters (a token, a CQL filter) passed through."""
    parts = urlsplit(source.url)
    given = parse_qsl(parts.query, keep_blank_values=True)
    lowered = {key.lower(): value for key, value in given}
    version = lowered.get("version", "2.0.0")
    type_name = lowered.get("typenames") or lowered.get("typename") or source.layer
    params = {key: value for key, value in given if key.lower() not in WFS_OWN_PARAMETERS}
    params.update(service="WFS", version=version, request="GetFeature")
    params["typeNames" if version.startswith("2") else "typeName"] = type_name
    url = urlunsplit(parts._replace(query=""))
    formats = (lowered["outputformat"],) if lowered.get("outputformat") else WFS_OUTPUT_FORMATS
    for output_format in formats:
        try:
            return _wfs_pages(client, url, params, version, output_format)
        except ValueError:
            continue
    raise RuntimeError(f"{url}: no GeoJSON output format accepted among {', '.join(formats)}")


def _swap_axes(coordinates):
    if isinstance(coordinates[0], (int, float)):
        return [coordinates[1], coordinates[0], *coordinates[2:]]
    return [_swap_axes(part) for part in coordinates]


def _first_position(coordinates):
    while not isinstance(coordinates[0], (int, float)):
        coordinates = coordinates[0]
    return coordinates


def _in_wgs84(geometries: list[dict]) -> list[dict]:
    """The geometries in lon, lat order: swapped when the service answered lat, lon; RuntimeError for a projected
    system (the service ignored srsName)."""
    positions = [_first_position(geometry["coordinates"]) for geometry in geometries]
    if not positions:
        return geometries
    x, y = positions[0][:2]
    if SWEDEN_LAT[0] <= x <= SWEDEN_LAT[1] and SWEDEN_LON[0] <= y <= SWEDEN_LON[1]:
        return [geometry | {"coordinates": _swap_axes(geometry["coordinates"])} for geometry in geometries]
    if abs(x) > 180 or abs(y) > 90:
        raise RuntimeError(f"coordinates not in WGS84 (first position {x}, {y})")
    return geometries


def _polygons(raw: list[dict], boundary) -> list[dict]:
    """The features with a polygon that meets the kommun boundary, as plain GeoJSON features."""
    with_geometry = [item for item in raw if item.get("geometry")
                     and item["geometry"].get("type") in ("Polygon", "MultiPolygon")]
    geometries = _in_wgs84([item["geometry"] for item in with_geometry])
    return [{"type": "Feature", "geometry": geometry, "properties": item.get("properties") or {}}
            for item, geometry in zip(with_geometry, geometries) if shape(geometry).intersects(boundary)]


# --- the snapshot ---------------------------------------------------------------------------------------------------

def _boundary(client: httpx.Client, source: PlanSource, out: Path) -> tuple[dict, str]:
    """(the kommun boundary feature, the date it was fetched): the file on disk, else Nominatim."""
    path = out / "kommun.geojson"
    if path.exists():
        manifest_path = out / "manifest.json"
        fetched = (json.loads(manifest_path.read_text(encoding="utf-8")).get("kommun", {}).get("fetched")
                   if manifest_path.exists() else None)
        return json.loads(path.read_text(encoding="utf-8")), fetched or today()
    geometry = kommun_boundary(client, source.code, source.name)
    return {"type": "Feature", "geometry": geometry, "properties": {
        "code": source.code, "name": source.name, "source": BOUNDARY_SOURCE, "licence": BOUNDARY_LICENCE}}, today()


def _reason(count: int, source: PlanSource) -> str | None:
    if count == 0:
        return "no polygons in the layer"
    if not source.shared and source.survey_count and count < MIN_SHARE_OF_SURVEY * source.survey_count:
        return f"{count} polygons, the survey counted {source.survey_count}"
    return None


def _write(out: Path, boundary: dict, boundary_date: str, features: list[dict], source: PlanSource, row: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "kommun.geojson").write_text(json.dumps(boundary, ensure_ascii=False), encoding="utf-8")
    (out / f"{LAYER_ID}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                                          ensure_ascii=False), encoding="utf-8")
    manifest = {"kommun": {"code": source.code, "name": source.name, "fetched": boundary_date,
                           "source": BOUNDARY_SOURCE, "licence": BOUNDARY_LICENCE},
                "layers": {LAYER_ID: {"title": LAYER_TITLE, "provider": f"{source.name} kommun",
                                      "licence": source.licence, "url": source.url, "layer_id": None,
                                      "type_name": source.layer, "count": len(features), "fetched": row["date"],
                                      "complete": False, "service": source.service, "status": source.status,
                                      "ref_share": row["ref_share"], "link_share": row["link_share"],
                                      "dropped_links": row["dropped_links"]}}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _shares(plans: list[dict]) -> dict:
    """The coverage row's shares and dropped links over the PLAN_KEY blocks of a snapshot."""
    return {"dropped_links": sum(plan["dropped_links"] for plan in plans),
            "ref_share": sum(1 for plan in plans if plan["ref"]) / len(plans),
            "link_share": sum(1 for plan in plans if plan["page"] or plan["documents"]) / len(plans)}


def _snapshot(client: httpx.Client, source: PlanSource, out: Path, row: dict) -> None:
    """Fetch, normalise and write the source's layer, filling in `row`; nothing written when the row gets a reason."""
    boundary, boundary_date = _boundary(client, source, out)
    raw = (fetch_arcgis(client, _arcgis_layer(source), None) if source.service == "arcgis"
           else _fetch_wfs(client, source))
    features = _polygons(raw, shape(boundary["geometry"]))
    row["count"] = len(features)
    row["reason"] = _reason(len(features), source)
    if row["reason"]:
        return
    for item in features:
        item["properties"][PLAN_KEY] = _plan_properties(source, item["properties"])
    row.update(_shares([item["properties"][PLAN_KEY] for item in features]))
    _write(out, boundary, boundary_date, features, source, row)
    row["fetched"] = True


def fetch_plan_layer(source: PlanSource, *, client: httpx.Client | None = None, out_dir: Path = GEO_DIR) -> dict:
    """Snapshot the plan layer of `source` into `out_dir`/<code>/, the format place.store.PlaceStore reads:

    - `kommun.geojson`: the kommun boundary from OpenStreetMap (place.fetch.kommun_boundary), fetched when the file
      is missing and kept otherwise
    - `plans.geojson`: every polygon of the layer that meets the boundary (a shared server's other kommuner are
      left out), with the provider's raw attributes plus a PLAN_KEY block: {"ref" (aktbeteckning), "name", "date"
      (ISO), "type" (when the layer states it, else None), "page" (the first link that is not a file), "documents"
      (the file links, absolute, each once), "dropped_links"}. A link that is only a file name becomes absolute
      through the source's base_url ("{file}" replaced, or the name joined to the pattern); a link wrapped in HTML
      keeps the addresses of its anchors; an internal path (a UNC path, a drive letter, file:) and a bare name
      without a base_url are dropped and counted; a "www." address gets https.
    - `manifest.json`: "kommun" {"code", "name", "fetched", "source", "licence"} and "layers" {"plans": {"title",
      "provider" ("<name> kommun"), "licence", "url", "layer_id" None, "type_name", "count", "fetched" (today),
      "complete" False, "service", "status", "ref_share", "link_share", "dropped_links"}}

    Returns the coverage row: {"code", "name", "fetched" (True when the snapshot was written), "reason" (why it
    was not, else None), "count" (polygons kept), "survey_count", "ref_share" (share of the kept polygons with an
    aktbeteckning), "link_share" (share with a page or document link), "dropped_links", "date" (today)}. The
    shares are None when nothing was fetched.

    No snapshot is written, and an earlier one is left as it is, when the service fails, answers with no polygon,
    or with fewer than MIN_SHARE_OF_SURVEY of the survey's count for a source that is not shared; the row then
    carries the reason. A failing service never raises."""
    row = {"code": source.code, "name": source.name, "fetched": False, "reason": None, "count": 0,
           "survey_count": source.survey_count, "ref_share": None, "link_share": None, "dropped_links": 0,
           "date": today()}
    http = client or new_client()
    started = time.time()
    try:
        _snapshot(http, source, Path(out_dir) / source.code, row)
    except (httpx.HTTPError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        row["reason"] = f"{type(exc).__name__}: {exc}"[:REASON_LENGTH]
    finally:
        if client is None:
            http.close()
    logger.info("%s %s: %s (%d polygons, %.1f s)", source.code, source.name,
                "fetched" if row["fetched"] else f"not fetched: {row['reason']}", row["count"], time.time() - started)
    return row


def fetch_registry(sources: Iterable[PlanSource], *, client: httpx.Client | None = None,
                   out_dir: Path = GEO_DIR) -> list[dict]:
    """fetch_plan_layer for every source, in the order given, going on after a kommun that fails, then
    coverage_report of the rows written to `out_dir`/COVERAGE_REPORT. Returns the coverage rows."""
    http = client or new_client()
    try:
        rows = [fetch_plan_layer(source, client=http, out_dir=out_dir) for source in sources]
    finally:
        if client is None:
            http.close()
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / COVERAGE_REPORT).write_text(coverage_report(rows), encoding="utf-8")
    return rows


def _share(value: float | None) -> str:
    return "–" if value is None else f"{round(value * 100)} %"


def coverage_report(rows: list[dict]) -> str:
    """The coverage rows as Markdown: a heading with the date and how many kommuner were fetched, then a table with
    one row per kommun: code, name, fetched or not with the reason, polygons, the survey's count, share with an
    aktbeteckning, share with a link, dropped links."""
    fetched = sum(1 for row in rows if row["fetched"])
    lines = [f"# Plan layer coverage, {today()}", "", f"{fetched} of {len(rows)} kommuner fetched.", "",
             "| Kod | Kommun | Fetched | Polygons | Survey | With aktbeteckning | With link | Dropped links |",
             "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        status = "yes" if row["fetched"] else f"no: {(row['reason'] or '').replace('|', '/')}"
        lines.append(f"| {row['code']} | {row['name']} | {status} | {row['count']} | "
                     f"{row['survey_count'] if row['survey_count'] is not None else '–'} | {_share(row['ref_share'])} | "
                     f"{_share(row['link_share'])} | {row['dropped_links']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    """CLI: --kommun <code> (repeatable, default every kommun in the registry) and --registry <json>."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kommun", action="append", help="kommun code (default: every kommun in the registry)")
    parser.add_argument("--registry", type=Path, default=None, help="registry file (default: place/plan_sources.json)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    registry = load_registry(args.registry) if args.registry else load_registry()
    codes = args.kommun or list(registry)
    unknown = [code for code in codes if code not in registry]
    if unknown:
        raise SystemExit(f"not in the registry: {', '.join(unknown)}")
    rows = fetch_registry([registry[code] for code in codes])
    print(f"{sum(1 for row in rows if row['fetched'])} of {len(rows)} kommuner fetched -> {GEO_DIR / COVERAGE_REPORT}")


if __name__ == "__main__":
    main()
