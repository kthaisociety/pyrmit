"""GET /api/place/profile and /api/place/coverage with the fake snapshot and a stand-in user."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from routers import place as place_router
from tests.unit.place.snapshot import FETCHED, PIN, fake_property, registry


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
