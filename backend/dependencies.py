from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
import models
from datetime import datetime

def get_current_user(req: Request, db: Session = Depends(get_db)):
    token = req.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session = db.query(models.Session).filter(
        models.Session.token == token,
        models.Session.expires_at > datetime.utcnow()
    ).first()
    
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    
    return session.user
