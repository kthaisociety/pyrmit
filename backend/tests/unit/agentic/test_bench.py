"""Unit tests for agentic.bench: the language and quote checks of a graded answer, and the bilingual cases file. A fake
judge model: no API call."""

import json
from pathlib import Path

import pytest

from agentic import bench
from tests.unit.agentic.judge_client import JudgeClient

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
