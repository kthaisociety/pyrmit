from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from db.database import get_db
import models
import schemas
from dependencies import get_current_session, get_current_user
from security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    get_access_token_expire_minutes,
    get_password_hash,
    verify_password,
)

router = APIRouter()


def _authenticate_user(db: Session, email: str, password: str) -> models.User | None:
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None

    account = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.provider_id == "credentials",
    ).first()
    if account is None or not account.password:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None

    if not verify_password(password, account.password):
        return None

    return user


def _issue_access_token(user: models.User, db: Session) -> schemas.Token:
    session_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(
        minutes=get_access_token_expire_minutes()
    )
    access_token = create_access_token(
        subject=f"user:{user.id}",
        session_id=session_id,
        expires_at=expires_at,
    )
    db.add(models.Session(id=session_id, user_id=user.id, expires_at=expires_at))
    db.commit()
    return schemas.Token(access_token=access_token, token_type="bearer")


@router.post("/signup", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def signup(request: schemas.SignUpRequest, db: Session = Depends(get_db)):
    existing_user = db.query(models.User).filter(models.User.email == request.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create User
    user_id = str(uuid.uuid4())
    new_user = models.User(
        id=user_id,
        name=request.name,
        email=request.email,
        image=f"https://api.dicebear.com/7.x/avataaars/svg?seed={request.name}" # Default avatar
    )
    db.add(new_user)
    
    # Create Account (Credentials)
    account_id = str(uuid.uuid4())
    new_account = models.Account(
        id=account_id,
        user_id=user_id,
        provider_id="credentials",
        account_id=request.email, # Using email as provider account id for credentials
        password=get_password_hash(request.password)
    )
    db.add(new_account)

    return _issue_access_token(new_user, db)


@router.post("/token", response_model=schemas.Token)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = _authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_access_token(user, db)


@router.post("/signin", response_model=schemas.Token)
def signin(request: schemas.SignInRequest, db: Session = Depends(get_db)):
    user = _authenticate_user(db, request.email, request.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_access_token(user, db)

@router.post("/signout")
def signout(
    session: models.Session = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    db.delete(session)
    db.commit()
    return {"message": "Signed out successfully"}

@router.get("/me", response_model=schemas.UserPublic)
def get_me(user: models.User = Depends(get_current_user)):
    return schemas.UserPublic(id=user.id, name=user.name, email=user.email)

@router.patch("/me", response_model=schemas.UserPublic)
def update_profile(request: schemas.UpdateProfileRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    user.name = request.name
    db.commit()
    db.refresh(user)
    return schemas.UserPublic(id=user.id, name=user.name, email=user.email)

@router.patch("/password")
def change_password(request: schemas.ChangePasswordRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    account = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.provider_id == "credentials"
    ).first()
    if not account or not account.password:
        raise HTTPException(status_code=400, detail="No password-based account found")
    if not verify_password(request.current_password, account.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    account.password = get_password_hash(request.new_password)
    db.commit()
    return {"message": "Password changed successfully"}
