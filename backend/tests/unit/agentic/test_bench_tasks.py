"""Scoring of explain / propose / develop cases (agentic/bench.py grade_answer), with a fake judge model: no API call."""

import pytest

from agentic import bench
from tests.unit.agentic.judge_client import JudgeClient

PROPOSE = {
    "id": "p", "task": "propose", "question": "Where could we build?", "key_points": ["a", "b"],
    "anchors": [{"name": "Kårsta"}, {"name": "Älmsta", "aliases": ["Almsta"]}, {"name": "Karby", "aliases": ["Brottby"]}],
    "min_anchors": 2, "evidence": [],
}
DEVELOP = {
    "id": "d", "task": "develop", "question": "Idea?", "evidence": [],
    "key_points": ["Obstacle: o1", "Obstacle: o2", "Lever: l1", "Ask: a1"],
}
VERDICT = {"id": "v", "question": "q", "verdicts": ["not_feasible"], "key_points": ["k"], "evidence": []}


class NoTools:
    def get_chunk(self, chunk_id):
        return None


def graded(monkeypatch, case, answer, grade):
    monkeypatch.setattr(bench, "get_openai_client", lambda: JudgeClient(grade))
    return bench.grade_answer(case, answer, NoTools(), "judge")


@pytest.fixture
def propose_row(monkeypatch):
    return graded(monkeypatch, PROPOSE, "We suggest Kårsta, Karby and Älmsta.", {
        "verdict": "none", "points": [2, 1], "unsupported_claims": 1,
        "proposals": [{"place": "Kårsta", "sourced": True}, {"place": "Somewhere", "sourced": False}],
    })


@pytest.fixture
def develop_row(monkeypatch):
    """The judge returns one score too few."""
    return graded(monkeypatch, DEVELOP, "answer", {"verdict": "none", "points": [2, 0, 1], "unsupported_claims": 0})


@pytest.fixture
def verdict_row(monkeypatch):
    return graded(monkeypatch, VERDICT, "answer", {"verdict": "not_feasible", "points": [2], "unsupported_claims": 0})


def test_anchor_hits_whole_words_and_aliases():
    answer = "Options: Kårstavägen is a road; the station village Almsta, and Brottby."
    assert bench.anchor_hits(PROPOSE, answer) == ["Älmsta", "Karby"]


def test_a_case_without_accepted_verdicts_has_no_verdict_score(propose_row):
    assert propose_row["verdict_ok"] is None


def test_propose_points(propose_row):
    assert propose_row["points"] == 0.75


def test_propose_anchors_are_capped_at_min_anchors(propose_row):
    assert propose_row["anchors"] == 1.0


def test_propose_lists_every_anchor_hit(propose_row):
    assert len(propose_row["anchors_hit"]) == 3


def test_propose_counts_the_proposals(propose_row):
    assert propose_row["proposals"] == 2


def test_propose_share_of_sourced_proposals(propose_row):
    assert propose_row["proposals_sourced"] == 0.5


def test_a_missing_judge_score_counts_as_zero(develop_row):
    assert develop_row["points"] == 3 / 8


@pytest.mark.parametrize(("kind", "share"), [("obstacle", 0.5), ("lever", 0.5), ("ask", 0.0)])
def test_develop_points_per_kind(develop_row, kind, share):
    assert develop_row[f"points_{kind}"] == share


def test_a_verdict_case_is_a_verdict_task(verdict_row):
    assert verdict_row["task"] == "verdict"


def test_a_verdict_case_scores_its_verdict(verdict_row):
    assert verdict_row["verdict_ok"] is True


def test_a_verdict_case_scores_its_points(verdict_row):
    assert verdict_row["points"] == 1.0


@pytest.mark.parametrize("key", ["anchors", "proposals"])
def test_a_verdict_case_has_no_task_scores(verdict_row, key):
    assert key not in verdict_row


@pytest.mark.parametrize(("case", "mode", "ok"), [
    ({"task": "verdict", "modes": ["verdict", "explain"]}, "explain", True),
    ({"task": "verdict", "modes": ["verdict", "explain"]}, "propose", False),
    (DEVELOP, "develop", True),
    (DEVELOP, None, False),
])
def test_mode_ok_accepts_the_modes_of_mixed_questions(case, mode, ok):
    assert bench.mode_ok(case, mode) is ok
