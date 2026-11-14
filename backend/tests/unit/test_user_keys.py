"""Unit tests for user_keys: users' own OpenRouter keys, stored encrypted (issue #108)."""
import logging

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
import user_keys

USER_KEY = "sk-or-v1-" + "ab12" * 16  # a made-up key in OpenRouter's format


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv(user_keys.ENCRYPTION_KEY_ENV, key)
    return key


@pytest.fixture
def db():
    """Only the users and their keys, in in-memory SQLite (PCR-0011)."""
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine, tables=[models.User.__table__, models.UserApiKey.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def user(db):
    db.add(models.User(id="u1", name="Anna", email="anna@example.com"))
    db.commit()
    return "u1"


def test_a_key_comes_back_unchanged_after_encryption(encryption_key):
    token = user_keys.encrypt(USER_KEY)
    assert USER_KEY not in token
    assert user_keys.decrypt(token) == USER_KEY


def test_the_database_holds_only_the_encrypted_key_and_its_last_4_characters(db, user, encryption_key):
    user_keys.save(db, user, USER_KEY)
    row = db.get(models.UserApiKey, (user, "openrouter"))
    assert USER_KEY not in row.encrypted_key
    assert row.last4 == USER_KEY[-4:]
    assert USER_KEY not in repr(row) and row.encrypted_key not in repr(row)
    assert user_keys.key_for(db, user) == USER_KEY


def test_a_new_key_replaces_the_old_one(db, user, encryption_key):
    user_keys.save(db, user, USER_KEY)
    newer = "sk-or-v1-" + "cd34" * 16
    user_keys.save(db, user, newer)
    assert db.query(models.UserApiKey).count() == 1
    assert user_keys.key_for(db, user) == newer
    assert user_keys.status(db, user) == {"enabled": True, "has_key": True, "last4": "cd34"}


def test_a_pasted_key_loses_its_surrounding_whitespace(db, user, encryption_key):
    user_keys.save(db, user, f"  {USER_KEY}\n")
    assert user_keys.key_for(db, user) == USER_KEY


@pytest.mark.parametrize("text", ["", "hello", "sk-proj-" + "x" * 40, "sk-or-short", f"{USER_KEY} extra"])
def test_a_text_that_is_not_an_openrouter_key_is_refused_without_repeating_it(db, user, encryption_key, text):
    with pytest.raises(user_keys.InvalidApiKey) as error:
        user_keys.save(db, user, text)
    assert text.strip() == "" or text not in str(error.value)
    assert db.query(models.UserApiKey).count() == 0


def test_deleting_the_key_goes_back_to_the_shared_key(db, user, encryption_key):
    user_keys.save(db, user, USER_KEY)
    user_keys.delete(db, user)
    assert user_keys.key_for(db, user) is None
    assert user_keys.status(db, user) == {"enabled": True, "has_key": False, "last4": None}


def test_without_an_encryption_key_the_feature_is_off():
    assert not user_keys.enabled()
    with pytest.raises(RuntimeError):
        user_keys.encrypt(USER_KEY)


def test_without_an_encryption_key_a_stored_key_is_not_used(db, user, encryption_key, monkeypatch):
    user_keys.save(db, user, USER_KEY)
    monkeypatch.delenv(user_keys.ENCRYPTION_KEY_ENV)
    assert user_keys.key_for(db, user) is None
    assert user_keys.status(db, user) == {"enabled": False, "has_key": False, "last4": None}


def test_an_invalid_encryption_key_turns_the_feature_off_and_is_never_logged(monkeypatch, caplog):
    monkeypatch.setenv(user_keys.ENCRYPTION_KEY_ENV, "not-a-fernet-key")
    with caplog.at_level(logging.ERROR):
        assert not user_keys.enabled()
    assert "not-a-fernet-key" not in caplog.text


def test_a_key_stored_under_another_encryption_key_counts_as_no_key(db, user, encryption_key, monkeypatch):
    user_keys.save(db, user, USER_KEY)
    monkeypatch.setenv(user_keys.ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    assert user_keys.key_for(db, user) is None
    assert user_keys.status(db, user)["has_key"] is False


def test_a_rotated_encryption_key_still_reads_keys_stored_under_the_old_one(db, user, encryption_key, monkeypatch):
    user_keys.save(db, user, USER_KEY)
    monkeypatch.setenv(user_keys.ENCRYPTION_KEY_ENV, f"{Fernet.generate_key().decode()},{encryption_key}")
    assert user_keys.key_for(db, user) == USER_KEY
