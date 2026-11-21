"""agentic.claim_referee: the locked question set, the run that saves answers with the claim check's verdicts, the
referee's labels in a frozen reference, the agreement report and the recheck, with a fake agent, a fake check and a
fake referee. No real services (PCR-0011)."""

import json

import pytest

from agentic import claim_referee
from place.bench_answers import load_cases
from tests.unit.agentic.claims import CHUNKS, FEE, HOUSE, A, B, get_chunk

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


def row(items, condition="pin", split="validation", case="norby", status="answered", check="checked") -> dict:
    return {"id": f"{case}:{condition}", "case": case, "condition": condition, "split": split, "answer": ANSWER,
            "seen": [A, B], "place_text": PLACE, "questions": [], "status": status, "check": check, "items": items}


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

def test_the_recheck_shows_validation_agreement_next_to_the_frozen_one():
    """The current check runs on the stored answers, without new agent answers; its validation agreement is shown
    next to the frozen one, with the share of the referee's "no" claims it still flags."""
    no = {"supported": "no", "missing": "the fee", "needs_source": "fact", "split": "one"}
    yes = {"supported": "yes", "missing": "", "needs_source": "fact", "split": "one"}
    reference = {"check_version": "old", "rows": [
        row([item(HOUSE, "supported", [A], **yes), item(FEE, "supported", [B], **no)]),
        row([item(HOUSE, "supported", [A], **yes)], split="tuning", case="kvarnbo")]}
    calls = []
    out = claim_referee.recheck(reference, fake_check({"house": "supported", "fee": "unsupported"}, calls=calls))
    assert calls == [ANSWER]  # validation answers only
    assert out["frozen"]["share"] == 0.5 and out["now"]["share"] == 1.0
    assert out["no_still_flagged"] == 1.0
    assert out["frozen_version"] == "old" and out["version"] == claim_referee.check_version()
    assert reference["rows"][0]["items"][1]["check"] == "supported"  # the frozen reference is not changed
