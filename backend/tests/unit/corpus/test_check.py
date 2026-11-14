import json
import sqlite3

from corpus import check


def _corpus(tmp_path, monkeypatch, model: str, vectors: list[str], stored: int):
    chunks = tmp_path / "chunks.jsonl"
    documents = tmp_path / "documents.jsonl"
    chunks.write_text("".join(json.dumps({"chunk_id": c, "doc_id": "d", "header": "h"}) + "\n" for c in ("a", "b")))
    documents.write_text(json.dumps({"doc_id": "d"}) + "\n")
    (tmp_path / "dense" / model).mkdir(parents=True)
    (tmp_path / "dense" / model / "ids.json").write_text(json.dumps(vectors))
    (tmp_path / "store" / model).mkdir(parents=True)
    db = sqlite3.connect(tmp_path / "store" / model / "corpus.sqlite")
    db.execute("CREATE TABLE chunks (chunk_id)")
    db.executemany("INSERT INTO chunks VALUES (?)", [(str(i),) for i in range(stored)])
    db.commit()
    db.close()
    monkeypatch.setattr(check, "CHUNKS_PATH", chunks)
    monkeypatch.setattr(check, "DOCUMENTS_PATH", documents)
    monkeypatch.setattr(check, "INDEX_DIR", tmp_path)


def _errors(report: check.Report) -> list[str]:
    return [line["message"] for line in report.lines if line["level"] == "ERROR"]


def test_index_check_reads_the_given_model(tmp_path, monkeypatch):
    """The 2026-11-14 rebuild failed its check: it looked at the old model's index (hard-coded) instead of bge-m3's."""
    _corpus(tmp_path, monkeypatch, "st-bge-m3", ["a", "b"], 2)
    report = check.Report()
    check.check_index(report, "st-bge-m3")
    assert _errors(report) == []


def test_index_check_of_a_model_without_an_index(tmp_path, monkeypatch):
    _corpus(tmp_path, monkeypatch, "st-bge-m3", ["a", "b"], 2)
    report = check.Report()
    check.check_index(report, "st-arctic-l-v2")
    assert any("no dense index" in message for message in _errors(report))


def test_index_check_finds_missing_vectors(tmp_path, monkeypatch):
    _corpus(tmp_path, monkeypatch, "st-bge-m3", ["a"], 1)
    report = check.Report()
    check.check_index(report, "st-bge-m3")
    assert len(_errors(report)) == 2  # one chunk without a vector, the store one chunk behind
