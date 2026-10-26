from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from db.database import get_db
import models
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
        models.Session.expires_at > datetime.now(timezone.utc),
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
