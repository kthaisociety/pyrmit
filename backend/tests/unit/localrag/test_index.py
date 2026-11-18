"""VectorStore: vectors written in place in a memmap that grows, re-embedded chunks replaced, reopened after a save."""

import numpy as np

from localrag import index


def chunk(chunk_id, text="text", header="h"):
    return {"chunk_id": chunk_id, "header": header, "text": text}


def test_vector_store_grows_and_replaces(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "INDEX_DIR", tmp_path)
    store = index.VectorStore("m", writable=True)
    store.add([chunk("a"), chunk("b")], np.array([[1, 0], [0, 1]], dtype=np.float32))
    store.save()
    store.add([chunk("c")] + [chunk(f"x{i}") for i in range(5)], np.full((6, 2), 2, dtype=np.float32))  # grows
    store.add([chunk("a", header="new header")], np.array([[3, 3]], dtype=np.float32))  # re-embedded in place
    store.save()
    assert store.matrix.shape[0] >= 8

    reopened = index.VectorStore("m")
    assert reopened.ids == ["a", "b", "c"] + [f"x{i}" for i in range(5)]
    assert reopened.get(["a", "b", "c"]).tolist() == [[3, 3], [0, 1], [2, 2]]
    assert not reopened.needs(chunk("a", header="new header")) and reopened.needs(chunk("a"))
    assert reopened.needs(chunk("d"))


def test_unsaved_rows_are_ignored_on_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(index, "INDEX_DIR", tmp_path)
    store = index.VectorStore("m", writable=True)
    store.capacity_hint = 10
    store.add([chunk("a")], np.ones((1, 2), dtype=np.float32))
    store.save()
    store.add([chunk("b")], np.ones((1, 2), dtype=np.float32))  # interrupted before save
    del store
    reopened = index.VectorStore("m")
    assert reopened.ids == ["a"] and reopened.matrix.shape == (10, 2)


def test_adding_labels_to_embedded_chunks_needs_no_embedding(tmp_path, monkeypatch):
    """chunks.jsonl rebuilt with the schema labels (#106): every chunk keeps its vector."""
    monkeypatch.setattr(index, "INDEX_DIR", tmp_path)
    before = [chunk("a", "Byggnadsarea 200 m2", "Vallentuna kommun – Plan"), chunk("b", "1 § Text.", "PBL, 1 §")]
    store = index.VectorStore("m", writable=True)
    store.add(before, np.ones((2, 2), dtype=np.float32))
    store.save()
    labels = {"place": "Vallentuna", "fetched_at": "2026-10-22T14:08:43+00:00", "fetched_at_source": "file_mtime",
              "plan_id": "0123456789abcdef", "plan_stage": "in_force", "content_sha1": "f" * 40}
    assert index.VectorStore("m").missing([{**c, **labels} for c in before]) == []
