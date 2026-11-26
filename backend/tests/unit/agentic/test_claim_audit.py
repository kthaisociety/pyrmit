"""The claim-support eval (agentic.claim_audit): the stored claims of a benchmark run, a second reader per claim, and
the report of what is behind the numbers. The auditor and the claim check are scripted (PCR-0011)."""

import json

from agentic import claim_audit
from tests.unit.agentic.claims import CHUNKS, FEE, HOUSE, A, B, get_chunk

ADVICE = "Contact the kommun; the fee is 12 000 kr"


class Tools:
    get_chunk = staticmethod(get_chunk)


def claim(text: str, verdict: str, chunk_ids=(), **audit) -> dict:
    out = {"text": text, "verdict": verdict, "chunk_ids": list(chunk_ids)}
    if audit:
        out["audit"] = {"kind": "rule", "form": "statement", "backed": "yes", "missing": "", "sources": ["law"],
                        "model": "m", **audit}
    return out


def row(claims: list[dict], condition: str = "pin", case: str = "norby", repeat: int = 0, **extra) -> dict:
    return {"case": case, "condition": condition, "repeat": repeat, "answer": "an answer", "claim_check": "checked",
            "claim_list": claims, **extra}


def reply(*entries: dict) -> str:
    return json.dumps({"claims": [{"n": n, **entry} for n, entry in enumerate(entries, 1)]})


YES = {"kind": "rule", "form": "statement", "backed": "yes", "missing": ""}
NO = {"kind": "number", "form": "advice", "backed": "no", "missing": "the fee of 12 000 kr"}


def audit(rows, text: str, **kwargs) -> dict:
    asked = kwargs.pop("asked", [])

    def ask(model, prompt):
        asked.append(prompt)
        return text, 0.002
    return claim_audit.audit(rows, Tools(), ask=ask, chunk_text=lambda chunk: chunk["text"], workers=1, **kwargs)


# --- result files -------------------------------------------------------------------------------------------------

def test_both_benchmarks_result_files_are_read(tmp_path):
    """place.bench_answers saves {"rows": [...]}, agentic.bench a bare list."""
    (tmp_path / "place.json").write_text(json.dumps({"rows": [{"case": "a"}]}))
    (tmp_path / "bench.json").write_text(json.dumps([{"case": "b"}]))
    assert claim_audit.load(tmp_path / "place.json")[1] == [{"case": "a"}]
    assert claim_audit.load(tmp_path / "bench.json")[1] == [{"case": "b"}]


def test_a_row_is_grouped_by_its_condition_or_else_its_system():
    assert claim_audit.group_of({"condition": "pin", "system": "agent"}) == "pin"
    assert claim_audit.group_of({"system": "agent"}) == "agent"


def test_only_checked_rows_give_claims():
    rows = [row([claim(HOUSE, "supported", [A])]), {"case": "x", "claim_check": "failed", "claim_list": None},
            {"case": "y", "claim_check": None}]
    assert [c["text"] for c in claim_audit.claims_of(rows)] == [HOUSE]


def test_a_stretch_of_several_sentences_is_counted_as_such():
    assert claim_audit.sentences_in(HOUSE) == 1
    assert claim_audit.sentences_in("Bygglov krävs. Avgiften är 12 000 kr. Sök i tid") == 3


# --- recheck ------------------------------------------------------------------------------------------------------

def test_a_recheck_puts_the_stored_answer_to_the_check_with_its_chunks_and_place():
    seen = []

    def support(run, tools, place):
        seen.append((run.answer, run.seen_chunks, place))
        return {"claim_check": "checked", "claim_list": [claim(HOUSE, "supported", [A])]}
    rows = [{"case": "norby", "answer": "an answer", "seen": [A], "place_text": "[Place]"}, {"case": "card", "answer": ""}]
    assert claim_audit.recheck(rows, support, Tools(), workers=1) == 1
    assert seen == [("an answer", [A], "[Place]")] and rows[0]["claim_list"][0]["text"] == HOUSE


def test_a_recheck_of_the_missing_ones_leaves_checked_answers_alone():
    rows = [row([claim(HOUSE, "supported", [A])])]
    assert claim_audit.recheck(rows, lambda *args: {"claim_list": []}, Tools(), only_missing=True, workers=1) == 0
    assert rows[0]["claim_list"]


# --- audit --------------------------------------------------------------------------------------------------------

def test_the_auditor_reads_each_claim_with_the_text_of_its_sources_and_the_place_data():
    asked = []
    audit([row([claim(HOUSE, "supported", [A]), claim(FEE, "uncited")], place_text="[Place] Norby 114:1")],
          reply(YES, NO), asked=asked)
    assert CHUNKS[A]["text"] in asked[0] and "[Place] Norby 114:1" in asked[0]
    assert "cites no source" in asked[0] and CHUNKS[B]["text"] not in asked[0]


def test_each_claim_gets_the_auditors_labels_and_its_sources_kinds():
    rows = [row([claim(HOUSE, "supported", [A]), claim(ADVICE, "unsupported", [B])])]
    stats = audit(rows, reply(YES, NO))
    first, second = (c["audit"] for c in rows[0]["claim_list"])
    assert (first["kind"], first["backed"], first["sources"]) == ("rule", "yes", ["law"])
    assert (second["form"], second["backed"], second["missing"]) == ("advice", "no", "the fee of 12 000 kr")
    assert (stats["claims"], stats["unusable"], stats["cost"]) == (2, 0, 0.002)


def test_a_source_that_cannot_be_read_is_said_so():
    rows = [row([claim(HOUSE, "unsupported", ["f" * 16])])]
    asked = []
    audit(rows, reply(NO), asked=asked)
    assert "could not be read" in asked[0] and rows[0]["claim_list"][0]["audit"]["sources"] == ["unreadable"]


def test_an_unusable_reply_leaves_the_claims_unaudited():
    for text in ("not json", reply({"kind": "poem", "form": "statement", "backed": "yes"})):
        rows = [row([claim(HOUSE, "supported", [A])])]
        assert audit(rows, text)["unusable"] == 1 and "audit" not in rows[0]["claim_list"][0]


def test_a_reply_wrapped_in_prose_is_read():
    rows = [row([claim(HOUSE, "supported", [A])])]
    audit(rows, f"Here you go:\n```json\n{reply(YES)}\n```")
    assert rows[0]["claim_list"][0]["audit"]["backed"] == "yes"


def test_audited_rows_are_not_audited_again():
    rows = [row([claim(HOUSE, "supported", [A], backed="yes")])]
    assert audit(rows, reply(NO))["rows"] == 0 and rows[0]["claim_list"][0]["audit"]["backed"] == "yes"
    assert audit(rows, reply(NO), only_missing=False)["rows"] == 1


# --- numbers ------------------------------------------------------------------------------------------------------

def test_the_shares_are_over_all_claims_of_the_condition():
    rows = [row([claim(HOUSE, "supported", [A])] * 3), row([claim(FEE, "unsupported", [B])], repeat=1),
            row([claim(HOUSE, "supported", [A])], condition="address")]
    groups = claim_audit.summary(rows)["groups"]
    assert (groups["pin"]["claims"], groups["pin"]["supported"], groups["pin"]["unsupported"]) == (4, 0.75, 0.25)
    assert groups["address"]["supported"] == 1.0


def test_answers_without_a_flag_and_flags_per_answer_are_reported():
    rows = [row([claim(HOUSE, "supported", [A])]), row([claim(FEE, "unsupported", [B]), claim(FEE, "uncited")]),
            row([]), {"case": "x", "condition": "pin", "claim_check": "failed", "claim_list": None}]
    pin = claim_audit.summary(rows)["groups"]["pin"]
    assert (pin["answers"], pin["answers_checked"], pin["checks_failed"]) == (4, 3, 1)
    assert (pin["answers_clean"], pin["flags_per_answer"]) == (0.5, 1.0)  # the answer without claims is left out


def test_the_interval_brackets_the_share_and_is_the_same_on_every_run():
    rows = [row([claim(HOUSE, "supported", [A])] * 4), row([claim(FEE, "unsupported", [B])] * 4)] * 5
    low, high = claim_audit.support_interval(rows)
    assert low < 0.5 < high and claim_audit.support_interval(rows) == (low, high)
    assert claim_audit.support_interval([row([])]) is None


def test_the_check_is_compared_with_the_auditor_on_cited_claims():
    rows = [row([claim(HOUSE, "supported", [A], backed="yes"), claim(HOUSE, "supported", [A], backed="no"),
                 claim(FEE, "unsupported", [B], backed="yes"), claim(FEE, "unsupported", [B], backed="partly"),
                 claim(FEE, "uncited", backed="no"), claim(FEE, "unsupported", [B])])]
    agree = claim_audit.agreement(claim_audit.claims_of(rows))
    assert (agree["claims"], agree["flagged"], agree["false_flags"], agree["passed"], agree["misses"]) == (4, 2, 1, 2, 1)


def test_support_is_reported_per_kind_form_length_and_source():
    rows = [row([claim(HOUSE, "supported", [A], kind="rule"),
                 claim(ADVICE, "unsupported", [B], kind="number", form="advice", sources=["taxa"]),
                 claim("One. Two. Three", "unsupported", [B], kind="number", sources=["taxa", "law"])])]
    numbers = claim_audit.summary(rows)
    assert numbers["kinds"]["number"]["supported"] == 0.0 and numbers["kinds"]["rule"]["supported"] == 1.0
    assert numbers["forms"]["advice"]["claims"] == 1
    assert numbers["lengths"]["3 or more"]["claims"] == 1 and numbers["lengths"]["1 sentence"]["claims"] == 1
    assert numbers["sources"]["law"]["claims"] == 2 and numbers["sources"]["taxa"]["supported"] == 0.0


# --- report -------------------------------------------------------------------------------------------------------

def big_run() -> list[dict]:
    """Ten pin answers: single cited sentences hold, advice with a fee glued on does not (and the auditor agrees)."""
    return [row([claim(HOUSE, "supported", [A], kind="rule")] * 3
                + [claim(f"{ADVICE}. Apply in time", "unsupported", [B], kind="number", form="advice", backed="no",
                         missing="the fee of 12 000 kr", sources=["taxa"])], repeat=repeat) for repeat in range(10)]


def test_the_report_gives_the_headline_per_condition():
    text = claim_audit.report(big_run(), title="T", sources=["run.json"])
    assert "| pin | 10 / 10 | 40 | 75% |" in text and "`run.json`" in text


def test_the_report_lists_the_confirmed_flags_with_what_the_source_lacks():
    text = claim_audit.report(big_run(), title="T", sources=["run.json"])
    confirmed = text.split("## Flagged and confirmed")[1].split("\n## ")[0]
    assert ADVICE in confirmed and "the fee of 12 000 kr" in confirmed


def test_the_report_recommends_judging_sentences_apart_when_long_stretches_fail():
    text = claim_audit.report(big_run(), title="T", sources=["run.json"])
    suggestions = text.split("## What the numbers suggest")[1].split("\n## ")[0]
    assert "Judge each sentence on its own" in suggestions and "tell the user what to do" in suggestions


def test_the_report_warns_when_the_auditor_backs_what_the_check_flags():
    rows = [row([claim(FEE, "unsupported", [B], backed="yes")] * 5 + [claim(HOUSE, "supported", [A], backed="yes")] * 5)]
    text = claim_audit.report(rows, title="T", sources=["run.json"])
    assert "The check flags claims its sources do back" in text and "5 of the 5" in text


def test_hand_written_findings_come_after_the_headline():
    text = claim_audit.report(big_run(), title="T", sources=["run.json"], findings="The plan texts are missing.")
    assert text.index("## Headline") < text.index("The plan texts are missing.") < text.index("## What the numbers suggest")


def test_a_run_without_an_audit_still_reports():
    rows = [row([claim(HOUSE, "supported", [A]), claim(FEE, "unsupported", [B])])]
    text = claim_audit.report(rows, title="T", sources=["run.json"])
    assert "## Is the check right?" not in text and "## Flagged, not audited" in text
