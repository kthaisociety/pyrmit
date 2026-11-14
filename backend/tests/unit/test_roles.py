"""Unit tests for roles (issue #112)."""
import pytest

import models
import roles
import schemas
from routers import auth


def add_user(db, user_id, email, role="user"):
    user = models.User(id=user_id, name=user_id, email=email, role=role)
    db.add(user)
    db.commit()
    return user


def test_a_new_account_is_a_plain_user(token, db):
    assert db.query(models.User).one().role == "user"


def test_owner_emails_are_read_case_insensitively_and_blanks_are_ignored(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", " Anna@KTH.se, ,bo@kth.se,")
    assert roles.owner_emails() == {"anna@kth.se", "bo@kth.se"}


def test_without_owner_emails_startup_promotes_nobody(db, monkeypatch):
    monkeypatch.delenv("OWNER_EMAILS", raising=False)
    add_user(db, "a", "anna@kth.se")
    assert roles.apply_owner_emails(db) == 0
    assert db.get(models.User, "a").role == "user"


def test_startup_makes_the_owner_emails_accounts_owners_and_demotes_nobody(db, monkeypatch):
    add_user(db, "a", "Anna@kth.se")
    add_user(db, "b", "bo@kth.se", role="developer")
    add_user(db, "c", "cy@kth.se", role="owner")
    monkeypatch.setenv("OWNER_EMAILS", "anna@kth.se")
    assert roles.apply_owner_emails(db) == 1
    assert {u.id: u.role for u in db.query(models.User)} == {"a": "owner", "b": "developer", "c": "owner"}


def test_an_owner_emails_account_is_owner_from_its_sign_up(db, monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "test@example.com")
    auth.signup(schemas.SignUpRequest(name="Test User", email="test@example.com", password="test-password"), db)
    assert db.query(models.User).one().role == "owner"


def test_sign_in_makes_an_account_owner_once_it_is_added_to_owner_emails(token, db, signup_request, monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", signup_request.email.upper())
    auth.signin(schemas.SignInRequest(email=signup_request.email, password=signup_request.password), db)
    assert db.query(models.User).one().role == "owner"


@pytest.mark.parametrize("role", ["developer", "user"])
def test_an_owner_can_be_demoted_while_another_owner_remains(db, role):
    add_user(db, "a", "anna@kth.se", role="owner")
    add_user(db, "b", "bo@kth.se", role="owner")
    assert roles.set_role(db, db.get(models.User, "a"), role).role == role


@pytest.mark.parametrize("role", ["developer", "user"])
def test_the_last_owner_cannot_be_demoted(db, role):
    add_user(db, "a", "anna@kth.se", role="owner")
    add_user(db, "b", "bo@kth.se", role="developer")
    with pytest.raises(roles.RoleChangeRefused, match="last owner"):
        roles.set_role(db, db.get(models.User, "a"), role)
    db.rollback()
    assert db.get(models.User, "a").role == "owner"


def test_an_owner_named_in_owner_emails_cannot_be_demoted_from_the_app(db, monkeypatch):
    add_user(db, "a", "anna@kth.se", role="owner")
    add_user(db, "b", "bo@kth.se", role="owner")
    monkeypatch.setenv("OWNER_EMAILS", "anna@kth.se")
    with pytest.raises(roles.RoleChangeRefused, match="OWNER_EMAILS"):
        roles.set_role(db, db.get(models.User, "a"), "user")


def test_users_can_be_promoted_and_an_unknown_role_is_refused(db):
    add_user(db, "a", "anna@kth.se")
    assert roles.set_role(db, db.get(models.User, "a"), "owner").role == "owner"
    with pytest.raises(ValueError):
        roles.set_role(db, db.get(models.User, "a"), "admin")
