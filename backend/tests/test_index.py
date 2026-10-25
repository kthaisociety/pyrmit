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
