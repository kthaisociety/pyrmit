from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from passlib.context import CryptContext
import uuid
from datetime import datetime, timedelta
from dependencies import get_current_user

router = APIRouter()

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_session(db: Session, user_id: str, ip_address: str = None, user_agent: str = None):
    session_id = str(uuid.uuid4())
    token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(days=30)
    
    db_session = models.Session(
        id=session_id,
        user_id=user_id,
        token=token,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session

@router.post("/signup", response_model=schemas.SessionResponse)
def signup(request: schemas.SignUpRequest, response: Response, req: Request, db: Session = Depends(get_db)):
    # Check if user exists
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
    db.commit()
    db.refresh(new_user)

    # Create Session
    client_ip = req.client.host
    user_agent = req.headers.get("user-agent")
    session = create_session(db, user_id, client_ip, user_agent)

    # Set cookie
    response.set_cookie(
        key="session_token",
        value=session.token,
        httponly=True,
        max_age=30 * 24 * 60 * 60, # 30 days
        samesite="lax",
        secure=False # Set to True in production with HTTPS
    )

    return schemas.SessionResponse(
        session_id=session.id,
        user=schemas.UserPublic(id=new_user.id, name=new_user.name, email=new_user.email)
    )

@router.post("/signin", response_model=schemas.SessionResponse)
def signin(request: schemas.SignInRequest, response: Response, req: Request, db: Session = Depends(get_db)):
    # Find User
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    # Find Account
    account = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.provider_id == "credentials"
    ).first()

    if not account or not account.password:
        raise HTTPException(status_code=400, detail="Invalid credentials or social login used")

    if not verify_password(request.password, account.password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    # Create Session
    client_ip = req.client.host
    user_agent = req.headers.get("user-agent")
    session = create_session(db, user.id, client_ip, user_agent)

    # Set cookie
    response.set_cookie(
        key="session_token",
        value=session.token,
        httponly=True,
        max_age=30 * 24 * 60 * 60, # 30 days
        samesite="lax",
        secure=False 
    )

    return schemas.SessionResponse(
        session_id=session.id,
        user=schemas.UserPublic(id=user.id, name=user.name, email=user.email)
    )

@router.post("/signout")
def signout(response: Response, req: Request, db: Session = Depends(get_db)):
    token = req.cookies.get("session_token")
    if token:
        db.query(models.Session).filter(models.Session.token == token).delete()
        db.commit()
    
    response.delete_cookie("session_token")
    return {"message": "Signed out successfully"}

@router.get("/me", response_model=schemas.UserPublic)
def get_me(user: models.User = Depends(get_current_user)):
    return schemas.UserPublic(id=user.id, name=user.name, email=user.email)
