"""Acceptance tests for #37: ask about the pinned place in the chat. Temporary, folded into tests/unit/ by
refactor-issue. A temporary SQLite database, a fake agent and a fake place profile: no network (PCR-0011)."""

import json
import os
import time
import types

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.pop("ACCESS_GATE_PASSWORD", None)
os.environ.pop("DEV_ACCESS_PASSWORD", None)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_as_json(element, compiler, **kw):
    return "JSON"


import agentic.service  # noqa: E402
import models  # noqa: E402
from db.database import get_db  # noqa: E402
from dependencies import get_current_user  # noqa: E402
from place.context import NO_PIN_HINT, compact_profile, place_context  # noqa: E402
from place.profile import build_profile  # noqa: E402
from routers import chat  # noqa: E402
from tests.unit.place.snapshot import PIN, fake_property, registry, remains_at, write_national_snapshot  # noqa: E402

QUESTION = "What can I build here?"


@pytest.fixture
def profile_of(tmp_path):
    """The place profile of the fake Kungsängen 7:8 (national layers and remains included)."""
    store = write_national_snapshot(tmp_path)

    def build(lat, lon):
        return build_profile(lat, lon, store=store, property_at=fake_property, plan_registry=registry,
                             ancient_remains_at=remains_at)
    return build


@pytest.fixture
def harness(monkeypatch, profile_of):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.ChatSession.__table__,
                                                    models.ChatMessage.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(models.User(id="u1", name="Test", email="test@example.com"))
        db.commit()
    asked = []

    def fake_stream_agent(question, history, record, sse, flush=lambda: []):
        asked.append(question)
        yield sse({"type": "response.output_text.delta", "delta": "An answer."})
        return {"answer": "An answer.", "law_rows": [], "local_rows": [], "sources": [], "citations": [], "run": None}

    monkeypatch.setattr(chat, "SessionLocal", Session)
    monkeypatch.setattr(chat, "get_openai_client", lambda: object())
    monkeypatch.setattr(chat, "agent_enabled", lambda: True)
    monkeypatch.setattr(agentic.service, "stream_agent", fake_stream_agent)

    app = FastAPI()
    app.include_router(chat.router, prefix="/api")

    def db_override():
        db = Session()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(id="u1")
    app.dependency_overrides[chat.get_place_profile] = lambda: profile_of
    return types.SimpleNamespace(client=TestClient(app), Session=Session, asked=asked)


def ask(harness, place=None):
    body = {"messages": [{"role": "user", "content": QUESTION}]}
    if place:
        body["place"] = place
    response = harness.client.post("/api/chat/stream", json=body)
    response.read()
    return response


def saved_answer(harness, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with harness.Session() as db:
            message = db.query(models.ChatMessage).filter(models.ChatMessage.role == "assistant").one()
            if message.status != "streaming":
                return message
        time.sleep(0.1)
    raise AssertionError("the answer was not saved")


PINNED = {"lat": PIN[0], "lon": PIN[1], "label": "Uppsala Kungsängen 7:8"}


# --- the agent gets the place ----------------------------------------------------------------------------------

def test_a_pinned_question_gives_the_agent_the_place_profile(harness):
    """With a pin, the agent's question carries the property, its plans, protections and permits."""
    ask(harness, PINNED)
    [question] = harness.asked
    for fact in ("Uppsala Kungsängen 7:8", "0380-P2002/5", "BCK", "Kungsängsängen", "Fyrisån", "Uppsala 123:1",
                 "Bygglov"):
        assert fact in question


def test_the_question_itself_comes_after_the_place(harness):
    """The user's own question follows the place block, unchanged."""
    ask(harness, PINNED)
    [question] = harness.asked
    assert question.rstrip().endswith(QUESTION)
    assert question.index("Uppsala Kungsängen 7:8") < question.index(QUESTION)


def test_a_question_without_pin_gets_the_pin_hint(harness):
    """Without a pin the question goes as today, with the hint to suggest pinning when the place is unclear."""
    ask(harness)
    [question] = harness.asked
    assert QUESTION in question
    assert NO_PIN_HINT in question
    assert "Kungsängen" not in question


def test_a_bad_pin_is_rejected(harness):
    """A pin that is not a coordinate is a 422."""
    assert ask(harness, {"lat": 123, "lon": 17.6}).status_code == 422


# --- the answer keeps the place --------------------------------------------------------------------------------

def test_the_answer_records_the_place_it_was_asked_about(harness):
    """The saved answer's trace holds the pin it was asked about."""
    ask(harness, PINNED)
    trace = saved_answer(harness).trace
    [event] = [e for e in trace if e["stage"] == "place"]
    assert event["data"]["pin"] == PINNED
    assert event["data"]["profile"]["property"]["designation"] == "Uppsala Kungsängen 7:8"


def test_the_recorded_profile_has_no_geometry(harness):
    """The place in the trace is kept small: no geometry anywhere in it."""
    ask(harness, PINNED)
    [event] = [e for e in saved_answer(harness).trace if e["stage"] == "place"]
    assert '"geometry"' not in json.dumps(event["data"]["profile"])


def test_an_answer_without_pin_records_no_place(harness):
    """Without a pin there is no place event."""
    ask(harness)
    assert not [e for e in saved_answer(harness).trace if e["stage"] == "place"]


# --- the place as text -----------------------------------------------------------------------------------------

def test_the_place_context_says_this_is_the_place_of_the_question(profile_of):
    """The agent is told the pin is the place the question is about, so it does not ask where."""
    text = place_context(profile_of(*PIN)).lower()
    assert "pinned" in text
    assert "do not ask where" in text


def test_the_place_context_asks_to_check_a_different_place(profile_of):
    """The agent is told to ask which place is meant when the question names another one."""
    assert "names a different place" in place_context(profile_of(*PIN)).lower()


def test_the_place_context_lists_the_card(profile_of):
    """The place block lists the detaljplan status, zones, plans in progress, strandskydd and permits."""
    text = place_context(profile_of(*PIN))
    for fact in ("inside a detaljplan", "BCK", "Kungsängen 7:8 m.fl.", "strandskyddsdispens", "MB 7 kap. 7 §",
                 "Registry data, not a decision"):
        assert fact.lower() in text.lower()


def test_the_place_context_of_an_uncovered_place_says_so(profile_of):
    """Outside the pilot kommuner the block says the map does not cover the place."""
    assert "not cover" in place_context(profile_of(57.70, 11.97)).lower()


def test_the_compact_profile_keeps_everything_but_geometry(profile_of):
    """The compact profile has the same rows, without geometry."""
    profile = profile_of(*PIN)
    compact = compact_profile(profile)
    assert [row["ref"] for row in compact["plans"]] == [row["ref"] for row in profile["plans"]]
    assert "geometry" not in compact["property"]
    assert all("geometry" not in row for row in compact["zones"] + compact["ancient_remains"])
