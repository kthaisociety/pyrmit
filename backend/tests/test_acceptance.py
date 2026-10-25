"""Acceptance tests for #35: pin a place in Uppsala and see its property and plans. Temporary, folded into
tests/unit/ by refactor-issue. No real services: snapshots are written to a temp folder, the property service and
the corpus registry are fakes (PCR-0011)."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from place.fetch import fetch_kommun
from place.live import PlaceSourceUnavailable
from place.profile import NOT_A_DECISION, build_profile
from place.store import PlaceStore
from routers import place as place_router

FETCHED = "2026-10-25"
PROPERTY = [[17.640, 59.850], [17.642, 59.850], [17.642, 59.851], [17.640, 59.851], [17.640, 59.850]]
PIN = (59.8505, 17.641)          # lat, lon inside PROPERTY
STREET = (59.8530, 17.641)       # inside the kommun, no property there
EMPTY_LOT = (59.8800, 17.680)    # a property with no plan
OUTSIDE = (57.70, 11.97)         # Göteborg


def square(west, south, east, north):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north],
                                                [west, south]]]}


def collection(*features):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": g, "properties": p}
                                                       for g, p in features]}


def plan(ref, name, laga_kraft, url_ref=None):
    return {"Plannamn": name, "Aktbeteckning": ref, "LagaKraftDatum": laga_kraft, "Plantyp": "DP",
            "UrlDokument": f"https://www.uppsala.se/detaljplan/?aktbeteckning={url_ref or ref}",
            "Kommentar": "Tolkad, kan finnas osäkra gränser"}


LAYERS = {
    "plans": collection(
        (square(17.635, 59.845, 17.650, 59.855), plan("0380-P1990/3", "Stadsplan för Kungsängen", "19900312")),
        (square(17.6405, 59.8495, 17.6430, 59.8515), plan("0380-P2002/5", "Del av Atle, Kungsängen 7:8", "20020109")),
        # a neighbour that only touches the property's east edge
        (square(17.64199, 59.850, 17.660, 59.851), plan("0380-P2010/1", "Grannplanen", "20100101")),
    ),
    "plan_additions": collection(
        (square(17.639, 59.849, 17.643, 59.852), plan("0380-P2012/9", "Tillägg till stadsplan för Kungsängen",
                                                      "20120601")),
    ),
    "area_regulations": collection(
        (square(17.639, 59.849, 17.6415, 59.852), {**plan("0380-O2005/1", "Områdesbestämmelser Kungsängen",
                                                          "20050101"), "Plantyp": "OB"}),
    ),
    "plans_pending": collection(
        (square(17.638, 59.849, 17.645, 59.852), {"Name": "Kungsängen 7:8 m.fl.", "DiarieNummer": "PLA 2024-001",
                                                  "Status": "Samråd", "HUVUDSAKLIGT_SYFTE": "Bostäder"}),
    ),
    "zones_kvartersmark": collection(
        (square(17.640, 59.850, 17.6415, 59.851), {"AnvBeteckning": "BCK", "Anvandningstyp": "Kvarter",
                                                   "AnvBestammelse": "Bostäder, Centrumfunktion, Kontor",
                                                   "Kommentar": "Tolkad, kan finnas osäkra gränser"}),
        (square(17.6415, 59.850, 17.642, 59.851), {"AnvBeteckning": "P", "Anvandningstyp": "Kvarter",
                                                   "AnvBestammelse": "Parkering",
                                                   "Kommentar": "Tolkad, kan finnas osäkra gränser"}),
    ),
    "zones_allman_plats": collection(),
    "zones_vatten": collection(),
}


def write_snapshot(root, layers=LAYERS, complete=True, missing=()):
    folder = root / "0380"
    folder.mkdir(parents=True)
    (folder / "kommun.geojson").write_text(json.dumps({"type": "Feature", "geometry": square(17.5, 59.7, 17.9, 60.0),
                                                       "properties": {"code": "0380", "name": "Uppsala"}}))
    manifest = {"kommun": {"code": "0380", "name": "Uppsala", "fetched": FETCHED, "source": "OpenStreetMap",
                           "licence": "ODbL"}, "layers": {}}
    for layer_id, data in layers.items():
        manifest["layers"][layer_id] = {"title": layer_id, "provider": "Uppsala kommun", "licence": "open data",
                                        "count": len(data["features"]), "fetched": FETCHED,
                                        "complete": complete if layer_id == "plans" else False}
        if layer_id not in missing:
            (folder / f"{layer_id}.geojson").write_text(json.dumps(data))
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return PlaceStore(root)


def fake_property(code, lon, lat):
    if 17.640 <= lon <= 17.642 and 59.850 <= lat <= 59.851:
        return {"designation": "Uppsala Kungsängen 7:8", "source": "Uppsala kommun", "fetched": FETCHED,
                "geometry": {"type": "Polygon", "coordinates": [PROPERTY]}}
    if 17.679 <= lon <= 17.681 and 59.879 <= lat <= 59.881:
        return {"designation": "Uppsala Kåbo 1:1", "source": "Uppsala kommun", "fetched": FETCHED,
                "geometry": square(17.679, 59.879, 17.681, 59.881)}
    return None


def registry(code):
    return [{"plan_id": "f41489", "kommun_code": "0380", "name": "Del av Atle, Kungsängen 7:8 - Uppsala kommun",
             "plan_number": None, "provisions": [{"code": "e1", "text": "Största byggnadsarea 300 m²"}]},
            {"plan_id": "a00001", "kommun_code": "0380", "name": "Stadsplan för Kungsängen - Uppsala kommun",
             "plan_number": None, "provisions": []}]


@pytest.fixture
def store(tmp_path):
    return write_snapshot(tmp_path)


def profile(store, at=PIN, **kwargs):
    return build_profile(*at, store=store, property_at=kwargs.pop("property_at", fake_property),
                         plan_registry=kwargs.pop("plan_registry", registry), **kwargs)


# --- the property and its plans ---------------------------------------------------------------------------------

def test_names_the_property_at_the_pin(store):
    """A pin in Uppsala gives the property's designation and its boundary."""
    result = profile(store)
    assert result["property_status"] == "found"
    assert result["property"]["designation"] == "Uppsala Kungsängen 7:8"
    assert result["property"]["geometry"]["type"] == "Polygon"


def test_lists_plans_in_force_newest_first(store):
    """Plans in force covering the property come newest laga kraft date first."""
    refs = [p["ref"] for p in profile(store)["plans"] if p["kind"] == "plan"]
    assert refs == ["0380-P2002/5", "0380-P1990/3"]


def test_plan_rows_carry_name_date_and_document_link(store):
    """Each plan has its aktbeteckning, name, laga kraft date and a link to the plan documents."""
    atle = next(p for p in profile(store)["plans"] if p["ref"] == "0380-P2002/5")
    assert atle["name"] == "Del av Atle, Kungsängen 7:8"
    assert atle["date"] == "2002-01-09"
    assert atle["url"] == "https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5"


def test_lists_additions_and_area_regulations_with_the_plans(store):
    """Tillägg and områdesbestämmelser covering the property are listed with the plans."""
    kinds = {p["ref"]: p["kind"] for p in profile(store)["plans"]}
    assert kinds["0380-P2012/9"] == "plan_addition"
    assert kinds["0380-O2005/1"] == "area_regulations"


def test_lists_land_use_zones_with_code_and_wording(store):
    """Land-use zones on the property come with their code, wording and the interpreted-boundary caveat."""
    zones = {z["ref"]: z for z in profile(store)["zones"]}
    assert zones["BCK"]["name"] == "Bostäder, Centrumfunktion, Kontor"
    assert "Tolkad" in zones["BCK"]["note"]


def test_points_to_corpus_provisions_when_indexed(store):
    """A plan whose provisions the corpus holds points to that corpus plan."""
    atle = next(p for p in profile(store)["plans"] if p["ref"] == "0380-P2002/5")
    assert atle["corpus_plan_id"] == "f41489"
    assert atle["provisions_indexed"] is True


def test_says_provisions_not_indexed_otherwise(store):
    """A plan without provisions in the corpus is marked as not indexed."""
    old = next(p for p in profile(store)["plans"] if p["ref"] == "0380-P1990/3")
    assert old["provisions_indexed"] is False


def test_lists_pending_plans_separately(store):
    """Plans in progress are listed apart from the plans in force, with their stage."""
    result = profile(store)
    assert [p["name"] for p in result["pending_plans"]] == ["Kungsängen 7:8 m.fl."]
    assert result["pending_plans"][0]["status"] == "Samråd"
    assert all(p["kind"] != "plan_pending" for p in result["plans"])


def test_says_inside_detaljplan(store):
    """A property covered by a plan in force is inside a detaljplan."""
    assert profile(store)["detaljplan"] == "inside"


def test_says_outside_detaljplan_when_the_plan_layer_is_complete(store):
    """No plan found and a complete plan layer means outside a detaljplan."""
    assert profile(store, at=EMPTY_LOT)["detaljplan"] == "outside"


def test_says_unknown_when_the_plan_layer_is_incomplete(tmp_path):
    """No plan found in an incomplete plan layer is not proof of being outside one."""
    store = write_snapshot(tmp_path, complete=False)
    assert profile(store, at=EMPTY_LOT)["detaljplan"] == "unknown"


def test_lists_every_plan_and_zone_the_property_spans(store):
    """A property spanning several zones gets each one, with the share of the property it covers."""
    shares = {z["ref"]: z["share"] for z in profile(store)["zones"]}
    assert set(shares) == {"BCK", "P"}
    assert shares["BCK"] == pytest.approx(0.75, abs=0.02)


def test_leaves_out_a_neighbour_that_only_touches_the_property(store):
    """A plan touching the property's boundary is not listed."""
    assert "0380-P2010/1" not in [p["ref"] for p in profile(store)["plans"]]


def test_rows_carry_geometry_for_the_map(store):
    """Plans and zones carry their outline so the map can draw them."""
    result = profile(store)
    assert all(row["geometry"]["type"] in ("Polygon", "MultiPolygon") for row in result["plans"] + result["zones"])


# --- no property, not covered, failures -------------------------------------------------------------------------

def test_reports_no_property_on_a_street(store):
    """A pin with no property at it says so."""
    result = profile(store, at=STREET)
    assert result["property"] is None
    assert result["property_status"] == "none"


def test_reports_property_service_failure(store):
    """A failing property service is reported as unavailable, not as no property."""
    def broken(code, lon, lat):
        raise PlaceSourceUnavailable("timeout")
    result = profile(store, property_at=broken)
    assert result["property_status"] == "unavailable"


def test_reports_a_place_outside_the_pilot_kommuner(store):
    """A pin outside the pilot kommuner is not covered."""
    result = profile(store, at=OUTSIDE)
    assert result["covered"] is False
    assert result["kommun"] is None
    assert result["property_status"] == "not_covered"
    assert result["plans"] == []


def test_rejects_a_point_that_is_not_a_coordinate(store):
    """A latitude outside -90..90 is an error."""
    with pytest.raises(ValueError):
        profile(store, at=(123.0, 17.6))


# --- sources ---------------------------------------------------------------------------------------------------

def test_every_row_names_its_source_and_date(store):
    """Plans, zones and pending plans each name their source and snapshot date."""
    result = profile(store)
    for row in result["plans"] + result["zones"] + result["pending_plans"]:
        assert row["source"] == "Uppsala kommun"
        assert row["fetched"] == FETCHED


def test_says_registry_data_not_a_decision(store):
    """The first note says the card is registry data, not a decision."""
    assert profile(store)["notes"][0] == NOT_A_DECISION


def test_lists_the_layers_consulted_with_their_status(tmp_path):
    """A layer without its snapshot file is reported as unavailable."""
    store = write_snapshot(tmp_path, missing=("plans_pending",))
    status = {layer["id"]: layer["status"] for layer in profile(store)["layers"]}
    assert status["plans"] == "ok"
    assert status["plans_pending"] == "unavailable"


# --- the API ---------------------------------------------------------------------------------------------------

@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[place_router.get_property_lookup] = lambda: fake_property
    app.dependency_overrides[place_router.get_plan_registry] = lambda: registry
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    return TestClient(app)


def test_profile_endpoint_returns_the_profile(client):
    """GET /api/place/profile returns the profile of the point."""
    response = client.get("/api/place/profile", params={"lat": PIN[0], "lon": PIN[1]})
    assert response.status_code == 200
    assert response.json()["property"]["designation"] == "Uppsala Kungsängen 7:8"


def test_profile_endpoint_rejects_bad_coordinates(client):
    """A latitude out of range is a 422."""
    assert client.get("/api/place/profile", params={"lat": 123, "lon": 17.6}).status_code == 422


def test_profile_endpoint_requires_sign_in(store):
    """Without a token the profile is not served."""
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    assert TestClient(app).get("/api/place/profile", params={"lat": PIN[0], "lon": PIN[1]}).status_code == 401


def test_coverage_endpoint_lists_pilot_kommuner(client):
    """GET /api/place/coverage lists Uppsala with its bounding box and snapshot date."""
    [uppsala] = client.get("/api/place/coverage").json()
    assert uppsala["code"] == "0380"
    assert uppsala["bbox"] == pytest.approx([17.5, 59.7, 17.9, 60.0])
    assert uppsala["fetched"] == FETCHED


# --- the snapshot command --------------------------------------------------------------------------------------

def fake_services(fail_layer: str | None = None):
    """Nominatim, ArcGIS MapServer and WFS answers for fetch_kommun."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "nominatim" in url:
            return httpx.Response(200, json=[{"addresstype": "municipality",
                                              "geojson": square(17.5, 59.7, 17.9, 60.0)}])
        if "/query" in url:
            layer_id = request.url.path.rstrip("/").split("/")[-2]
            if fail_layer and layer_id == fail_layer:
                return httpx.Response(500)
            if request.url.params.get("returnIdsOnly") == "true":
                return httpx.Response(200, json={"objectIds": [1, 2]})
            inside = {"type": "Feature", "geometry": square(17.6, 59.8, 17.61, 59.81),
                      "properties": {"OBJECTID": 1, "Plannamn": "Inne"}}
            outside = {"type": "Feature", "geometry": square(11.9, 57.6, 11.95, 57.65),
                       "properties": {"OBJECTID": 2, "Plannamn": "Ute"}}
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [inside, outside]})
        if "wfs" in url:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_writes_a_dated_snapshot(tmp_path):
    """The snapshot command writes the boundary, each layer and a manifest with the fetch date."""
    manifest = fetch_kommun("0380", client=fake_services(), out_dir=tmp_path)
    folder = tmp_path / "0380"
    assert (folder / "kommun.geojson").exists()
    assert (folder / "plans.geojson").exists()
    assert manifest["layers"]["plans"]["fetched"]
    assert manifest["layers"]["plans"]["complete"] is True
    assert json.loads((folder / "manifest.json").read_text())["kommun"]["code"] == "0380"


def test_fetch_keeps_only_national_features_inside_the_kommun(tmp_path):
    """National layers keep only the features that meet the kommun boundary."""
    fetch_kommun("0380", client=fake_services(), out_dir=tmp_path)
    names = [f["properties"].get("Plannamn") for f in
             json.loads((tmp_path / "0380" / "riks_naturvard.geojson").read_text())["features"]]
    assert names == ["Inne"]


def test_fetch_keeps_the_previous_snapshot_of_a_failing_layer(tmp_path):
    """A layer whose fetch fails keeps its earlier file and records the error."""
    fetch_kommun("0380", client=fake_services(), out_dir=tmp_path)
    before = (tmp_path / "0380" / "plans.geojson").read_text()
    manifest = fetch_kommun("0380", only={"plans"}, client=fake_services(fail_layer="122"), out_dir=tmp_path)
    assert (tmp_path / "0380" / "plans.geojson").read_text() == before
    assert "last_error" in manifest["layers"]["plans"]


def test_fetch_refuses_a_kommun_that_is_not_a_pilot(tmp_path):
    """Only pilot kommuner can be fetched."""
    with pytest.raises(KeyError):
        fetch_kommun("0115", client=fake_services(), out_dir=tmp_path)
