"""agentic.claim_referee: the locked question set, the run that saves answers with the claim check's verdicts, the
referee's labels in a frozen reference, the agreement report, the recheck, the rule that keeps a change, the tune run
and the prompts and labels for new stretches, the second referee, the disputed stretches, the known-answer cases, the
measure, the rule that lets a change win and the improve run, with a fake agent, a fake check and a fake referee. No real services (PCR-0011)."""

import copy
import json
import re
from dataclasses import asdict

import pytest

from agentic import claim_check, claim_referee
from agentic.claim_check import CheckOptions
from place.bench_answers import load_cases
from tests.unit.agentic.claims import (
    CHUNKS,
    EARLIER,
    FEE,
    HOUSE,
    TWO_SENTENCES,
    A,
    B,
    get_chunk,
)
from tests.unit.agentic.referees import (
    AREA,
    NEEDED,
    PARTLY,
    PERMIT,
    SHORE,
    SOURCES,
    TIP,
    WRONG,
    H,
    N,
    O,
    answered,
    disputed_rows,
    first_only_rows,
    known,
    known_for,
    labelled,
    labels_reply,
    measure_result,
    measured,
    numbers,
    run_second,
    scripted_check,
    split_result,
    two_referee_reference,
)

UNCITED = "Kontakta kommunen för mer"
ANSWER = f"{HOUSE} [c:{A}]. {FEE} [c:{B}]. {UNCITED}."
PLACE = "Property Uppsala Norby 114:1, inside detaljplan 0380-P90/6."


def fake_check(verdicts: dict[str, str], status: str = "checked", calls: list | None = None):
    """The claim check, scripted: each stretch whose text holds a key of `verdicts` gets that verdict, the others are
    left out (as a failed call leaves them out)."""
    def check(answer, seen, place_text):
        if calls is not None:
            calls.append(answer)
        if status != "checked":
            return {"status": status, "claims": []}
        claims = []
        for text, chunk_ids in ((HOUSE, [A]), (FEE, [B]), (UNCITED, [])):
            for key, verdict in verdicts.items():
                if key in text and text in answer:
                    claims.append({"text": text, "verdict": verdict, "chunk_ids": chunk_ids if verdict != "uncited" else []})
        return {"status": "checked", "claims": claims}
    return check


def fake_answer(calls: list, questions=()):
    def answer(item):
        calls.append(item["id"])
        if questions:
            return {"answer": "", "questions": list(questions), "seen": [], "place_text": None, "mode": None}
        return {"answer": ANSWER, "questions": [], "seen": [A, B], "place_text": PLACE, "mode": "explain"}
    return answer


def item(text, check, chunk_ids=(), **referee) -> dict:
    out = {"text": text, "cited": bool(chunk_ids), "chunk_ids": list(chunk_ids), "check": check}
    if referee:
        out["referee"] = referee
    return out


def row(items, condition="pin", split="validation", case="norby", status="answered", check="checked", answer=ANSWER,
        **extra) -> dict:
    return {"id": f"{case}:{condition}", "case": case, "condition": condition, "split": split, "answer": answer,
            "seen": [A, B], "place_text": PLACE, "questions": [], "status": status, "check": check, "items": items,
            **extra}


def reply(*entries) -> str:
    return json.dumps({"items": [{"n": n, **entry} for n, entry in enumerate(entries, start=1)]})


GOOD = reply({"supported": "yes", "missing": "", "needs_source": "fact", "split": "one"},
             {"supported": "no", "missing": "the 12 000 kr", "needs_source": "fact", "split": "one"},
             {"needed": False})


def referee(rows, *answers, events=None):
    """Run the referee with a scripted reply per call (the last one repeats); returns the prompts sent."""
    prompts, events = [], events if events is not None else []

    def ask(model, prompt):
        events.append("ask")
        prompts.append(prompt)
        return answers[min(len(prompts) - 1, len(answers) - 1)], 0.01

    stats = claim_referee.referee(rows, get_chunk, ask=ask, chunk_text=lambda chunk: chunk["text"],
                                  announce=lambda estimate: events.append(("estimate", estimate)), workers=1)
    return prompts, stats


# --- the question set ---------------------------------------------------------------------------------------------

def test_the_question_set_splits_by_case_into_tuning_and_validation():
    """Every place case is asked with a pin and with the address, every general question once, and each case is
    either tuning or validation as a whole: 10 and 5 place cases, 10 and 5 general questions."""
    items = claim_referee.question_set(load_cases(), claim_referee.load_questions())
    assert len(items) == 45
    by_case: dict[str, set] = {}
    for entry in items:
        by_case.setdefault(entry["case"], set()).add(entry["split"])
    assert all(len(splits) == 1 for splits in by_case.values())
    place = [entry for entry in items if entry["condition"] != "general"]
    general = [entry for entry in items if entry["condition"] == "general"]
    assert sorted({entry["condition"] for entry in place}) == ["address", "pin"]
    for chosen, tuning, validation in ((place, 20, 10), (general, 10, 5)):
        assert sum(entry["split"] == "tuning" for entry in chosen) == tuning
        assert sum(entry["split"] == "validation" for entry in chosen) == validation


def test_refuses_an_unlocked_question_set(tmp_path):
    """A question set without its lock date is refused: questions written after seeing answers are no reference."""
    path = tmp_path / "questions.json"
    data = json.loads(claim_referee.QUESTIONS_PATH.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "locked": None}), encoding="utf-8")
    with pytest.raises(ValueError, match="locked"):
        claim_referee.load_questions(path)


# --- the run -------------------------------------------------------------------------------------------------------

ITEMS = [{"id": "norby:pin", "case": "norby", "condition": "pin", "split": "tuning"},
         {"id": "general-1:general", "case": "general-1", "condition": "general", "split": "validation"}]


def test_the_run_saves_every_answer_with_the_checks_verdicts(tmp_path):
    """Each question is answered once and saved with every stretch of its answer and the check's verdict on it."""
    path, asked = tmp_path / "answers.json", []
    claim_referee.run_set(ITEMS, fake_answer(asked), fake_check({"house": "supported", "fee": "unsupported",
                                                                  "Kontakta": "uncited"}), path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert asked == ["norby:pin", "general-1:general"]
    assert saved["check_version"] == claim_referee.check_version()
    first = saved["rows"][0]
    assert first["answer"] == ANSWER and first["split"] == "tuning" and first["status"] == "answered"
    assert [(i["text"], i["cited"], i["check"]) for i in first["items"]] == [
        (HOUSE, True, "supported"), (FEE, True, "unsupported"), (UNCITED, False, "uncited")]


def test_an_interrupted_run_resumes_without_answering_again(tmp_path):
    """A saved question is not answered again when the run resumes."""
    path, asked = tmp_path / "answers.json", []
    claim_referee.run_set(ITEMS[:1], fake_answer(asked), fake_check({"house": "supported"}), path)
    claim_referee.run_set(ITEMS, fake_answer(asked), fake_check({"house": "supported"}), path)
    assert asked == ["norby:pin", "general-1:general"]
    assert [r["id"] for r in json.loads(path.read_text(encoding="utf-8"))["rows"]] == ["norby:pin", "general-1:general"]


def test_an_ask_user_answer_has_no_claims_and_is_only_counted(tmp_path):
    """A question card is saved without claims, never put to the check, and counted in the report."""
    path, asked, checked = tmp_path / "answers.json", [], []
    claim_referee.run_set(ITEMS[:1], fake_answer(asked, questions=[{"question": "Vilken fastighet?"}]),
                          fake_check({}, calls=checked), path)
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    assert checked == [] and rows[0]["status"] == "asked" and rows[0]["items"] == []
    assert claim_referee.summary(rows)["asked"] == 1


def test_a_failed_check_call_counts_as_not_checked(tmp_path):
    """A claim the check could not judge, the whole check failing or one call missing, is "not checked", never
    unsupported, and stays out of the agreement."""
    path, asked = tmp_path / "answers.json", []
    claim_referee.run_set(ITEMS[:1], fake_answer(asked), fake_check({}, status="failed"), path)
    claim_referee.run_set(ITEMS[1:], fake_answer(asked), fake_check({"house": "supported"}), path)
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    assert [i["check"] for i in rows[0]["items"]] == ["not_checked", "not_checked", "not_checked"]
    assert [i["check"] for i in rows[1]["items"] if i["cited"]] == ["supported", "not_checked"]
    for entry in rows[1]["items"][1:2]:
        entry["referee"] = {"supported": "no", "missing": "", "needs_source": "fact", "split": "one"}
    numbers = claim_referee.summary(rows)
    assert numbers["not_checked"] == 4
    assert numbers["validation"]["support"]["claims"] == 0


# --- the referee ---------------------------------------------------------------------------------------------------

def test_the_referee_labels_every_claim_and_uncited_sentence():
    """The referee reads each claim with the full text of its cited chunks and the place data, and each claim and
    uncited sentence gets its labels."""
    rows = [row([item(HOUSE, "supported", [A]), item(FEE, "unsupported", [B]), item(UNCITED, "passed")])]
    prompts, _ = referee(rows, GOOD)
    assert CHUNKS[A]["text"] in prompts[0] and CHUNKS[B]["text"] in prompts[0] and PLACE in prompts[0]
    labels = [entry["referee"] for entry in rows[0]["items"]]
    assert labels[0] == {"supported": "yes", "missing": "", "needs_source": "fact", "split": "one"}
    assert labels[1]["supported"] == "no" and labels[1]["missing"] == "the 12 000 kr"
    assert labels[2] == {"needed": False}


def test_the_reference_is_saved_tagged_with_the_check_version(tmp_path):
    """The frozen reference holds the answers, the check's verdicts and the referee's labels, under the check's
    version."""
    rows = [row([item(HOUSE, "supported", [A], supported="yes", missing="", needs_source="fact", split="one")])]
    path = tmp_path / "reference.json"
    claim_referee.freeze(rows, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["check_version"] == claim_referee.check_version() and saved["rows"] == rows
    assert saved["referee_model"] == claim_referee.REFEREE_MODEL


def test_the_referee_cost_is_estimated_and_shown_before_any_call():
    """The estimate (tokens and dollars at the referee's price) is announced before the first call."""
    rows = [row([item(HOUSE, "supported", [A]), item(FEE, "unsupported", [B]), item(UNCITED, "passed")])]
    events = []
    referee(rows, GOOD, events=events)
    assert isinstance(events[0], tuple) and events[0][0] == "estimate" and "ask" in events[1:]
    estimate = events[0][1]
    assert estimate["calls"] == 1 and estimate["input_tokens"] > 0 and estimate["output_tokens"] > 0
    assert estimate["dollars"] == pytest.approx((estimate["input_tokens"] * claim_referee.PRICE_IN
                                                 + estimate["output_tokens"] * claim_referee.PRICE_OUT) / 1e6)


def test_an_unreadable_referee_reply_is_retried_once():
    """An unreadable reply is asked again once, and the second reply's labels are kept."""
    rows = [row([item(HOUSE, "supported", [A]), item(FEE, "unsupported", [B]), item(UNCITED, "passed")])]
    prompts, _ = referee(rows, "not json", GOOD)
    assert len(prompts) == 2 and all("referee" in entry for entry in rows[0]["items"])


def test_a_twice_unreadable_reply_counts_as_no_referee_verdict():
    """After a second unreadable reply the answer has no referee verdict, which the report counts apart."""
    rows = [row([item(HOUSE, "supported", [A]), item(FEE, "unsupported", [B]), item(UNCITED, "passed")])]
    prompts, stats = referee(rows, "not json")
    assert len(prompts) == 2 and stats["no_verdict"] == 1
    assert rows[0]["referee"] == "no_verdict" and not any("referee" in entry for entry in rows[0]["items"])
    numbers = claim_referee.summary(rows)
    assert numbers["no_verdict"] == 1 and numbers["validation"]["support"]["claims"] == 0


# --- the report ----------------------------------------------------------------------------------------------------

def labelled_rows() -> list[dict]:
    yes = {"supported": "yes", "missing": "", "needs_source": "fact", "split": "one"}
    return [
        row([item(HOUSE, "supported", [A], **yes),
             item(FEE, "supported", [B], supported="no", missing="the fee", needs_source="fact", split="several"),
             item(UNCITED, "passed", needed=True)], condition="pin", split="tuning"),
        row([item(HOUSE, "supported", [A], **{**yes, "needs_source": "advice"}),
             item(FEE, "unsupported", [B], supported="no", missing="the fee", needs_source="fact", split="one")],
            condition="address", split="validation"),
        row([item(HOUSE, "unsupported", [A], **{**yes, "split": "part"})], condition="general", split="validation",
            case="general-1"),
    ]


def test_the_report_gives_agreement_per_condition_form_and_split_label_for_each_split():
    """Agreement (check "supported" when the referee says "yes") per condition, form and split label, tuning and
    validation apart."""
    numbers = claim_referee.summary(labelled_rows())
    tuning, validation = numbers["tuning"], numbers["validation"]
    assert tuning["support"] == {"claims": 2, "agree": 1, "share": 0.5}
    assert validation["support"] == {"claims": 3, "agree": 2, "share": pytest.approx(2 / 3)}
    assert validation["condition"]["address"]["share"] == 1.0 and validation["condition"]["general"]["share"] == 0.0
    assert tuning["form"]["fact"]["claims"] == 2 and validation["form"]["advice"]["agree"] == 1
    assert tuning["split"]["several"]["agree"] == 0 and validation["split"]["part"]["claims"] == 1
    assert tuning["uncited"] == {"claims": 1, "agree": 0, "share": 0.0}


def test_the_report_lists_every_disagreement():
    """Every claim and uncited sentence where check and referee disagree is listed, with what lacks a source."""
    numbers = claim_referee.summary(labelled_rows())
    listed = {(d["id"], d["text"], d["check"], d["referee"]) for d in numbers["disagreements"]}
    assert listed == {("norby:pin", FEE, "supported", "no"), ("norby:pin", UNCITED, "passed", "needed"),
                      ("general-1:general", HOUSE, "unsupported", "yes")}
    text = claim_referee.report(labelled_rows())
    assert "Tuning" in text and "Validation" in text and "the fee" in text and UNCITED in text


# --- the recheck ---------------------------------------------------------------------------------------------------

YES = {"supported": "yes", "missing": "", "needs_source": "fact", "split": "one"}
NO = {"supported": "no", "missing": "the 12 000 kr", "needs_source": "fact", "split": "one"}
NOT_NEEDED = {"needed": False}


def frozen_items() -> list[dict]:
    """The frozen verdicts and labels of ANSWER: the check backed both claims (the referee: yes, no) and passed the
    uncited sentence (the referee: no source needed). Agreement 2 of 3."""
    return [item(HOUSE, "supported", [A], **YES), item(FEE, "supported", [B], **NO), item(UNCITED, "passed", **NOT_NEEDED)]


def reference() -> dict:
    return {"date": "2026-11-20T10:00:00+01:00", "check_version": "old", "referee_model": "referee",
            "rows": [row(frozen_items()), row(frozen_items(), split="tuning", case="kvarnbo")]}


def test_the_recheck_gives_both_splits():
    """The recheck runs the check on the answers of both splits and gives each split's numbers."""
    out = claim_referee.recheck(reference(), fake_check({"house": "supported", "fee": "unsupported"}))
    assert out["tuning"]["now"]["all"]["claims"] == 3 and out["validation"]["now"]["all"]["claims"] == 3


def test_the_recheck_gives_agreement_on_cited_uncited_and_all_items():
    """Each split's agreement now is given on cited claims, uncited sentences and all items."""
    now = claim_referee.recheck(reference(), fake_check({"house": "supported", "fee": "unsupported"}))["validation"]["now"]
    assert (now["cited"]["share"], now["uncited"]["share"], now["all"]["share"]) == (1.0, 1.0, 1.0)


def test_the_recheck_sets_the_frozen_agreement_next_to_the_current_one():
    """Each split gives the frozen agreement of the reference next to the current one."""
    out = claim_referee.recheck(reference(), fake_check({"house": "supported", "fee": "unsupported"}))
    assert out["validation"]["frozen"]["all"]["agree"] == 2 and out["validation"]["frozen"]["all"]["claims"] == 3


def test_the_recheck_names_the_frozen_and_the_current_check_version():
    """The recheck's result names the check version the reference was frozen with and the version run now."""
    out = claim_referee.recheck(reference(), fake_check({"house": "supported", "fee": "unsupported"}))
    assert (out["frozen_version"], out["version"]) == ("old", claim_referee.check_version())


def test_a_no_claim_the_check_flags_counts_as_still_flagged():
    """A claim the referee says its sources do not back, and the check calls unsupported, is still flagged."""
    out = claim_referee.recheck(reference(), fake_check({"house": "supported", "fee": "unsupported"}))
    assert out["validation"]["no_still_flagged"] == 1.0


def test_a_skipped_claim_counts_as_not_flagged():
    """A claim the check skipped counts as not flagged: a referee "no" claim skipped is not still flagged."""
    out = claim_referee.recheck(reference(), fake_check({"house": "supported", "fee": "skipped"}))
    assert (out["validation"]["no_still_flagged"], out["validation"]["now"]["cited"]["share"]) == (0.0, 0.5)


def test_a_claim_the_check_left_out_counts_as_not_checked():
    """A cited claim the check gave no verdict (its call failed) stays out of the agreement."""
    out = claim_referee.recheck(reference(), fake_check({"house": "supported"}))
    assert out["validation"]["now"]["cited"]["claims"] == 1


def test_the_recheck_leaves_the_reference_unchanged():
    """The reference's rows, verdicts and labels are the same after a recheck."""
    ref = reference()
    before = copy.deepcopy(ref)
    claim_referee.recheck(ref, fake_check({"house": "unsupported", "fee": "skipped"}))
    assert ref == before


def test_the_recheck_records_its_options():
    """The recheck's result names the options the check ran with."""
    out = claim_referee.recheck(reference(), fake_check({"house": "supported"}), options=CheckOptions(skip_hedges=True))
    assert out["options"]["skip_hedges"] is True and out["options"]["question"] == "strict"


def per_sentence_reference(labels=None) -> dict:
    """A validation row whose frozen item is the two sentences as one claim; `labels` is its labels map."""
    extra = {"labels": labels} if labels is not None else {}
    return {"check_version": "old", "rows": [
        row([item(f"{EARLIER}. {HOUSE}", "supported", [A], **YES)], answer=TWO_SENTENCES, **extra)]}


def test_the_recheck_takes_a_new_stretchs_label_from_the_labels_map():
    """A stretch that options cut differently takes its label from the row's labels map."""
    ref = per_sentence_reference({HOUSE: YES, EARLIER: NOT_NEEDED})
    out = claim_referee.recheck(ref, fake_check({"house": "supported"}), options=CheckOptions(per_sentence=True))
    assert out["validation"]["now"]["all"]["claims"] == 2 and out["validation"]["unlabelled"] == 0


def test_a_stretch_with_no_label_anywhere_is_counted_unlabelled():
    """A stretch with no frozen label and none in the labels map is counted unlabelled and left out."""
    out = claim_referee.recheck(per_sentence_reference(), fake_check({"house": "supported"}),
                                options=CheckOptions(per_sentence=True))
    assert out["validation"]["unlabelled"] == 2 and out["validation"]["now"]["all"]["claims"] == 0


# --- the rule that keeps a change ---------------------------------------------------------------------------------

def recheck_result(share: float, flagged: float | None = 1.0, unlabelled: int = 0, tuning: float = 0.5) -> dict:
    def split(now: float, still: float | None, missing: int) -> dict:
        stats = {"claims": 10, "agree": round(now * 10), "share": now}
        return {"frozen": {"cited": stats, "uncited": stats, "all": stats},
                "now": {"cited": stats, "uncited": stats, "all": stats},
                "no_claims": 4, "no_still_flagged": still, "unlabelled": missing}
    return {"options": {}, "frozen_version": "old", "version": "new",
            "validation": split(share, flagged, unlabelled), "tuning": split(tuning, 1.0, 0)}


def test_a_change_is_kept_when_validation_agreement_rises_and_no_claims_stay_flagged():
    """A change that raises validation agreement and flags the referee's "no" claims as often is kept."""
    assert claim_referee.keeps(recheck_result(0.8), recheck_result(0.7)) is True


def test_a_change_is_not_kept_when_validation_agreement_does_not_rise():
    """A change with the baseline's validation agreement is not kept."""
    assert claim_referee.keeps(recheck_result(0.7), recheck_result(0.7)) is False


def test_a_change_is_not_kept_when_it_flags_fewer_no_claims():
    """A change that raises agreement but flags fewer of the referee's "no" claims is not kept."""
    assert claim_referee.keeps(recheck_result(0.8, flagged=0.75), recheck_result(0.7, flagged=1.0)) is False


def test_a_change_is_not_kept_with_unlabelled_validation_stretches():
    """A change that leaves validation stretches unlabelled is not kept."""
    assert claim_referee.keeps(recheck_result(0.8, unlabelled=1), recheck_result(0.7)) is False


def test_the_tuning_split_never_decides():
    """A change that raises validation agreement is kept even when its tuning agreement falls."""
    assert claim_referee.keeps(recheck_result(0.8, tuning=0.2), recheck_result(0.7, tuning=0.9)) is True


# --- the tune run -------------------------------------------------------------------------------------------------

THRESHOLD, HEDGES, CORE = CheckOptions(supported_at=0.3), CheckOptions(skip_hedges=True), CheckOptions(question="core")
BOTH = CheckOptions(supported_at=0.3, skip_hedges=True)
VARIANTS = {"threshold": THRESHOLD, "hedges": HEDGES, "core": CORE}


def tune_with(table: dict[CheckOptions, dict[str, str]]) -> dict:
    """Run tune with a scripted check per options; an options missing from the table fails the test."""
    return claim_referee.tune(reference(), lambda options: fake_check(table[options]), variants=VARIANTS, workers=1)


# Against the validation labels (HOUSE yes, FEE no, UNCITED needs none): the baseline gets 1 of 3, the threshold
# and the hedges 2 of 3 each, the core question 0 of 3, both changes together 3 of 3.
TABLE = {
    CheckOptions(): {"house": "unsupported", "fee": "unsupported", "Kontakta": "uncited"},
    THRESHOLD: {"house": "supported", "fee": "unsupported", "Kontakta": "uncited"},
    HEDGES: {"house": "unsupported", "fee": "unsupported", "Kontakta": "skipped"},
    CORE: {"house": "unsupported", "fee": "supported", "Kontakta": "uncited"},
    BOTH: {"house": "supported", "fee": "unsupported", "Kontakta": "skipped"},
}


def share(run: dict) -> float:
    return run["validation"]["now"]["all"]["share"]


def test_tune_rechecks_the_current_check_as_its_baseline():
    """The baseline is the current check rechecked in the same run, not the frozen numbers."""
    assert share(tune_with(TABLE)["baseline"]) == pytest.approx(1 / 3)


def test_tune_keeps_each_change_that_wins_alone():
    """Each change is rechecked alone and kept by the rule; a change that loses is not kept."""
    out = tune_with(TABLE)
    assert out["kept"] == ["threshold", "hedges"] and out["variants"]["core"]["kept"] is False


def test_tune_measures_the_kept_changes_together():
    """With two or more changes kept, their changed fields together are rechecked as the combination."""
    combined = tune_with(TABLE)["combined"]
    assert (combined["options"], share(combined)) == (asdict(BOTH), 1.0)


def test_two_kept_changes_to_one_field_combine_with_the_better_one():
    """When two kept changes set the same field, the combination takes the value of the one with the higher
    validation agreement, whatever their order."""
    high, low = CheckOptions(supported_at=0.7), CheckOptions(supported_at=0.3)
    table = {CheckOptions(): TABLE[CheckOptions()],
             high: {"house": "supported", "fee": "unsupported", "Kontakta": "skipped"},
             low: {"house": "supported", "fee": "unsupported", "Kontakta": "uncited"}}
    out = claim_referee.tune(reference(), lambda options: fake_check(table[options]),
                             variants={"high": high, "low": low}, workers=1)
    assert out["kept"] == ["high", "low"] and out["combined"]["options"]["supported_at"] == 0.7


def test_tune_makes_the_combination_live_when_it_beats_each_change_alone():
    """The combination is what to make live when it is kept and beats every kept change alone."""
    assert tune_with(TABLE)["live"] == "combined"


def test_tune_makes_the_best_single_change_live_when_the_combination_is_worse():
    """When the combination loses, the kept change with the highest validation agreement is what to make live."""
    table = {**TABLE, THRESHOLD: {"house": "supported", "fee": "unsupported"},
             BOTH: {"house": "supported", "fee": "supported", "Kontakta": "uncited"}}
    assert tune_with(table)["live"] == "threshold"


def test_tune_measures_no_combination_with_a_single_winner():
    """With one change kept there is no combination, and that change is what to make live."""
    out = tune_with({**TABLE, HEDGES: TABLE[CheckOptions()]})
    assert out["combined"] is None and out["live"] == "threshold"


def test_tune_makes_nothing_live_when_no_change_wins():
    """With no change kept there is no combination and nothing to make live."""
    out = tune_with({**TABLE, THRESHOLD: TABLE[CheckOptions()], HEDGES: TABLE[CheckOptions()]})
    assert (out["kept"], out["combined"], out["live"]) == ([], None, None)


def test_the_tune_report_has_a_row_per_run():
    """The tune report has one table row for the baseline, each change and the combination."""
    rows = [line for line in claim_referee.tune_report(tune_with(TABLE)).splitlines() if line.startswith("|")]
    runs = ("baseline", "threshold", "hedges", "core", "combined")
    assert [name for name in runs if not any(name in line for line in rows)] == []


def test_the_tune_report_shows_the_frozen_agreement():
    """The tune report shows the frozen validation agreement next to the current one."""
    assert "67% (2/3)" in claim_referee.tune_report(tune_with(TABLE))


def test_the_tune_report_says_when_no_change_is_kept():
    """With nothing kept, the tune report says no change is kept."""
    out = tune_with({**TABLE, THRESHOLD: TABLE[CheckOptions()], HEDGES: TABLE[CheckOptions()]})
    assert "no change" in claim_referee.tune_report(out).lower()


# --- the referee prompts and labels for new stretches -------------------------------------------------------------

def asked_texts(entries: list[dict]) -> list[list[str]]:
    return [[asked["text"] for asked in entry["items"]] for entry in entries]


def prompts_for(rows, options=None):
    return claim_referee.prompts(rows, get_chunk, options=options, chunk_text=lambda chunk: chunk["text"])


def test_prompts_ask_only_for_stretches_without_a_label():
    """For a reference, only the stretches the options cut that have no frozen label or labels-map entry are asked."""
    ref = per_sentence_reference({HOUSE: YES})
    assert asked_texts(prompts_for(ref["rows"], CheckOptions(per_sentence=True))) == [[EARLIER]]


def test_prompts_for_an_answers_file_ask_for_every_stretch():
    """For an answers file, with no labels at all, every stretch of every answer is asked."""
    rows = [row([item(HOUSE, "supported", [A]), item(FEE, "unsupported", [B]), item(UNCITED, "passed")])]
    entries = prompts_for(rows)
    assert [(asked["text"], asked["cited"]) for asked in entries[0]["items"]] == [
        (HOUSE, True), (FEE, True), (UNCITED, False)]


def test_a_prompt_carries_the_referee_instructions_and_the_cited_sources():
    """Each prompt holds the referee's instructions and the full text of the sources its claims cite."""
    rows = [row([item(HOUSE, "supported", [A])], answer=f"{HOUSE} [c:{A}].")]
    prompt = prompts_for(rows)[0]["prompt"]
    assert claim_referee.REFEREE_INSTRUCTIONS in prompt and CHUNKS[A]["text"] in prompt


def test_prompts_skip_rows_with_nothing_to_ask():
    """A fully labelled row and a question card get no prompt."""
    card = row([], case="kvarnbo", status="asked")
    assert prompts_for([row(frozen_items()), card]) == []


def test_prompts_change_nothing():
    """Writing the prompts leaves the rows as they were."""
    ref = per_sentence_reference({HOUSE: YES})
    before = copy.deepcopy(ref)
    prompts_for(ref["rows"], CheckOptions(per_sentence=True))
    assert ref == before


def asked_new(row_id="norby:pin") -> list[dict]:
    """What prompts asks for the per-sentence stretches of TWO_SENTENCES."""
    return [{"id": row_id, "items": [{"text": EARLIER, "cited": False}, {"text": HOUSE, "cited": True}],
             "prompt": "..."}]


def test_labels_for_new_stretches_go_into_the_labels_map():
    """A readable reply's labels for stretches that are no frozen item go into the row's labels map."""
    ref = per_sentence_reference()
    claim_referee.add_labels(ref["rows"], asked_new(), {"norby:pin": reply(NOT_NEEDED, YES)})
    assert ref["rows"][0]["labels"] == {EARLIER: NOT_NEEDED, HOUSE: YES}


def test_labels_never_change_the_frozen_items():
    """Adding labels leaves the frozen items, the check version and the date as they were."""
    ref = per_sentence_reference()
    items, version, date = copy.deepcopy(ref["rows"][0]["items"]), ref["check_version"], ref.get("date")
    claim_referee.add_labels(ref["rows"], asked_new(), {"norby:pin": reply(NOT_NEEDED, YES)})
    assert (ref["rows"][0]["items"], ref["check_version"], ref.get("date")) == (items, version, date)


def test_labels_count_the_stretches_labelled():
    """add_labels counts every stretch it labelled."""
    ref = per_sentence_reference()
    stats = claim_referee.add_labels(ref["rows"], asked_new(), {"norby:pin": reply(NOT_NEEDED, YES)})
    assert stats["labelled"] == 2


def test_an_unreadable_reply_leaves_its_stretches_unlabelled():
    """An unreadable reply labels nothing and counts as no_verdict."""
    ref = per_sentence_reference()
    stats = claim_referee.add_labels(ref["rows"], asked_new(), {"norby:pin": "not json"})
    assert stats["no_verdict"] == 1 and not ref["rows"][0].get("labels")


def test_a_row_without_a_reply_counts_as_missing():
    """A prompt with no reply leaves its row as it was and counts as missing."""
    ref = per_sentence_reference()
    before = copy.deepcopy(ref)
    stats = claim_referee.add_labels(ref["rows"], asked_new(), {})
    assert stats["missing"] == 1 and ref == before


def test_labels_for_an_answers_file_go_on_its_items():
    """For an answers file, the labels go on the row's items and the row records who labelled them."""
    rows = [row([item(HOUSE, "supported", [A]), item(FEE, "unsupported", [B]), item(UNCITED, "passed")])]
    asked = [{"id": "norby:pin", "items": [{"text": HOUSE, "cited": True}, {"text": FEE, "cited": True},
                                           {"text": UNCITED, "cited": False}], "prompt": "..."}]
    claim_referee.add_labels(rows, asked, {"norby:pin": reply(YES, NO, NOT_NEEDED)}, model="opus-in-a-session")
    assert ([entry["referee"] for entry in rows[0]["items"]], rows[0]["referee"]) == (
        [YES, NO, NOT_NEEDED], "opus-in-a-session")


# --- the second referee ----------------------------------------------------------------------------------------------


def test_the_second_referee_labels_every_item_beside_the_first():
    """Each item the first referee labelled gets the second referee's label as `second`."""
    rows = first_only_rows()[:1]
    run_second(rows, labels_reply(PARTLY, NEEDED))
    assert [entry["second"] for entry in rows[0]["items"]] == [PARTLY, NEEDED]


def test_the_second_referee_names_its_model_on_the_row():
    """A row the second referee labelled carries its model as `second_referee`."""
    rows = first_only_rows()[:1]
    run_second(rows, labels_reply(YES, NOT_NEEDED))
    assert rows[0]["second_referee"] == claim_referee.SECOND_REFEREE_MODEL


def test_the_second_referee_is_asked_as_another_model_than_the_first():
    """The second referee's calls go to its own model, not the first referee's."""
    events = []
    run_second(first_only_rows()[:1], labels_reply(YES, NOT_NEEDED), events=events)
    assert [event[1] for event in events if event[0] == "ask"] == [claim_referee.SECOND_REFEREE_MODEL]


def test_the_second_referee_never_changes_the_first_labels():
    """The first referee's labels, the check's verdicts and the row's referee stay as they were."""
    rows = first_only_rows()
    before = copy.deepcopy(rows)
    run_second(rows, labels_reply(NO, NEEDED), labels_reply(YES))

    def first(some_rows):
        return [({key: value for key, value in one.items() if key not in ("items", "second_referee")},
                 [{key: value for key, value in entry.items() if key != "second"} for entry in one["items"]])
                for one in some_rows]
    assert first(rows) == first(before)


def test_the_second_referee_cost_is_shown_before_any_call():
    """The cost estimate goes out before the first call to the second referee."""
    events = []
    run_second(first_only_rows(), labels_reply(YES, NOT_NEEDED), labels_reply(NO), events=events)
    assert events[0][0] == "estimate"


def test_the_second_referee_cost_is_estimated_at_its_own_price():
    """The estimate prices the tokens at the second referee's price per million, in and out."""
    events = []
    run_second(first_only_rows(), labels_reply(YES, NOT_NEEDED), labels_reply(NO), events=events, price=(1.0, 2.0))
    estimate = events[0][1]
    assert estimate["dollars"] == pytest.approx((estimate["input_tokens"] * 1.0 + estimate["output_tokens"] * 2.0) / 1e6)


def test_a_twice_unreadable_second_reply_leaves_the_row_without_a_second_verdict():
    """After two unreadable replies the row is "no_verdict" for the second referee and its items get no `second`."""
    rows = first_only_rows()[:1]
    run_second(rows, "not json")
    assert (rows[0]["second_referee"], ["second" in entry for entry in rows[0]["items"]]) == ("no_verdict", [False, False])


def test_a_row_the_second_referee_already_labelled_is_not_asked_again():
    """A second run asks only the rows without a second referee, so an interrupted run resumes."""
    rows = first_only_rows()
    run_second(rows[:1], labels_reply(YES, NOT_NEEDED))
    prompts, _ = run_second(rows, labels_reply(NO))
    assert len(prompts) == 1


def test_a_row_without_a_first_verdict_is_not_put_to_the_second_referee():
    """A row the first referee could not label is left alone."""
    rows = [answered("norby", [labelled(AREA, [N])], referee="no_verdict", second_referee=None)]
    prompts, _ = run_second(rows, labels_reply(YES))
    assert (prompts, "second_referee" in rows[0]) == ([], False)


# --- agreed and disputed ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("first", "second", "expected"), [
    (YES, YES, "agreed"),
    (PARTLY, NO, "agreed"),
    (YES, PARTLY, "disputed"),
    (NO, YES, "disputed"),
])
def test_a_claim_is_agreed_when_both_referees_say_yes_or_both_say_otherwise(first, second, expected):
    """A cited claim is agreed when the two referees match on two levels: "yes" against anything else."""
    entry = labelled(AREA, [N], referee=first, second=second)
    assert claim_referee.standing(answered("norby", [entry]), entry) == expected


@pytest.mark.parametrize(("first", "second", "expected"), [
    (NEEDED, NEEDED, "agreed"),
    (NEEDED, NOT_NEEDED, "disputed"),
])
def test_an_uncited_sentence_is_agreed_when_both_referees_give_the_same_need(first, second, expected):
    """An uncited sentence is agreed when both referees say it needs a source, or both say it does not."""
    entry = labelled(TIP, referee=first, second=second)
    assert claim_referee.standing(answered("norby", [entry]), entry) == expected


def test_a_row_the_second_referee_could_not_label_is_disputed():
    """Every stretch of a row whose second referee reply was unreadable twice is disputed."""
    entry = labelled(AREA, [N], referee=YES)
    assert claim_referee.standing(answered("norby", [entry], second_referee="no_verdict"), entry) == "disputed"


def test_a_stretch_no_second_referee_saw_stands_single():
    """Without a second referee on the row a stretch is neither agreed nor disputed."""
    entry = labelled(AREA, [N], referee=YES)
    assert claim_referee.standing(answered("norby", [entry], second_referee=None), entry) == "single"


def test_a_disputed_stretch_is_left_out_of_the_reports_agreement():
    """The agreement counts only the stretches the two referees agree on."""
    support = claim_referee.summary(disputed_rows())["validation"]["support"]
    assert (support["claims"], support["agree"]) == (1, 1)


def test_a_disputed_stretch_is_not_listed_as_a_disagreement():
    """A stretch the referees dispute is not a disagreement between check and referee."""
    assert claim_referee.summary(disputed_rows())["disagreements"] == []


def test_the_summary_lists_every_disputed_stretch_with_both_labels():
    """Each disputed stretch is listed with the first and the second referee's label."""
    disputed = claim_referee.summary(disputed_rows())["disputed"]
    assert [(entry["text"], entry["referee"], entry["second"]) for entry in disputed] == [(PERMIT, "no", "yes")]


def test_the_report_has_a_section_with_the_disputed_stretches():
    """The report lists the disputed stretches under their own heading."""
    text = claim_referee.report(disputed_rows())
    assert "Disputed" in text and PERMIT in text.split("Disputed")[1]


def test_the_recheck_leaves_disputed_stretches_out_and_counts_them():
    """A recheck's current agreement covers the agreed stretches only and says how many were disputed."""
    reference = {"check_version": "frozen", "rows": disputed_rows()}
    validation = claim_referee.recheck(reference, scripted_check({AREA: "supported", PERMIT: "supported"}),
                                       workers=1)["validation"]
    assert (validation["now"]["all"]["claims"], validation["disputed"]) == (1, 1)


# --- the known-answer cases ------------------------------------------------------------------------------------------


def test_every_claim_both_referees_call_supported_gives_an_untouched_case():
    """Each agreed, supported claim comes back as it is, expected to be supported."""
    assert sorted((case["text"], case["expect"]) for case in known_for(kind="untouched")) == sorted(
        (text, "supported") for text in (AREA, PERMIT, SHORE))


def test_a_number_case_changes_only_a_number_of_the_claim():
    """A number-changed case is the claim with one number replaced and nothing else touched."""
    (case,) = known_for(kind="number", text=AREA)
    assert (re.sub(r"\d+", "#", case["text"]), case["text"] != AREA) == (re.sub(r"\d+", "#", AREA), True)


def test_a_number_case_holds_a_number_its_source_does_not_state():
    """The replaced number stands nowhere in the claim's cited chunk, so the source cannot back it."""
    (case,) = known_for(kind="number", text=AREA)
    assert not set(numbers(case["text"])) & set(numbers(SOURCES[N]["text"]))


def test_a_number_case_is_expected_to_be_flagged():
    """A claim with a changed number is wrong by construction."""
    assert [case["expect"] for case in known_for(kind="number")] == ["flagged", "flagged"]


def test_a_claim_without_a_number_from_its_source_gives_no_number_case():
    """A claim holding no number that its cited chunk states gets no number-changed case."""
    assert known_for(kind="number", text=PERMIT) == []


def test_a_source_case_cites_a_chunk_of_another_case():
    """A source-swapped case keeps the claim and cites one chunk that only another case's answers cite."""
    (case,) = known_for(kind="source", text=AREA)
    assert (case["text"], case["chunk_ids"], case["expect"]) == (AREA, [O], "flagged")


def test_a_source_case_never_cites_a_chunk_of_its_own_case():
    """With no other case to take a chunk from, there is no source-swapped case."""
    alone = {"rows": two_referee_reference()["rows"][:1]}
    assert known_for(alone, kind="source") == []


def test_a_claim_with_place_data_gives_no_source_case():
    """A row with place data gets no source-swapped case: the place data may back the claim on its own."""
    assert known_for(two_referee_reference(place_text=PLACE, condition="pin"), kind="source", text=AREA) == []


def test_a_claim_the_referees_do_not_both_call_supported_gives_no_case():
    """A disputed claim, or one both referees reject, is no base for a known-answer case."""
    ref = {"rows": [answered("norby", [labelled(AREA, [N], referee=YES, second=PARTLY), labelled(PERMIT, [H], referee=NO, second=NO)]),
                    answered("dalby", [labelled(SHORE, [O], referee=YES, second=YES)])]}
    assert {case["from"] for case in known_for(ref)} == {SHORE}


def test_a_reference_without_a_second_referee_gives_no_cases():
    """With no second referee no claim is agreed, so there is nothing to build from."""
    assert known_for({"rows": first_only_rows()}) == []


def test_a_case_carries_the_split_and_case_of_its_row():
    """Each case is tuning or validation as the answer it was taken from."""
    assert {(case["case"], case["split"]) for case in known_for()} == {("norby", "validation"), ("dalby", "tuning")}


def test_every_case_has_its_own_id():
    """No two known-answer cases share an id."""
    ids = [case["id"] for case in known_for()]
    assert len(ids) == len(set(ids)) > 0


def test_building_the_cases_twice_gives_the_same_cases():
    """The cases are built by rule: the same reference gives the same cases in the same order."""
    assert known_for() == known_for()


def test_building_the_cases_leaves_the_reference_as_it_was():
    """Building the known-answer cases changes nothing in the reference."""
    ref = two_referee_reference()
    before = copy.deepcopy(ref)
    known_for(ref)
    assert ref == before


# --- the measure -----------------------------------------------------------------------------------------------------


def test_the_measure_gives_agreement_on_the_agreed_stretches_only():
    """The agreement of a measure counts the agreed stretches and leaves the disputed ones out."""
    validation = measured(ref={"rows": disputed_rows()})["validation"]
    assert (validation["agreement"]["all"]["claims"], validation["disputed"]) == (1, 1)


def test_the_measure_keeps_tuning_and_validation_apart():
    """Each split has its own figures: a wrong verdict on a tuning claim does not touch validation."""
    result = measured({SHORE: "unsupported"})
    assert (result["tuning"]["agreement"]["cited"]["share"], result["validation"]["agreement"]["cited"]["share"]) == (0.0, 1.0)


def test_an_untouched_case_is_right_when_the_check_does_not_flag_it():
    """The share of untouched claims the check passes counts the ones it leaves unflagged."""
    result = measured({AREA: "unsupported"}, [known("untouched", AREA, "supported"),
                                              known("untouched", PERMIT, "supported", chunk_ids=(H,))])
    assert result["validation"]["known"]["untouched"] == {"cases": 2, "right": 1, "share": 0.5}


def test_a_changed_case_is_right_when_the_check_flags_it():
    """The share of changed claims the check catches counts the ones it flags."""
    result = measured({WRONG: "unsupported"}, [known("number", WRONG, "flagged")])
    assert result["validation"]["known"]["number"] == {"cases": 1, "right": 1, "share": 1.0}


def test_a_source_case_the_check_calls_supported_is_missed():
    """A source-swapped claim the check still calls supported counts against it."""
    result = measured({}, [known("source", AREA, "flagged", chunk_ids=(O,))])
    assert result["validation"]["known"]["source"] == {"cases": 1, "right": 0, "share": 0.0}


def test_a_kind_without_cases_has_no_share():
    """A kind of known-answer case with no case in the split shows no share."""
    assert measured()["validation"]["known"]["number"] == {"cases": 0, "right": 0, "share": None}


def test_a_case_the_check_did_not_judge_is_not_checked_not_wrong():
    """A known-answer case whose check call failed is left out of the shares and counted as not checked."""
    validation = measured({WRONG: "not_checked"}, [known("number", WRONG, "flagged")])["validation"]
    assert (validation["known"]["number"]["cases"], validation["not_checked"]) == (0, 1)


def test_a_case_is_checked_as_an_answer_holding_only_its_claim():
    """Each known-answer case goes to the check as its claim with its citations, its seen chunks and place data."""
    sent = []
    measured({}, [known("source", AREA, "flagged", chunk_ids=(O,))], seen_answers=sent)
    (answer, seen, place_text), = [call for call in sent if AREA in call[0] and PERMIT not in call[0]]
    assert ([stretch.text for stretch in claim_check.stretches(answer)],
            [list(stretch.chunk_ids) for stretch in claim_check.stretches(answer)], seen, place_text) == (
        [AREA], [[O]], [O], None)


def test_the_measure_gives_the_time_per_answer():
    """The time per answer is the median and the maximum of the seconds the check reported for each answer."""
    ref = {"rows": [answered("norby", [labelled(AREA, [N], referee=YES, second=YES)]),
                    answered("dalby", [labelled(SHORE, [O], referee=YES, second=YES)]),
                    answered("fansta", [labelled(PERMIT, [H], referee=YES, second=YES)])]}
    validation = measured(ref=ref, seconds={AREA: 0.4, SHORE: 1.0, PERMIT: 3.0})["validation"]
    assert (validation["answers"], validation["seconds"]) == (3, {"median": 1.0, "max": 3.0})


def test_the_measure_gives_the_decision_model_calls_per_answer():
    """The calls per answer are the mean of what the check reported for each answer."""
    assert measured(calls=7)["validation"]["calls"] == 7


def test_the_time_does_not_count_the_known_answer_cases():
    """Only the saved answers are timed: a slow known-answer case does not move the time per answer."""
    validation = measured({}, [known("number", WRONG, "flagged")], seconds={WRONG: 9.0})["validation"]
    assert validation["seconds"]["max"] == 0.5


def test_an_answer_over_the_slow_limit_is_listed_with_its_calls_and_claims():
    """An answer the check took more than SLOW_SECONDS on is listed with its seconds, calls and claims judged."""
    validation = measured(seconds={AREA: 3.5}, calls=9)["validation"]
    assert validation["slow"] == [{"id": "norby:general", "seconds": 3.5, "calls": 9, "claims": 2}]


def test_no_answer_is_slow_under_the_limit():
    """With every answer under SLOW_SECONDS nothing is listed as slow."""
    assert measured()["validation"]["slow"] == []


def test_the_saved_answers_are_checked_one_at_a_time():
    """The answers are timed as the chat runs the check: never two answers at once."""
    active = []
    ref = two_referee_reference()
    measured(ref=ref, active=active)
    answers = {one["answer"] for one in ref["rows"]}
    assert [count for answer, count in active if answer in answers] == [1, 1]


def test_measuring_leaves_the_reference_and_the_cases_as_they_were():
    """A measure changes neither the reference nor the cases."""
    ref, some = two_referee_reference(), [known("number", WRONG, "flagged")]
    before = copy.deepcopy((ref, some))
    measured({}, some, ref=ref)
    assert (ref, some) == before


# --- the measure: the wrong cases and the match on three levels ---------------------------------------------------------

def with_levels(check, levels: dict[str, str]):
    """`check` with a `level` on each claim whose text `levels` holds."""
    def levelled(answer, seen, place_text):
        result = check(answer, seen, place_text)
        return {**result, "claims": [{**claim, "level": levels.get(claim["text"])} for claim in result["claims"]]}
    return levelled


def test_the_measure_lists_the_known_answer_cases_the_check_got_wrong():
    """A changed case the check did not flag is listed with its kind, text and verdict."""
    validation = measured({}, [known("number", WRONG, "flagged")])["validation"]
    assert validation["wrong"] == [{"id": "norby:general#1:number", "kind": "number", "text": WRONG, "verdict": "supported"}]


def test_an_untouched_case_the_check_flags_is_listed_as_wrong():
    """An untouched case the check flags is a wrong one too."""
    validation = measured({AREA: "unsupported"}, [known("untouched", AREA, "supported")])["validation"]
    assert [(case["kind"], case["verdict"]) for case in validation["wrong"]] == [("untouched", "unsupported")]


def test_a_measure_with_every_case_right_lists_none_as_wrong():
    """Nothing is listed when the check gets every known-answer case right."""
    assert measured({WRONG: "unsupported"}, [known("number", WRONG, "flagged")])["validation"]["wrong"] == []


def levels_reference() -> dict:
    """Validation claims the two referees label alike: yes, partly, and one they label "partly" against "no"."""
    return {"rows": [answered("norby", [labelled(AREA, [N], referee=YES, second=YES),
                                         labelled(PERMIT, [H], referee=PARTLY, second=PARTLY),
                                         labelled(SHORE, [O], referee=PARTLY, second=NO)])]}


def levels_of(levels: dict[str, str]) -> dict:
    verdicts = {PERMIT: "unsupported", SHORE: "unsupported"}
    return claim_referee.measure(levels_reference(), [], with_levels(scripted_check(verdicts), levels), workers=1)["validation"]["levels"]


def test_the_measure_gives_the_match_on_three_levels():
    """The three-level match counts the claims whose level equals the label both referees gave."""
    assert levels_of({AREA: "full", PERMIT: "none", SHORE: "none"})["match"] == 1


def test_the_three_level_match_leaves_out_claims_the_referees_label_differently():
    """A claim one referee calls "partly" and the other "no" is agreed on two levels but not counted on three."""
    assert levels_of({AREA: "full", PERMIT: "partly", SHORE: "none"}) == {"claims": 2, "match": 2, "share": 1.0}


def test_a_check_without_levels_has_no_three_level_match():
    """A check that gives no levels shows no match on three levels."""
    assert measured()["validation"]["levels"] == {"claims": 0, "match": 0, "share": None}


# --- the measure report ----------------------------------------------------------------------------------------------


def test_the_measure_report_shows_the_agreement_on_the_agreed_stretches():
    """The report gives the agreement with its counts and the number of disputed stretches left out."""
    text = claim_referee.measure_report(measure_result())
    assert "80% (8/10)" in text and "4" in text.split("isputed")[1].splitlines()[0]


def test_the_measure_report_has_a_row_per_kind_of_known_answer_case():
    """The report gives, per kind of known-answer case, how many the check got right."""
    text = claim_referee.measure_report(measure_result())
    assert all(figure in text for figure in ("95% (19/20)", "75% (9/12)", "100% (5/5)"))


def test_the_measure_report_shows_the_time_and_the_calls_per_answer():
    """The report gives the median and the maximum time per answer and the mean decision model calls."""
    text = claim_referee.measure_report(measure_result())
    assert all(value in text for value in ("1.2", "1.9", "6.0"))


def test_the_measure_report_breaks_down_the_slow_answers():
    """An answer over the slow limit gets a line with its seconds, calls and claims."""
    slow = [{"id": "norby:pin", "seconds": 3.5, "calls": 19, "claims": 14}]
    text = claim_referee.measure_report(measure_result(slow=slow))
    assert "Slow answers" in text and all(value in text.split("Slow answers")[1] for value in ("norby:pin", "3.5", "19", "14"))


def test_the_measure_report_has_no_slow_section_without_slow_answers():
    """With no answer over the limit the report has no slow-answers table."""
    assert "Slow answers" not in claim_referee.measure_report(measure_result()) and "80%" in claim_referee.measure_report(measure_result())


def test_the_measure_report_lists_the_disputed_stretches():
    """The report lists every disputed stretch handed to it with both referees' labels."""
    disputed = [{"id": "norby:pin", "split": "validation", "condition": "pin", "text": PERMIT, "referee": "no", "second": "yes"}]
    text = claim_referee.measure_report(measure_result(), disputed=disputed)
    assert PERMIT in text and "norby:pin" in text


def test_the_measure_report_shows_the_match_on_three_levels():
    """The report gives the match on three levels with its counts."""
    text = claim_referee.measure_report(measure_result(levels={"claims": 8, "match": 6, "share": 0.75},
                                                       wrong=[]))
    assert "75% (6/8)" in text


def test_the_measure_report_lists_the_cases_the_check_got_wrong():
    """The report lists each known-answer case the check got wrong with its kind and verdict."""
    wrong = [{"id": "norby:general#1:number", "kind": "number", "text": WRONG, "verdict": "supported"}]
    text = claim_referee.measure_report(measure_result(wrong=wrong, levels={"claims": 0, "match": 0, "share": None}))
    assert all(part in text.split("got wrong")[1] for part in ("norby:general#1:number", "number", "supported", WRONG))


# --- the rule: better on both measures ------------------------------------------------------------------------------

def result_with(agree: int, right: int, *, tuning: tuple[int, int] = (5, 5)) -> dict:
    """A measure result with `agree` of 10 agreed stretches and `right` of 10 known-answer cases on validation."""
    def split(agreed: int, cases_right: int) -> dict:
        stats = {"claims": 10, "agree": agreed, "share": agreed / 10}
        kinds = {"untouched": {"cases": 4, "right": min(4, cases_right), "share": min(4, cases_right) / 4},
                 "number": {"cases": 3, "right": max(0, min(3, cases_right - 4)), "share": max(0, min(3, cases_right - 4)) / 3},
                 "source": {"cases": 3, "right": max(0, cases_right - 7), "share": max(0, cases_right - 7) / 3}}
        return split_result(agreement={"cited": stats, "uncited": stats, "all": stats}, known=kinds, wrong=[],
                            levels={"claims": 0, "match": 0, "share": None})
    return {"options": {}, "version": "v", "tuning": split(*tuning), "validation": split(agree, right)}


def test_a_change_wins_when_it_beats_the_current_check_on_both_measures():
    """Higher validation agreement and more known-answer cases right: the change wins."""
    assert claim_referee.wins(result_with(9, 9), result_with(8, 8)) is True


def test_a_change_with_no_higher_agreement_does_not_win():
    """More cases right but the same agreement on the agreed stretches is not enough."""
    assert claim_referee.wins(result_with(8, 9), result_with(8, 8)) is False


def test_a_change_with_no_more_cases_right_does_not_win():
    """Higher agreement but the same share of known-answer cases right is not enough."""
    assert claim_referee.wins(result_with(9, 8), result_with(8, 8)) is False


def test_the_known_answer_cases_count_together_over_the_three_kinds():
    """One more changed claim caught wins even when the untouched claims passed stay the same."""
    assert claim_referee.wins(result_with(9, 6), result_with(8, 5)) is True


def test_a_change_that_wins_on_tuning_but_not_on_validation_does_not_win():
    """The tuning split never decides."""
    assert claim_referee.wins(result_with(8, 8, tuning=(10, 10)), result_with(8, 8, tuning=(1, 1))) is False


def test_a_change_with_nothing_judged_does_not_win():
    """A run with no agreement to show never wins."""
    empty = result_with(9, 9)
    empty["validation"]["agreement"]["all"] = {"claims": 0, "agree": 0, "share": None}
    assert claim_referee.wins(empty, result_with(8, 8)) is False


# --- the improve run -------------------------------------------------------------------------------------------------

def improve_reference() -> dict:
    """A validation answer with one claim both referees back and two both reject."""
    return {"check_version": "frozen", "rows": [answered("norby", [labelled(AREA, [N], referee=YES, second=YES),
                                                                    labelled(PERMIT, [H], referee=NO, second=NO),
                                                                    labelled(SHORE, [O], referee=NO, second=NO)])]}


HEDGES, ADDITIONS, LEVELS = CheckOptions(skip_hedges=True), CheckOptions(additions=True), CheckOptions(levels=True)
CASES = [known("untouched", AREA, "supported"), known("number", WRONG, "flagged")]
BOTH_ON = CheckOptions(skip_hedges=True, additions=True)
FLAGS_ONE = {PERMIT: "unsupported", WRONG: "unsupported"}  # agreement 2 of 3, cases 2 of 2
FLAGS_ALL = {PERMIT: "unsupported", SHORE: "unsupported", WRONG: "unsupported"}  # agreement 3 of 3, cases 2 of 2


def improved(table: dict[CheckOptions, dict[str, str]], seen: list | None = None, **check) -> dict:
    """An improve run on a check scripted per options: `table` maps the options to the verdicts the check gives with
    them (the current check, and any options not in the table, call every claim supported)."""
    def check_with(options):
        if seen is not None:
            seen.append(options)
        return scripted_check(table.get(options, {}), **check)
    variants = {name: options for name, options in (("skip_hedges", HEDGES), ("additions", ADDITIONS), ("levels", LEVELS))}
    return claim_referee.improve(improve_reference(), CASES, check_with, variants=variants, workers=1)


def test_every_change_is_measured_beside_the_current_check():
    """The run holds the current check's measure and one per change."""
    result = improved({})
    assert (sorted(result["variants"]), result["baseline"]["validation"]["answers"]) == (
        ["additions", "levels", "skip_hedges"], 1)


def test_the_current_check_is_measured_in_the_same_run():
    """The baseline is the current check measured now, with the live options."""
    seen = []
    improved({}, seen=seen)
    assert CheckOptions() in seen


def test_a_change_that_beats_the_current_check_on_both_measures_wins():
    """A change with higher agreement and more known-answer cases right is marked as winning."""
    result = improved({HEDGES: FLAGS_ONE})
    assert (result["variants"]["skip_hedges"]["wins"], result["won"]) == (True, ["skip_hedges"])


def test_a_change_that_only_raises_the_agreement_says_which_measure_it_missed():
    """A change that does not win names the measure it did not beat the current check on."""
    result = improved({HEDGES: {PERMIT: "unsupported"}})
    assert (result["variants"]["skip_hedges"]["wins"], result["variants"]["skip_hedges"]["why"]) == (False, ["known"])


def test_a_change_that_only_catches_more_cases_missed_the_agreement():
    """More cases right with no higher agreement does not win, and says so."""
    assert improved({HEDGES: {WRONG: "unsupported"}})["variants"]["skip_hedges"]["why"] == ["agreement"]


def test_the_single_winner_is_what_to_make_live():
    """With one change winning, it is the one to make live, with its options."""
    result = improved({HEDGES: FLAGS_ONE})
    assert (result["live"], result["options"]["skip_hedges"], result["combined"]) == ("skip_hedges", True, None)


def test_two_winning_changes_are_measured_together():
    """When two changes win, their options are switched on together and measured as the combination."""
    seen = []
    result = improved({HEDGES: FLAGS_ONE, ADDITIONS: FLAGS_ONE, BOTH_ON: FLAGS_ALL}, seen=seen)
    assert (BOTH_ON in seen, result["combined"]["validation"]["agreement"]["all"]["agree"]) == (True, 3)


def test_the_combination_is_made_live_when_it_beats_every_winner_alone():
    """A combination that wins and agrees more than each winning change alone is the one to make live."""
    result = improved({HEDGES: FLAGS_ONE, ADDITIONS: FLAGS_ONE, BOTH_ON: FLAGS_ALL})
    assert (result["live"], result["options"]["skip_hedges"], result["options"]["additions"]) == ("combined", True, True)


def test_the_best_single_change_is_made_live_when_the_combination_is_no_better():
    """With several winners and a combination that agrees no more, the winner with the higher agreement goes live."""
    result = improved({HEDGES: FLAGS_ONE, ADDITIONS: FLAGS_ALL, BOTH_ON: FLAGS_ONE})
    assert result["live"] == "additions"


def test_with_no_change_winning_nothing_is_made_live():
    """When no change beats the current check on both measures, there is nothing to make live."""
    result = improved({HEDGES: {PERMIT: "unsupported"}})
    assert (result["won"], result["live"], result["options"]) == ([], None, None)


def test_the_improve_run_leaves_the_reference_and_the_cases_as_they_were():
    """An improve run changes neither the reference nor the cases."""
    reference, some = improve_reference(), copy.deepcopy(CASES)

    def check_with(options):
        return scripted_check({})
    claim_referee.improve(reference, some, check_with, variants={"skip_hedges": HEDGES}, workers=1)
    assert (reference, some) == (improve_reference(), CASES)


# --- the improve report ---------------------------------------------------------------------------------------------

def test_the_improve_report_has_a_row_for_the_current_check_and_each_change():
    """The report names the current check, every change and the combination in its table."""
    text = claim_referee.improve_report(improved({HEDGES: FLAGS_ONE, ADDITIONS: FLAGS_ONE, BOTH_ON: FLAGS_ALL}))
    assert all(name in text for name in ("current check", "skip_hedges", "additions", "levels", "combined"))


def test_the_improve_report_shows_each_runs_agreement_and_cases_right():
    """Each row gives the validation agreement on the agreed stretches and the known-answer cases right."""
    text = claim_referee.improve_report(improved({HEDGES: FLAGS_ONE}))
    assert all(figure in text for figure in ("33% (1/3)", "67% (2/3)", "50% (1/2)", "100% (2/2)"))


def test_the_improve_report_ends_with_what_to_make_live():
    """With a winner, the report's last line says which change to make the CheckOptions default."""
    last = claim_referee.improve_report(improved({HEDGES: FLAGS_ONE})).strip().splitlines()[-1]
    assert last.startswith("Make live: skip_hedges") and "skip_hedges=True" in last


def test_the_improve_report_says_why_when_no_change_wins():
    """With no winner, the report says the live check stays and names what each change missed."""
    text = claim_referee.improve_report(improved({HEDGES: {PERMIT: "unsupported"}}))
    assert "No change wins" in text and "known" in text.split("No change wins")[1]


def test_the_improve_report_breaks_down_a_run_with_slow_answers():
    """A run with an answer over the slow limit gets a slow-answers section naming the run and the answer."""
    text = claim_referee.improve_report(improved({}, seconds={AREA: 3.5}, calls=21))
    assert "Slow answers" in text and all(part in text.split("Slow answers")[1] for part in ("norby:general", "3.5", "21"))


def test_the_improve_report_lists_the_cases_the_current_check_got_wrong():
    """The known-answer cases the current check got wrong are listed with their text."""
    text = claim_referee.improve_report(improved({HEDGES: FLAGS_ONE}))
    assert WRONG in text.split("got wrong")[1]
