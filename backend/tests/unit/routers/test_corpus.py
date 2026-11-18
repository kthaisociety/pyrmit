"""Unit tests for routers.corpus (issue #114): only owners act on the corpus, developers read its status."""
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import corpus_admin
import models
from db.database import get_db
from dependencies import get_current_user
from routers import corpus

DUMP = b"PGDMP" + bytes(range(200))
MANIFEST = {"format": "pyrmit-corpus-dump", "version": 1, "schema": "corpus_next", "model": "st-bge-m3", "dim": 1024,
            "chunks": 10, "kommuner": [], "label_schema_version": 1, "built": "2026-11-14", "database_mb": 1.0,
            "dump_file": "x.dump", "dump_bytes": len(DUMP), "sha256": hashlib.sha256(DUMP).hexdigest()}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CORPUS_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CORPUS_UPLOAD_PART_MB", str(64 / (1 << 20)))  # 64-byte parts
    monkeypatch.setattr(corpus_admin, "status", lambda db: {"active": None, "history": []})

    def make(role):
        app = FastAPI()
        app.include_router(corpus.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: models.User(id=role, email=f"{role}@kth.se", role=role)
        return TestClient(app)

    return make


OWNER_ROUTES = [
    ("post", "/api/corpus/uploads", {"file_name": "x.dump", "size": len(DUMP), "manifest": MANIFEST}),
    ("get", "/api/corpus/uploads/" + "0" * 32, None),
    ("put", "/api/corpus/uploads/" + "0" * 32 + "?offset=0", None),
    ("delete", "/api/corpus/uploads/" + "0" * 32, None),
    ("post", "/api/corpus/uploads/" + "0" * 32 + "/restore", None),
    ("post", "/api/corpus/rollback", None),
    ("get", "/api/corpus/manifest", None),
    ("post", "/api/corpus/download-link", None),
]


@pytest.mark.parametrize("role", ["developer", "user"])
@pytest.mark.parametrize("method, path, body", OWNER_ROUTES)
def test_only_owners_act_on_the_corpus(client, role, method, path, body):
    response = getattr(client(role), method)(path, **({"json": body} if body else {}))
    assert response.status_code == 403


def test_developers_read_the_status_and_users_do_not(client):
    assert client("developer").get("/api/corpus").status_code == 200
    assert client("owner").get("/api/corpus").status_code == 200
    assert client("user").get("/api/corpus").status_code == 403


def test_an_owner_uploads_in_parts_over_http(client):
    owner = client("owner")
    state = owner.post("/api/corpus/uploads", json={"file_name": "x.dump", "size": len(DUMP), "manifest": MANIFEST}).json()
    assert state["part_bytes"] == 64 and state["received"] == 0
    while state["received"] < state["size"]:
        part = DUMP[state["received"]:state["received"] + state["part_bytes"]]
        state = owner.put(f"/api/corpus/uploads/{state['id']}?offset={state['received']}", content=part).json()
    assert state["complete"]
    assert owner.put(f"/api/corpus/uploads/{state['id']}?offset=0", content=b"x" * 65).status_code == 413
    assert owner.get(f"/api/corpus/uploads/{state['id']}").json()["received"] == len(DUMP)


def test_a_bad_manifest_is_a_400(client):
    response = client("owner").post("/api/corpus/uploads",
                                    json={"file_name": "x.dump", "size": len(DUMP), "manifest": {**MANIFEST, "schema": "corpus"}})
    assert response.status_code == 400 and "--from-schema corpus" in response.json()["detail"]


def test_the_download_needs_its_link(client):
    plain = client("owner")
    assert plain.get("/api/corpus/download").status_code == 422
    assert plain.get("/api/corpus/download?token=nonsense").status_code == 401
    link = plain.post("/api/corpus/download-link").json()
    assert link["url"].startswith("/api/corpus/download?token=") and link["expires_minutes"] == 5
