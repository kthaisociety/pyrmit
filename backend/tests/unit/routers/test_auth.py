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


# --- the user's own OpenRouter key (issue #108) -----------------------------------------------------------------------

USER_KEY = "sk-or-v1-" + "ab12" * 16  # a made-up key in OpenRouter's format


@pytest.fixture
def encryption_key(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def api(signup_request):
    """The auth router over HTTP, signed in as a fresh user. Its own engine: TestClient runs the routes in another
    thread, which the shared in-memory SQLite engine refuses."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from db.database import get_db
    from dependencies import get_current_user

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine, tables=[model.__table__ for model in
                                                    (models.User, models.Account, models.Session, models.UserApiKey)])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        user_id = get_current_session(auth.signup(signup_request, db).access_token, db).user_id

    def db_override():
        with Session() as db:
            yield db

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: models.User(id=user_id, name=signup_request.name,
                                                                     email=signup_request.email)
    yield TestClient(app)
    engine.dispose()


def test_a_saved_key_is_reported_by_its_last_4_characters_only(api, encryption_key):
    saved = api.put("/api/auth/api-key", json={"api_key": USER_KEY})
    read = api.get("/api/auth/api-key")
    for response in (saved, read):
        assert response.status_code == 200
        assert response.json() == {"enabled": True, "has_key": True, "last4": "ab12"}
        assert USER_KEY not in response.text


def test_without_a_key_the_shared_key_is_reported(api, encryption_key):
    assert api.get("/api/auth/api-key").json() == {"enabled": True, "has_key": False, "last4": None}


def test_a_removed_key_is_reported_as_gone(api, encryption_key):
    api.put("/api/auth/api-key", json={"api_key": USER_KEY})
    response = api.delete("/api/auth/api-key")
    assert response.json() == {"enabled": True, "has_key": False, "last4": None}


def test_a_text_that_is_not_a_key_is_refused_without_echoing_it(api, encryption_key):
    typo = "sk-proj-" + "secret" * 8
    response = api.put("/api/auth/api-key", json={"api_key": typo})
    assert response.status_code == 400
    assert typo not in response.text


def test_without_an_encryption_key_no_key_can_be_saved(api):
    assert api.get("/api/auth/api-key").json() == {"enabled": False, "has_key": False, "last4": None}
    response = api.put("/api/auth/api-key", json={"api_key": USER_KEY})
    assert response.status_code == 503
    assert USER_KEY not in response.text


def test_the_key_request_hides_the_key_in_its_repr():
    request = schemas.SetApiKeyRequest(api_key=USER_KEY)
    assert USER_KEY not in repr(request) and USER_KEY not in str(request)


def test_users_profile_never_carries_the_key(api, encryption_key):
    api.put("/api/auth/api-key", json={"api_key": USER_KEY})
    assert USER_KEY not in api.get("/api/auth/me").text
