"""Acceptance tests for #76: answers in the question's language, Swedish sources quoted verbatim (PCR-0006).

No real model calls or databases (PCR-0011): the model client is faked at its boundary. Whether the model actually
answers in the right language is measured by the bilingual eval (agentic/bench.py on cases_bilingual.jsonl), not here.
"""

import json
import os
import time
import types
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

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


import glossary
import models
from agentic import agent, bench
from agents.base import BaseRAGAgent
from agents.law_agent import LawAgent
from agents.orchestrator import Orchestrator
from agents.parsers import format_response
from answer_language import (
    LANGUAGE_RULE,
    REWRITE_LANGUAGE_SUFFIX,
    parse_language,
    split_language,
)
from db.database import get_db
from dependencies import get_current_user
from routers import chat

SWEDISH_QUESTION = "Behöver jag bygglov för en friggebod på min tomt?"
ENGLISH_REWRITE = "Do I need a building permit for a small shed on my plot?"
SOURCE = "Det krävs bygglov för nybyggnad."


# --- The language decision -------------------------------------------------------------------------------------

def test_a_swedish_lang_line_gives_swedish():
    """A rewrite output whose LANG line says sv decides Swedish."""
    assert parse_language(f"{ENGLISH_REWRITE}\nLANG: sv") == "sv"


def test_an_english_lang_line_gives_english():
    """A rewrite output whose LANG line says en decides English."""
    assert parse_language(f"{ENGLISH_REWRITE}\nLANG: en") == "en"


def test_the_lang_line_is_read_case_insensitively():
    """'lang: SV' decides Swedish like 'LANG: sv'."""
    assert parse_language(f"{ENGLISH_REWRITE}\nlang: SV") == "sv"


def test_a_missing_lang_line_gives_english():
    """Without a LANG line the answer is in English."""
    assert parse_language(ENGLISH_REWRITE) == "en"


def test_a_lang_line_naming_another_language_gives_english():
    """A LANG line naming any language but sv or en gives English."""
    assert parse_language(f"{ENGLISH_REWRITE}\nLANG: de") == "en"


def test_an_empty_rewrite_output_gives_english():
    """An empty rewrite output gives English."""
    assert parse_language("") == "en"


def test_split_language_removes_only_the_lang_line():
    """The rewrite output comes back without its LANG line, the SV search line kept."""
    output = f"{ENGLISH_REWRITE}\nSV: bygglov friggebod tomt\nLANG: sv"
    assert split_language(output) == (f"{ENGLISH_REWRITE}\nSV: bygglov friggebod tomt", "sv")


def test_the_rewrite_suffix_asks_for_a_lang_line():
    """The rewrite prompt suffix asks the model for the LANG line."""
    assert "LANG:" in REWRITE_LANGUAGE_SUFFIX


def test_the_language_rule_asks_for_swedish_quotes_verbatim():
    """The shared answer rule tells the model to quote Swedish sources verbatim."""
    assert "verbatim" in LANGUAGE_RULE


# --- The glossary ----------------------------------------------------------------------------------------------

def test_the_glossary_has_the_tickets_terms():
    """The glossary explains detaljplan, bygglov, strandskydd, plankarta, byggnadsarea and komplementbyggnad."""
    terms = {"detaljplan", "bygglov", "strandskydd", "plankarta", "byggnadsarea", "komplementbyggnad"}
    assert terms <= set(glossary.GLOSSARY)


def test_every_glossary_term_has_an_explanation():
    """No glossary term has an empty explanation."""
    assert glossary.GLOSSARY and all(explanation.strip() for explanation in glossary.GLOSSARY.values())


def test_the_glossary_prompt_lists_each_term_with_its_explanation():
    """The glossary block has a '<term>: <explanation>' line for every term."""
    block = glossary.glossary_prompt()
    assert glossary.GLOSSARY and all(f"{term}: {text}" in block for term, text in glossary.GLOSSARY.items())


def test_an_empty_glossary_gives_no_prompt(monkeypatch):
    """With no terms the glossary block is empty."""
    monkeypatch.setattr(glossary, "GLOSSARY", {})
    assert glossary.glossary_prompt() == ""


# --- The agent -------------------------------------------------------------------------------------------------

class AnsweringClient:
    """A model that answers on its first turn; keeps the instructions it was given."""

    def __init__(self):
        self.instructions = []
        self.responses = types.SimpleNamespace(create=self.create)

    def create(self, instructions="", stream=False, **kwargs):
        self.instructions.append(instructions)
        usage = types.SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)
        return types.SimpleNamespace(output=[], output_text="Svar.", usage=usage)


def agent_instructions(monkeypatch) -> str:
    client = AnsweringClient()
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    monkeypatch.setattr(agent, "kommun_scope", lambda tools: agent.NATIONAL_SCOPE)
    agent.run_agent(SWEDISH_QUESTION, tools=None, model="test/model")
    return client.instructions[0]


def test_the_agent_is_instructed_with_the_language_rule(monkeypatch):
    """The agent's model is given the shared answer-language rule."""
    assert LANGUAGE_RULE and LANGUAGE_RULE in agent_instructions(monkeypatch)


def test_the_agent_is_not_told_to_answer_in_english(monkeypatch):
    """No line of the agent's instructions fixes the answer language to English."""
    assert "Answer in English" not in agent_instructions(monkeypatch)


def test_the_agent_is_not_told_users_ask_in_english(monkeypatch):
    """The agent's role no longer says users ask in English."""
    assert "ask in English" not in agent_instructions(monkeypatch)


def test_the_agent_names_the_swedish_headings(monkeypatch):
    """The answer format gives the Swedish headings for a Swedish answer."""
    assert "**Bedömning:**" in agent_instructions(monkeypatch)


def test_the_agent_carries_the_glossary(monkeypatch):
    """The agent's instructions include the glossary block."""
    block = glossary.glossary_prompt()
    assert block and block in agent_instructions(monkeypatch)


def test_ask_user_asks_in_the_users_language():
    """The agent's question to the user is no longer fixed to English."""
    description = agent.ASK_USER_TOOL["parameters"]["properties"]["question"]["description"]
    assert "in English" not in description


# --- The chat's RAG path ---------------------------------------------------------------------------------------

@pytest.fixture
def rag(monkeypatch):
    """The chat in RAG mode on pgvector, with a fake model: the rewrite decides Swedish."""
    monkeypatch.setenv("RETRIEVAL_BACKEND", "pgvector")
    monkeypatch.setenv("CHAT_MODE", "rag")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.ChatSession.__table__,
                                                    models.ChatMessage.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(models.User(id="u1", name="Test", email="test@example.com"))
        db.commit()
    state = types.SimpleNamespace(calls=[], rows=[{"source": "PBL", "chunk_index": 0, "distance": 0.1,
                                                   "content": SOURCE, "preview": ""}])

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


def stream(rag) -> str:
    body = {"messages": [{"role": "user", "content": SWEDISH_QUESTION}], "session_id": None}
    response = rag.client.post("/api/chat/stream", json=body)
    response.read()
    deadline = time.time() + 10
    while time.time() < deadline:
        with rag.Session() as db:
            message = db.query(models.ChatMessage).filter(models.ChatMessage.role == "assistant").one_or_none()
            if message is not None and message.status != "streaming":
                return message.content
        time.sleep(0.1)
    raise AssertionError("the answer was not saved")


def post(rag) -> str:
    body = {"messages": [{"role": "user", "content": SWEDISH_QUESTION}], "session_id": None}
    return rag.client.post("/api/chat", json=body).json()["content"]


def answer_call(rag) -> dict:
    return next(call for call in rag.calls if "instructions" in call)


def rewrite_call(rag) -> dict:
    return next(call for call in rag.calls if "instructions" not in call)


def test_the_streamed_answer_is_asked_the_users_own_words(rag):
    """The streamed RAG answer gets the user's question as written, not its English rewrite."""
    stream(rag)
    assert SWEDISH_QUESTION in answer_call(rag)["input"][-1]["content"]


def test_the_streamed_answer_follows_the_language_rule(rag):
    """The streamed RAG answer is instructed with the shared answer-language rule."""
    stream(rag)
    assert LANGUAGE_RULE and LANGUAGE_RULE in answer_call(rag)["instructions"]


def test_the_streamed_answer_is_not_told_to_answer_in_english(rag):
    """The streamed RAG answer's instructions no longer fix English."""
    stream(rag)
    assert "Answer in English" not in answer_call(rag)["instructions"]


def test_the_streamed_rewrite_asks_for_the_language(rag):
    """The streamed chat's rewrite prompt asks for the LANG line."""
    stream(rag)
    assert REWRITE_LANGUAGE_SUFFIX and REWRITE_LANGUAGE_SUFFIX in rewrite_call(rag)["input"]


def test_the_streamed_clarifying_prompt_follows_a_swedish_decision(rag):
    """With nothing retrieved, a question decided Swedish gets the clarifying prompt in Swedish."""
    rag.rows = []
    assert "I need a bit more information" not in stream(rag)


def test_the_answer_is_asked_the_users_own_words(rag):
    """The /api/chat RAG answer gets the user's question as written, not its English rewrite."""
    post(rag)
    assert SWEDISH_QUESTION in answer_call(rag)["input"][-1]["content"]


def test_the_answer_follows_the_language_rule(rag):
    """The /api/chat RAG answer is instructed with the shared answer-language rule."""
    post(rag)
    assert LANGUAGE_RULE and LANGUAGE_RULE in answer_call(rag)["instructions"]


def test_the_rewrite_asks_for_the_language(rag):
    """The /api/chat rewrite prompt asks for the LANG line."""
    post(rag)
    assert REWRITE_LANGUAGE_SUFFIX and REWRITE_LANGUAGE_SUFFIX in rewrite_call(rag)["input"]


def test_the_clarifying_prompt_follows_a_swedish_decision(rag):
    """With nothing retrieved, /api/chat answers a question decided Swedish with the clarifying prompt in Swedish."""
    rag.rows = []
    assert "I need a bit more information" not in post(rag)


# --- The feasibility analysis ----------------------------------------------------------------------------------

RESULT = {"feasibility": "HIGHLY FEASIBLE", "confidence": 80, "summary": "S", "law_findings": "L",
          "case_findings": "C", "requirements": ["R"], "timeline": 6, "next_steps": ["N"]}


def test_a_swedish_feasibility_answer_has_swedish_headings():
    """The feasibility template in Swedish opens with the Swedish heading."""
    assert format_response(RESULT, "sv").startswith("## Bedömning av genomförbarhet")


def test_a_swedish_feasibility_answer_has_no_english_headings():
    """The feasibility template in Swedish keeps none of the English headings."""
    text = format_response(RESULT, "sv")
    assert not any(heading in text for heading in ("Feasibility Analysis", "### Summary", "Recommended Next Steps"))


class FakeAgent:
    def __init__(self, result):
        self.result = result

    def query(self, location, project_type, units, language="en"):
        return dict(self.result)


def test_a_swedish_analysis_has_swedish_next_steps():
    """An analysis in Swedish gives its next steps in Swedish, not the English defaults."""
    law = {"max_units_allowed": 50, "conditions": [], "sources": []}
    document = {"approval_rate": 0.9, "common_requirements": [], "sources": []}
    english = Orchestrator(FakeAgent(law), FakeAgent(document)).analyze("Uppsala", "residential", 10)["next_steps"]
    swedish = Orchestrator(FakeAgent(law), FakeAgent(document)).analyze("Uppsala", "residential", 10,
                                                                         language="sv")["next_steps"]
    assert swedish and not set(swedish) & set(english)


class CapturingClient:
    def __init__(self, output):
        self.calls = []
        self.output = output
        self.responses = types.SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(output_text=self.output, usage=None)


def test_a_swedish_law_reading_is_not_asked_in_english(monkeypatch):
    """The law agent asked in Swedish does not tell the model to answer in English."""
    monkeypatch.setattr(BaseRAGAgent, "_embed", lambda self, text: [0.0])
    monkeypatch.setattr(BaseRAGAgent, "_retrieve_debug_rows_from_embedding",
                        lambda self, embedding, k=5: [{"source": "PBL", "chunk_index": 0, "distance": 0.1,
                                                       "content": SOURCE, "preview": ""}])
    client = CapturingClient(json.dumps({"max_units_allowed": 10, "conditions": []}))
    LawAgent(None, client).query("Uppsala", "residential", 10, language="sv")
    sent = client.calls[0]
    assert "in English" not in f"{sent.get('instructions', '')}\n{sent.get('input', '')}"


# --- The bilingual eval ----------------------------------------------------------------------------------------

SV_CASE = {"id": "x-sv", "lang": "sv", "question": SWEDISH_QUESTION, "key_points": ["a"], "verdicts": []}
EN_CASE = {"id": "x-en", "lang": "en", "question": ENGLISH_REWRITE, "key_points": ["a"], "verdicts": []}
SWEDISH_ANSWER = ("**Bedömning:** Ja, du behöver bygglov för att uppföra en ny byggnad på din tomt, "
                  "och kommunen prövar ansökan mot detaljplanen [c:aa11bb22cc33dd44].")
ENGLISH_ANSWER = ("**Verdict:** Yes, you need a building permit for a new building on your plot, and the kommun "
                  "checks the application against the detaljplan [c:aa11bb22cc33dd44].")
ENGLISH_ANSWER_QUOTING = (f'**Verdict:** Yes. PBL says "{SOURCE}" ("A building permit is required for new '
                          f'construction.") [c:aa11bb22cc33dd44], so you need one before you build.')


def test_a_swedish_answer_is_ok_for_a_swedish_case():
    """A Swedish answer to a Swedish case is in the right language."""
    assert bench.answer_language_ok(SV_CASE, SWEDISH_ANSWER) is True


def test_an_english_answer_fails_a_swedish_case():
    """An English answer to a Swedish case is in the wrong language."""
    assert bench.answer_language_ok(SV_CASE, ENGLISH_ANSWER) is False


def test_a_swedish_answer_fails_an_english_case():
    """A Swedish answer to an English case is in the wrong language."""
    assert bench.answer_language_ok(EN_CASE, SWEDISH_ANSWER) is False


def test_an_english_answer_quoting_swedish_law_is_english():
    """Swedish quotes in an English answer do not make it Swedish."""
    assert bench.answer_language_ok(EN_CASE, ENGLISH_ANSWER_QUOTING) is True


def test_a_case_without_lang_is_english():
    """A case with no lang field expects English."""
    assert bench.answer_language_ok({"id": "x", "question": "q", "key_points": ["a"]}, ENGLISH_ANSWER) is True


def test_an_empty_answer_is_never_in_the_right_language():
    """An empty answer fails the language check."""
    assert bench.answer_language_ok(EN_CASE, "") is False


def test_a_quote_found_in_a_source_is_verbatim():
    """A Swedish quote that appears word for word in a source passes."""
    assert bench.quotes_verbatim(f'PBL says "{SOURCE}"', [f"9 kap. 2 §  {SOURCE} Det gäller även tillbyggnad."])


def test_a_reworded_quote_is_not_verbatim():
    """A Swedish quote reworded from its source fails."""
    assert bench.quotes_verbatim('PBL says "Bygglov krävs för nybyggnad."', [SOURCE]) is False


def test_a_block_quote_is_checked():
    """A Swedish markdown block quote not found in any source fails."""
    assert bench.quotes_verbatim("> Bygglov krävs alltid för nybyggnad.\n\nSo you need one.", [SOURCE]) is False


def test_an_answer_without_quotes_passes_the_quote_check():
    """An answer that quotes nothing passes."""
    assert bench.quotes_verbatim(ENGLISH_ANSWER, [SOURCE]) is True


def test_an_english_translation_in_quotes_is_not_checked():
    """A quoted English translation next to its Swedish original does not fail the check."""
    assert bench.quotes_verbatim(ENGLISH_ANSWER_QUOTING, [SOURCE]) is True


class NoTools:
    def get_chunk(self, chunk_id):
        return {"chunk_id": chunk_id, "header": "PBL 9 kap. 2 §", "text": SOURCE} if chunk_id == "aa11bb22cc33dd44" else None


def graded(monkeypatch, case, answer):
    grade = {"verdict": "none", "points": [2], "unsupported_claims": 0, "comment": ""}
    monkeypatch.setattr(bench, "get_openai_client", lambda: CapturingClient(json.dumps(grade)))
    return bench.grade_answer(case, answer, NoTools(), "judge")


def test_a_graded_row_carries_the_language_check(monkeypatch):
    """A graded row says whether the answer was in the case's language."""
    assert graded(monkeypatch, SV_CASE, SWEDISH_ANSWER)["language_ok"] is True


def test_a_graded_row_carries_the_quote_check(monkeypatch):
    """A graded row says whether the answer's quotes are verbatim in the cited sources."""
    assert graded(monkeypatch, EN_CASE, ENGLISH_ANSWER_QUOTING)["quotes_ok"] is True


def test_a_graded_row_carries_the_case_language(monkeypatch):
    """A graded row names the case's language."""
    assert graded(monkeypatch, SV_CASE, SWEDISH_ANSWER)["lang"] == "sv"


BILINGUAL = Path(bench.__file__).resolve().parent / "cases_bilingual.jsonl"


def bilingual_cases() -> list[dict]:
    assert BILINGUAL.exists(), "agentic/cases_bilingual.jsonl does not exist yet"
    return [json.loads(line) for line in BILINGUAL.read_text().splitlines() if line.strip()]


def test_every_ordinary_bilingual_case_has_a_twin_in_the_other_language():
    """Each non-hard case has a case with the same pair id in the other language."""
    ordinary = [case for case in bilingual_cases() if not case.get("hard")]
    pairs: dict = {}
    for case in ordinary:
        pairs.setdefault(case["pair"], set()).add(case["lang"])
    assert pairs and all(langs == {"sv", "en"} for langs in pairs.values())


def test_there_are_at_least_24_pairs():
    """The bilingual eval holds at least 24 Swedish-English pairs."""
    assert len({case["pair"] for case in bilingual_cases() if not case.get("hard")}) >= 24


def test_the_hard_cases_are_marked():
    """The bilingual eval holds at least 8 cases marked hard."""
    assert sum(1 for case in bilingual_cases() if case.get("hard")) >= 8
