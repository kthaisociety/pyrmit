"""ask_user: the agent asks a question with options the user can click, and the run ends there (fake LLM)."""

import json
from types import SimpleNamespace

import agentic.agent as agent
from tests.test_agent_images import FakeCall


class AskingClient:
    def __init__(self, arguments):
        self.calls = 0
        self.arguments = arguments
        self.responses = SimpleNamespace(create=self.create)

    def create(self, input, stream=False, **kwargs):
        self.calls += 1
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)
        assert not stream, "an ask_user turn needs no final answer call"
        return SimpleNamespace(output=[FakeCall(name="ask_user", arguments=json.dumps(self.arguments), call_id="1")],
                               output_text="", usage=usage)


def run_with(monkeypatch, arguments):
    client = AskingClient(arguments)
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    return agent.run_agent("Can I build 20 apartments in Södermalm?", tools=None, model="test/model"), client


def test_ask_user_ends_the_run_with_the_question_and_its_options(monkeypatch):
    run, client = run_with(monkeypatch, {"question": "Which place do you mean?",
                                         "options": ["The pinned Uppsala property", "A site in Södermalm"]})
    assert run.answer == "Which place do you mean?"
    assert run.choices == ["The pinned Uppsala property", "A site in Södermalm"]
    assert client.calls == 1


def test_options_are_trimmed_deduplicated_and_capped(monkeypatch):
    run, _ = run_with(monkeypatch, {"question": "Which?", "options": [" A ", "A", "", "B", "C", "D", "E"]})
    assert run.choices == ["A", "B", "C", "D"]


def test_ask_user_is_offered_to_the_model():
    assert "ask_user" in agent.SYSTEM_PROMPT
    assert agent.ASK_USER_TOOL["name"] == "ask_user"


def test_ask_user_can_offer_to_pin_the_place(monkeypatch):
    run, _ = run_with(monkeypatch, {"question": "Which property?", "options": ["Answer generally"], "offer_pin": True})
    assert run.choices == ["Answer generally"] and run.offer_pin is True


def test_the_prompt_forbids_options_that_ask_for_more_input():
    assert "Never an option that asks the user to provide" in agent.SYSTEM_PROMPT
