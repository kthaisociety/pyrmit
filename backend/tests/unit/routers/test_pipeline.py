import json

from routers import pipeline


def test_install_without_the_corpus_shows_the_national_snapshot(tmp_path, monkeypatch):
    """Corpus on Neon: no check.json here, so the page is the versioned one of the national corpus."""
    snapshot = tmp_path / "pipeline-national.json"
    snapshot.write_text(json.dumps({"corpus": "data", "steps": [], "snapshot": {"built": "2026-11-01"}}))
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path / "corpus")
    monkeypatch.setattr(pipeline, "SNAPSHOT_PATH", snapshot)
    monkeypatch.setattr(pipeline, "build", lambda: {"corpus": "neon-test", "steps": []})
    assert pipeline.pipeline(None)["snapshot"] == {"built": "2026-11-01"}


def test_machine_with_the_corpus_measures_it_live(tmp_path, monkeypatch):
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "check.json").write_text("{}")
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path / "corpus")
    monkeypatch.setattr(pipeline, "SNAPSHOT_PATH", tmp_path / "pipeline-national.json")
    monkeypatch.setattr(pipeline, "_signature", lambda: ("live",))
    monkeypatch.setattr(pipeline, "_cache", {})
    monkeypatch.setattr(pipeline, "build", lambda: {"corpus": "data", "steps": []})
    monkeypatch.setattr(pipeline, "costs_card", lambda: None)
    assert pipeline.pipeline(None) == {"corpus": "data", "steps": [], "costs": None}


def test_the_rebuild_costs_sit_apart_from_the_numbered_steps(tmp_path, monkeypatch):
    """The costs cover running every step: they come beside the steps, never as a step of their own, snapshot or not."""
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path / "corpus")
    monkeypatch.setattr(pipeline, "SNAPSHOT_PATH", pipeline.AGENTIC_DIR / "pipeline-national.json")
    result = pipeline.pipeline(None)
    assert [step["step"] for step in result["steps"]] == [1, 2, 3, 4, 5, 6]
    assert result["costs"]["id"] == "costs" and "step" not in result["costs"]


def test_costs_card_reads_the_versioned_timings():
    """The versioned file builds a card whose tables the view renders as they are."""
    step = pipeline.costs_card()
    assert step["id"] == "costs"
    assert step["flow"]["value"].startswith("≈ ")
    titles = [section["title"] for section in step["sections"]]
    assert titles == ["Each step on the laptop", "Full rebuild: the options", "Running it locally", "Updates",
                      "Price sources"]
    for section in step["sections"]:
        table = section["table"]
        assert all(len(row) == len(table["columns"]) for row in table["rows"]), section["title"]


def test_no_costs_file_no_costs_card(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "COSTS_PATH", tmp_path / "missing.json")
    assert pipeline.costs_card() is None
