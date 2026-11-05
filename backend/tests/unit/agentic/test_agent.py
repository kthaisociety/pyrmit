"""agentic.agent: the agent reads a pinned plan, and what its instructions say about a pin. A fake model: no real services
(PCR-0011)."""

import json
from types import SimpleNamespace

import pytest

from agentic import agent
from agentic.tools import CorpusTools, _MemoryCorpus
from tests.test_agent_images import FakeCall

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
