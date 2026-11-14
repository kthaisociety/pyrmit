"""Unit tests for routers.benchmark."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import models
from dependencies import get_current_user
from routers import benchmark


def test_plain_users_cannot_start_a_run_that_spends_credits():
    """Issue #112: running a case calls the agent and the judge, so only developers and owners may."""
    app = FastAPI()
    app.include_router(benchmark.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: models.User(id="u", email="u@kth.se", role="user")
    response = TestClient(app).post("/api/benchmark/run", json={"set": "cases", "id": "x"})
    assert response.status_code == 403
    assert benchmark.JOBS == {}


def test_the_summary_route_serves_the_studies_to_staff_only(monkeypatch):
    import agentic.bench_summary

    monkeypatch.setattr(agentic.bench_summary, "summary", lambda: {"studies": [{"key": "rag-vs-agent"}]})
    app = FastAPI()
    app.include_router(benchmark.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: models.User(id="d", email="d@kth.se", role="developer")
    assert TestClient(app).get("/api/benchmark/summary").json() == {"studies": [{"key": "rag-vs-agent"}]}
    app.dependency_overrides[get_current_user] = lambda: models.User(id="u", email="u@kth.se", role="user")
    assert TestClient(app).get("/api/benchmark/summary").status_code == 403
