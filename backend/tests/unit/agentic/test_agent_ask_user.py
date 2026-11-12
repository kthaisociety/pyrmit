"""ask_user: the agent asks for missing facts in a question card instead of answering, and the run ends there
(fake LLM)."""

import json
from types import SimpleNamespace

from agentic import agent
from agentic.agent import AgentRun, AskedQuestion
from tests.unit.agentic.test_agent_images import FakeCall

USAGE = SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)


def asking(arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(output=[FakeCall(name="ask_user", arguments=json.dumps(arguments), call_id="1")],
                           output_text="", usage=USAGE)


def answering(text: str) -> SimpleNamespace:
    return SimpleNamespace(output=[], output_text=text, usage=USAGE)


class ScriptedClient:
    """Answers each model call with the next scripted response, and keeps what every call was given."""

    def __init__(self, *responses):
        self.responses_left = list(responses)
        self.inputs: list = []
        self.tools: list[list[str]] = []
        self.responses = SimpleNamespace(create=self.create)

    def create(self, input, tools=(), stream=False, **kwargs):
        self.inputs.append(json.dumps(input, ensure_ascii=False, default=str))
        self.tools.append([tool["name"] for tool in tools])
        return self.responses_left.pop(0)


class AskIfAllowedClient(ScriptedClient):
    """Asks for the use whenever ask_user is offered, else answers."""

    def create(self, input, tools=(), stream=False, **kwargs):
        self.inputs.append(json.dumps(input, ensure_ascii=False, default=str))
        self.tools.append([tool["name"] for tool in tools])
        if any(tool["name"] == "ask_user" for tool in tools):
            return asking({"questions": [{"question": "What will the building be used for?", "options": []}]})
        return answering("A permanent home needs bygglov.")


def run_with(monkeypatch, *responses) -> tuple[AgentRun, ScriptedClient]:
    client = ScriptedClient(*responses)
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    return agent.run_agent("Can I build a house on my plot?", tools=None, model="test/model"), client


USE = {"question": "What will the building be used for?", "options": ["A permanent home", "A holiday home"]}
SIZE = {"question": "Roughly how large will it be?", "options": []}


# --- the question card of a run ---------------------------------------------------------------------------------

def test_a_run_that_asks_returns_each_question_with_its_options(monkeypatch):
    """ask_user with two questions ends the run with both, in order, each with its own options."""
    run, _ = run_with(monkeypatch, asking({"questions": [USE, SIZE]}))
    assert run.questions == [AskedQuestion(USE["question"], USE["options"]), AskedQuestion(SIZE["question"], [])]


def test_an_open_question_has_no_options(monkeypatch):
    """A question asked without options stays an open question (only the "Other" field in the card)."""
    run, _ = run_with(monkeypatch, asking({"questions": [SIZE]}))
    assert run.questions == [AskedQuestion(SIZE["question"], [])]


def test_a_card_keeps_at_most_three_questions(monkeypatch):
    """A card asks at most three questions: further ones are dropped."""
    questions = [{"question": f"Question {i}?", "options": []} for i in range(1, 6)]
    run, _ = run_with(monkeypatch, asking({"questions": questions}))
    assert [q.question for q in run.questions] == ["Question 1?", "Question 2?", "Question 3?"]


def test_options_are_trimmed_deduplicated_and_capped_per_question(monkeypatch):
    """Each question's options are trimmed, without empties or repeats, and at most four."""
    run, _ = run_with(monkeypatch, asking({"questions": [
        {"question": "Which?", "options": [" A ", "A", "", "B", "C", "D", "E"]}]}))
    assert run.questions[0].options == ["A", "B", "C", "D"]


def test_a_question_without_text_is_dropped(monkeypatch):
    """An empty question is left out of the card; the others stay."""
    run, _ = run_with(monkeypatch, asking({"questions": [{"question": "  ", "options": ["X"]}, SIZE]}))
    assert run.questions == [AskedQuestion(SIZE["question"], [])]


def test_the_reply_text_holds_every_question(monkeypatch):
    """The saved reply of a card lists each of its questions, so the conversation reads without the card."""
    run, _ = run_with(monkeypatch, asking({"questions": [USE, SIZE]}))
    assert USE["question"] in run.answer and SIZE["question"] in run.answer


def test_a_card_can_offer_to_pin_the_place(monkeypatch):
    run, _ = run_with(monkeypatch, asking({"questions": [{"question": "Which plot do you mean?", "options": []}],
                                           "offer_pin": True}))
    assert run.offer_pin is True


def test_the_card_is_offered_to_the_model_as_a_list_of_questions():
    """The model asks through one tool call holding a list of questions, so all missing facts come in one round."""
    properties = agent.ASK_USER_TOOL["parameters"]["properties"]
    assert properties["questions"]["maxItems"] == agent.MAX_QUESTIONS


def test_an_answer_to_the_card_cannot_ask_again(monkeypatch):
    """A run on the user's reply to a card has no ask_user, so it answers (on stated assumptions if need be)."""
    client = AskIfAllowedClient()
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    run = agent.run_agent("Answer anyway", tools=None, model="test/model", allow_ask=False)
    assert (run.questions, run.answer) == ([], "A permanent home needs bygglov.")


def test_ask_user_is_offered_to_the_model():
    assert "ask_user" in agent.SYSTEM_PROMPT
    assert agent.ASK_USER_TOOL["name"] == "ask_user"


def test_the_prompt_forbids_options_that_ask_for_more_input():
    """The card adds a free-text field, so an option never asks the user to type something."""
    assert '"Please specify" as an option' in agent.SYSTEM_PROMPT


def test_a_run_that_cannot_ask_is_not_told_to_ask(monkeypatch):
    """Once the user has answered the card, the asking rule leaves the prompt, so the agent answers instead of asking
    again in plain text."""
    given = []

    class Client:
        responses = SimpleNamespace(create=lambda **kwargs: (given.append(kwargs["instructions"]),
                                                             SimpleNamespace(output=[], output_text="Answer.",
                                                                             usage=None))[1])
    monkeypatch.setattr(agent, "get_openai_client", lambda: Client())
    agent.run_agent("A holiday home", tools=None, model="test/model", allow_ask=False)
    assert agent.ASK_GUIDE not in given[0] and agent.ANSWERED_GUIDE in given[0]


def test_a_run_that_can_ask_keeps_the_asking_rule(monkeypatch):
    given = []

    class Client:
        responses = SimpleNamespace(create=lambda **kwargs: (given.append(kwargs["instructions"]),
                                                             SimpleNamespace(output=[], output_text="Answer.",
                                                                             usage=None))[1])
    monkeypatch.setattr(agent, "get_openai_client", lambda: Client())
    agent.run_agent("Can I build a shed?", tools=None, model="test/model")
    assert agent.ASK_GUIDE in given[0]
