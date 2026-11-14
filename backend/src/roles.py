"""User roles (issue #112): owner, developer, user.

- `owner`: everything, including changing other users' roles and replacing the corpus.
- `developer`: the work tools (ingesting chunks, benchmark runs) and read access to the admin views.
- `user`: the chat.

The first owners come from `OWNER_EMAILS` (comma-separated, case-insensitive), applied at startup and at every sign-in.
Nobody can remove the last owner. The backend checks roles on every sensitive route (`dependencies.require_role`);
the UI only hides what the role can't use.
"""
import logging
import os

from sqlalchemy import func
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

OWNER = "owner"
DEVELOPER = "developer"
USER = "user"
ROLES = (OWNER, DEVELOPER, USER)

# Roles that may use the work tools: writes to the shared database, runs that spend credits
STAFF = (OWNER, DEVELOPER)


class RoleChangeRefused(Exception):
    """A role change that would break a rule (last owner, an owner set by OWNER_EMAILS). The message says why."""


def owner_emails() -> frozenset[str]:
    return frozenset(email.strip().lower() for email in os.getenv("OWNER_EMAILS", "").split(",") if email.strip())


def is_env_owner(user: models.User) -> bool:
    return (user.email or "").lower() in owner_emails()


def promote_if_env_owner(user: models.User) -> None:
    """At sign-in or sign-up: an account named in OWNER_EMAILS becomes owner. The caller commits (with the login
    session, so a failed sign-up leaves nothing behind). Never demotes anyone."""
    if user.role != OWNER and is_env_owner(user):
        user.role = OWNER
        logger.info("OWNER_EMAILS made user %s owner", user.id)


def apply_owner_emails(db: Session) -> int:
    """At startup: every account named in OWNER_EMAILS becomes owner. Never demotes anyone. Returns how many accounts
    changed. Commits."""
    emails = owner_emails()
    if not emails:
        return 0
    promoted = db.query(models.User).filter(func.lower(models.User.email).in_(emails),
                                            models.User.role != OWNER).all()
    for account in promoted:
        account.role = OWNER
    if promoted:
        db.commit()
        logger.info("OWNER_EMAILS made %d account(s) owner", len(promoted))
    return len(promoted)


def set_role(db: Session, target: models.User, role: str) -> models.User:
    """Give `target` a new role. Refuses to remove the last owner or an owner named in OWNER_EMAILS. Commits."""
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}")
    if target.role == OWNER and role != OWNER:
        if is_env_owner(target):
            raise RoleChangeRefused(
                f"{target.email} is an owner through OWNER_EMAILS: remove them from it first"
            )
        # Lock the owner rows, so two owners demoting each other at once can't leave none (Postgres; SQLite ignores it)
        owners = db.query(models.User.id).filter(models.User.role == OWNER).with_for_update().all()
        if len(owners) <= 1:
            raise RoleChangeRefused("This is the last owner: make someone else owner first")
    target.role = role
    db.commit()
    db.refresh(target)
    return target
