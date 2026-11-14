"""Unit tests for routers.chunks."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import models
from dependencies import get_current_user
from routers import chunks


@pytest.mark.parametrize("path", ["/api/chunks/ingest-detaljplan", "/api/chunks/ingest-data-folder"])
def test_plain_users_cannot_ingest(path):
    """Ingesting writes the shared database and spends OCR credits: developers and owners only (issue #112)."""
    app = FastAPI()
    app.include_router(chunks.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: models.User(id="u", email="u@kth.se", role="user")
    assert TestClient(app).post(path, json={"input_path": "x.pdf", "folder_path": "x"}).status_code == 403
