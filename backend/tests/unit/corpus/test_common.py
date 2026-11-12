"""Where the corpus steps read and write: backend/data, as on v2, now that the code sits in backend/src (#64)."""
import importlib

import pytest

from corpus import common


@pytest.fixture
def reload_common(monkeypatch):
    """Reload corpus.common under a patched environment, without reading the developer's backend/.env, and restore
    it afterwards for the other tests."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    yield lambda: importlib.reload(common)
    monkeypatch.undo()
    importlib.reload(common)


def test_backend_dir_is_the_backend_folder():
    assert (common.BACKEND_DIR / "pyproject.toml").is_file()
    assert common.SRC_DIR == common.BACKEND_DIR / "src"


def test_data_folder_defaults_to_backend_data(monkeypatch, reload_common):
    monkeypatch.delenv("CORPUS_DATA_DIR", raising=False)
    module = reload_common()
    assert module.DATA_DIR == module.BACKEND_DIR / "data" / "corpus"
    assert module.INDEX_DIR == module.BACKEND_DIR / "data" / "index"


def test_snapshot_setting_picks_another_corpus_folder(monkeypatch, reload_common):
    monkeypatch.setenv("CORPUS_DATA_DIR", "data/small")
    module = reload_common()
    assert module.DATA_DIR == module.BACKEND_DIR / "data" / "small" / "corpus"
    assert module.RESULTS_ROOT == module.BACKEND_DIR / "data"  # benchmark results stay in data/ whatever the corpus


@pytest.mark.parametrize("garbled, fixed", [
    ("OmvandlingsomrÃ¥den - Haninge kommun", "Omvandlingsområden - Haninge kommun"),
    ("VÃ¤lj kranvatten â\x80\x93 bra", "Välj kranvatten – bra"),  # read as latin-1
    ("VÃ¤lj kranvatten â€“ bra", "Välj kranvatten – bra"),  # read as cp1252
    ("Planprogram för Ã rsta Slott", "Planprogram för Årsta Slott"),  # the 0x85 of "Å" became a space
    ("Café Ångström – 50 m² “citat”", "Café Ångström – 50 m² “citat”"),  # correct text is left alone
    ("", ""),
])
def test_repair_mojibake(garbled, fixed):
    from corpus.common import repair_mojibake

    assert repair_mojibake(garbled) == fixed
