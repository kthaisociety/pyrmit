"""agentic.agent: the agent reads a pinned plan, what its instructions say about a pin, and the answer language it is
told to follow. A fake model: no real services (PCR-0011)."""

import json
from types import SimpleNamespace

import pytest

from agentic import agent
from agentic.tools import CorpusTools, _MemoryCorpus
from answer_language import LANGUAGE_RULE
from glossary import glossary_prompt
from tests.unit.agentic.test_agent_images import FakeCall

DESCRIPTION = "pdf:0380:description"


class ReadingClient:
    """A fake model: reads the plan, then says it is ready."""

    def __init__(self):
        self.turns = [[FakeCall(name="read_plan", arguments=json.dumps({"doc_ids": [DESCRIPTION]}), call_id="1")],
                      [FakeCall(name="answer_ready", arguments=json.dumps({"mode": "verdict"}), call_id="2")]]
        self.offered = None
        self.responses = SimpleNamespace(create=self.create)

    def create(self, input, stream=False, tools=None, **kwargs):
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)
        if stream:
            return iter([SimpleNamespace(type="response.output_text.delta", delta="Answer."),
                         SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))])
        self.offered = {tool["name"] for tool in tools}
        return SimpleNamespace(output=self.turns.pop(0), output_text="", usage=usage)


@pytest.fixture
def reading(monkeypatch):
    """A run where the fake model reads a plan of two chunks, and the client it talked to."""
    tools = CorpusTools.__new__(CorpusTools)
    tools.corpus = _MemoryCorpus([{"chunk_id": f"{index:016d}", "doc_id": DESCRIPTION, "chunk_index": index, "section": None,
                                   "text": "Text", "header": "", "title": "Planbeskrivning", "kind": "pdf",
                                   "doc_type": "detaljplan", "kommun": "Uppsala", "kommun_code": "0380", "url": None}
                                  for index in range(2)])
    client = ReadingClient()
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    return agent.run_agent("Får vi bygga?", tools, model="test/model"), client


def test_the_model_is_offered_read_plan(reading):
    assert "read_plan" in reading[1].offered


def test_the_agents_read_plan_call_runs(reading):
    assert [step["tool"] for step in reading[0].steps] == ["read_plan"]


def test_what_the_agent_read_counts_as_seen_evidence(reading):
    """A passage read with read_plan can be cited."""
    assert len(reading[0].seen_chunks) == 2


def test_the_instructions_hold_the_guidance_on_a_pin():
    assert agent.PIN_GUIDE in agent.SYSTEM_PROMPT


@pytest.mark.parametrize("words", ["address", "property designation", "aktbeteckning", '"here"', '"my plot"'])
def test_the_instructions_say_what_counts_as_a_specific_question(words):
    """Each sign of a question about one specific place is named."""
    assert words in agent.PIN_GUIDE


@pytest.mark.parametrize("words", [
    "read_plan", "without searching", "statute",        # with a pin: read the plans first, search only for the rest
    "general question", "without bringing in",          # a general question stays general
    "offer_pin", "before any search", "offer to pin",   # without a pin: ask, or offer
    "text not read", "link", "statutes",                # a plan with no text
])
def test_the_instructions_say_what_a_pin_changes(words):
    assert words in agent.PIN_GUIDE.lower()


# --- the answer language --------------------------------------------------------------------------------------------

class AnsweringClient:
    """A fake model that answers on its first turn; keeps the instructions it was given."""

    def __init__(self):
        self.instructions = []
        self.responses = SimpleNamespace(create=self.create)

    def create(self, instructions="", stream=False, **kwargs):
        self.instructions.append(instructions)
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)
        return SimpleNamespace(output=[], output_text="Svar.", usage=usage)


@pytest.fixture
def instructions(monkeypatch) -> str:
    """The instructions the agent's model gets for a Swedish question."""
    client = AnsweringClient()
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    agent.run_agent("Behöver jag bygglov för en friggebod på min tomt?", tools=None, model="test/model")
    return client.instructions[0]


def test_the_agent_is_instructed_with_the_language_rule(instructions):
    assert LANGUAGE_RULE and LANGUAGE_RULE in instructions


def test_the_agent_is_not_told_to_answer_in_english(instructions):
    assert "Answer in English" not in instructions


def test_the_agent_is_not_told_users_ask_in_english(instructions):
    assert "ask in English" not in instructions


def test_the_agent_names_the_swedish_headings(instructions):
    assert "**Bedömning:**" in instructions


def test_the_agent_carries_the_glossary(instructions):
    block = glossary_prompt()
    assert block and block in instructions


def test_ask_user_asks_in_the_users_language():
    question = agent.ASK_USER_TOOL["parameters"]["properties"]["questions"]["items"]["properties"]["question"]
    description = question["description"]
    assert "in English" not in description


class ReadyClient:
    """A fake model: says it is ready on its first turn, then streams the answer; keeps the final turn's input."""

    def __init__(self):
        self.final_input = None
        self.responses = SimpleNamespace(create=self.create)

    def create(self, input, stream=False, **kwargs):
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)
        if stream:
            self.final_input = list(input)
            return iter([SimpleNamespace(type="response.output_text.delta", delta="Answer."),
                         SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))])
        ready = FakeCall(name="answer_ready", arguments=json.dumps({"mode": "verdict"}), call_id="1")
        return SimpleNamespace(output=[ready], output_text="", usage=usage)


def test_the_final_answer_turn_repeats_the_language_rule(monkeypatch):
    """Asked for the final answer, the model is reminded to write it in the user's language, not the sources'."""
    client = ReadyClient()
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    agent.run_agent("Do I need a permit for a shed?", tools=None, model="test/model")
    assert any(agent.ANSWER_LANGUAGE_REMINDER in str(item.get("output", "")) for item in client.final_input)
