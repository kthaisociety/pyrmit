"""
Acceptance tests of issue #82: every factual claim of a chat answer is checked live against its cited sources, and
what they don't back is rewritten once or flagged.

No real model or database (PCR-0011): the model is a scripted fake client, the chat runs on in-memory SQLite.
"""

import json
import os
import threading
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
import llm
import models
import observability
from agentic import claim_check
from agentic.claim_check import (
    Claim,
    ClaimCheck,
    Support,
    VerifiedAnswer,
    verify_answer,
)
from db.database import get_db
from dependencies import get_current_user
from routers import chat

A, B, C = "a" * 16, "b" * 16, "c" * 16
CHUNKS = {
    A: {"chunk_id": A, "kind": "law", "title": "PBL", "section": "9 kap. 4 §", "header": "PBL 9 kap. 4 §",
        "text": "Bygglov krävs för nybyggnad av en byggnad."},
    B: {"chunk_id": B, "kind": "local", "kommun": "Ydre", "title": "Bygglovstaxa", "header": "Ydre – Bygglovstaxa",
        "text": "Avgiften för bygglov tas ut enligt kommunens taxa."},
    # Read by the agent, not cited
    C: {"chunk_id": C, "kind": "local", "kommun": "Ydre", "title": "Avgifter", "header": "Ydre – Avgifter",
        "text": "Avgiften för bygglov för ett enbostadshus är 12 000 kr."},
}

HOUSE = "Bygglov is needed for a new house"
FEE = "The fee is 12 000 kr"
RAW = f"{HOUSE} [c:{A}]. {FEE} [c:{B}]."
REVISED = f"{HOUSE} [c:{A}]. {FEE} [c:{C}]."
SHORTENED = f"{HOUSE} [c:{A}]."

HOUSE_SUPPORTED = {"text": HOUSE, "verdict": "supported", "chunk_ids": [A],
                   "supporting": [{"chunk_id": A, "sentence": "Bygglov krävs för nybyggnad av en byggnad."}]}
FEE_UNSUPPORTED = {"text": FEE, "verdict": "unsupported", "chunk_ids": [B], "supporting": []}
FEE_UNCITED = {"text": FEE, "verdict": "uncited", "chunk_ids": [], "supporting": []}
FEE_SUPPORTED = {"text": FEE, "verdict": "supported", "chunk_ids": [C],
                 "supporting": [{"chunk_id": C, "sentence": "Avgiften för bygglov för ett enbostadshus är 12 000 kr."}]}


def judged(*claims: dict) -> str:
    """The judge's reply: JSON in the shape of the claims."""
    return json.dumps({"claims": list(claims)}, ensure_ascii=False)


def get_chunk(chunk_id: str) -> dict | None:
    return CHUNKS.get(chunk_id)


class FakeClient:
    """A Responses API client that answers with scripted replies, in order. A reply that is an exception is raised;
    a reply that is a float is a stalled call of that many seconds."""

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.responses = self
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else AssertionError("no more scripted replies")
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, float):
            time.sleep(reply)
            reply = judged()
        return types.SimpleNamespace(output_text=reply, output=[], usage=None,
                                     choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=reply))])

    def seen(self, call: int) -> str:
        """Everything sent to the model in one call, as text."""
        return json.dumps(self.calls[call], default=str, ensure_ascii=False)


@pytest.fixture
def model(monkeypatch):
    """Script the model: model(reply, ...) -> the fake client, whichever llm accessor the check uses."""
    def script(*replies) -> FakeClient:
        client = FakeClient(list(replies))
        for module in (llm, observability, claim_check):
            monkeypatch.setattr(module, "get_openai_client", lambda: client, raising=False)
        return client
    return script


def verify(answer: str = RAW, seen: tuple[str, ...] = (A, B, C), **kwargs) -> VerifiedAnswer:
    return verify_answer(answer, get_chunk, list(seen), **kwargs)


# --- the check ------------------------------------------------------------------------------------------------

def test_a_supported_answer_is_kept_as_it_is(model):
    """An answer whose claims are all supported comes back unchanged and checked."""
    model(judged(HOUSE_SUPPORTED))
    result = verify(SHORTENED)
    assert (result.answer, result.check.status) == (SHORTENED, "checked")


def test_a_supported_answer_is_not_rewritten(model):
    """When every claim is supported, the judge is the only model call."""
    client = model(judged(HOUSE_SUPPORTED))
    verify(SHORTENED)
    assert len(client.calls) == 1


def test_each_claim_gets_its_verdict_and_supporting_sentences(model):
    """A supported claim keeps its cited chunks and the sentences of them that back it."""
    model(judged(HOUSE_SUPPORTED))
    [claim] = verify(SHORTENED).check.claims
    assert claim == Claim(text=HOUSE, verdict="supported", chunk_ids=[A],
                          supporting=[Support(chunk_id=A, sentence="Bygglov krävs för nybyggnad av en byggnad.")])


def test_the_judge_reads_the_full_text_of_every_cited_source(model):
    """The judge is given the whole text of each chunk the answer cites."""
    client = model(judged(HOUSE_SUPPORTED, FEE_SUPPORTED | {"chunk_ids": [B]}))
    verify()
    assert CHUNKS[A]["text"] in client.seen(0) and CHUNKS[B]["text"] in client.seen(0)


def test_an_answer_without_claims_is_checked(model):
    """An answer the judge finds no factual claim in is checked, with no claims and no rewrite."""
    client = model(judged())
    result = verify("Feel free to ask the kommun.", seen=())
    assert (result.check.status, result.check.claims, len(client.calls)) == ("checked", [], 1)


def test_the_check_uses_the_claim_check_model(model, monkeypatch):
    """CLAIM_CHECK_MODEL picks the judge's model."""
    monkeypatch.setenv("CLAIM_CHECK_MODEL", "openai/claim-judge")
    client = model(judged(HOUSE_SUPPORTED))
    verify(SHORTENED)
    assert client.calls[0]["model"].endswith("claim-judge")


# --- one rewrite ----------------------------------------------------------------------------------------------

def test_an_unsupported_claim_is_rewritten(model):
    """An unsupported claim goes back once, and the rewritten answer is what the user gets."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    assert verify().answer == REVISED


def test_an_uncited_claim_is_rewritten(model):
    """A claim with no citation goes back for the rewrite like an unsupported one."""
    model(judged(HOUSE_SUPPORTED, FEE_UNCITED), SHORTENED, judged(HOUSE_SUPPORTED))
    assert verify(f"{HOUSE} [c:{A}]. {FEE}.").answer == SHORTENED


def test_the_rewrite_is_told_which_claims_to_fix(model):
    """The rewrite is given the claims the sources do not back."""
    client = model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    verify()
    assert FEE in client.seen(1)


def test_the_rewrite_reads_the_chunks_the_agent_read(model):
    """The rewrite may re-cite a chunk the agent read but did not cite."""
    client = model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    verify()
    assert CHUNKS[C]["text"] in client.seen(1)


def test_the_verdicts_are_those_of_the_rewritten_answer(model):
    """After a rewrite, the claims are judged again and those verdicts are kept."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, judged(HOUSE_SUPPORTED, FEE_SUPPORTED))
    assert [claim.verdict for claim in verify().check.claims] == ["supported", "supported"]


def test_a_claim_still_unsupported_after_the_rewrite_keeps_its_verdict(model):
    """A claim the rewrite did not fix stays in the answer as unsupported, to be flagged."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), RAW, judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED))
    claims = verify().check.claims
    assert [(claim.text, claim.verdict) for claim in claims] == [(HOUSE, "supported"), (FEE, "unsupported")]


def test_an_answer_is_rewritten_at_most_once(model):
    """Still-unsupported claims after the rewrite do not start a second one."""
    client = model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), RAW, judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED))
    verify()
    assert len(client.calls) == 3


# --- failures -------------------------------------------------------------------------------------------------

def test_a_model_error_keeps_the_answer(model):
    """When the judge fails, the answer stays as it was."""
    model(RuntimeError("model down"))
    assert verify().answer == RAW


def test_a_model_error_fails_the_check(model):
    """When the judge fails, the check is marked failed, with no claims."""
    model(RuntimeError("model down"))
    check = verify().check
    assert (check.status, check.claims) == ("failed", [])


def test_a_judge_reply_that_is_not_json_fails_the_check(model):
    """A judge reply that cannot be read is a failed check."""
    model("I think the answer is fine.")
    assert verify().check.status == "failed"


def test_a_check_over_its_time_fails(model):
    """A judge that stalls past the timeout gives a failed check, not a wait."""
    model(2.0)
    started = time.perf_counter()
    result = verify(timeout_s=0.3)
    assert (result.check.status, result.answer) == ("failed", RAW)
    assert time.perf_counter() - started < 1.5


def test_an_unreadable_cited_source_fails_the_check(model):
    """A cited chunk that cannot be read fails the check and keeps the answer."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED))
    result = verify_answer(f"{HOUSE} [c:{A}]. {FEE} [c:{'d' * 16}].", get_chunk, [A])
    assert (result.check.status, result.answer) == ("failed", f"{HOUSE} [c:{A}]. {FEE} [c:{'d' * 16}].")


def test_a_failed_rewrite_keeps_the_answer_and_its_first_verdicts(model):
    """When the rewrite fails, the answer stays and the first check's verdicts are kept, so it is flagged."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), RuntimeError("model down"))
    result = verify()
    assert result.answer == RAW
    assert (result.check.status, [c.verdict for c in result.check.claims]) == ("checked", ["supported", "unsupported"])


def test_a_failed_second_check_keeps_the_answer_and_its_first_verdicts(model):
    """When judging the rewritten answer fails, the original answer and its verdicts are kept."""
    model(judged(HOUSE_SUPPORTED, FEE_UNSUPPORTED), REVISED, RuntimeError("model down"))
    result = verify()
    assert result.answer == RAW
    assert (result.check.status, [c.verdict for c in result.check.claims]) == ("checked", ["supported", "unsupported"])


# --- the saved form -------------------------------------------------------------------------------------------

def test_a_check_is_saved_as_its_verdicts_and_supporting_sentences():
    """The check's trace data lists every claim with its verdict, chunks and supporting sentences."""
    check = ClaimCheck(status="checked", claims=[
        Claim(text=HOUSE, verdict="supported", chunk_ids=[A],
              supporting=[Support(chunk_id=A, sentence="Bygglov krävs för nybyggnad av en byggnad.")]),
        Claim(text=FEE, verdict="uncited"),
    ])
    assert check.as_event() == {"status": "checked", "claims": [HOUSE_SUPPORTED, FEE_UNCITED]}


def test_a_failed_check_is_saved_as_failed():
    """A failed check's trace data says so, with no claims."""
    assert ClaimCheck(status="failed").as_event() == {"status": "failed", "claims": []}


# --- the chat -------------------------------------------------------------------------------------------------

QUESTION = "Do I need bygglov for a house in Ydre, and what does it cost?"


@pytest.fixture
def harness(monkeypatch):
    """The streamed chat in agent mode, with a fake agent that answers RAW and a scriptable verify_answer."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.ChatSession.__table__,
                                                    models.ChatMessage.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(models.User(id="u1", name="Test", email="test@example.com"))
        db.commit()
    state = types.SimpleNamespace(choices=[], verified=None, checked=[], release=None, entered=threading.Event())

    def fake_stream_agent(question, history, record, sse, flush=list, allow_ask=True):
        numberer = agentic.service.CitationNumberer(get_chunk)
        shown = numberer.feed(RAW) + numberer.close()
        yield sse({"type": "response.output_text.delta", "delta": shown})
        run = types.SimpleNamespace(answer=RAW, seen_chunks=[A, B, C], choices=list(state.choices), offer_pin=False)
        return {"answer": shown, "law_rows": [], "local_rows": [], "sources": numberer.labels,
                "citations": numberer.citations(), "choices": list(state.choices), "offer_pin": False, "run": run}

    def fake_verify_answer(answer, get_chunk_, seen_chunk_ids, timeout_s=None):
        state.checked.append((answer, list(seen_chunk_ids)))
        state.entered.set()
        if state.release is not None:
            state.release.wait(10)
        return state.verified or VerifiedAnswer(answer=answer, check=ClaimCheck(status="checked"))

    monkeypatch.setattr(chat, "SessionLocal", Session)
    monkeypatch.setattr(chat, "get_openai_client", lambda: object())
    monkeypatch.setattr(chat, "agent_enabled", lambda: True)
    monkeypatch.setattr(chat, "verify_answer", fake_verify_answer, raising=False)
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


def ask(harness) -> list[dict]:
    """Ask QUESTION; the SSE events of the answer."""
    response = harness.client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": QUESTION}]})
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def assistant(harness) -> models.ChatMessage:
    with harness.Session() as db:
        return db.query(models.ChatMessage).filter(models.ChatMessage.role == "assistant").one()


def saved_answer(harness, timeout: float = 10) -> models.ChatMessage:
    deadline = time.time() + timeout
    while time.time() < deadline:
        message = assistant(harness)
        if message.status != "streaming":
            return message
        time.sleep(0.05)
    raise AssertionError("the answer was not saved")


def claim_events(message: models.ChatMessage) -> list[dict]:
    return [event for event in message.trace or [] if event["stage"] == "claim_check"]


def test_the_agents_raw_answer_is_checked(harness):
    """The chat checks the agent's raw answer against the chunks the agent read."""
    ask(harness)
    assert harness.checked == [(RAW, [A, B, C])]


def test_the_stream_says_the_claims_are_being_checked(harness):
    """While the check runs, the stream shows that the claims are being checked."""
    events = ask(harness)
    assert {"type": "thinking", "label": "Checking the claims"} in events


def test_the_answer_stays_streaming_until_the_check_is_done(harness):
    """The streamed answer is saved, but marked streaming, while its claims are still being checked."""
    harness.release = threading.Event()
    asking = threading.Thread(target=ask, args=(harness,))
    asking.start()
    try:
        assert harness.entered.wait(10), "the answer was never checked"
        time.sleep(2.5)  # the worker saves every 2 s
        message = assistant(harness)
        assert (message.status, HOUSE in message.content) == ("streaming", True)
    finally:
        harness.release.set()
        asking.join(10)


def test_the_verdicts_are_saved_with_the_answer(harness):
    """The check's verdicts and supporting sentences are saved in the answer's trace."""
    harness.verified = VerifiedAnswer(answer=RAW, check=ClaimCheck(status="checked", claims=[
        Claim(text=HOUSE, verdict="supported", chunk_ids=[A],
              supporting=[Support(chunk_id=A, sentence="Bygglov krävs för nybyggnad av en byggnad.")]),
        Claim(text=FEE, verdict="unsupported", chunk_ids=[B]),
    ]))
    ask(harness)
    [event] = claim_events(saved_answer(harness))
    assert event["data"] == {"status": "checked", "claims": [HOUSE_SUPPORTED, FEE_UNSUPPORTED]}


def test_a_failed_check_is_saved_with_the_answer(harness):
    """A check that could not run is saved as failed, and the answer is kept."""
    harness.verified = VerifiedAnswer(answer=RAW, check=ClaimCheck(status="failed"))
    ask(harness)
    message = saved_answer(harness)
    assert [e["data"] for e in claim_events(message)] == [{"status": "failed", "claims": []}]
    assert message.content.startswith(f"{HOUSE} [1]. {FEE} [2].")


def test_a_rewritten_answer_replaces_the_saved_text(harness):
    """The saved answer is the rewritten one, numbered, with its source list."""
    harness.verified = VerifiedAnswer(answer=SHORTENED, check=ClaimCheck(status="checked"))
    ask(harness)
    content = saved_answer(harness).content
    assert content.startswith(f"{HOUSE} [1].") and FEE not in content


def test_a_rewritten_answer_is_sent_to_the_open_chat(harness):
    """The stream sends the rewritten answer, as saved, to replace the text already shown."""
    harness.verified = VerifiedAnswer(answer=SHORTENED, check=ClaimCheck(status="checked"))
    events = ask(harness)
    [replaced] = [event for event in events if event["type"] == "answer_replaced"]
    assert replaced["content"] == saved_answer(harness).content


def test_an_unchanged_answer_is_not_resent(harness):
    """When the check ran and changed nothing, no replacement is sent."""
    events = ask(harness)
    assert harness.checked and not [event for event in events if event["type"] == "answer_replaced"]


def test_the_citations_follow_the_rewritten_answer(harness):
    """After a rewrite that re-cites, the numbered sources are those of the rewritten answer."""
    harness.verified = VerifiedAnswer(answer=REVISED, check=ClaimCheck(status="checked"))
    ask(harness)
    [event] = [e for e in saved_answer(harness).trace if e["stage"] == "citations"]
    assert [item["label"] for item in event["data"]["items"]] == ["PBL, 9 kap. 4 §", "Ydre – Avgifter"]


def test_a_question_back_to_the_user_is_not_checked(harness):
    """Of a question back to the user and an answer, only the answer is checked."""
    harness.choices.extend(["Ydre", "Linköping"])
    ask(harness)
    harness.choices.clear()
    ask(harness)
    assert harness.checked == [(RAW, [A, B, C])]
