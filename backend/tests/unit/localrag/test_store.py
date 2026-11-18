"""localrag.store.build: the schema labels reach the disk store, and a chunk missing a required one is refused."""

import json
import sqlite3

import numpy as np
import pytest

from localrag import index, store

LABELS = {"place": "Vallentuna", "fetched_at": "2026-10-22T14:08:43+00:00", "fetched_at_source": "file_mtime",
          "plan_id": "0123456789abcdef", "plan_stage": "in_force", "content_sha1": "f" * 40}


def chunk(chunk_id, **labels):
    return {"chunk_id": chunk_id, "doc_id": "pdf:0115:a", "chunk_index": 0, "kind": "pdf", "doc_type": "detaljplan",
            "kommun_code": "0115", "kommun": "Vallentuna", "title": "Plan", "url": f"https://x.se/{chunk_id}.pdf",
            "section": None, "header": "Vallentuna kommun – Plan", "text": "Byggnadsarea 200 kvadratmeter.",
            **LABELS, **labels}


@pytest.fixture
def built(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(store, "CHUNKS_PATH", tmp_path / "chunks.jsonl")

    def build(chunks):
        (tmp_path / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8")
        vectors = index.VectorStore("m", writable=True)
        vectors.add(chunks, np.eye(len(chunks), 4, dtype=np.float32))
        vectors.save()
        store.build("m")
        connection = sqlite3.connect(tmp_path / "store" / "m" / "corpus.sqlite")
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM chunks ORDER BY rowid")]

    return build


def test_labels_reach_the_disk_store(built):
    (row,) = built([chunk("a")])
    assert {label: row[label] for label in LABELS} == LABELS


def test_a_chunk_missing_a_required_label_stays_out_of_the_store(built, capsys):
    rows = built([chunk("a"), chunk("b", fetched_at=None), chunk("c", place=None)])
    assert [row["chunk_id"] for row in rows] == ["a"]
    assert "2 chunks rejected for a missing label {'place': 1, 'fetched_at': 1}" in capsys.readouterr().out


def test_a_chunks_file_from_before_the_labels_is_refused(built):
    old = {key: value for key, value in chunk("a").items() if key not in LABELS}
    with pytest.raises(SystemExit, match="re-run corpus.extract and corpus.chunk"):
        built([old])
