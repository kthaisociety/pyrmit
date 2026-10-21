"""Scoring of explain / propose / develop cases (agentic/bench.py grade_answer), with a fake judge: no API call."""

import agentic.bench as bench

PROPOSE = {
    "id": "p", "task": "propose", "question": "Where could we build?", "key_points": ["a", "b"],
    "anchors": [{"name": "Kårsta"}, {"name": "Älmsta", "aliases": ["Almsta"]}, {"name": "Karby", "aliases": ["Brottby"]}],
    "min_anchors": 2, "evidence": [],
}
DEVELOP = {
    "id": "d", "task": "develop", "question": "Idea?", "evidence": [],
    "key_points": ["Obstacle: o1", "Obstacle: o2", "Lever: l1", "Ask: a1"],
}


class NoTools:
    def get_chunk(self, chunk_id):
        return None


def fake_judge(grade):
    return lambda case, answer, model, sources="": {**grade, "judge_cost": 0.001}


def test_anchor_hits_whole_words_and_aliases():
    answer = "Options: Kårstavägen is a road; the station village Almsta, and Brottby."
    assert bench.anchor_hits(PROPOSE, answer) == ["Älmsta", "Karby"]


def test_propose_scores(monkeypatch):
    monkeypatch.setattr(bench, "judge", fake_judge({
        "verdict": "none", "points": [2, 1], "unsupported_claims": 1,
        "proposals": [{"place": "Kårsta", "sourced": True}, {"place": "Somewhere", "sourced": False}],
    }))
    row = bench.grade_answer(PROPOSE, "We suggest Kårsta, Karby and Älmsta.", NoTools(), "judge")
    assert row["verdict_ok"] is None  # no accepted verdicts: not scored
    assert row["points"] == 0.75
    assert row["anchors"] == 1.0 and len(row["anchors_hit"]) == 3  # capped at min_anchors
    assert row["proposals"] == 2 and row["proposals_sourced"] == 0.5


def test_develop_points_per_kind_and_short_judge_output(monkeypatch):
    monkeypatch.setattr(bench, "judge", fake_judge({"verdict": "none", "points": [2, 0, 1], "unsupported_claims": 0}))
    row = bench.grade_answer(DEVELOP, "answer", NoTools(), "judge")
    assert row["points"] == 3 / 8  # the missing 4th score counts as 0
    assert row["points_obstacle"] == 0.5 and row["points_lever"] == 0.5 and row["points_ask"] == 0.0


def test_verdict_case_unchanged(monkeypatch):
    case = {"id": "v", "question": "q", "verdicts": ["not_feasible"], "key_points": ["k"], "evidence": []}
    monkeypatch.setattr(bench, "judge", fake_judge({"verdict": "not_feasible", "points": [2], "unsupported_claims": 0}))
    row = bench.grade_answer(case, "answer", NoTools(), "judge")
    assert row["task"] == "verdict" and row["verdict_ok"] is True and row["points"] == 1.0
    assert "anchors" not in row and "proposals" not in row


def test_mode_ok_accepts_the_modes_of_mixed_questions():
    mixed = {"task": "verdict", "modes": ["verdict", "explain"]}
    assert bench.mode_ok(mixed, "explain") and not bench.mode_ok(mixed, "propose")
    assert bench.mode_ok(DEVELOP, "develop") and not bench.mode_ok(DEVELOP, None)
