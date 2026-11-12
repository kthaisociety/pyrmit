"""Unit tests for agents.parsers: the feasibility template in Swedish."""

from agents.parsers import format_response

RESULT = {"feasibility": "HIGHLY FEASIBLE", "confidence": 80, "summary": "S", "law_findings": "L",
          "case_findings": "C", "requirements": ["R"], "timeline": 6, "next_steps": ["N"]}


def test_a_swedish_feasibility_answer_has_swedish_headings():
    assert format_response(RESULT, "sv").startswith("## Bedömning av genomförbarhet")


def test_a_swedish_feasibility_answer_has_no_english_headings():
    text = format_response(RESULT, "sv")
    assert not any(heading in text for heading in ("Feasibility Analysis", "### Summary", "Recommended Next Steps"))
