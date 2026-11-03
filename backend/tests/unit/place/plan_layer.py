"""A fake kommun with an open plan layer (Nacka, as place.registry describes one), with fake Nominatim, ArcGIS and
WFS services for place.plan_layers, shared by the place tests. No real services (PCR-0011)."""

import json

import httpx

from place.plan_layers import PLAN_KEY, fetch_plan_layer
from place.registry import PlanSource
from place.store import PlaceStore
from tests.unit.place.snapshot import square, write_snapshot

NACKA_BOUNDARY = square(18.0, 59.25, 18.4, 59.40)
IN_NACKA = (59.31, 18.16)            # lat, lon: covered by NEWER and OLDER
NO_PLAN_IN_NACKA = (59.38, 18.05)    # inside the kommun, no plan
NEWER = square(18.15, 59.30, 18.17, 59.32)
OLDER = square(18.10, 59.28, 18.20, 59.35)
ELSEWHERE = square(18.30, 59.26, 18.35, 59.28)
OUTSIDE_NACKA = square(17.0, 59.0, 17.1, 59.1)

NACKA_FEATURES = [
    (NEWER, {"OBJECTID": 1, "aktbeteckning": "0182-P2015/3", "plannamn": "Kvarnholmen etapp 4",
             "lagakraft": "2015-06-01", "plantyp": "Detaljplan",
             "url": "http://infobank.nacka.se/ext/planer/kvarnholmen.pdf"}),
    (OLDER, {"OBJECTID": 2, "aktbeteckning": "0182-P1988/12", "plannamn": "Sicklaön", "lagakraft": "19880309",
             "plantyp": "Stadsplan", "url": "https://www.nacka.se/planer/sicklaon/"}),
    (ELSEWHERE, {"OBJECTID": 3, "aktbeteckning": None, "plannamn": "Utan akt", "lagakraft": None, "plantyp": None,
                 "url": None}),
]


def source(**fields) -> PlanSource:
    """The Nacka plan source, with `fields` overriding."""
    base = {"code": "0182", "name": "Nacka", "status": "A", "service": "arcgis",
            "url": "https://karta.nacka.se/arcgis/rest/services/Plan/MapServer/3", "layer": "Gällande detaljplaner",
            "akt_fields": ("aktbeteckning",), "url_fields": ("url",), "name_fields": ("plannamn",),
            "date_fields": ("lagakraft",), "type_fields": ("plantyp",), "survey_count": 3}
    return PlanSource(**(base | fields))


def fake_services(features=NACKA_FEATURES, *, fail_host: str | None = None, boundary=NACKA_BOUNDARY,
                  nominatim: list[dict] | None = None, paged: bool = True):
    """Nominatim (every kommun gets `boundary`, or the `nominatim` results), an ArcGIS layer and a WFS type, both
    serving `features`; a WFS that is not `paged` answers 400 to a request with startIndex."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "nominatim" in url:
            return httpx.Response(200, json=nominatim or [
                {"addresstype": "municipality", "name": request.url.params["q"], "geojson": boundary}])
        if fail_host and fail_host in url:
            return httpx.Response(500)
        if not paged and "startIndex" in request.url.params:
            return httpx.Response(400, text="Cannot do natural order without a primary key")
        if "/query" in url:
            if request.url.params.get("returnIdsOnly") == "true":
                return httpx.Response(200, json={"objectIds": [p["OBJECTID"] for _, p in features]})
            ids = {int(i) for i in request.url.params["objectIds"].split(",")}
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": p["OBJECTID"], "geometry": g, "properties": p}
                for g, p in features if p["OBJECTID"] in ids]})
        if "getfeature" in url.lower():
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": f"plan.{p['OBJECTID']}", "geometry": g, "properties": p}
                for g, p in features]})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def with_link(link, **extra):
    """The Nacka features with the newest plan's link replaced."""
    geometry, props = NACKA_FEATURES[0]
    return [(geometry, props | {"url": link} | extra)] + NACKA_FEATURES[1:]


def snapshot_plans(out_dir):
    return json.loads((out_dir / "0182" / "plans.geojson").read_text(encoding="utf-8"))["features"]


def plan_block(out_dir, ref):
    return next(f["properties"][PLAN_KEY] for f in snapshot_plans(out_dir) if f["properties"]["aktbeteckning"] == ref)


def nacka_store(tmp_path, features=NACKA_FEATURES) -> PlaceStore:
    """A store with the fake Uppsala snapshot and Nacka's plan layer fetched from the fake services."""
    write_snapshot(tmp_path)
    fetch_plan_layer(source(), client=fake_services(features), out_dir=tmp_path)
    return PlaceStore(tmp_path)
