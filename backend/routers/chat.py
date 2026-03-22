import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
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
from agents.base import OPENAI_CHAT_MODEL

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
        session.updated_at = func.now()
    
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

    # Translate user message to English before processing
    original_content = last_message.content
    try:
        translation_response = client.chat.completions.create(
            model=OPENAI_CHAT_MODEL,
            messages=[
                {"role": "user", "content": f"Translate to English if not already in English (return only the translation, no explanation): {original_content}"}
            ],
            temperature=0,
        )
        translated_content = translation_response.choices[0].message.content.strip()
    except Exception:
        logger.warning("Translation failed, using original content", exc_info=True)
        translated_content = original_content

    # Parse the (translated) user query for location, units, project_type
    parsed = parse_query(translated_content)
    location = parsed.get("location")
    units = parsed.get("units")
    project_type = parsed.get("project_type") or "residential"

    if not location or not units:
        logger.info("Missing location or units — falling back to general RAG")
        # General RAG fallback: answer using retrieved law + document chunks
        try:
            law_agent = LawAgent(db, client)
            document_agent = DocumentAgent(db, client)
            law_chunks = law_agent._retrieve(translated_content, k=5)
            doc_chunks = document_agent._retrieve(translated_content, k=5)
            all_chunks = law_chunks + doc_chunks
            if all_chunks:
                context = "\n\n".join(
                    f"Source {i + 1}:\n{chunk}" for i, chunk in enumerate(all_chunks)
                )
                rag_response = client.chat.completions.create(
                    model=OPENAI_CHAT_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a Swedish land law and urban planning expert. "
                                "Answer in English based on the provided Swedish legal sources. "
                                "When quoting Swedish source text directly, use this format:\n"
                                "> **English:** [your English interpretation]\n"
                                "> **Original (Swedish):** [exact Swedish text]\n"
                                "Use markdown formatting for clarity."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Based on these sources:\n\n{context}\n\nAnswer this question: {translated_content}",
                        },
                    ],
                    temperature=0,
                )
                ai_response_content = rag_response.choices[0].message.content
            else:
                ai_response_content = (
                    "I need a bit more information to run a full feasibility analysis.\n\n"
                    "Please provide:\n"
                    "- **Location** — e.g. Södermalm, Vasastan, Kungsholmen\n"
                    "- **Number of units** — e.g. 20 apartments\n\n"
                    "Example: \"Can I build 20 apartments in Södermalm?\""
                )
        except Exception as e:
            logger.error("General RAG failed", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    else:
        logger.info("Running multi-agent analysis: location=%s units=%s type=%s", location, units, project_type)
        # Run full multi-agent feasibility analysis
        try:
            law_agent = LawAgent(db, client)
            document_agent = DocumentAgent(db, client)
            orchestrator = Orchestrator(law_agent, document_agent)
            result = orchestrator.analyze(location, project_type, units)
            ai_response_content = format_response(result)
        except Exception as e:
            logger.error("Multi-agent analysis failed", exc_info=True)
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