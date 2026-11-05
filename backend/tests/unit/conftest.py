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


# A few kommuner for the gazetteer (localrag.gazetteer), so no test reads data/corpus/municipalities.json, which only a
# machine with the corpus has (PCR-0011). Kårsta is a locality of both Vallentuna and Örebro, as in Wikidata.
FAKE_MUNICIPALITIES = [
    {"code": "0115", "name": "Vallentuna kommun", "short_name": "Vallentuna", "localities": ["Kårsta", "Lindholmen"]},
    {"code": "0180", "name": "Stockholms kommun", "short_name": "Stockholm", "localities": []},
    {"code": "0188", "name": "Norrtälje kommun", "short_name": "Norrtälje", "localities": ["Rimbo"]},
    {"code": "0380", "name": "Uppsala kommun", "short_name": "Uppsala", "localities": ["Storvreta"]},
    {"code": "0980", "name": "Gotlands kommun", "short_name": "Gotland", "localities": ["Visby"]},
    {"code": "1880", "name": "Örebro kommun", "short_name": "Örebro", "localities": ["Kårsta"]},
]


@pytest.fixture(autouse=True)
def fake_municipalities(tmp_path, monkeypatch):
    import json

    from localrag import gazetteer

    path = tmp_path / "municipalities.json"
    path.write_text(json.dumps(FAKE_MUNICIPALITIES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(gazetteer, "MUNICIPALITIES_PATH", path)
    gazetteer._patterns.cache_clear()
    gazetteer._names_by_code.cache_clear()
    yield
    gazetteer._patterns.cache_clear()
    gazetteer._names_by_code.cache_clear()
