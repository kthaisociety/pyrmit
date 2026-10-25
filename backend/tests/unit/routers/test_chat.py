"""POST /api/chat/stream with a pinned place (#37): what the agent gets and what the answer keeps. A temporary
SQLite database, a fake agent and a fake place profile: no network (PCR-0011)."""

import json
import os
import time
import types

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.pop("ACCESS_GATE_PASSWORD", None)
os.environ.pop("DEV_ACCESS_PASSWORD", None)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb_as_json(element, compiler, **kw):
    return "JSON"


import agentic.service
import models
from db.database import get_db
from dependencies import get_current_user
from place.context import NO_PIN_HINT
from routers import chat
from tests.unit.place.snapshot import PIN

QUESTION = "What can I build here?"


@pytest.fixture
def harness(monkeypatch, profile_of):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.ChatSession.__table__,
                                                    models.ChatMessage.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(models.User(id="u1", name="Test", email="test@example.com"))
        db.commit()
    asked, choices = [], []

    def fake_stream_agent(question, history, record, sse, flush=list):
        asked.append(question)
        yield sse({"type": "response.output_text.delta", "delta": "An answer."})
        return {"answer": "An answer.", "law_rows": [], "local_rows": [], "sources": [], "citations": [],
                "choices": list(choices), "run": None}

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
    app.dependency_overrides[chat.get_law_text] = lambda: (
        lambda law, section: "[c:aa11bb22cc33dd44] Miljöbalk 7 kap. 7 §" if (law, section) == ("MB", "7 kap. 7 §") else None)
    return types.SimpleNamespace(client=TestClient(app), Session=Session, asked=asked, choices=choices)


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


def test_a_pinned_question_carries_the_statute_text_of_its_permits(harness):
    """The sections the permits cite come with the place, read from the corpus."""
    ask(harness, PINNED)
    [question] = harness.asked
    assert "[c:aa11bb22cc33dd44] Miljöbalk 7 kap. 7 §" in question


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


def test_a_question_with_options_records_them_for_the_buttons(harness):
    """When the agent asks the user to choose, the options are saved with the answer, for the chat's buttons."""
    harness.choices.extend(["The pinned Uppsala property", "A site in Södermalm"])
    ask(harness, PINNED)
    [event] = [e for e in saved_answer(harness).trace if e["stage"] == "choices"]
    assert event["data"]["options"] == ["The pinned Uppsala property", "A site in Södermalm"]


def test_an_ordinary_answer_records_no_options(harness):
    ask(harness, PINNED)
    assert not [e for e in saved_answer(harness).trace if e["stage"] == "choices"]
