"""Acceptance tests of #75: the place card's notes and permits in the page language, and the shared glossary."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dependencies import get_current_user
from glossary import GLOSSARY
from place.profile import build_profile
from routers import glossary as glossary_router
from routers import place as place_router
from tests.unit.place.snapshot import (
    EMPTY_LOT,
    PIN,
    fake_property,
    no_remains,
    registry,
    remains_at,
    write_national_snapshot,
)


@pytest.fixture
def store(tmp_path):
    return write_national_snapshot(tmp_path)


def profile(store, at=PIN, **kwargs):
    return build_profile(*at, store=store, property_at=fake_property, plan_registry=registry,
                         ancient_remains_at=remains_at, **kwargs)


def bygglov(result):
    return next(p for p in result["permits"] if p["key"] == "bygglov")


@pytest.fixture
def place_client(store):
    app = FastAPI()
    app.include_router(place_router.router, prefix="/api")
    app.dependency_overrides[place_router.get_place_store] = lambda: store
    app.dependency_overrides[place_router.get_property_lookup] = lambda: fake_property
    app.dependency_overrides[place_router.get_plan_registry] = lambda: registry
    app.dependency_overrides[place_router.get_ancient_remains_lookup] = lambda: no_remains
    app.dependency_overrides[place_router.get_corpus_documents] = lambda: lambda doc_ids: {}
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    return TestClient(app)


@pytest.fixture
def glossary_client():
    app = FastAPI()
    app.include_router(glossary_router.router, prefix="/api")
    return TestClient(app)


def test_profile_notes_are_in_swedish_when_asked(store):
    """With language "sv" every note of the profile is written in Swedish, not the English note."""
    english, swedish = profile(store)["notes"], profile(store, language="sv")["notes"]
    assert len(swedish) == len(english)
    assert all(sv != en for sv, en in zip(swedish, english))


def test_permit_reasons_are_in_swedish_when_asked(store):
    """With language "sv" every permit's reason is written in Swedish, not the English reason."""
    english, swedish = profile(store)["permits"], profile(store, language="sv")["permits"]
    assert [p["key"] for p in swedish] == [p["key"] for p in english]
    assert all(sv["reason"] != en["reason"] for sv, en in zip(swedish, english))


def test_swedish_permit_title_carries_no_english_explanation(store):
    """In Swedish the bygglov is titled "Bygglov", with no English explanation in parentheses."""
    assert bygglov(profile(store, language="sv"))["title"] == "Bygglov"


def test_english_permit_reason_explains_a_glossary_term_on_first_use(store):
    """In English a glossary term in a permit's reason keeps its Swedish form, followed by its explanation."""
    reason = bygglov(profile(store, at=EMPTY_LOT))["reason"]
    assert f"förhandsbesked ({GLOSSARY['förhandsbesked']})" in reason


def test_profile_endpoint_answers_in_the_asked_language(place_client):
    """GET /api/place/profile with language=sv returns the notes in Swedish, unlike the default English."""
    params = {"lat": PIN[0], "lon": PIN[1]}
    english = place_client.get("/api/place/profile", params=params).json()["notes"]
    swedish = place_client.get("/api/place/profile", params=params | {"language": "sv"}).json()["notes"]
    assert swedish[0] != english[0]


def test_glossary_endpoint_returns_the_glossary(glossary_client):
    """GET /api/glossary returns every glossary term with its English explanation."""
    assert glossary_client.get("/api/glossary").json() == GLOSSARY


def test_glossary_endpoint_needs_no_sign_in(glossary_client):
    """GET /api/glossary answers 200 without a bearer token."""
    assert glossary_client.get("/api/glossary").status_code == 200
