import pytest

from localrag import service


def test_corpus_database_defaults_to_the_app_database(monkeypatch):
    """Without CORPUS_DATABASE_URL the corpus is read from DATABASE_URL, the one database the deployed app has."""
    monkeypatch.delenv("CORPUS_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app/db")
    assert service.corpus_database_url() == "postgresql://app/db"


def test_corpus_database_url_wins_over_the_app_database(monkeypatch):
    """A separate corpus database (the Neon demo branch) is used when CORPUS_DATABASE_URL names one."""
    monkeypatch.setenv("CORPUS_DATABASE_URL", "postgresql://corpus/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app/db")
    assert service.corpus_database_url() == "postgresql://corpus/db"


def test_empty_corpus_database_url_counts_as_unset(monkeypatch):
    """An empty CORPUS_DATABASE_URL (a blank line in an env file) falls back to DATABASE_URL."""
    monkeypatch.setenv("CORPUS_DATABASE_URL", "  ")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app/db")
    assert service.corpus_database_url() == "postgresql://app/db"


def test_no_database_at_all_raises(monkeypatch):
    """Neither variable set is an error at startup, not a silent empty corpus."""
    monkeypatch.delenv("CORPUS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(KeyError):
        service.corpus_database_url()
