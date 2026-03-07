from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
import models
import schemas
import os
import uuid
from openai import OpenAI
from sqlalchemy.sql import func
from dependencies import get_current_user
from agents.law_agent import LawAgent
from agents.document_agent import DocumentAgent
from agents.orchestrator import Orchestrator
from agents.parsers import parse_query, format_response

router = APIRouter()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.get("/sessions", response_model=list[schemas.ChatSession])
def get_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.ChatSession).filter(models.ChatSession.user_id == user.id).order_by(models.ChatSession.updated_at.desc()).all()

@router.get("/sessions/{session_id}", response_model=list[schemas.MessageResponse])
def get_session_history(session_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # Verify session belongs to user
    session = db.query(models.ChatSession).filter(models.ChatSession.id == session_id, models.ChatSession.user_id == user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).order_by(models.ChatMessage.created_at).all()

@router.post("/chat", response_model=schemas.MessageResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # Handle Session
    session_id = request.session_id
    if not session_id:
        session_id = str(uuid.uuid4())
        # Create new session with title from first message
        first_msg_content = request.messages[-1].content
        title = (first_msg_content[:30] + '...') if len(first_msg_content) > 30 else first_msg_content
        new_session = models.ChatSession(id=session_id, title=title, user_id=user.id)
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
    else:
        # Verify session exists and belongs to user
        session = db.query(models.ChatSession).filter(models.ChatSession.id == session_id, models.ChatSession.user_id == user.id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        # Update timestamp
        session.updated_at = func.now() # This might need explicit datetime if func.now() doesn't trigger on python side update, but let's rely on DB or explicit set
        # Actually sqlalchemy defaults might not update on python object modification unless configured. 
        # Let's just touch it if needed, or rely on the fact we are adding messages.
    
    last_message = request.messages[-1]

    # Save user message
    user_message = models.ChatMessage(
        role=last_message.role,
        content=last_message.content,
        session_id=session_id,
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # Parse the user query for location, units, project_type
    parsed = parse_query(last_message.content)
    location = parsed.get("location")
    units = parsed.get("units")
    project_type = parsed.get("project_type") or "residential"

    if not location or not units:
        # Not enough info to run feasibility analysis — ask the user to clarify
        ai_response_content = (
            "Jag behöver lite mer information för att kunna göra en genomförbarhetsanalys.\n\n"
            "Vänligen ange:\n"
            "• **Plats** — t.ex. Södermalm, Vasastan, Kungsholmen\n"
            "• **Antal enheter** — t.ex. 20 lägenheter\n\n"
            "Exempel: \"Kan jag bygga 20 lägenheter i Södermalm?\""
        )
    else:
        # Run full multi-agent feasibility analysis
        try:
            law_agent = LawAgent(db, client)
            document_agent = DocumentAgent(db, client)
            orchestrator = Orchestrator(law_agent, document_agent)
            result = orchestrator.analyze(location, project_type, units)
            ai_response_content = format_response(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # Save AI response
    ai_message = models.ChatMessage(
        role="assistant", 
        content=ai_response_content,
        session_id=session_id
    )
    db.add(ai_message)
    db.commit()
    db.refresh(ai_message)

    return ai_message

@router.get("/history", response_model=list[schemas.MessageResponse])
def get_history(db: Session = Depends(get_db)):
    return db.query(models.ChatMessage).order_by(models.ChatMessage.created_at).all()