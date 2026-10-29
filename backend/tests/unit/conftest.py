"""Shared fixtures for backend unit tests."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
import schemas
from routers import auth

# In-memory SQLite stands in for Postgres (PCR-0011). Only tables without pgvector columns work here.
AUTH_TABLES = (models.User, models.Account, models.Session, models.ChatSession, models.ChatMessage)


@pytest.fixture(autouse=True)
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-signing-key-at-least-32-bytes")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine, tables=[model.__table__ for model in AUTH_TABLES])
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def signup_request():
    return schemas.SignUpRequest(name="Test User", email="test@example.com", password="test-password")


@pytest.fixture
def token(db, signup_request):
    """Access token of a freshly signed-up user."""
    return auth.signup(signup_request, db).access_token
