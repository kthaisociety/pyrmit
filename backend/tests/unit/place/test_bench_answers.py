"""place.bench_answers: which jobs run, what the agent is sent per condition, the string-matched place facts and the
scores, with a fake agent, fake profile and fake judge. No real services (PCR-0011)."""

import json
from types import SimpleNamespace

import pytest

from place import bench_answers
from place.bench_answers import (
    AnswerBench,
    compare,
    facts_named,
    jobs,
    load_cases,
    prompt,
    run_bench,
    scores,
    summarise,
)
from place.context import NO_PIN_HINT

CASES = [
    {"id": "norby", "kommun": "0380", "pin": {"lat": 59.82, "lon": 17.61, "label": "Eksoppsvägen 37, Uppsala"},
     "question": "Kan jag bygga ett attefallshus på tomten?",
     "question_address": "Kan jag bygga ett attefallshus på Eksoppsvägen 37 i Uppsala?",
     "reference_place": "Property Uppsala Norby 114:1, inside detaljplan 0380-P90/6.",
     "facts": [{"label": "property", "any": ["Norby 114:1"]}, {"label": "detaljplan", "any": ["0380-P90/6", "Del av Norby"]}],
     "key_points": ["Names the plan.", "Says 30 m² needs no bygglov."], "vague": True, "conflict_with": "kvarnbo",
     "locked": "2026-10-25"},
    {"id": "kvarnbo", "kommun": "0380", "pin": {"lat": 59.84, "lon": 17.56, "label": "Kvarnbo 25, Uppsala"},
     "question": "Behöver jag lov för en gäststuga?", "question_address": "Behöver jag lov för en gäststuga på Kvarnbo 25?",
     "reference_place": "Property Uppsala Kvarnbo 1:1, outside detaljplan.", "facts": [], "key_points": ["Outside."],
     "locked": "2026-10-25"},
]
BY_ID = {case["id"]: case for case in CASES}


def fake_profile(lat, lon):
    return {"point": {"lat": lat, "lon": lon}, "covered": False}


def test_runs_pin_and_address_for_every_case_and_the_others_where_marked():
    assert sorted(jobs(CASES)) == sorted([("norby", "pin", 0), ("norby", "address", 0), ("norby", "vague", 0),
                                          ("norby", "conflict", 0), ("kvarnbo", "pin", 0), ("kvarnbo", "address", 0)])
    assert len(jobs(CASES, repeats=3)) == 18


def test_refuses_an_unlocked_case(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({**CASES[0], "locked": None}) + "\n")
    with pytest.raises(ValueError, match="norby"):
        load_cases(path)


def test_the_pin_condition_sends_the_place_before_the_question():
    typed, sent, place = prompt(CASES[0], "pin", BY_ID, fake_profile)
    assert typed == CASES[0]["question"]
    assert sent.startswith("[Place pinned by the user") and sent.endswith(typed)
    assert place and place in sent


def test_the_address_and_vague_conditions_send_no_place():
    for condition, question in (("address", "question_address"), ("vague", "question")):
        typed, sent, place = prompt(CASES[0], condition, BY_ID, fake_profile)
        assert typed == CASES[0][question]
        assert sent == f"{NO_PIN_HINT}\n\n{typed}" and place is None


def test_the_conflict_condition_pins_this_place_and_names_the_other():
    typed, sent, place = prompt(CASES[0], "conflict", BY_ID, fake_profile)
    assert typed == BY_ID["kvarnbo"]["question_address"]
    assert "59.82000, 17.61000" in sent and place


def test_facts_match_any_alias_ignoring_case():
    assert facts_named(CASES[0], "Fastigheten NORBY 114:1 ligger i planen Del av Norby.") == ["property", "detaljplan"]
    assert facts_named(CASES[0], "Inget om platsen.") == []


def test_asking_for_the_place_is_right_only_when_the_condition_expects_it():
    grade = {"points": [2, 1], "asks": True, "unsupported": 1, "wrong_place": 0}
    assert scores({"condition": "vague"}, grade)["asks_ok"] is True
    assert scores({"condition": "pin"}, grade) == {"points": 0.75, "asks_ok": False, "unsupported": 1, "wrong_place": 0}
    assert scores({"condition": "address"}, grade)["asks_ok"] is True  # a named address without a pin: ask for the pin


def fake_grade(case, condition, typed, answer, place_text, sources, cases_by_id, model):
    wanted = len(case["key_points"]) if condition in ("pin", "address") else 0
    return {"points": [2] * wanted, "unsupported": 0, "wrong_place": 0, "asks": condition in ("vague", "conflict"),
            "comment": "", "cost": 0.001, "model": model}


def fake_agent(question, tools, **kwargs):
    answer = "Norby 114:1 i Del av Norby." if "Eksoppsvägen" in question or "[Place" in question else "Var ligger det?"
    return SimpleNamespace(answer=answer, mode="verdict", seconds=1.0, first_token_s=0.5, usage={"cost": 0.01},
                           llm_calls=2, error=None, steps=[{"tool": "search"}], seen_chunks=[])


def make_bench(**kwargs):
    return AnswerBench(CASES, run_agent=fake_agent, tools=object(), profile_of=fake_profile,
                       sources_of=lambda answer, seen: "", grade=fake_grade, **kwargs)


def test_a_run_saves_every_row_with_its_grade_and_summary(tmp_path):
    result = run_bench(CASES, repeats=1, workers=1, bench=make_bench(), out_dir=tmp_path, label="t")
    saved = json.loads((tmp_path / result["path"].split("/")[-1]).read_text())
    assert result["path"].endswith("-t.json") and len(saved["rows"]) == 6
    pin = saved["summary"]["pin"]
    assert pin["points"] == 1.0 and pin["asks_ok"] == 1.0 and pin["answers"] == 2
    assert saved["summary"]["vague"]["asks_ok"] == 1.0
    assert saved["summary"]["by_case"]["norby"]["address"]["facts"] == 1.0


def test_a_run_stops_starting_answers_once_the_budget_is_spent(tmp_path):
    result = run_bench(CASES, repeats=1, workers=1, bench=make_bench(max_cost=0.015), out_dir=tmp_path)
    assert len(result["rows"]) == 2  # the second answer passes the budget


def test_resume_skips_the_answers_already_saved(tmp_path):
    first = run_bench(CASES, conditions=("pin",), repeats=1, workers=1, bench=make_bench(), out_dir=tmp_path)
    again = run_bench(CASES, repeats=1, workers=1, bench=make_bench(), resume=first["path"])
    assert len(again["rows"]) == 6
    assert [row["condition"] for row in again["rows"]].count("pin") == 2


def test_rejudge_adds_a_second_judges_grades(tmp_path):
    first = run_bench(CASES, conditions=("pin",), repeats=1, workers=1, bench=make_bench(), out_dir=tmp_path)
    result = bench_answers.rejudge(first["path"], "other/judge", CASES, bench=make_bench())
    assert all("other/judge" in row["grades"] for row in result["rows"])
    assert result["summaries"]["other/judge"]["pin"]["points"] == 1.0


def test_summary_counts_a_failed_run_as_an_error():
    rows = [{"case": "norby", "condition": "pin", "repeat": 0, "error": "Timeout", "facts_share": None}]
    assert summarise(rows, "j")["pin"]["errors"] == 1


def test_the_pin_condition_can_carry_the_permits_statute_text():
    profile = lambda lat, lon: {**fake_profile(lat, lon)}
    _, sent, _ = prompt(CASES[0], "pin", BY_ID, profile, law_text=lambda law, section: "text")
    assert sent.startswith("[Place pinned")  # an uncovered place has no permits, so no statute text


# --- general questions, and two runs side by side --------------------------------------------------------------------

GENERAL = {**CASES[0], "question_general": "Vad är en attefallsåtgärd?", "vague": False, "conflict_with": None,
           "facts": [{"label": "plan", "any": ["0380-P90/6"]}], "key_points": ["Names the plan."]}


def general_grade(case, condition, typed, answer, place_text, sources, cases_by_id, model):
    return {"points": [2], "unsupported": 0, "wrong_place": 0, "asks": False, "offers_pin": condition == "general",
            "comment": "", "cost": 0.001, "model": model}


def general_agent(question, tools, **kwargs):
    return SimpleNamespace(answer="En attefallsåtgärd, 0380-P90/6.", mode="explain", seconds=1.0, first_token_s=0.5,
                           usage={"cost": 0.01}, llm_calls=2, error=None, seen_chunks=[], choices=[], offer_pin=False,
                           steps=[{"tool": "read_plan"}, {"tool": "search"}, {"tool": "grep"}])


@pytest.fixture
def general_run(tmp_path):
    bench = AnswerBench([GENERAL], run_agent=general_agent, tools=object(), profile_of=fake_profile,
                        sources_of=lambda answer, seen: "", grade=general_grade)
    return run_bench([GENERAL], repeats=1, workers=1, bench=bench, out_dir=tmp_path)["summary"]


def test_a_case_with_a_general_question_runs_it_with_and_without_the_pin():
    assert {("norby", "general", 0), ("norby", "general_pin", 0)} <= set(jobs([GENERAL]))


def test_a_case_without_a_general_question_does_not():
    assert not [job for job in jobs(CASES) if job[1].startswith("general")]


def test_the_general_condition_sends_the_hint_and_the_question():
    typed, sent, place = prompt(GENERAL, "general", {"norby": GENERAL}, fake_profile)
    assert (typed, sent, place) == (GENERAL["question_general"], f"{NO_PIN_HINT}\n\n{GENERAL['question_general']}", None)


def test_the_pinned_general_condition_sends_the_place_before_the_question():
    _, sent, place = prompt(GENERAL, "general_pin", {"norby": GENERAL}, fake_profile)
    assert sent == f"{place}\n\n{GENERAL['question_general']}"


def test_an_address_the_answer_asks_to_pin_has_no_points_to_grade():
    """Asking for the pin is the right answer to a named address, so its key points do not count against it."""
    asked = scores({"condition": "address"}, {"points": [0], "asks": True, "unsupported": 0, "wrong_place": 0})
    assert asked["points"] is None


def test_an_address_answered_without_asking_keeps_its_points():
    answered = scores({"condition": "address"}, {"points": [2], "asks": False, "unsupported": 0, "wrong_place": 0})
    assert answered["points"] == 1.0


@pytest.mark.parametrize("condition", ["general", "general_pin"])
def test_a_general_question_should_not_ask_where(condition):
    grade = {"points": [], "asks": True, "unsupported": 0, "wrong_place": 0}
    assert scores({"condition": condition}, grade)["asks_ok"] is False


def test_the_summary_counts_the_calls_that_look_for_documents(general_run):
    """read_plan reads, so it is a tool call but not a search."""
    assert (general_run["pin"]["tool_calls"], general_run["pin"]["searches"]) == (3.0, 2.0)


def test_the_summary_counts_the_offers_to_pin(general_run):
    assert (general_run["general"]["offers_pin"], general_run["general_pin"]["offers_pin"]) == (1.0, 0.0)


def test_the_summary_counts_the_plan_brought_into_a_general_answer(general_run):
    """An answer to a pinned general question that names the place's plan shows in its facts."""
    assert general_run["general_pin"]["facts"] == 1.0


def result_of(judge, tool_calls, conditions=("pin",), **row):
    grade = {"points": 1.0, "asks": False, "asks_ok": True, "unsupported": 0, "wrong_place": 0}
    return {"judge": judge, "rows": [{"condition": condition, "case": "norby", "tool_calls": tool_calls, "answer": "x",
                                      "grades": {judge: grade}, **row} for condition in conditions]}


def test_compare_puts_a_metric_of_two_runs_side_by_side():
    assert compare(result_of("a", 9), result_of("a", 3))["pin"]["tool_calls"] == {"before": 9.0, "after": 3.0}


def test_compare_reads_each_run_under_its_own_judge():
    assert compare(result_of("a", 9), result_of("b", 3))["pin"]["points"] == {"before": 1.0, "after": 1.0}


def test_compare_leaves_out_a_condition_only_one_run_has():
    assert "general" not in compare(result_of("a", 1), result_of("a", 1, ("pin", "general")))


def test_compare_leaves_a_metric_an_older_run_did_not_record_empty():
    """A result file from before a metric existed gives None on its side."""
    compared = compare(result_of("a", 1), result_of("a", 1, tools=["search"]))
    assert compared["pin"]["searches"] == {"before": None, "after": 1.0}


def test_the_real_cases_carry_general_questions():
    """The locked cases hold general questions, so the conditions run on the real file."""
    assert sum(bool(case.get("question_general")) for case in load_cases()) >= 3
