"""Unit tests for dependencies."""
import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

import models
from dependencies import get_current_session, get_current_user
from security import decode_access_token


def assert_unauthorized(token, db):
    with pytest.raises(HTTPException) as error:
        get_current_session(token, db)
    assert error.value.status_code == 401


def test_valid_token_resolves_its_session_and_user(token, db, signup_request):
    session = get_current_session(token, db)
    claims = decode_access_token(token)
    assert claims["sid"] == session.id
    assert claims["sub"] == f"user:{session.user_id}"
    assert get_current_user(session).email == signup_request.email


def test_expired_session_is_rejected_but_not_deleted(token, db):
    session = get_current_session(token, db)
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert_unauthorized(token, db)
    assert db.query(models.Session).count() == 1


def test_deleted_session_is_rejected(token, db):
    db.delete(get_current_session(token, db))
    db.commit()
    assert_unauthorized(token, db)


def _invalid_payloads(claims):
    yield from (
        dict(claims, sid="missing"),
        dict(claims, sid=""),
        dict(claims, sid=123),
        dict(claims, sub="user:someone-else"),
        dict(claims, exp=0),
    )
    for field in ("sub", "sid", "exp"):
        yield {k: v for k, v in claims.items() if k != field}


def test_invalid_claims_are_rejected(token, db):
    for payload in _invalid_payloads(decode_access_token(token)):
        assert_unauthorized(jwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256"), db)


def test_wrong_signature_is_rejected(token, db):
    claims = decode_access_token(token)
    assert_unauthorized(jwt.encode(claims, "different-test-key-at-least-32-bytes", algorithm="HS256"), db)
