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
