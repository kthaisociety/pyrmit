"""GET /api/glossary: the shared glossary, served without sign-in."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from glossary import GLOSSARY
from routers import glossary as glossary_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(glossary_router.router, prefix="/api")
    return TestClient(app)


def test_glossary_endpoint_returns_the_glossary(client):
    """GET /api/glossary returns every glossary term with its English explanation."""
    assert client.get("/api/glossary").json() == GLOSSARY


def test_glossary_endpoint_needs_no_sign_in(client):
    """GET /api/glossary answers 200 without a bearer token."""
    assert client.get("/api/glossary").status_code == 200
