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
