from datetime import datetime, UTC
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from db.database import get_db
import models
from roles import ROLES
from security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def get_current_session(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    payload = decode_access_token(token)
    subject = payload.get("sub")
    session_id = payload.get("sid")
    if (
        not isinstance(subject, str) or not subject.startswith("user:")
        or not isinstance(session_id, str) or not session_id
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = subject.removeprefix("user:")
    session = db.query(models.Session).filter(
        models.Session.id == session_id,
        models.Session.user_id == user_id,
        models.Session.expires_at > datetime.now(UTC),
    ).first()
    if session is None or session.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return session


def get_current_user(session: models.Session = Depends(get_current_session)):
    return session.user


def require_role(*roles: str):
    """A dependency giving the current user if their role is one of `roles`, else 403 (roles.py, issue #112).
    Put it on the route itself (`user = Depends(require_role("owner"))`): hiding a button is not a check."""
    unknown = set(roles) - set(ROLES)
    if not roles or unknown:
        raise ValueError(f"require_role needs roles among {ROLES}, got {roles}")

    def current_user_with_role(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role does not allow this")
        return user

    return current_user_with_role


# The two checks the routes use (module-level, so a route's default argument is not a call)
require_owner = require_role("owner")
require_staff = require_role("owner", "developer")  # roles.STAFF: ingestion, benchmark runs
