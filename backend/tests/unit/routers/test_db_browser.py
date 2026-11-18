from pathlib import Path
from types import SimpleNamespace

import pytest

from corpus.common import BACKEND_DIR
from routers import db_browser


def test_database_label_names_the_endpoint_without_the_password():
    url = "postgresql://neondb_owner:secret@ep-quiet-lake-123456-pooler.c-2.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    assert db_browser.database_label(url) == "ep-quiet-lake-123456/neondb"
    assert db_browser.database_label(None) == "not set"


@pytest.fixture
def serve(monkeypatch):
    """Make localrag.service.get_retriever return `retriever` (or raise it)."""
    import localrag.gazetteer
    import localrag.service

    monkeypatch.setattr(localrag.gazetteer, "kommun_label", lambda code: {"0380": "Uppsala (0380)"}.get(code, code))

    def use(retriever):
        def get_retriever():
            if isinstance(retriever, Exception):
                raise retriever
            return retriever
        monkeypatch.setattr(localrag.service, "get_retriever", get_retriever)
    return use


def test_agent_corpus_in_postgres(serve):
    store = SimpleNamespace(url="postgresql://u:p@ep-quiet-lake-123456-pooler.x.neon.tech/neondb",
                            meta={"chunks": 115127, "kommuner": ["0380"], "model": "st-bge-m3"})
    serve(SimpleNamespace(store=store, model="or-bge-m3"))
    source = db_browser.local_source()
    assert source.name == "Agent corpus · Postgres"  # no Neon in the Database tab any more (issue #114)
    assert "ep-quiet-lake-123456/neondb" in source.detail and "115,127 chunks of Uppsala (0380)" in source.detail
    assert "st-bge-m3 vectors, queries embedded with or-bge-m3" in source.detail


def test_agent_corpus_on_disk(serve):
    serve(SimpleNamespace(store=SimpleNamespace(dir=BACKEND_DIR / "data" / "index" / "store" / "st-arctic-l-v2"),
                          model="st-arctic-l-v2"))
    source = db_browser.local_source()
    assert source.name == "Agent corpus · disk"
    assert source.detail.startswith("disk store data/index/store/st-arctic-l-v2 ")


def test_agent_corpus_in_memory_or_missing(serve):
    serve(SimpleNamespace(chunks=[], model="st-bge-m3"))
    assert db_browser.local_source().name == "Agent corpus · memory"
    serve(FileNotFoundError("No store for st-arctic-l-v2"))
    assert db_browser.local_source().detail == "not available: No store for st-arctic-l-v2"


def test_store_outside_the_backend_folder_is_shown_whole(serve, tmp_path):
    serve(SimpleNamespace(store=SimpleNamespace(dir=Path(tmp_path)), model="m"))
    assert Path(tmp_path).as_posix() in db_browser.local_source().detail
