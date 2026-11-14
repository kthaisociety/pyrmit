"""Unit tests for routers.users (issue #112): owners list users and change their roles; nobody else can."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from db.database import get_db
from dependencies import get_current_user
from routers import users


@pytest.fixture
def make_client():
    """The users router over HTTP with three accounts (owner, developer, user), signed in as the one asked for. Its own
    engine: TestClient runs the routes in another thread, which the shared in-memory SQLite engine refuses."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        for role in ("owner", "developer", "user"):
            db.add(models.User(id=role, name=role.title(), email=f"{role}@kth.se", role=role))
        db.commit()

    def db_override():
        with Session() as db:
            yield db

    def make(signed_in_as):
        app = FastAPI()
        app.include_router(users.router, prefix="/api")
        app.dependency_overrides[get_db] = db_override

        def current_user():
            with Session() as db:
                return db.get(models.User, signed_in_as)

        app.dependency_overrides[get_current_user] = current_user
        return TestClient(app)

    yield make
    engine.dispose()


def test_an_owner_sees_every_user_with_their_role(make_client, monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "owner@kth.se")
    response = make_client("owner").get("/api/users")
    assert response.status_code == 200
    assert {row["id"]: (row["role"], row["from_owner_emails"]) for row in response.json()} == {
        "owner": ("owner", True), "developer": ("developer", False), "user": ("user", False)}


@pytest.mark.parametrize("signed_in_as", ["developer", "user"])
def test_only_owners_can_list_users_or_change_roles(make_client, signed_in_as):
    client = make_client(signed_in_as)
    assert client.get("/api/users").status_code == 403
    assert client.patch("/api/users/user/role", json={"role": "owner"}).status_code == 403
    assert client.patch(f"/api/users/{signed_in_as}/role", json={"role": "owner"}).status_code == 403


def test_an_owner_changes_a_role(make_client):
    client = make_client("owner")
    response = client.patch("/api/users/user/role", json={"role": "developer"})
    assert response.status_code == 200
    assert response.json()["role"] == "developer"
    assert {row["id"]: row["role"] for row in client.get("/api/users").json()}["user"] == "developer"


def test_the_last_owner_cannot_demote_themself(make_client):
    response = make_client("owner").patch("/api/users/owner/role", json={"role": "user"})
    assert response.status_code == 409
    assert "last owner" in response.json()["detail"]


def test_an_owner_can_step_down_once_there_is_another(make_client):
    client = make_client("owner")
    assert client.patch("/api/users/developer/role", json={"role": "owner"}).status_code == 200
    assert client.patch("/api/users/owner/role", json={"role": "developer"}).json()["role"] == "developer"


def test_an_unknown_role_or_user_is_refused(make_client):
    client = make_client("owner")
    assert client.patch("/api/users/user/role", json={"role": "admin"}).status_code == 422
    assert client.patch("/api/users/nobody/role", json={"role": "user"}).status_code == 404
