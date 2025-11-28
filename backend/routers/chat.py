from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
import models
import schemas
import os
import uuid
import yaml
from pathlib import Path
from openai import OpenAI
from sqlalchemy.sql import func
from dependencies import get_current_user

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
    
    # Save user message
    last_message = request.messages[-1]

    # --- STEP 1: Generate Embedding ---
    embedding_vector = None
    try:
        response = client.embeddings.create(
            input=last_message.content,
            model="text-embedding-3-small"
        )
        embedding_vector = response.data[0].embedding
        print(f"✅ Embedding generated successfully.")
    except Exception as e:
        print(f"⚠️ Embedding failed: {e}")
    # ------------------------------------------------

    # Save user message
    user_message = models.ChatMessage(
        role=last_message.role, 
        content=last_message.content,
        session_id=session_id
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # Call OpenAI Chat
    try:
        # We should probably fetch the full history for this session from DB to give context
        # instead of relying on what frontend sent, OR trust frontend. 
        # For now, let's trust the frontend sends the context or we fetch it.
        # The previous implementation trusted request.messages. Let's stick to that for now but ideally we load from DB.
        
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        # Load system prompt from YAML
        prompt_path = Path(__file__).parent.parent / 'prompts' / 'land_law_prompt.yaml'
        with open(prompt_path, 'r', encoding='utf-8') as f:
            system_prompt = yaml.safe_load(f)

        if not any(m["role"] == "system" for m in messages):
            messages.insert(0, system_prompt)
        else:
            messages[0] = system_prompt

        completion = client.chat.completions.create(
            model="gpt-3.5-turbo", 
            messages=messages,
            temperature=0.2 # Very low temperature for high precision
        )
        ai_response_content = completion.choices[0].message.content
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