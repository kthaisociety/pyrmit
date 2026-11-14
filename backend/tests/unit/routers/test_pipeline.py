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
    assert pipeline.pipeline(None) == {"corpus": "data", "steps": []}


def test_costs_step_reads_the_versioned_timings():
    """The versioned file builds a step whose tables the view renders as they are."""
    step = pipeline.costs_step()
    assert step["id"] == "costs" and step["step"] == 7
    assert step["flow"]["value"].startswith("≈ ")
    titles = [section["title"] for section in step["sections"]]
    assert titles == ["Each step on the laptop", "Full rebuild: the options", "Running it locally", "Updates",
                      "Price sources"]
    for section in step["sections"]:
        table = section["table"]
        assert all(len(row) == len(table["columns"]) for row in table["rows"]), section["title"]


def test_no_costs_file_no_costs_step(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "COSTS_PATH", tmp_path / "missing.json")
    assert pipeline.costs_step() is None
