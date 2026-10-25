"""GET /api/place/profile and /api/place/coverage with the fake snapshot and a stand-in user."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from place.live import PlaceSourceUnavailable
from routers import place as place_router
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
