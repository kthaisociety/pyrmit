"""Users and their roles, for owners (issue #112, roles.py).

- GET   /api/users                  every user with their role, and whether OWNER_EMAILS names them
- PATCH /api/users/{user_id}/role   give a user another role; 409 for the last owner or an OWNER_EMAILS owner
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import models
import roles
import schemas
from db.database import get_db
from dependencies import require_owner

router = APIRouter()


def _row(user: models.User) -> schemas.UserWithRole:
    return schemas.UserWithRole(id=user.id, name=user.name or "", email=user.email, role=user.role or roles.USER,
                                from_owner_emails=roles.is_env_owner(user))


@router.get("/users", response_model=list[schemas.UserWithRole])
def list_users(db: Session = Depends(get_db), _owner: models.User = Depends(require_owner)):
    users = db.query(models.User).order_by(models.User.created_at, models.User.email).all()
    return [_row(user) for user in users]


@router.patch("/users/{user_id}/role", response_model=schemas.UserWithRole)
def set_user_role(user_id: str, request: schemas.SetRoleRequest, db: Session = Depends(get_db),
                  _owner: models.User = Depends(require_owner)):
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    try:
        roles.set_role(db, target, request.role)
    except roles.RoleChangeRefused as refused:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refused)) from None
    return _row(target)
