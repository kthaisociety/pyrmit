"""Unit tests for routers.auth."""
from datetime import UTC

import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import event

import models
import schemas
from dependencies import get_current_session
from routers import auth
from security import decode_access_token


def test_every_login_route_creates_its_own_session(token, db, signup_request):
    signin = auth.signin(
        schemas.SignInRequest(email=signup_request.email, password=signup_request.password), db
    ).access_token
    form_login = auth.login_for_access_token(
        OAuth2PasswordRequestForm(username=signup_request.email, password=signup_request.password), db
    ).access_token

    session_ids = set()
    for issued in (token, signin, form_login):
        session = get_current_session(issued, db)
        expires_at = int(session.expires_at.replace(tzinfo=UTC).timestamp())
        assert decode_access_token(issued)["exp"] == expires_at
        session_ids.add(session.id)
    assert len(session_ids) == 3


def test_signout_revokes_only_the_current_login_and_keeps_chat_history(token, db):
    session = get_current_session(token, db)
    user = session.user
    other_token = auth._issue_access_token(user, db).access_token
    db.add(models.ChatSession(id="chat", user_id=user.id, title="Keep"))
    db.flush()
    db.add(models.ChatMessage(session_id="chat", role="user", content="Keep"))
    db.commit()

    auth.signout(session, db)

    with pytest.raises(HTTPException) as error:
        get_current_session(token, db)
    assert error.value.status_code == 401
    assert get_current_session(other_token, db) is not None
    assert db.query(models.User).count() == 1
    assert db.query(models.Account).count() == 1
    assert db.query(models.ChatMessage).count() == 1


def test_wrong_password_does_not_create_a_session(token, db, signup_request):
    with pytest.raises(HTTPException) as error:
        auth.signin(schemas.SignInRequest(email=signup_request.email, password="wrong-password"), db)
    assert error.value.status_code == 401
    assert db.query(models.Session).count() == 1


def test_signup_rolls_back_the_user_if_the_session_insert_fails(token, db, engine):
    def fail_session_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO sessions"):
            raise RuntimeError("Simulated database failure")

    event.listen(engine, "before_cursor_execute", fail_session_insert)
    try:
        with pytest.raises(RuntimeError):
            auth.signup(
                schemas.SignUpRequest(name="Another User", email="another@example.com", password="test-password"),
                db,
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_session_insert)
        db.rollback()
    assert db.query(models.User).count() == 1
    assert db.query(models.Account).count() == 1
    assert db.query(models.Session).count() == 1
