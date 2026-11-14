"""Unit tests for localrag.corpus_dump (issue #114): manifest, dump contents, validation rules, swap and roll back SQL."""
import hashlib

import pytest

from localrag import corpus_dump
from localrag.corpus_dump import InvalidManifest

SHA = "ab" * 32


def manifest(**changes):
    return {"format": "pyrmit-corpus-dump", "version": 1, "schema": "corpus_next", "model": "st-bge-m3", "dim": 1024,
            "chunks": 4500, "kommuner": ["0115"], "label_schema_version": 1, "built": "2026-11-14T19:45:32+00:00",
            "database_mb": 15.5, "dump_file": "x.dump", "dump_bytes": 1000, "sha256": SHA, **changes}


def test_a_good_manifest_passes():
    assert corpus_dump.check_manifest(manifest(), 1000)["chunks"] == 4500


@pytest.mark.parametrize("changes, message", [
    ({"format": "other"}, "Not a pyrmit-corpus-dump"),
    ({"version": 2}, "version 2"),
    ({"sha256": None}, "lacks sha256"),
    ({"sha256": "nothex"}, "not a hex SHA-256"),
    ({"schema": "corpus"}, "--from-schema corpus"),  # a downloaded dump: re-export it first
    ({"chunks": 0}, "chunks is not a positive"),
    ({"dim": "1024"}, "dim is not a positive"),
])
def test_a_manifest_the_restore_cannot_use_is_refused(changes, message):
    with pytest.raises(InvalidManifest, match=message):
        corpus_dump.check_manifest(manifest(**changes))


def test_the_file_size_must_be_the_manifests():
    with pytest.raises(InvalidManifest, match="the manifest says 1,000"):
        corpus_dump.check_manifest(manifest(), 999)


def test_sha256_of_a_file_reports_its_progress(tmp_path):
    path = tmp_path / "x.dump"
    path.write_bytes(b"0123456789" * 1000)
    seen = []
    assert corpus_dump.sha256_file(path, seen.append, block=4096) == hashlib.sha256(path.read_bytes()).hexdigest()
    assert seen == [4096, 8192, 10000]


def test_label_schema_version():
    assert corpus_dump.label_schema_version(["chunk_id", "text"]) == 1
    assert corpus_dump.label_schema_version(["chunk_id", "text", "place", "fetched_at", "plan_id"]) == 2


# What pg_restore -l printed for a dump of localrag.export (the end-to-end check of issue #114), shortened
TOC = """;
; Archive created at 2026-11-14 19:40:41 UTC
;     dbname: export
;
7; 2615 17155 SCHEMA - corpus_next pyrmit
221; 1259 17156 TABLE corpus_next corpus_chunks pyrmit
227; 1259 23215 VIEW corpus_next chunks pyrmit
3641; 0 17156 TABLE DATA corpus_next corpus_chunks pyrmit
3482; 2606 17162 CONSTRAINT corpus_next corpus_chunks corpus_chunks_pkey pyrmit
3484; 1259 23213 INDEX corpus_next corpus_chunks_stems pyrmit
"""


def test_a_dump_of_corpus_next_is_accepted_and_its_entries_counted():
    assert corpus_dump.toc_entries(TOC) == 6


@pytest.mark.parametrize("line, message", [
    ("9; 1259 1 TABLE public users pyrmit", "holds schema public"),
    ("9; 1259 1 TABLE corpus corpus_chunks pyrmit", "holds schema corpus,"),
    ("9; 1255 1 FUNCTION corpus_next evil() pyrmit", "doesn't accept"),
    ("9; 3079 1 EXTENSION - vector", "doesn't accept"),
    ("9; 2615 1 SCHEMA - other pyrmit", "outside schema corpus_next"),
])
def test_a_dump_with_anything_else_is_refused(line, message):
    with pytest.raises(ValueError, match=message):
        corpus_dump.toc_entries(TOC + line + "\n")


def test_an_empty_dump_is_refused():
    with pytest.raises(ValueError, match="empty"):
        corpus_dump.toc_entries(";\n; nothing\n")


def test_restore_progress_counts_finished_items():
    assert corpus_dump.restore_progress("pg_restore: finished item 3641 TABLE DATA corpus_chunks")
    assert not corpus_dump.restore_progress("pg_restore: launching item 3641 TABLE DATA corpus_chunks")


def facts(**changes):
    return {"meta": {"model": "st-bge-m3", "dim": 1024, "chunks": 4500}, "chunks": 4500, "dim": 1024,
            "columns": ["chunk_id", "text", "embedding"], "query_error": None, **changes}


def same(a, b):
    return {a, b} <= {"st-bge-m3", "or-bge-m3"}


def errors(facts_, manifest_=None, app_model="or-bge-m3", app_dim=1024, columns=("chunk_id", "text")):
    return corpus_dump.validation_errors(manifest_ or manifest(), facts_, app_model, app_dim, same, columns)


def test_a_corpus_matching_the_manifest_and_the_app_is_valid():
    assert errors(facts()) == []
    assert errors(facts(), app_dim=None) == []  # the model's dimension unknown: the others must still agree


@pytest.mark.parametrize("facts_, kwargs, message", [
    (facts(meta=None), {}, "no corpus_meta"),
    (facts(), {"app_model": "st-arctic-l-v2"}, "the app embeds queries with st-arctic-l-v2"),
    (facts(meta={"model": "or-bge-m3", "dim": 1024, "chunks": 4500}), {}, "the manifest st-bge-m3"),
    (facts(dim=768), {}, "the embedding column 768"),
    (facts(), {"app_dim": 3072}, "the app's model 3072"),
    (facts(chunks=4499), {}, "rows 4499"),
    (facts(), {"manifest_": manifest(chunks=4501)}, "the manifest 4501"),
    (facts(), {"columns": ("chunk_id", "place")}, "lacks the columns this app reads: place"),
    (facts(query_error="chunk 0 not found by its own vector"), {}, "test query failed: chunk 0"),
])
def test_a_corpus_that_does_not_fit_is_refused(facts_, kwargs, message):
    found = errors(facts_, **kwargs)
    assert any(message in error for error in found), found


def test_the_swap_drops_the_old_previous_version_and_keeps_the_live_one():
    assert corpus_dump.swap_statements({"corpus", "corpus_prev", "corpus_next"}) == [
        "DROP SCHEMA corpus_prev CASCADE",
        "ALTER SCHEMA corpus RENAME TO corpus_prev",
        "ALTER SCHEMA corpus_next RENAME TO corpus",
    ]


def test_the_first_swap_and_one_without_a_previous_version():
    assert corpus_dump.swap_statements({"corpus_next"}) == ["ALTER SCHEMA corpus_next RENAME TO corpus"]
    assert corpus_dump.swap_statements({"corpus", "corpus_next"}) == [
        "ALTER SCHEMA corpus RENAME TO corpus_prev", "ALTER SCHEMA corpus_next RENAME TO corpus"]


def test_no_swap_without_corpus_next():
    with pytest.raises(ValueError):
        corpus_dump.swap_statements({"corpus", "corpus_prev"})


def test_the_roll_back_swaps_the_live_and_previous_versions():
    assert corpus_dump.rollback_statements({"corpus", "corpus_prev"}) == [
        "ALTER SCHEMA corpus RENAME TO corpus_rollback",
        "ALTER SCHEMA corpus_prev RENAME TO corpus",
        "ALTER SCHEMA corpus_rollback RENAME TO corpus_prev",
    ]
    with pytest.raises(ValueError, match="no previous version"):
        corpus_dump.rollback_statements({"corpus"})
