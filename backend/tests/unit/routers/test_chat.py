"""
POST /api/chat/stream. The streamed answer must survive the client leaving: the generation runs in a background worker
that saves the assistant message (partial, then final) whatever happens to the HTTP connection.

Runs against a temporary SQLite database with a fake, slow LLM: no network, no Neon.
"""

import json
import os
import threading
import time
import types
import unittest

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ["RETRIEVAL_BACKEND"] = "pgvector"
os.environ["CHAT_MODE"] = "rag"
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
from agentic.agent import AgentRun
from agentic.claim_check import ClaimCheck
from agents.base import BaseRAGAgent
from answer_language import LANGUAGE_RULE, REWRITE_LANGUAGE_INSTRUCTION
from db.database import get_db
from dependencies import get_current_user
from place.context import NO_PIN_HINT
from routers import chat
from tests.unit.agentic.claims import (
    FEE,
    FEE_UNSUPPORTED,
    HOUSE,
    HOUSE_SUPPORTED,
    RAW,
    A,
    B,
    C,
    get_chunk,
)
from tests.unit.place.snapshot import PIN

ANSWER_PARTS = [f"part{i} " for i in range(12)]


def fake_completion(client, **kwargs):
    if kwargs.get("stream"):
        def events():
            for part in ANSWER_PARTS:
                time.sleep(0.25)  # slow model: the client leaves in the middle
                yield types.SimpleNamespace(type="response.output_text.delta", delta=part)
            yield types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage=None))
        return events()
    return types.SimpleNamespace(output_text="What is the building permit process?", usage=None)


class BackgroundAnswerTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        tables = [models.User.__table__, models.ChatSession.__table__, models.ChatMessage.__table__]
        models.Base.metadata.create_all(engine, tables=tables)
        self.Session = sessionmaker(bind=engine)
        with self.Session() as db:
            db.add(models.User(id="u1", name="Test", email="test@example.com"))
            db.commit()

        self.patches = [
            (chat, "SessionLocal", self.Session),
            (chat, "create_chat_completion", fake_completion),
            (chat, "recorded_chat_completion", lambda recorder, client, **kw: fake_completion(client, **kw)),
            (chat, "get_openai_client", lambda: object()),
            (BaseRAGAgent, "_embed", lambda self, text: [0.0]),
            (BaseRAGAgent, "_retrieve_debug_rows_from_embedding",
             lambda self, embedding, k=5: [{"source": "PBL", "chunk_index": 0, "distance": 0.1,
                                            "content": "Det krävs bygglov för nybyggnad.", "preview": ""}]),
        ]
        self.originals = [(obj, name, getattr(obj, name)) for obj, name, _ in self.patches]
        for obj, name, value in self.patches:
            setattr(obj, name, value)

        app = FastAPI()
        app.include_router(chat.router, prefix="/api")

        def db_override():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = db_override
        app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(id="u1")
        self.client = TestClient(app)

    def tearDown(self):
        for obj, name, value in self.originals:
            setattr(obj, name, value)

    def assistant_message(self):
        with self.Session() as db:
            return db.query(models.ChatMessage).filter(models.ChatMessage.role == "assistant").one()

    def wait_until_done(self, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self.assistant_message()
            if message.status != "streaming":
                return message
            time.sleep(0.2)
        return self.assistant_message()

    def answer_after_disconnect(self):
        """Leave the stream in the middle of the answer, then wait for the saved message."""
        body = {"messages": [{"role": "user", "content": "Hur söker man bygglov?"}], "session_id": None}
        with self.client.stream("POST", "/api/chat/stream", json=body) as response:
            seen = 0
            for line in response.iter_lines():
                if line.startswith("data:") and "output_text.delta" in line:
                    seen += 1
                    if seen == 2:
                        break  # leave in the middle of the answer
        return self.wait_until_done()

    def test_answer_completes_when_client_disconnects(self):
        self.assertEqual(self.answer_after_disconnect().status, "done")

    def test_full_answer_saved_when_client_disconnects(self):
        message = self.answer_after_disconnect()
        self.assertEqual(message.content.split("\n\n---")[0], "".join(ANSWER_PARTS))

    def test_trace_saved_when_client_disconnects(self):
        stages = [event["stage"] for event in (self.answer_after_disconnect().trace or [])]
        self.assertIn("retrieval", stages)

    def full_stream_event_types(self):
        body = {"messages": [{"role": "user", "content": "Hur söker man bygglov?"}], "session_id": None}
        events = []
        with self.client.stream("POST", "/api/chat/stream", json=body) as response:
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:]))
        return [event["type"] for event in events]

    def test_full_stream_starts_with_the_session_id(self):
        self.assertEqual(self.full_stream_event_types()[0], "session_id")

    def test_full_stream_ends_with_done(self):
        self.assertIn("done", self.full_stream_event_types())

    def test_full_stream_saves_the_answer(self):
        self.full_stream_event_types()
        self.assertEqual(self.wait_until_done().status, "done")


if __name__ == "__main__":
    unittest.main()


# --- A pinned place (#37): what the agent gets and what the answer keeps ---

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
    asked, choices, allowed = [], [], []

    def fake_stream_agent(question, history, record, sse, flush=list, allow_ask=True):
        asked.append(question)
        allowed.append(allow_ask)
        yield sse({"type": "response.output_text.delta", "delta": "An answer."})
        return {"answer": "An answer.", "law_rows": [], "local_rows": [], "sources": [], "citations": [],
                "questions": [{"question": "Which place do you mean?", "options": list(choices)}] if choices else [],
                "run": None}

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
    return types.SimpleNamespace(client=TestClient(app), Session=Session, asked=asked, choices=choices, allowed=allowed)


def ask(harness, place=None, **extra):
    body = {"messages": [{"role": "user", "content": QUESTION}], **extra}
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

@pytest.mark.parametrize("fact", ["Uppsala Kungsängen 7:8", "0380-P2002/5", "BCK", "Kungsängsängen", "Fyrisån",
                                  "Uppsala 123:1", "Bygglov"])
def test_a_pinned_question_gives_the_agent_the_place_profile(harness, fact):
    """With a pin, the agent's question carries the property, its plans, protections and permits."""
    ask(harness, PINNED)
    [question] = harness.asked
    assert fact in question


def test_a_pinned_question_carries_the_statute_text_of_its_permits(harness):
    """The sections the permits cite come with the place, read from the corpus."""
    ask(harness, PINNED)
    [question] = harness.asked
    assert "[c:aa11bb22cc33dd44] Miljöbalk 7 kap. 7 §" in question


def test_the_question_itself_comes_last_unchanged(harness):
    """The user's own question ends the agent's question, unchanged."""
    ask(harness, PINNED)
    [question] = harness.asked
    assert question.rstrip().endswith(QUESTION)


def test_the_question_itself_comes_after_the_place(harness):
    ask(harness, PINNED)
    [question] = harness.asked
    assert question.index("Uppsala Kungsängen 7:8") < question.index(QUESTION)


def test_a_question_without_pin_is_sent_as_asked(harness):
    ask(harness)
    [question] = harness.asked
    assert QUESTION in question


def test_a_question_without_pin_gets_the_pin_hint(harness):
    """The hint to suggest pinning when the place is unclear."""
    ask(harness)
    [question] = harness.asked
    assert NO_PIN_HINT in question


def test_a_question_without_pin_gets_no_place(harness):
    ask(harness)
    [question] = harness.asked
    assert "Kungsängen" not in question


def test_a_bad_pin_is_rejected(harness):
    """A pin that is not a coordinate is a 422."""
    assert ask(harness, {"lat": 123, "lon": 17.6}).status_code == 422


# --- the answer keeps the place --------------------------------------------------------------------------------

def place_event(harness) -> dict:
    [event] = [e for e in saved_answer(harness).trace if e["stage"] == "place"]
    return event


def test_the_answer_records_the_pin_it_was_asked_about(harness):
    """The saved answer's trace holds the pin it was asked about."""
    ask(harness, PINNED)
    assert place_event(harness)["data"]["pin"] == PINNED


def test_the_answer_records_the_pinned_property(harness):
    ask(harness, PINNED)
    assert place_event(harness)["data"]["profile"]["property"]["designation"] == "Uppsala Kungsängen 7:8"


def test_the_recorded_profile_has_no_geometry(harness):
    """The place in the trace is kept small: no geometry anywhere in it."""
    ask(harness, PINNED)
    [event] = [e for e in saved_answer(harness).trace if e["stage"] == "place"]
    assert '"geometry"' not in json.dumps(event["data"]["profile"])


def test_an_answer_without_pin_records_no_place(harness):
    """Without a pin there is no place event."""
    ask(harness)
    assert not [e for e in saved_answer(harness).trace if e["stage"] == "place"]


def choices_event(harness) -> dict:
    harness.choices.extend(["The pinned Uppsala property", "A site in Södermalm"])
    ask(harness, PINNED)
    [event] = [e for e in saved_answer(harness).trace if e["stage"] == "choices"]
    return event


def test_a_question_with_options_records_them_for_the_buttons(harness):
    """When the agent asks the user to choose, the options are saved with the answer, for the chat's buttons."""
    assert choices_event(harness)["data"]["questions"][0]["options"] == ["The pinned Uppsala property",
                                                                         "A site in Södermalm"]


def test_a_question_with_options_offers_no_pin_unless_asked(harness):
    assert choices_event(harness)["data"]["offer_pin"] is False


def test_an_ordinary_answer_records_no_options(harness):
    ask(harness, PINNED)
    assert not [e for e in saved_answer(harness).trace if e["stage"] == "choices"]


# The agent's question card (#91): saved with its questions, never claim-checked

def card_harness(harness, monkeypatch, questions, offer_pin=False):
    checked = []

    def fake_stream_agent(question, history, record, sse, flush=list, allow_ask=True):
        yield sse({"type": "response.output_text.delta", "delta": "What will the building be used for?"})
        return {"answer": "What will the building be used for?", "law_rows": [], "local_rows": [], "sources": [],
                "citations": [], "questions": questions, "offer_pin": offer_pin, "run": AgentRun()}

    monkeypatch.setattr(agentic.service, "stream_agent", fake_stream_agent)
    monkeypatch.setattr(chat, "_check_claims", lambda run: checked.append(run) or ({"status": "checked"}, None))
    ask(harness, PINNED)
    return saved_answer(harness), checked


def card_event(message) -> dict:
    [event] = [e for e in message.trace if e["stage"] == "choices"]
    return event["data"]


def test_a_card_is_saved_with_its_questions(harness, monkeypatch):
    """The card's questions and options are saved with the answer, for the chat to show."""
    questions = [{"question": "What will the building be used for?", "options": ["A permanent home"]},
                 {"question": "Roughly how large will it be?", "options": []}]
    message, _ = card_harness(harness, monkeypatch, questions)
    assert card_event(message)["questions"] == questions


def test_an_open_question_is_saved_as_a_card(harness, monkeypatch):
    """A card with only open questions and no pin offer is still a card, not an answer."""
    message, _ = card_harness(harness, monkeypatch, [{"question": "Roughly how large will it be?", "options": []}])
    assert card_event(message)["questions"] == [{"question": "Roughly how large will it be?", "options": []}]


def test_a_card_records_its_pin_offer_beside_its_questions(harness, monkeypatch):
    """A card about the place keeps both its question and the button that opens the map."""
    message, _ = card_harness(harness, monkeypatch, [{"question": "Which plot?", "options": []}], offer_pin=True)
    assert card_event(message) == {"questions": [{"question": "Which plot?", "options": []}], "offer_pin": True}


def test_a_card_is_not_claim_checked(harness, monkeypatch):
    """A question back to the user makes no claims: its claims are not checked."""
    _, checked = card_harness(harness, monkeypatch, [{"question": "Roughly how large will it be?", "options": []}])
    assert checked == []


def test_an_answer_to_the_agents_question_is_marked(harness):
    ask(harness, PINNED, answer_to_question=True)
    assert "answer to your question" in harness.asked[0]


def test_an_answer_to_the_agents_question_cannot_ask_again(harness):
    ask(harness, PINNED, answer_to_question=True)
    assert harness.allowed == [False]


def test_an_ordinary_question_may_be_answered_with_a_question(harness):
    ask(harness, PINNED)
    assert harness.allowed == [True]


# --- the claim check of an agent answer -------------------------------------------------------------------------

@pytest.fixture
def checked_chat(monkeypatch):
    """The streamed chat in agent mode, with a fake agent that answers RAW having read A, B and C. The claim check
    runs for real: script its decision model with the `jev` fixture."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.ChatSession.__table__,
                                                    models.ChatMessage.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(models.User(id="u1", name="Test", email="test@example.com"))
        db.commit()
    state = types.SimpleNamespace(choices=[])

    def fake_stream_agent(question, history, record, sse, flush=list, allow_ask=True):
        numberer = agentic.service.CitationNumberer(get_chunk)
        shown = numberer.feed(RAW) + numberer.close()
        yield sse({"type": "response.output_text.delta", "delta": shown})
        run = types.SimpleNamespace(answer=RAW, seen_chunks=[A, B, C], choices=list(state.choices), offer_pin=False)
        return {"answer": shown, "law_rows": [], "local_rows": [], "sources": numberer.labels,
                "citations": numberer.citations(),
                "questions": [{"question": "Which kommun?", "options": list(state.choices)}] if state.choices else [],
                "offer_pin": False, "run": run}

    monkeypatch.setattr(chat, "SessionLocal", Session)
    monkeypatch.setattr(chat, "get_openai_client", lambda: object())
    monkeypatch.setattr(chat, "agent_enabled", lambda: True)
    monkeypatch.setattr(agentic.service, "stream_agent", fake_stream_agent)
    monkeypatch.setattr(agentic.service, "get_tools", lambda: types.SimpleNamespace(get_chunk=get_chunk))

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
    app.dependency_overrides[chat.get_place_profile] = lambda: None
    app.dependency_overrides[chat.get_law_text] = lambda: (lambda law, section: None)
    state.client, state.Session = TestClient(app), Session
    return state


def stream_events(checked_chat) -> list[dict]:
    """Ask a question; the SSE events of the answer."""
    response = checked_chat.client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": QUESTION}]})
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def assistant_message(checked_chat) -> models.ChatMessage:
    with checked_chat.Session() as db:
        return db.query(models.ChatMessage).filter(models.ChatMessage.role == "assistant").one()


def claim_events(message: models.ChatMessage) -> list[dict]:
    return [event["data"] for event in message.trace or [] if event["stage"] == "claim_check"]


def while_checking(checked_chat, jev) -> models.ChatMessage:
    """The saved answer while a slow decision model (3 s) checks its claims."""
    fake = jev(delay=3.0)
    asking = threading.Thread(target=stream_events, args=(checked_chat,))
    asking.start()
    try:
        deadline = time.time() + 10
        while not fake.calls and time.time() < deadline:
            time.sleep(0.05)
        assert fake.calls, "the answer was never checked"
        time.sleep(0.5)
        return assistant_message(checked_chat)
    finally:
        asking.join(10)


def test_the_agents_raw_answer_is_checked(checked_chat, jev):
    """The chat puts the claims of the agent's raw answer to the decision model."""
    fake = jev(supported={HOUSE: 0.9})
    stream_events(checked_chat)
    assert sorted(fake.claims_asked()) == sorted([HOUSE, FEE])


def test_the_stream_says_the_claims_are_being_checked(checked_chat, jev):
    """While the check runs, the stream shows that the claims are being checked."""
    jev(supported={HOUSE: 0.9})
    assert {"type": "thinking", "label": "Checking the claims"} in stream_events(checked_chat)


def test_the_citations_are_sent_before_the_claims_are_checked(checked_chat, jev):
    """The citation chips open their sources while the check runs: the citations come before it."""
    jev(supported={HOUSE: 0.9})
    order = [event.get("stage") or event.get("label") for event in stream_events(checked_chat)
             if event.get("stage") in ("citations", "claim_check") or event.get("label") == "Checking the claims"]
    assert order == ["citations", "Checking the claims", "claim_check"]


def test_the_answer_stays_streaming_until_the_check_is_done(checked_chat, jev):
    """An answer whose claims are still being checked is marked streaming."""
    assert while_checking(checked_chat, jev).status == "streaming"


def test_the_answer_is_saved_before_its_check_is_done(checked_chat, jev):
    """The streamed answer is saved while its claims are still being checked."""
    assert HOUSE in while_checking(checked_chat, jev).content


def test_the_verdicts_are_saved_with_the_answer(checked_chat, jev):
    """The check's verdicts and supporting sentences are saved in the answer's trace."""
    jev(supported={HOUSE: 0.9, FEE: 0.1})
    stream_events(checked_chat)
    assert claim_events(saved_answer(checked_chat)) == [{"status": "checked",
                                                         "claims": [HOUSE_SUPPORTED, FEE_UNSUPPORTED]}]


def test_a_failed_check_is_saved_with_the_answer(checked_chat, jev):
    """A check that could not run is saved as failed."""
    jev(error=RuntimeError("model down"))
    stream_events(checked_chat)
    assert claim_events(saved_answer(checked_chat)) == [{"status": "failed", "claims": []}]


def test_a_failed_check_keeps_the_answer(checked_chat, jev):
    """The answer of a check that could not run is saved as it streamed."""
    jev(error=RuntimeError("model down"))
    stream_events(checked_chat)
    assert saved_answer(checked_chat).content.startswith(f"{HOUSE} [1]. {FEE} [2].")


def test_a_flagged_answer_is_saved_as_it_streamed(checked_chat, jev):
    """The check flags but never rewrites: an answer with an unsupported claim is saved unchanged."""
    jev(supported={HOUSE: 0.9, FEE: 0.1})
    stream_events(checked_chat)
    assert saved_answer(checked_chat).content.startswith(f"{HOUSE} [1]. {FEE} [2].")


def test_the_check_sends_only_its_verdicts(checked_chat, jev):
    """After the answer has streamed, the check sends its verdicts and no replacement text."""
    jev(supported={HOUSE: 0.9, FEE: 0.1})
    sent = [event.get("stage", event["type"]) for event in stream_events(checked_chat)
            if event["type"] == "answer_replaced" or event.get("stage") == "claim_check"]
    assert sent == ["claim_check"]


def test_the_check_gets_the_pinned_place_data(monkeypatch):
    """The place data the agent was given is passed to the claim check as a source."""
    given = {}
    monkeypatch.setattr(agentic.service, "get_tools", lambda: types.SimpleNamespace(get_chunk=get_chunk))
    monkeypatch.setattr(chat, "check_claims", lambda answer, get, place=None: given.update(place=place)
                        or ClaimCheck(status="checked"))
    chat._check_claims(types.SimpleNamespace(answer=RAW, seen_chunks=[A]), "Property: Uppsala Kvarngärdet 27:2.")
    assert given["place"] == "Property: Uppsala Kvarngärdet 27:2."


def test_a_question_back_to_the_user_is_not_checked(checked_chat, jev):
    """Of a question back to the user and an answer, only the answer is checked."""
    fake = jev(supported={HOUSE: 0.9})
    checked_chat.choices.extend(["Ydre", "Linköping"])
    stream_events(checked_chat)
    checked_chat.choices.clear()
    stream_events(checked_chat)
    assert sorted(fake.claims_asked()) == sorted([HOUSE, FEE])


# --- the answer language (RAG mode) ----------------------------------------------------------------------------

SWEDISH_QUESTION = "Behöver jag bygglov för en friggebod på min tomt?"
ENGLISH_REWRITE = "Do I need a building permit for a small shed on my plot?"


@pytest.fixture
def rag(monkeypatch):
    """The chat in RAG mode on pgvector, with a fake model whose rewrite decides Swedish."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.ChatSession.__table__,
                                                    models.ChatMessage.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(models.User(id="u1", name="Test", email="test@example.com"))
        db.commit()
    state = types.SimpleNamespace(calls=[], rows=[{"source": "PBL", "chunk_index": 0, "distance": 0.1,
                                                   "content": "Det krävs bygglov för nybyggnad.", "preview": ""}])

    def completion(client, **kwargs):
        state.calls.append(kwargs)
        if kwargs.get("stream"):
            def events():
                yield types.SimpleNamespace(type="response.output_text.delta", delta="Ja.")
                yield types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage=None))
            return events()
        if "instructions" in kwargs:  # the answer of /api/chat
            return types.SimpleNamespace(output_text="Ja.", usage=None)
        return types.SimpleNamespace(output_text=f"{ENGLISH_REWRITE}\nLANG: sv", usage=None)

    monkeypatch.setattr(chat, "SessionLocal", Session)
    monkeypatch.setattr(chat, "create_chat_completion", completion)
    monkeypatch.setattr(chat, "recorded_chat_completion", lambda recorder, client, **kw: completion(client, **kw))
    monkeypatch.setattr(chat, "get_openai_client", lambda: object())
    monkeypatch.setattr(chat, "agent_enabled", lambda: False)
    monkeypatch.setattr(BaseRAGAgent, "_embed", lambda self, text: [0.0])
    monkeypatch.setattr(BaseRAGAgent, "_retrieve_debug_rows_from_embedding", lambda self, embedding, k=5: state.rows)

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
    state.client = TestClient(app)
    state.Session = Session
    return state


def stream_swedish(rag) -> str:
    body = {"messages": [{"role": "user", "content": SWEDISH_QUESTION}], "session_id": None}
    rag.client.post("/api/chat/stream", json=body).read()
    deadline = time.time() + 10
    while time.time() < deadline:
        with rag.Session() as db:
            message = db.query(models.ChatMessage).filter(models.ChatMessage.role == "assistant").one_or_none()
            if message is not None and message.status != "streaming":
                return message.content
        time.sleep(0.1)
    raise AssertionError("the answer was not saved")


def post_swedish(rag) -> str:
    body = {"messages": [{"role": "user", "content": SWEDISH_QUESTION}], "session_id": None}
    return rag.client.post("/api/chat", json=body).json()["content"]


def answer_call(rag) -> dict:
    return next(call for call in rag.calls if "instructions" in call)


def rewrite_call(rag) -> dict:
    return next(call for call in rag.calls if "instructions" not in call)


def test_the_streamed_answer_is_asked_the_users_own_words(rag):
    """The answer gets the question as written, not its English rewrite."""
    stream_swedish(rag)
    assert SWEDISH_QUESTION in answer_call(rag)["input"][-1]["content"]


def test_the_streamed_answer_follows_the_language_rule(rag):
    stream_swedish(rag)
    assert LANGUAGE_RULE and LANGUAGE_RULE in answer_call(rag)["instructions"]


def test_the_streamed_answer_is_not_told_to_answer_in_english(rag):
    stream_swedish(rag)
    assert "Answer in English" not in answer_call(rag)["instructions"]


def test_the_streamed_rewrite_asks_for_the_language(rag):
    stream_swedish(rag)
    assert REWRITE_LANGUAGE_INSTRUCTION and REWRITE_LANGUAGE_INSTRUCTION in rewrite_call(rag)["input"]


def test_the_streamed_clarifying_prompt_follows_a_swedish_decision(rag):
    """With nothing retrieved, a question decided Swedish gets the clarifying prompt in Swedish."""
    rag.rows = []
    assert "I need a bit more information" not in stream_swedish(rag)


def test_the_answer_is_asked_the_users_own_words(rag):
    post_swedish(rag)
    assert SWEDISH_QUESTION in answer_call(rag)["input"][-1]["content"]


def test_the_answer_follows_the_language_rule(rag):
    post_swedish(rag)
    assert LANGUAGE_RULE and LANGUAGE_RULE in answer_call(rag)["instructions"]


def test_the_rewrite_asks_for_the_language(rag):
    post_swedish(rag)
    assert REWRITE_LANGUAGE_INSTRUCTION and REWRITE_LANGUAGE_INSTRUCTION in rewrite_call(rag)["input"]


def test_the_clarifying_prompt_follows_a_swedish_decision(rag):
    rag.rows = []
    assert "I need a bit more information" not in post_swedish(rag)


def test_the_streamed_rewrite_starts_with_the_language_instruction(rag):
    """Asked for first, the LANG line is about the user's words, not the English rewrite."""
    stream_swedish(rag)
    assert rewrite_call(rag)["input"].startswith(REWRITE_LANGUAGE_INSTRUCTION)


def test_the_rewrite_starts_with_the_language_instruction(rag):
    post_swedish(rag)
    assert rewrite_call(rag)["input"].startswith(REWRITE_LANGUAGE_INSTRUCTION)


def test_the_answer_turn_repeats_the_language_rule(rag):
    """The answer's last turn says to answer in the user's language whatever the sources' language."""
    post_swedish(rag)
    assert "whatever the language of the sources" in answer_call(rag)["input"][-1]["content"]


# --- an off-topic answer (#102) ---------------------------------------------------------------------------------------

def test_an_off_topic_answer_is_not_claim_checked(harness, monkeypatch):
    """A short answer to an off-topic question cites nothing by design: the claim check would strip or flag it."""
    checked = []

    def fake_stream_agent(question, history, record, sse, flush=list, allow_ask=True):
        yield sse({"type": "response.output_text.delta", "delta": "Hej! Vad kan jag hjälpa dig med?"})
        return {"answer": "Hej! Vad kan jag hjälpa dig med?", "law_rows": [], "local_rows": [], "sources": [],
                "citations": [], "questions": [], "offer_pin": False, "run": AgentRun(mode="off_topic")}

    monkeypatch.setattr(agentic.service, "stream_agent", fake_stream_agent)
    monkeypatch.setattr(chat, "_check_claims", lambda run: checked.append(run) or ({"status": "checked"}, None))
    ask(harness, PINNED)
    assert checked == [] and saved_answer(harness).content.startswith("Hej!")
