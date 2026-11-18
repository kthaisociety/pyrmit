"""Unit tests for agentic.bench_summary (issue #116): result rows grouped into studies, success rates, best configs."""
import json

import pytest

from agentic import bench_summary


def row(system="agent", verdict_ok=True, points=0.5, cost=0.01, seconds=30.0, **extra):
    return {"case": "c", "system": system, "verdict_ok": verdict_ok, "points": points, "evidence": 0.5,
            "grounded": 0.8, "unsupported": 1, "tool_calls": 10, "seconds": seconds, "first_token_s": seconds - 5,
            "cost": cost, **extra}


MATRIX = [
    ("bench-20261017-133642-rag-medium-explore-low.json",
     [row("rag", True, 0.6, 0.002, 16), row("rag", True, 0.5, 0.002, 16)]),
    ("bench-20261017-134133-rag-medium-explore-low-cases_caselaw.json",
     [row("rag", True, 0.2, 0.002), row("rag", False, 0.2, 0.002)]),
    ("bench-20261007-215229-agent-medium-explore-medium.json", [row(points=0.8), row(points=0.7)]),
    ("bench-20261007-221849-agent-medium-explore-medium-cases_caselaw.json",
     [row(points=0.5), row(points=0.5), row(verdict_ok=False, points=0.4), row(error="provider timeout")]),
    ("bench-20261007-211220-agent-medium-explore-low.json", [row(points=0.7), row(verdict_ok=False, points=0.7)]),
    ("bench-20261008-141019-agent-medium-explore-medium-cases_plans-no-view_map_area.json", [row(verdict_ok=False)]),
    ("bench-20261007-145552-agent-medium.json", [row()]),  # before the effort matrix: in no study
    ("coverage-20261024.json", [{"anything": 1}]),  # not a result file
]


def study(result, key):
    return next(s for s in result["studies"] if s["key"] == key)


def config(found, key):
    return next(c for c in found["configs"] if c["key"] == key)


def test_the_matrix_compares_the_rag_and_the_agent_settings_per_set():
    found = study(bench_summary.summarise(MATRIX), "rag-vs-agent")
    assert found["sets"] == ["cases14", "caselaw", "plans"]
    assert [c["key"] for c in found["configs"]] == [
        "rag-medium", "agent-low-medium", "agent-medium-medium", "agent-medium-medium-no-view_map_area"]
    rag = config(found, "rag-medium")
    assert rag["name"] == "Classic RAG" and rag["settings"] == "answer effort medium"
    assert rag["results"]["cases14"] == {
        "n": 2, "success": 1.0, "verdict": 1.0, "points": 0.55, "evidence": 0.5, "grounded": 0.8, "unsupported": 1,
        "tools": 10, "seconds": 16, "first": 11, "cost": 0.002,
        "files": ["bench-20261017-133642-rag-medium-explore-low.json"]}
    assert config(found, "agent-medium-medium-no-view_map_area")["settings"] == (
        "exploration medium · answer medium · without the map crop tool")


def test_rows_with_an_error_are_left_out():
    agent = config(study(bench_summary.summarise(MATRIX), "rag-vs-agent"), "agent-medium-medium")
    assert agent["results"]["caselaw"]["n"] == 3
    assert agent["results"]["caselaw"]["success"] == pytest.approx(2 / 3, abs=1e-4)


def test_the_best_cell_of_each_set():
    found = study(bench_summary.summarise(MATRIX), "rag-vs-agent")
    # cases14: the RAG and the medium agent both at 100 %: the key points decide
    assert found["best_by_set"] == {"cases14": "agent-medium-medium", "caselaw": "agent-medium-medium",
                                    "plans": "agent-medium-medium-no-view_map_area"}
    # Only configurations run on every set compete for the study's best: none here
    assert found["best"] is None


def test_the_best_configuration_needs_every_set_and_ties_go_to_the_cheaper():
    files = [("bench-20261017-133642-rag-medium-explore-low.json", [row("rag", True, 0.5, 0.002)]),
             ("bench-20261007-215229-agent-medium-explore-medium.json", [row(True, 0.5, 0.009)])]
    found = study(bench_summary.summarise(files), "rag-vs-agent")
    assert found["best"] == "rag-medium"
    assert config(found, "rag-medium")["overall"] == {"success": 1.0, "points": 0.5, "cost": 0.002}
    assert found["in_use"] == "agent-medium-medium"


def test_explain_propose_develop_sets_score_key_points():
    files = [("bench-20261019-192703-rag-agent-medium-explore-medium-cases_tasks.json",
              [row("rag", None, 0.6), row("agent", None, 0.8)])]
    found = study(bench_summary.summarise(files), "beyond-verdict")
    assert config(found, "agent-medium-medium")["results"]["tasks"]["success"] == 0.8
    assert config(found, "rag-medium")["results"]["tasks"]["verdict"] is None
    assert found["best"] == "agent-medium-medium"


def test_the_optimisation_runs_are_named_and_in_the_order_they_were_made():
    files = [("bench-20261024-130438-agent-medium-explore-medium-x-filters.json", [row(model="openai/gpt-6-luna")]),
             ("bench-20261021-150200-agent-medium-explore-medium-x-base.json", [row(model="openai/gpt-6-luna")]),
             ("bench-20261021-183641-agent-medium-explore-medium-x-mimo-flash.json",
              [row(model="xiaomi/mimo-v2.6-flash")])]
    found = study(bench_summary.summarise(files), "optimisation")
    assert [c["key"] for c in found["configs"]] == ["x-base", "x-mimo-flash", "x-filters"]
    assert config(found, "x-mimo-flash")["name"] == "MiMo v2.6 Flash as the model instead of GPT-6 Luna"
    assert config(found, "x-mimo-flash")["settings"].endswith("mimo-v2.6-flash")
    assert found["in_use"] == "x-filters"


def test_the_missing_info_study_splits_should_ask_and_should_answer():
    files = [("missing-info-baseline-dev-medium-20261112.json",
              [row(expect="ask", ask_ok=False), row(expect="ask", ask_ok=True), row(expect="answer", ask_ok=True)]),
             ("bench-20261112-153506-agent-medium-explore-medium-cases_missing_info-x-run6.json",
              [row(expect="ask", ask_ok=True), row(expect="answer", ask_ok=True)])]
    found = study(bench_summary.summarise(files), "missing-info")
    assert found["sets"] == ["missing_ask", "missing_answer"]
    before, after = config(found, "x-baseline"), config(found, "x-run6")
    assert before["name"] == "Before: the agent always answered"
    assert before["results"]["missing_ask"]["success"] == 0.5 and after["results"]["missing_ask"]["success"] == 1.0
    assert found["best"] == "x-run6"


def test_sets_and_measures_are_described_for_a_reader():
    result = bench_summary.summarise(MATRIX)
    assert [s["key"] for s in result["sets"]] == ["cases14", "caselaw", "plans"]
    assert all(s["name"] and s["about"] and s["measure"] == "verdict" for s in result["sets"])
    assert {m["key"] for m in result["measures"]} >= {"success", "points", "seconds", "cost"}
    assert study(result, "rag-vs-agent")["period"] == ["2026-10-07", "2026-10-17"]


def test_no_files_no_studies():
    assert bench_summary.summarise([])["studies"] == []


def test_the_summary_reads_the_folder_and_follows_a_new_file(tmp_path):
    (tmp_path / MATRIX[2][0]).write_text(json.dumps(MATRIX[2][1]), encoding="utf-8")
    first = bench_summary.summary(tmp_path)
    assert first["files"] == 1 and study(first, "rag-vs-agent")["configs"][0]["key"] == "agent-medium-medium"
    assert bench_summary.summary(tmp_path) is first  # cached
    (tmp_path / MATRIX[0][0]).write_text(json.dumps(MATRIX[0][1]), encoding="utf-8")
    assert bench_summary.summary(tmp_path)["files"] == 2


def test_the_versioned_results_give_every_study():
    """The files in data/agentic (in the image too): four studies, with the report's numbers of 2026-10-25."""
    result = bench_summary.summary()
    if not result["files"]:
        pytest.skip("no result files")
    found = study(result, "rag-vs-agent")
    assert config(found, "rag-medium")["results"]["caselaw"]["success"] == pytest.approx(0.60, abs=0.005)
    assert config(found, "agent-medium-medium")["results"]["plans"]["success"] == pytest.approx(0.625, abs=0.005)
    assert found["best"] == "agent-medium-medium"
    assert {s["key"] for s in result["studies"]} == {"rag-vs-agent", "beyond-verdict", "optimisation", "missing-info"}
