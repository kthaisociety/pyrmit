import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from agents.base import OPENAI_CHAT_MODEL
from agents.document_agent import DocumentAgent
from agents.law_agent import LawAgent
from agents.orchestrator import Orchestrator
from agents.parsers import format_response, parse_query
from db.database import get_db
from dependencies import get_current_user
import models
from observability import create_chat_completion, get_openai_client, propagate_trace_attributes, start_observation
import schemas

logger = logging.getLogger(__name__)

router = APIRouter()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _get_user_session(session_id: str, user_id: str, db: Session) -> models.ChatSession:
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id,
        models.ChatSession.user_id == user_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _format_sources(sources: list[str]) -> str:
    if not sources:
        return ""
    items = "\n".join(f"- {s}" for s in sources)
    return f"\n\n---\n**Sources**\n{items}"

@router.get("/sessions", response_model=list[schemas.ChatSession])
def get_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.ChatSession).filter(models.ChatSession.user_id == user.id).order_by(models.ChatSession.updated_at.desc()).all()

@router.get("/sessions/{session_id}", response_model=list[schemas.MessageResponse])
def get_session_history(session_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _get_user_session(session_id, user.id, db)
    return db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).order_by(models.ChatMessage.created_at).all()

@router.delete("/sessions")
def delete_all_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session_ids = [s.id for s in db.query(models.ChatSession.id).filter(models.ChatSession.user_id == user.id).all()]
    if session_ids:
        db.query(models.ChatMessage).filter(models.ChatMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
        count = db.query(models.ChatSession).filter(models.ChatSession.id.in_(session_ids)).delete(synchronize_session=False)
        db.commit()
    else:
        count = 0
    return {"status": "deleted", "count": count}

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session = _get_user_session(session_id, user.id, db)
    db.delete(session)
    db.commit()
    return {"status": "deleted"}

@router.patch("/sessions/{session_id}", response_model=schemas.ChatSession)
def update_session(session_id: str, request: schemas.UpdateSessionRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session = _get_user_session(session_id, user.id, db)
    session.title = request.title
    db.commit()
    db.refresh(session)
    return session

@router.post("/chat", response_model=schemas.MessageResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # Handle Session
    session_id = request.session_id or str(uuid.uuid4())

    with start_observation(
        "chat.request",
        input={
            "message_count": len(request.messages),
            "last_message": request.messages[-1].content,
        },
        metadata={"route": "/api/chat"},
    ) as chat_obs, propagate_trace_attributes(
        user_id=user.id,
        session_id=session_id,
        metadata={"route": "chat"},
    ):
        if not request.session_id:
            # Create new session with title from first message
            first_msg_content = request.messages[-1].content
            title = (first_msg_content[:30] + '...') if len(first_msg_content) > 30 else first_msg_content
            new_session = models.ChatSession(id=session_id, title=title, user_id=user.id)
            db.add(new_session)
            db.commit()
            db.refresh(new_session)
        else:
            session = _get_user_session(session_id, user.id, db)
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

        # Translate and contextualize user message based on chat history
        original_content = last_message.content

        if len(request.messages) > 1:
            # Build chat history for context (last 5 messages, excluding the current one)
            history_msgs = request.messages[:-1][-5:]
            history_str = "\n".join([f"{msg.role}: {msg.content}" for msg in history_msgs])

            context_prompt = f"""
Given the following conversation history and the latest user message, rewrite the latest user message into a standalone query in English. 
Ensure any location, number of units, or project type implicitly mentioned in the history is explicitly included in the standalone query.
If the latest message is a completely new topic or just greetings, simply translate it to English.
Return ONLY the standalone English query, without any prefix or explanation.

Conversation History:
{history_str}

Latest User Message: {original_content}"""
        else:
            context_prompt = f"Translate the following user message to English (return only the translation, no explanation): {original_content}"

        try:
            translation_response = create_chat_completion(
                client,
                model=OPENAI_CHAT_MODEL,
                messages=[
                    {"role": "user", "content": context_prompt}
                ],
                temperature=0,
                name="chat.query_translation",
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

        chat_obs.update(
            metadata={
                "translated_content": translated_content,
                "parsed_location": location,
                "parsed_units": units,
                "parsed_project_type": project_type,
            }
        )

        if not location or not units:
            logger.info("Missing location or units — falling back to general RAG")
            # General RAG fallback: answer using retrieved law + document chunks
            try:
                law_agent = LawAgent(db, client)
                document_agent = DocumentAgent(db, client)
                embedding = law_agent._embed(translated_content)
                law_debug_rows = law_agent._retrieve_debug_rows_from_embedding(embedding, k=5)
                doc_debug_rows = document_agent._retrieve_debug_rows_from_embedding(embedding, k=5)
                law_agent._log_retrieval(translated_content, law_debug_rows)
                document_agent._log_retrieval(translated_content, doc_debug_rows)
                law_results = [(row["content"], row["source"]) for row in law_debug_rows]
                doc_results = [(row["content"], row["source"]) for row in doc_debug_rows]
                all_chunks = [c for c, _ in law_results] + [c for c, _ in doc_results]
                sources = list(dict.fromkeys(
                    [label for _, label in law_results] + [label for _, label in doc_results]
                ))
                with start_observation(
                    "chat.general_rag_retrieval",
                    metadata={
                        "query": translated_content,
                        "law_matches": [{key: value for key, value in row.items() if key != "content"} for row in law_debug_rows],
                        "document_matches": [{key: value for key, value in row.items() if key != "content"} for row in doc_debug_rows],
                    },
                ):
                    pass
                if all_chunks:
                    context = "\n\n".join(
                        f"Source {i + 1}:\n{chunk}" for i, chunk in enumerate(all_chunks)
                    )

                    # Build context-aware messages array for the final chat completion
                    completion_messages = [
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
                        }
                    ]

                    # Add up to 5 previous messages to give LLM conversation flow
                    if len(request.messages) > 1:
                        for msg in request.messages[:-1][-5:]:
                            completion_messages.append({
                                "role": msg.role,
                                "content": msg.content
                            })

                    # Add the final augmented prompt
                    completion_messages.append({
                        "role": "user",
                        "content": f"Based on these sources:\n\n{context}\n\nAnswer this question: {translated_content}",
                    })

                    rag_response = create_chat_completion(
                        client,
                        model=OPENAI_CHAT_MODEL,
                        messages=completion_messages,
                        temperature=0,
                        name="chat.general_rag_answer",
                    )
                    ai_response_content = rag_response.choices[0].message.content + _format_sources(sources)
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
                ai_response_content = format_response(result) + _format_sources(result.get("sources", []))
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

        chat_obs.update(output={"session_id": session_id})
        return ai_message

@router.get("/history", response_model=list[schemas.MessageResponse])
def get_history(db: Session = Depends(get_db)):
    return db.query(models.ChatMessage).order_by(models.ChatMessage.created_at).all()
