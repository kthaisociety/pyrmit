"""
How well the map's address search finds real addresses: a seeded sample of the kommun's own address register
(Uppsala publishes its belägenhetsadresser as points), each searched as a user would type it ("Kungsgatan 47A,
Uppsala") through place.geocode.search_places (Nominatim). Scored on the distance from the first match to the
register's point and on whether the first match lands on the same property, which is what the pin needs. No model
calls; Nominatim at one request a second, as in the app.

    cd backend && python -m place.check_search --kommun 0380 --n 150   # -> data/agentic/place-search-<time>.json
"""

import argparse
import json
import math
import random
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

from place.bench import RESULTS_DIR
from place.fetch import get_json, new_client
from place.live import PlaceSourceUnavailable
from place.sources import METRES_PER_DEGREE_LAT, SWEDEN_TZ, UPPSALA_MAP

ADDRESS_LAYERS = {"0380": f"{UPPSALA_MAP}/11"}  # Adresser: Name ("Kungsgatan 47A"), PostCode, PostCity
IDS_PER_REQUEST = 100
NEAR_M = (30, 100, 500)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres between two (lat, lon) points, flat-earth: fine within a kommun."""
    dlat = (a[0] - b[0]) * METRES_PER_DEGREE_LAT
    dlon = (a[1] - b[1]) * METRES_PER_DEGREE_LAT * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dlat, dlon)


def sample_addresses(code: str, n: int, *, seed: int = 25, client: httpx.Client | None = None) -> list[dict]:
    """`n` addresses of the kommun's register, seeded: [{"address", "postcode", "city", "lat", "lon"}]."""
    url = ADDRESS_LAYERS[code]
    with client or new_client() as http:
        ids = get_json(http, f"{url}/query", {"where": "1=1", "returnIdsOnly": "true", "f": "json"})["objectIds"]
        chosen = sorted(random.Random(seed).sample(ids, min(n, len(ids))))
        rows = []
        for start in range(0, len(chosen), IDS_PER_REQUEST):
            data = get_json(http, f"{url}/query", {
                "objectIds": ",".join(map(str, chosen[start:start + IDS_PER_REQUEST])),
                "outFields": "Name,PostCode,PostCity", "outSR": 4326, "f": "json"})
            rows += [{"address": f["attributes"]["Name"], "postcode": f["attributes"].get("PostCode"),
                      "city": f["attributes"].get("PostCity"), "lat": f["geometry"]["y"], "lon": f["geometry"]["x"]}
                     for f in data.get("features") or [] if f.get("geometry") and f["attributes"].get("Name")]
    return rows


def _designation(property_at, code: str, lat: float, lon: float) -> str | None:
    try:
        found = property_at(code, lon, lat)
    except PlaceSourceUnavailable:
        return "unavailable"
    return (found or {}).get("designation")


def score_address(row: dict, matches: list[dict], code: str, property_at) -> dict:
    """One address against the search's matches: {"query", "found", "top_m" (first match to the register point),
    "best_m" (closest match), "label_ok" (the first label starts with the address), "same_property" (the first
    match's point lies on the register point's property; None when the register point has no property),
    "top_label", "kind"}."""
    truth = (row["lat"], row["lon"])
    scored = {"query": row["query"], "found": bool(matches), "top_m": None, "best_m": None, "label_ok": False,
              "same_property": None, "top_label": None, "kind": None, "property": None}
    if not matches:
        return scored
    top = matches[0]
    scored.update(top_m=round(distance_m(truth, (top["lat"], top["lon"])), 1),
                  best_m=round(min(distance_m(truth, (m["lat"], m["lon"])) for m in matches), 1),
                  label_ok=top["label"].lower().startswith(row["address"].lower()), top_label=top["label"],
                  kind=top.get("kind"))
    expected = _designation(property_at, code, *truth)
    if expected and expected != "unavailable":
        got = _designation(property_at, code, top["lat"], top["lon"])
        scored.update(property=expected, same_property=got == expected)
    return scored


def summarise(rows: list[dict]) -> dict:
    """Shares over the sampled addresses: found, first match within NEAR_M metres, label right, same property
    (over the addresses whose register point has a property), and the median distance of the first match."""
    found = [row for row in rows if row["found"]]
    with_property = [row for row in found if row["same_property"] is not None]
    distances = sorted(row["top_m"] for row in found)
    share = lambda part, whole: round(part / whole, 3) if whole else None
    return {"addresses": len(rows), "found": share(len(found), len(rows)),
            **{f"within_{m}m": share(sum(row["top_m"] <= m for row in found), len(rows)) for m in NEAR_M},
            "label_ok": share(sum(row["label_ok"] for row in found), len(rows)),
            "same_property": share(sum(bool(row["same_property"]) for row in with_property), len(with_property)),
            "with_property": len(with_property),
            "median_top_m": distances[len(distances) // 2] if distances else None}


def run_check(code: str = "0380", n: int = 150, *, seed: int = 25,
              search: Callable[[str], list[dict]] | None = None, property_at=None,
              addresses: list[dict] | None = None, out_dir: Path = RESULTS_DIR) -> dict:
    """Search `n` sampled register addresses as "<address>, <post town>", score each (score_address) and save the
    result as `out_dir`/place-search-<YYYYmmdd-HHMMSS>.json: {"date", "kommun", "seed", "rows", "summary", "path"}.
    `search`, `property_at` and `addresses` default to place.geocode.search_places, place.live.property_at and
    sample_addresses."""
    from place.geocode import search_places
    from place.live import property_at as live_property

    search, property_at = search or search_places, property_at or live_property
    rows = []
    for row in addresses if addresses is not None else sample_addresses(code, n, seed=seed):
        row = {**row, "query": f"{row['address']}, {row['city']}" if row.get("city") else row["address"]}
        try:
            matches = search(row["query"])
        except PlaceSourceUnavailable as exc:
            rows.append({**row, "query": row["query"], "found": False, "error": str(exc)[:200], "top_m": None,
                         "best_m": None, "label_ok": False, "same_property": None})
            continue
        rows.append({**row, **score_address(row, matches, code, property_at), "error": None})
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"place-search-{datetime.now(SWEDEN_TZ).strftime('%Y%m%d-%H%M%S')}.json"
    result = {"date": datetime.now(SWEDEN_TZ).isoformat(timespec="seconds"), "kommun": code, "seed": seed,
              "rows": rows, "summary": summarise(rows), "path": str(path)}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the address search against the kommun's address register")
    parser.add_argument("--kommun", default="0380", choices=sorted(ADDRESS_LAYERS))
    parser.add_argument("--n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=25)
    args = parser.parse_args()
    result = run_check(args.kommun, args.n, seed=args.seed)
    print(json.dumps(result["summary"], indent=2), "->", result["path"])
    for row in result["rows"]:
        if not row["found"] or (row["top_m"] or 0) > 100 or row["same_property"] is False:
            print(f"  {row['query']:40} -> {row.get('top_label')} ({row['top_m']} m, same property {row['same_property']})")


if __name__ == "__main__":
    main()
