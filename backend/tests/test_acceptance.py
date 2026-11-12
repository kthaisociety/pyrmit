"""Acceptance tests of #91: the agent asks for missing facts in a question card instead of guessing, and the
missing-info eval that checks it. Fake models only (PCR-0011). Folded into tests/unit/ before merge."""

import json
from types import SimpleNamespace

import pytest

import agentic.agent
import agentic.service
from agentic import agent, bench
from agentic.agent import AgentRun, AskedQuestion
from corpus.common import read_jsonl
from routers import chat
from tests.unit.agentic.judge_client import JudgeClient
from tests.unit.agentic.test_agent_images import FakeCall
from tests.unit.conftest import profile_of  # noqa: F401 - fixture of the chat harness
from tests.unit.routers.test_chat import (  # noqa: F401 - harness is a fixture
    PINNED,
    ask,
    harness,
    saved_answer,
)

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
        super().create(input, tools, stream)
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


# --- the card in the streamed chat ------------------------------------------------------------------------------

def card_harness(harness, monkeypatch, questions, offer_pin=False):  # noqa: F811 - harness is the fixture
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


def test_a_card_is_saved_with_its_questions(harness, monkeypatch):  # noqa: F811
    """The card's questions and options are saved with the answer, for the chat to show."""
    questions = [{"question": "What will the building be used for?", "options": ["A permanent home"]},
                 {"question": "Roughly how large will it be?", "options": []}]
    message, _ = card_harness(harness, monkeypatch, questions)
    assert card_event(message)["questions"] == questions


def test_an_open_question_is_saved_as_a_card(harness, monkeypatch):  # noqa: F811
    """A card with only open questions and no pin offer is still a card, not an answer."""
    message, _ = card_harness(harness, monkeypatch, [{"question": "Roughly how large will it be?", "options": []}])
    assert card_event(message)["questions"] == [{"question": "Roughly how large will it be?", "options": []}]


def test_a_card_records_its_pin_offer_beside_its_questions(harness, monkeypatch):  # noqa: F811
    """A card about the place keeps both its question and the button that opens the map."""
    message, _ = card_harness(harness, monkeypatch, [{"question": "Which plot?", "options": []}], offer_pin=True)
    assert card_event(message) == {"questions": [{"question": "Which plot?", "options": []}], "offer_pin": True}


def test_a_card_is_not_claim_checked(harness, monkeypatch):  # noqa: F811
    """A question back to the user makes no claims: its claims are not checked."""
    _, checked = card_harness(harness, monkeypatch, [{"question": "Roughly how large will it be?", "options": []}])
    assert checked == []


def test_the_agent_service_returns_the_card_of_the_run(monkeypatch):
    """stream_agent hands the router the run's questions as plain data."""
    run = AgentRun(answer="What will the building be used for?",
                   questions=[AskedQuestion("What will the building be used for?", ["A permanent home"])])
    monkeypatch.setattr(agentic.agent, "run_agent", lambda *args, **kwargs: run)
    monkeypatch.setattr(agentic.service, "get_tools", lambda: SimpleNamespace(get_chunk=lambda chunk_id: None))
    stream = agentic.service.stream_agent("q", [], lambda **call: None, json.dumps)
    try:
        while True:
            next(stream)
    except StopIteration as done:
        outcome = done.value
    assert outcome["questions"] == [{"question": "What will the building be used for?",
                                     "options": ["A permanent home"]}]


# --- grading a missing-info case --------------------------------------------------------------------------------

ASK_CASE = {"id": "ask-1", "expect": "ask", "lang": "en", "kommun": ["0380"],
            "question": "Can I build a house on my plot in Uppsala?",
            "missing": ["what the house is for", "how large it is"], "reply": "A 120 m² permanent home",
            "key_points": ["A new home needs bygglov"], "evidence": []}
ANSWER_CASE = {"id": "answer-1", "expect": "answer", "lang": "en", "kommun": ["0380"],
               "question": "How does the bygglov process work in Uppsala?",
               "key_points": ["The application goes through the e-service"], "evidence": []}
ASKED = AgentRun(answer="What will it be used for? How large?",
                 questions=[AskedQuestion("What will it be used for?", ["A home"]), AskedQuestion("How large?", [])])
ANSWERED = AgentRun(answer="The application goes through the e-service.")


def graded(monkeypatch, case, run, grade):
    monkeypatch.setattr(bench, "get_openai_client", lambda: JudgeClient(grade))
    return bench.grade_asked(case, run, "judge")


def test_a_should_ask_case_passes_when_the_card_asks_for_every_missing_fact(monkeypatch):
    row = graded(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 1], "options_ok": True})
    assert (row["asked"], row["missing_covered"], row["ask_ok"]) == (True, 1.0, True)


def test_a_should_ask_case_fails_when_a_missing_fact_is_not_asked_for(monkeypatch):
    """Asking, but not for everything that changes the answer, is not enough."""
    row = graded(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 0], "options_ok": True})
    assert (row["missing_covered"], row["ask_ok"]) == (0.5, False)


def test_a_should_ask_case_fails_when_the_agent_answers(monkeypatch):
    """Answering on a guess where a fact was missing fails the case."""
    row = graded(monkeypatch, ASK_CASE, ANSWERED, {"covered": [1, 1], "options_ok": True})
    assert (row["asked"], row["ask_ok"], row["missing_covered"]) == (False, False, None)


def test_a_should_answer_case_passes_when_the_agent_answers(monkeypatch):
    row = graded(monkeypatch, ANSWER_CASE, ANSWERED, {})
    assert (row["asked"], row["ask_ok"]) == (False, True)


def test_a_should_answer_case_fails_when_the_agent_asks(monkeypatch):
    """Asking where nothing that changes the answer is missing fails the case."""
    row = graded(monkeypatch, ANSWER_CASE, ASKED, {"options_ok": True})
    assert (row["asked"], row["ask_ok"]) == (True, False)


def test_the_judges_view_of_the_options_is_reported(monkeypatch):
    row = graded(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 1], "options_ok": False})
    assert row["options_ok"] is False


def test_the_graded_row_keeps_the_card(monkeypatch):
    row = graded(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 1], "options_ok": True})
    assert row["questions"] == [{"question": "What will it be used for?", "options": ["A home"]},
                                {"question": "How large?", "options": []}]


def test_a_run_that_answered_needs_no_judge(monkeypatch):
    """Whether the agent asked is read from the run; the judge is only called about a card."""
    def no_judge():
        raise AssertionError("no judge call expected")
    monkeypatch.setattr(bench, "get_openai_client", no_judge)
    assert bench.grade_asked(ANSWER_CASE, ANSWERED, "judge")["ask_ok"] is True


# --- the follow-up answer ---------------------------------------------------------------------------------------

def test_the_follow_up_answers_without_asking_again(monkeypatch):
    """After the scripted reply the agent answers: it cannot ask a second card."""
    client = AskIfAllowedClient()
    monkeypatch.setattr(agentic.agent, "get_openai_client", lambda: client)
    run = bench.follow_up(ASK_CASE, ASKED, tools=None, model="test/model")
    assert (run.questions, run.answer) == ([], "A permanent home needs bygglov.")


def test_the_follow_up_sees_the_question_the_card_and_the_reply(monkeypatch):
    """The follow-up continues the conversation: the case's question, the card, then the scripted reply."""
    client = AskIfAllowedClient()
    monkeypatch.setattr(agentic.agent, "get_openai_client", lambda: client)
    bench.follow_up(ASK_CASE, ASKED, tools=None, model="test/model")
    seen = client.inputs[0]
    assert all(text in seen for text in (ASK_CASE["question"], ASKED.answer, ASK_CASE["reply"]))


# --- the summary and its threshold ------------------------------------------------------------------------------

def rows(expect: str, ok: int, failed: int, lang: str = "en", points: float = 0.8) -> list[dict]:
    return [{"expect": expect, "lang": lang, "ask_ok": i < ok, "points": points} for i in range(ok + failed)]


def test_the_eval_passes_at_95_percent_on_both_halves():
    summary = bench.missing_info_summary(rows("ask", 19, 1) + rows("answer", 19, 1))
    assert (summary["ask"]["rate"], summary["answer"]["rate"], summary["passed"]) == (0.95, 0.95, True)


def test_the_eval_fails_below_95_percent_on_the_should_ask_half():
    assert bench.missing_info_summary(rows("ask", 18, 2) + rows("answer", 20, 0))["passed"] is False


def test_the_eval_fails_below_95_percent_on_the_should_answer_half():
    assert bench.missing_info_summary(rows("ask", 20, 0) + rows("answer", 18, 2))["passed"] is False


def test_the_eval_fails_without_should_ask_cases():
    summary = bench.missing_info_summary(rows("answer", 20, 0))
    assert (summary["ask"]["rate"], summary["passed"]) == (None, False)


def test_the_eval_reports_each_question_language():
    summary = bench.missing_info_summary(rows("ask", 10, 0, "sv") + rows("ask", 5, 5, "en")
                                         + rows("answer", 10, 0, "sv") + rows("answer", 10, 0, "en"))
    assert (summary["by_lang"]["sv"]["ask"], summary["by_lang"]["en"]["ask"]) == (1.0, 0.5)


def test_the_eval_fails_when_answer_scores_drop_below_the_baseline():
    """The should-answer half must answer as well as before the change."""
    summary = bench.missing_info_summary(rows("ask", 20, 0) + rows("answer", 20, 0, points=0.7), baseline_points=0.8)
    assert (summary["answer"]["points_ok"], summary["passed"]) == (False, False)


def test_answer_scores_on_par_with_the_baseline_pass():
    summary = bench.missing_info_summary(rows("ask", 20, 0) + rows("answer", 20, 0, points=0.8), baseline_points=0.8)
    assert (summary["answer"]["points_ok"], summary["passed"]) == (True, True)


# --- the case set -----------------------------------------------------------------------------------------------

@pytest.fixture
def cases() -> list[dict]:
    """The set, or none while it is not written."""
    return read_jsonl(bench.MISSING_INFO_PATH) if bench.MISSING_INFO_PATH.exists() else []


@pytest.mark.parametrize("expect", ["ask", "answer"])
def test_the_set_has_50_cases_per_half(cases, expect):
    assert sum(case["expect"] == expect for case in cases) == 50


@pytest.mark.parametrize(("expect", "lang"), [("ask", "sv"), ("ask", "en"), ("answer", "sv"), ("answer", "en")])
def test_each_half_has_25_cases_per_language(cases, expect, lang):
    assert sum(case["expect"] == expect and case["lang"] == lang for case in cases) == 25


def test_every_should_ask_case_names_its_missing_facts_reply_and_key_points(cases):
    asking_cases = [case for case in cases if case["expect"] == "ask"]
    assert asking_cases and all(case["missing"] and case["reply"] and case["key_points"] for case in asking_cases)


def test_every_should_answer_case_has_key_points(cases):
    answering_cases = [case for case in cases if case["expect"] == "answer"]
    assert answering_cases and all(case["key_points"] for case in answering_cases)


def test_case_ids_are_unique(cases):
    assert cases and len({case["id"] for case in cases}) == len(cases)
