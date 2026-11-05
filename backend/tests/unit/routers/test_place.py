"""GET /api/place/profile and /api/place/coverage with the fake snapshot and a stand-in user."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from place.live import PlaceSourceUnavailable
from routers import place as place_router
from tests.unit.place.plan_layer import nacka_store, source
from tests.unit.place.snapshot import (
    FETCHED,
    PIN,
    fake_property,
    no_remains,
    registry,
    remains_at,
    write_national_snapshot,
)


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[place_router.get_property_lookup] = lambda: fake_property
    app.dependency_overrides[place_router.get_plan_registry] = lambda: registry
    app.dependency_overrides[place_router.get_ancient_remains_lookup] = lambda: no_remains
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


def test_coverage_endpoint_lists_every_kommun_with_a_snapshot(tmp_path):
    """GET /api/place/coverage names Nacka beside Uppsala once Nacka's plan layer has a snapshot."""
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    store = nacka_store(tmp_path)
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    assert [k["code"] for k in TestClient(app).get("/api/place/coverage").json()] == ["0182", "0380"]


# --- the constraints (#36) ---------------------------------------------------------------------------------------------------

def test_profile_endpoint_carries_the_new_sections(tmp_path):
    store = write_national_snapshot(tmp_path)
    """GET /api/place/profile returns the constraints and permits."""
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[place_router.get_property_lookup] = lambda: fake_property
    app.dependency_overrides[place_router.get_plan_registry] = lambda: registry
    app.dependency_overrides[place_router.get_ancient_remains_lookup] = lambda: remains_at
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    body = TestClient(app).get("/api/place/profile", params={"lat": PIN[0], "lon": PIN[1]}).json()
    assert body["protected_areas"][0]["name"] == "Kungsängsängen"
    assert any("Bygglov" in p["title"] for p in body["permits"])


# --- the address search (#38) ---------------------------------------------------------------------------------------------------

def client_with(search):
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_search] = lambda: search
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    return TestClient(app)


def test_search_endpoint_returns_the_matches():
    """GET /api/place/search returns the matches of the query."""
    match = {"label": "Kungsgatan 47A, Uppsala", "lat": 59.8599, "lon": 17.641, "kind": "house",
             "kommun": "Uppsala kommun", "in_pilot": True}
    response = client_with(lambda q: [match]).get("/api/place/search", params={"q": "kungsgatan 47a"})
    assert response.status_code == 200
    assert response.json() == [match]


def test_search_endpoint_rejects_a_too_short_query():
    """A query under two characters is a 422."""
    assert client_with(lambda q: []).get("/api/place/search", params={"q": "k"}).status_code == 422


def test_search_endpoint_says_when_the_service_is_down():
    """Nominatim down is a 503 with a message."""
    def down(q):
        raise PlaceSourceUnavailable("Nominatim: 503")
    response = client_with(down).get("/api/place/search", params={"q": "kungsgatan"})
    assert response.status_code == 503
    assert "address search" in response.json()["detail"].lower()


# --- the review mode (#55) ------------------------------------------------------------------------------------------

KVARNHOLMEN_BOX = "18.14,59.29,18.18,59.33"
SWEDEN_BOX = "10.5,55,24.5,69.5"
VARMDO = source(code="0120", name="Värmdö", url="https://karta.varmdo.se/arcgis/rest/services/P/MapServer/1")


@pytest.fixture
def review_client(tmp_path):
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    store = nacka_store(tmp_path)
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[place_router.get_plan_sources] = lambda: {"0182": source(), "0120": VARMDO}
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    return TestClient(app)


def test_review_coverage_endpoint_serves_every_kommun(review_client):
    """GET /api/place/review/coverage is the coverage collection of the registry and the snapshots."""
    features = review_client.get("/api/place/review/coverage").json()["features"]
    assert [feature["properties"]["code"] for feature in features] == ["0120", "0182", "0380"]


def test_review_plans_endpoint_serves_the_polygons_in_the_box(review_client):
    """GET /api/place/review/plans?bbox=w,s,e,n is the plans in that view."""
    features = review_client.get("/api/place/review/plans", params={"bbox": KVARNHOLMEN_BOX}).json()["features"]
    assert [feature["properties"]["ref"] for feature in features] == ["0182-P2015/3", "0182-P1988/12"]


def test_review_plans_endpoint_says_whether_it_truncated(review_client):
    """The collection carries its truncated flag to the map."""
    assert review_client.get("/api/place/review/plans", params={"bbox": KVARNHOLMEN_BOX}).json()["truncated"] is False


def test_review_plans_endpoint_rejects_a_country_sized_box(review_client):
    """A box wider than place.review.MAX_SPAN is a 422."""
    assert review_client.get("/api/place/review/plans", params={"bbox": SWEDEN_BOX}).status_code == 422


def test_review_plans_endpoint_says_why_a_box_is_refused(review_client):
    """The 422 carries a message the map can show."""
    assert "wider than a kommun" in review_client.get("/api/place/review/plans", params={"bbox": SWEDEN_BOX}).json()["detail"]


@pytest.mark.parametrize("bbox", ["18,59,x", "18,59,18.4", "18,59,18.4,59.4,1"], ids=["word", "three", "five"])
def test_review_plans_endpoint_rejects_a_box_that_is_not_four_numbers(review_client, bbox):
    """A bbox that does not parse as four numbers is a 422."""
    assert review_client.get("/api/place/review/plans", params={"bbox": bbox}).status_code == 422


@pytest.mark.parametrize("path, params", [("coverage", {}), ("plans", {"bbox": KVARNHOLMEN_BOX})], ids=["coverage", "plans"])
def test_review_endpoints_require_sign_in(tmp_path, path, params):
    """Without a token neither review endpoint is served."""
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    store = nacka_store(tmp_path)
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    assert TestClient(app).get(f"/api/place/review/{path}", params=params).status_code == 401
