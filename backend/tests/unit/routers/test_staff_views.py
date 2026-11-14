"""Issue #112: the Benchmark, Pipeline and Database views are for owners and developers, on the backend too."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import models
from db.database import get_db
from dependencies import get_current_user
from routers import benchmark, db_browser, pipeline

READ_ROUTES = [
    ("get", "/api/pipeline", None),
    ("get", "/api/db/sources", None),
    ("get", "/api/db/overview", None),
    ("get", "/api/db/chunks?table=law", None),
    ("get", "/api/db/documents?source=0115", None),
    ("post", "/api/db/search", {"query": "bygglov"}),
    ("get", "/api/benchmark/sets", None),
    ("get", "/api/benchmark/cases?set=cases", None),
    ("get", "/api/benchmark/case?set=cases&id=x", None),
    ("get", "/api/benchmark/image/x", None),
    ("post", "/api/benchmark/run", {"set": "cases", "id": "x"}),
    ("get", "/api/benchmark/run/x", None),
]


def client(role):
    app = FastAPI()
    for router in (pipeline.router, db_browser.router, benchmark.router):
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: models.User(id=role, email=f"{role}@kth.se", role=role)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method, path, body", READ_ROUTES)
def test_a_plain_user_gets_403_on_every_work_view_route(method, path, body):
    response = getattr(client("user"), method)(path, **({"json": body} if body else {}))
    assert response.status_code == 403


# Not the search (it embeds the query) nor the run (it calls the agent): no model call in a unit test (PCR-0011)
SAFE_ROUTES = [route for route in READ_ROUTES if route[1] not in ("/api/db/search", "/api/benchmark/run")]


@pytest.mark.parametrize("role", ["owner", "developer"])
@pytest.mark.parametrize("method, path, body", SAFE_ROUTES)
def test_owners_and_developers_get_past_the_role_check(role, method, path, body):
    # Past the check the route may still fail for want of data (no corpus, unknown case): anything but 401 / 403
    response = getattr(client(role), method)(path, **({"json": body} if body else {}))
    assert response.status_code not in (401, 403)
