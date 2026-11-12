"""Unit tests for agentic.bench: the language and quote checks of a graded answer, and the bilingual cases file. A fake
judge model: no API call."""

import json
from pathlib import Path

import pytest

import agentic.agent
from agentic import bench
from agentic.agent import AgentRun, AskedQuestion
from corpus.common import read_jsonl
from tests.unit.agentic.judge_client import JudgeClient
from tests.unit.agentic.test_agent_ask_user import AskIfAllowedClient

SOURCE = "Det krävs bygglov för nybyggnad."
SV_CASE = {"id": "x-sv", "lang": "sv", "question": "Behöver jag bygglov för en friggebod?", "key_points": ["a"],
           "verdicts": []}
EN_CASE = {"id": "x-en", "lang": "en", "question": "Do I need a permit for a shed?", "key_points": ["a"], "verdicts": []}
SWEDISH_ANSWER = ("**Bedömning:** Ja, du behöver bygglov för att uppföra en ny byggnad på din tomt, "
                  "och kommunen prövar ansökan mot detaljplanen [c:aa11bb22cc33dd44].")
ENGLISH_ANSWER = ("**Verdict:** Yes, you need a building permit for a new building on your plot, and the kommun "
                  "checks the application against the detaljplan [c:aa11bb22cc33dd44].")
ENGLISH_ANSWER_QUOTING = (f'**Verdict:** Yes. PBL says "{SOURCE}" ("A building permit is required for new '
                          f'construction.") [c:aa11bb22cc33dd44], so you need one before you build.')
BILINGUAL = Path(bench.__file__).resolve().parent / "cases_bilingual.jsonl"


def test_a_swedish_answer_is_ok_for_a_swedish_case():
    assert bench.answer_language_ok(SV_CASE, SWEDISH_ANSWER) is True


def test_an_english_answer_fails_a_swedish_case():
    assert bench.answer_language_ok(SV_CASE, ENGLISH_ANSWER) is False


def test_a_swedish_answer_fails_an_english_case():
    assert bench.answer_language_ok(EN_CASE, SWEDISH_ANSWER) is False


def test_an_english_answer_quoting_swedish_law_is_english():
    """Swedish quotes in an English answer do not make it Swedish."""
    assert bench.answer_language_ok(EN_CASE, ENGLISH_ANSWER_QUOTING) is True


def test_an_answer_in_a_third_language_fails_an_english_case():
    """A German question must get an English answer: a German one is in the wrong language."""
    german = ("**Antwort:** Grundsätzlich ist ein Ferienhaus 40 Meter vom Seeufer nicht ausgeschlossen, aber es ist "
              "auch nicht allein deshalb zulässig, weil das Grundstück außerhalb eines Bebauungsplans liegt.")
    assert bench.answer_language_ok(EN_CASE, german) is False


def test_a_case_without_lang_is_english():
    assert bench.answer_language_ok({"id": "x", "question": "q", "key_points": ["a"]}, ENGLISH_ANSWER) is True


def test_an_empty_answer_is_never_in_the_right_language():
    assert bench.answer_language_ok(EN_CASE, "") is False


def test_a_quote_found_in_a_source_is_verbatim():
    assert bench.quotes_verbatim(f'PBL says "{SOURCE}"', [f"9 kap. 2 §  {SOURCE} Det gäller även tillbyggnad."])


def test_a_reworded_quote_is_not_verbatim():
    assert bench.quotes_verbatim('PBL says "Bygglov krävs för nybyggnad."', [SOURCE]) is False


def test_a_block_quote_is_checked():
    assert bench.quotes_verbatim("> Bygglov krävs alltid för nybyggnad.\n\nSo you need one.", [SOURCE]) is False


def test_a_quoted_block_line_is_checked_without_its_reference():
    """A block quote line holding a quote and its law reference is checked on the quote alone."""
    assert bench.quotes_verbatim(f'> "{SOURCE}" (PBL 9 kap. 2 §)', [SOURCE]) is True


def test_a_quote_spanning_block_lines_is_checked_without_its_reference():
    source = f"{SOURCE} Det gäller även tillbyggnad."
    answer = f'> "{SOURCE}\n> Det gäller även tillbyggnad." (PBL 9 kap. 2 §)'
    assert bench.quotes_verbatim(answer, [source]) is True


def test_punctuation_and_case_do_not_break_a_verbatim_quote():
    assert bench.quotes_verbatim('PBL says "det krävs bygglov, för nybyggnad"', [SOURCE]) is True


def test_an_answer_without_quotes_passes_the_quote_check():
    assert bench.quotes_verbatim(ENGLISH_ANSWER, [SOURCE]) is True


def test_an_english_translation_in_quotes_is_not_checked():
    """A quoted English translation next to its Swedish original does not fail the check."""
    assert bench.quotes_verbatim(ENGLISH_ANSWER_QUOTING, [SOURCE]) is True


class CitedTools:
    def get_chunk(self, chunk_id):
        return {"chunk_id": chunk_id, "header": "PBL 9 kap. 2 §", "text": SOURCE} if chunk_id == "aa11bb22cc33dd44" else None


def graded(monkeypatch, case, answer):
    grade = {"verdict": "none", "points": [2], "unsupported_claims": 0, "comment": ""}
    monkeypatch.setattr(bench, "get_openai_client", lambda: JudgeClient(grade))
    return bench.grade_answer(case, answer, CitedTools(), "judge")


def test_a_graded_row_carries_the_language_check(monkeypatch):
    assert graded(monkeypatch, SV_CASE, SWEDISH_ANSWER)["language_ok"] is True


def test_a_graded_row_carries_the_quote_check(monkeypatch):
    """The quotes are checked against the chunks the answer cites."""
    assert graded(monkeypatch, EN_CASE, ENGLISH_ANSWER_QUOTING)["quotes_ok"] is True


def test_a_graded_row_carries_the_case_language(monkeypatch):
    assert graded(monkeypatch, SV_CASE, SWEDISH_ANSWER)["lang"] == "sv"


@pytest.fixture(scope="module")
def bilingual_cases() -> list[dict]:
    return [json.loads(line) for line in BILINGUAL.read_text().splitlines() if line.strip()]


def test_every_ordinary_bilingual_case_has_a_twin_in_the_other_language(bilingual_cases):
    pairs: dict = {}
    for case in bilingual_cases:
        if not case.get("hard"):
            pairs.setdefault(case["pair"], set()).add(case["lang"])
    assert pairs and all(langs == {"sv", "en"} for langs in pairs.values())


def test_there_are_at_least_24_pairs(bilingual_cases):
    assert len({case["pair"] for case in bilingual_cases if not case.get("hard")}) >= 24


def test_the_hard_cases_are_marked(bilingual_cases):
    assert sum(1 for case in bilingual_cases if case.get("hard")) >= 8


# --- the missing-info eval (#91) -------------------------------------------------------------------------------------

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


def graded_card(monkeypatch, case, run, grade):
    monkeypatch.setattr(bench, "get_openai_client", lambda: JudgeClient(grade))
    return bench.grade_asked(case, run, "judge")


def test_a_should_ask_case_passes_when_the_card_asks_for_every_missing_fact(monkeypatch):
    row = graded_card(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 1], "options_ok": True})
    assert (row["asked"], row["missing_covered"], row["ask_ok"]) == (True, 1.0, True)


def test_a_should_ask_case_fails_when_a_missing_fact_is_not_asked_for(monkeypatch):
    """Asking, but not for everything that changes the answer, is not enough."""
    row = graded_card(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 0], "options_ok": True})
    assert (row["missing_covered"], row["ask_ok"]) == (0.5, False)


def test_a_should_ask_case_fails_when_the_agent_answers(monkeypatch):
    """Answering on a guess where a fact was missing fails the case."""
    row = graded_card(monkeypatch, ASK_CASE, ANSWERED, {"covered": [1, 1], "options_ok": True})
    assert (row["asked"], row["ask_ok"], row["missing_covered"]) == (False, False, None)


def test_a_should_answer_case_passes_when_the_agent_answers(monkeypatch):
    row = graded_card(monkeypatch, ANSWER_CASE, ANSWERED, {})
    assert (row["asked"], row["ask_ok"]) == (False, True)


def test_a_should_answer_case_fails_when_the_agent_asks(monkeypatch):
    """Asking where nothing that changes the answer is missing fails the case."""
    row = graded_card(monkeypatch, ANSWER_CASE, ASKED, {"options_ok": True})
    assert (row["asked"], row["ask_ok"]) == (True, False)


def test_the_judges_view_of_the_options_is_reported(monkeypatch):
    row = graded_card(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 1], "options_ok": False})
    assert row["options_ok"] is False


def test_the_graded_row_keeps_the_card(monkeypatch):
    row = graded_card(monkeypatch, ASK_CASE, ASKED, {"covered": [1, 1], "options_ok": True})
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
    return list(read_jsonl(bench.MISSING_INFO_PATH)) if bench.MISSING_INFO_PATH.exists() else []


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
