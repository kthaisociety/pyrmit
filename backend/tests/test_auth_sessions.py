"""Run from backend/: python -m unittest tests.test_auth_sessions -v"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

# Never connect these tests to the application's configured database.
with patch.dict(os.environ, {"DATABASE_URL": "sqlite://"}):
    import models
    import schemas
    from dependencies import get_current_session, get_current_user
    from routers import auth
    from security import decode_access_token


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "JWT_SECRET_KEY": "test-only-signing-key-at-least-32-bytes",
            "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
        })
        env.start()
        self.addCleanup(env.stop)
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        models.Base.metadata.create_all(self.engine, tables=[
            model.__table__ for model in (
                models.User, models.Account, models.Session,
                models.ChatSession, models.ChatMessage,
            )
        ])
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.request = schemas.SignUpRequest(
            name="Test User", email="test@example.com", password="test-password",
        )
        self.token = auth.signup(self.request, self.db).access_token

    def assert_unauthorized(self, token):
        with self.assertRaises(HTTPException) as error:
            get_current_session(token, self.db)
        self.assertEqual(error.exception.status_code, 401)

    def test_all_login_routes_create_independent_sessions(self):
        signin = auth.signin(schemas.SignInRequest(
            email=self.request.email, password=self.request.password,
        ), self.db).access_token
        login = auth.login_for_access_token(OAuth2PasswordRequestForm(
            username=self.request.email, password=self.request.password,
        ), self.db).access_token
        ids = set()
        for token in (self.token, signin, login):
            claims = decode_access_token(token)
            session = get_current_session(token, self.db)
            ids.add(session.id)
            self.assertEqual(claims["sid"], session.id)
            self.assertEqual(claims["sub"], f"user:{session.user_id}")
            self.assertEqual(claims["exp"], int(
                session.expires_at.replace(tzinfo=timezone.utc).timestamp()
            ))
            self.assertEqual(get_current_user(session).email, self.request.email)
        self.assertEqual(len(ids), 3)

    def test_signout_revokes_only_current_login_and_preserves_history(self):
        session = get_current_session(self.token, self.db)
        user = session.user
        other = auth._issue_access_token(user, self.db).access_token
        self.db.add(models.ChatSession(id="chat", user_id=user.id, title="Keep"))
        self.db.flush()
        self.db.add(models.ChatMessage(session_id="chat", role="user", content="Keep"))
        self.db.commit()
        auth.signout(session, self.db)
        self.assert_unauthorized(self.token)
        self.assertIsNotNone(get_current_session(other, self.db))
        self.assertEqual(self.db.query(models.User).count(), 1)
        self.assertEqual(self.db.query(models.Account).count(), 1)
        self.assertEqual(self.db.query(models.ChatMessage).count(), 1)

    def test_expired_database_session_is_rejected_but_not_deleted(self):
        session = get_current_session(self.token, self.db)
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()
        self.assert_unauthorized(self.token)
        self.assertEqual(self.db.query(models.Session).count(), 1)

    def test_invalid_claims_and_signature_are_rejected(self):
        claims = decode_access_token(self.token)
        invalid = [dict(claims, sid="missing"), dict(claims, sid=""),
                   dict(claims, sid=123), dict(claims, sub="user:someone-else"),
                   dict(claims, exp=0)]
        for field in ("sub", "sid", "exp"):
            invalid.append({k: v for k, v in claims.items() if k != field})
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assert_unauthorized(jwt.encode(
                    payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256",
                ))
        self.assert_unauthorized(jwt.encode(claims, "different-test-key-at-least-32-bytes", algorithm="HS256"))

    def test_bad_password_does_not_create_session(self):
        with self.assertRaises(HTTPException) as error:
            auth.signin(schemas.SignInRequest(
                email=self.request.email, password="wrong-password",
            ), self.db)
        self.assertEqual(error.exception.status_code, 401)
        self.assertEqual(self.db.query(models.Session).count(), 1)

    def test_signup_rolls_back_if_session_insert_fails(self):
        def fail_session_insert(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO sessions"):
                raise RuntimeError("Simulated database failure")

        event.listen(self.engine, "before_cursor_execute", fail_session_insert)
        try:
            with self.assertRaises(RuntimeError):
                auth.signup(schemas.SignUpRequest(
                    name="Another User", email="another@example.com", password="test-password",
                ), self.db)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_session_insert)
            self.db.rollback()
        self.assertEqual(self.db.query(models.User).count(), 1)
        self.assertEqual(self.db.query(models.Account).count(), 1)
        self.assertEqual(self.db.query(models.Session).count(), 1)


if __name__ == "__main__":
    unittest.main()
