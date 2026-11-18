"""Unit tests for localrag.export (issue #114): the dump is hashed as it is written, the manifest says what the server
checks."""
import hashlib
import sys

import pytest

from localrag import corpus_dump, export

# Stands in for pg_dump: writes 3 MB to stdout whatever its arguments
FAKE_PG_DUMP = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'PGDMP' + b'x' * 3_000_000)"]


def test_the_dump_is_written_and_hashed_in_one_pass(tmp_path):
    size, sha256 = export.dump(FAKE_PG_DUMP, "postgresql://h/db", tmp_path / "c.dump")
    data = (tmp_path / "c.dump").read_bytes()
    assert size == len(data) == 3_000_005
    assert sha256 == hashlib.sha256(data).hexdigest()
    assert not (tmp_path / "c.partial").exists()


def test_a_failed_pg_dump_leaves_no_file(tmp_path):
    out = tmp_path / "export"
    out.mkdir()
    with pytest.raises(SystemExit, match="pg_dump failed"):
        export.dump([sys.executable, "-c", "import sys; sys.exit(3)"], "postgresql://h/db", out / "c.dump")
    assert list(out.iterdir()) == []


def test_the_manifest_passes_the_servers_check():
    facts = {"meta": {"model": "st-bge-m3", "dim": 1024, "kommuner": ["0115"], "built": "2026-11-14T19:45:32+00:00"},
             "columns": ["chunk_id", "place", "fetched_at"], "chunks": 4500, "database_mb": 15.5}
    manifest = export.manifest_for(facts, "c.dump", 1234, "ab" * 32, "pg_dump (PostgreSQL) 17.12")
    assert corpus_dump.check_manifest(manifest, 1234) is manifest
    assert manifest["label_schema_version"] == 2 and manifest["schema"] == "corpus_next"
