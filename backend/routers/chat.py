import json
import logging
import os
import uuid
from typing import Generator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from agents.base import OPENAI_CHAT_MODEL
from agents.document_agent import DocumentAgent
from agents.law_agent import LawAgent
from agents.orchestrator import Orchestrator
from agents.parsers import format_response, parse_query
from db.database import get_db
from dependencies import get_current_user
from llm import (
    build_responses_input,
    get_response_output_text,
    resolve_model_name,
)
import models
from observability import create_chat_completion, get_openai_client, propagate_trace_attributes, start_observation
import schemas

logger = logging.getLogger(__name__)

router = APIRouter()


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


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _response_input_with_user_prompt(
        messages: list[schemas.ChatMessage],
        user_prompt: str,
) -> list[dict[str, str]]:
    response_input = build_responses_input(messages[:-1][-5:])
    response_input.append({"role": "user", "content": user_prompt})
    return response_input


@router.get("/sessions", response_model=list[schemas.ChatSession])
def get_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.ChatSession).filter(models.ChatSession.user_id == user.id).order_by(
        models.ChatSession.updated_at.desc()).all()


@router.get("/sessions/{session_id}", response_model=list[schemas.MessageResponse])
def get_session_history(session_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _get_user_session(session_id, user.id, db)
    return db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).order_by(
        models.ChatMessage.created_at).all()


@router.delete("/sessions")
def delete_all_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    session_ids = [s.id for s in db.query(models.ChatSession.id).filter(models.ChatSession.user_id == user.id).all()]
    if session_ids:
        db.query(models.ChatMessage).filter(models.ChatMessage.session_id.in_(session_ids)).delete(
            synchronize_session=False)
        count = db.query(models.ChatSession).filter(models.ChatSession.id.in_(session_ids)).delete(
            synchronize_session=False)
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
def update_session(session_id: str, request: schemas.UpdateSessionRequest, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    session = _get_user_session(session_id, user.id, db)
    session.title = request.title
    db.commit()
    db.refresh(session)
    return session


@router.post("/chat", response_model=schemas.MessageResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    client = get_openai_client()

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
                model=resolve_model_name(OPENAI_CHAT_MODEL),
                input=context_prompt,
                temperature=0,
                name="chat.query_translation",
            )
            translated_content = get_response_output_text(translation_response).strip() or original_content
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

                law_results = law_agent._retrieve_with_meta_from_embedding(embedding, k=5)
                doc_results = document_agent._retrieve_with_meta_from_embedding(embedding, k=5)
                all_chunks = [c for c, _ in law_results] + [c for c, _ in doc_results]
                sources = list(dict.fromkeys(
                    [label for _, label in law_results] + [label for _, label in doc_results]
                ))

                with start_observation(
                        "chat.general_rag_retrieval",
                        metadata={
                            "query": translated_content,
                            "law_matches": [{key: value for key, value in row.items() if key != "content"} for row in
                                            law_debug_rows],
                            "document_matches": [{key: value for key, value in row.items() if key != "content"} for row
                                                 in doc_debug_rows],
                        },
                ):
                    pass

                if all_chunks:
                    context = "\n\n".join(
                        f"Source {i + 1}:\n{chunk}" for i, chunk in enumerate(all_chunks)
                    )

                    rag_response = create_chat_completion(
                        client,
                        model=resolve_model_name(OPENAI_CHAT_MODEL),
                        instructions=(
                            "You are a Swedish land law and urban planning expert. "
                            "Answer in English based on the provided Swedish legal sources. "
                            "When quoting Swedish source text directly, use this format:\n"
                            "> **English:** [your English interpretation]\n"
                            "> **Original (Swedish):** [exact Swedish text]\n"
                            "Use markdown formatting for clarity."
                        ),
                        input=_response_input_with_user_prompt(
                            request.messages,
                            f"Based on these sources:\n\n{context}\n\nAnswer this question: {translated_content}",
                        ),
                        temperature=0,
                        name="chat.general_rag_answer",
                    )
                    ai_response_content = get_response_output_text(rag_response) + _format_sources(sources)
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


@router.post("/chat/stream")
def chat_stream(
        request: schemas.ChatRequest,
        db: Session = Depends(get_db),
        user: models.User = Depends(get_current_user),
):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # All setup done eagerly so HTTPException can still be raised before streaming
    client = get_openai_client()

    session_id = request.session_id
    is_new_session = not session_id
    if is_new_session:
        session_id = str(uuid.uuid4())
        first_msg_content = request.messages[-1].content
        title = (first_msg_content[:30] + "...") if len(first_msg_content) > 30 else first_msg_content
        new_session = models.ChatSession(id=session_id, title=title, user_id=user.id)
        db.add(new_session)
        db.commit()
    else:
        session = _get_user_session(session_id, user.id, db)
        session.updated_at = func.now()
        db.commit()

    last_message = request.messages[-1]
    user_message = models.ChatMessage(role=last_message.role, content=last_message.content, session_id=session_id)
    db.add(user_message)
    db.commit()

    # Capture for use inside generator
    messages_snapshot = list(request.messages)
    original_content = last_message.content

    def generate() -> Generator[str, None, None]:
        with start_observation(
                "chat.stream",
                input={"last_message": original_content},
                metadata={"stream": True}
        ) as stream_obs, propagate_trace_attributes(
            user_id=user.id,
            session_id=session_id,
        ):
            accumulated = ""
            yield ": connected\n\n"

            if is_new_session:
                yield _sse({"type": "session_id", "session_id": session_id})

            try:
                # ── Step 1: translate / contextualize ──────────────────────────
                yield _sse({"type": "thinking", "label": "Understanding your question"})

                if len(messages_snapshot) > 1:
                    history_msgs = messages_snapshot[:-1][-5:]
                    history_str = "\n".join(f"{m.role}: {m.content}" for m in history_msgs)
                    context_prompt = (
                        "Given the following conversation history and the latest user message, "
                        "rewrite the latest user message into a standalone query in English. "
                        "Ensure any location, number of units, or project type implicitly mentioned "
                        "in the history is explicitly included in the standalone query. "
                        "If the latest message is a completely new topic or just greetings, simply translate it. "
                        "Return ONLY the standalone English query, no prefix or explanation.\n\n"
                        f"Conversation History:\n{history_str}\n\n"
                        f"Latest User Message: {original_content}"
                    )
                else:
                    context_prompt = (
                        f"Translate the following user message to English "
                        f"(return only the translation, no explanation): {original_content}"
                    )

                try:
                    tr = create_chat_completion(
                        client,
                        model=resolve_model_name(OPENAI_CHAT_MODEL),
                        input=context_prompt,
                        temperature=0,
                        name="chat.stream.translation"
                    )
                    translated = get_response_output_text(tr).strip() or original_content
                except Exception:
                    logger.warning("Translation failed, using original", exc_info=True)
                    translated = original_content

                # ── Step 2: parse intent ───────────────────────────────────────
                yield _sse({"type": "thinking", "label": "Parsing intent"})
                parsed = parse_query(translated)
                location = parsed.get("location")
                units = parsed.get("units")
                project_type = parsed.get("project_type") or "residential"

                stream_obs.update(metadata={"location": location, "units": units, "translated": translated})

                if not location or not units:
                    # ── General RAG path ───────────────────────────────────────
                    yield _sse({"type": "tool_call", "name": "embed_query", "input": translated})
                    law_agent = LawAgent(db, client)
                    document_agent = DocumentAgent(db, client)
                    embedding = law_agent._embed(translated)
                    yield _sse({"type": "tool_result", "name": "embed_query", "result": "Embedding computed"})

                    yield _sse({"type": "tool_call", "name": "retrieve_law_chunks", "input": f"k=5"})
                    law_debug_rows = law_agent._retrieve_debug_rows_from_embedding(embedding, k=5)
                    doc_debug_rows = document_agent._retrieve_debug_rows_from_embedding(embedding, k=5)

                    law_agent._log_retrieval(translated, law_debug_rows)
                    document_agent._log_retrieval(translated, doc_debug_rows)

                    law_results = law_agent._retrieve_with_meta_from_embedding(embedding, k=5)
                    yield _sse(
                        {"type": "tool_result", "name": "retrieve_law_chunks", "result": f"{len(law_results)} chunks"})

                    yield _sse({"type": "tool_call", "name": "retrieve_document_chunks", "input": f"k=5"})
                    doc_results = document_agent._retrieve_with_meta_from_embedding(embedding, k=5)
                    yield _sse({"type": "tool_result", "name": "retrieve_document_chunks",
                                "result": f"{len(doc_results)} chunks"})

                    all_chunks = [c for c, _ in law_results] + [c for c, _ in doc_results]
                    sources = list(dict.fromkeys(
                        [label for _, label in law_results] + [label for _, label in doc_results]
                    ))

                    if not all_chunks:
                        fallback = (
                            "I need a bit more information to run a full feasibility analysis.\n\n"
                            "Please provide:\n"
                            "- **Location** — e.g. Södermalm, Vasastan, Kungsholmen\n"
                            "- **Number of units** — e.g. 20 apartments\n\n"
                            'Example: "Can I build 20 apartments in Södermalm?"'
                        )
                        accumulated = fallback
                        yield _sse({"type": "response.output_text.delta", "delta": fallback})
                    else:
                        context = "\n\n".join(f"Source {i + 1}:\n{c}" for i, c in enumerate(all_chunks))
                        yield _sse({"type": "thinking", "label": "Composing answer"})
                        stream = create_chat_completion(
                            client,
                            model=resolve_model_name(OPENAI_CHAT_MODEL),
                            instructions=(
                                "You are a Swedish land law and urban planning expert. "
                                "Answer in English based on the provided Swedish legal sources. "
                                "When quoting Swedish source text directly, use this format:\n"
                                "> **English:** [your English interpretation]\n"
                                "> **Original (Swedish):** [exact Swedish text]\n"
                                "Use markdown formatting for clarity."
                            ),
                            input=_response_input_with_user_prompt(
                                messages_snapshot,
                                f"Based on these sources:\n\n{context}\n\nAnswer this question: {translated}",
                            ),
                            temperature=0,
                            stream=True,
                            name="chat.stream.rag_answer"
                        )
                        for event in stream:
                            if event.type == "response.output_text.delta" and event.delta:
                                accumulated += event.delta
                                yield _sse({"type": event.type, "delta": event.delta})
                            elif event.type == "response.failed":
                                raise RuntimeError("Model response failed")
                            elif event.type == "error":
                                raise RuntimeError(event.message)

                        suffix = _format_sources(sources)
                        if suffix:
                            accumulated += suffix
                            yield _sse({"type": "response.output_text.delta", "delta": suffix})

                else:
                    # ── Multi-agent feasibility path ───────────────────────────
                    yield _sse({"type": "tool_call", "name": "law_agent",
                                "input": f"location={location}, units={units}, type={project_type}"})
                    law_agent = LawAgent(db, client)
                    document_agent = DocumentAgent(db, client)
                    orchestrator = Orchestrator(law_agent, document_agent)

                    yield _sse({"type": "tool_call", "name": "document_agent", "input": f"location={location}"})
                    result = orchestrator.analyze(location, project_type, units)
                    yield _sse({"type": "tool_result", "name": "law_agent",
                                "result": f"confidence={result.get('confidence', '?')}%"})
                    yield _sse({"type": "tool_result", "name": "document_agent",
                                "result": result.get("feasibility", "unknown")})

                    yield _sse({"type": "thinking", "label": "Formatting analysis"})
                    full_text = format_response(result) + _format_sources(result.get("sources", []))

                    # Emit word-by-word so the frontend renders progressively
                    words = full_text.split(" ")
                    for i, word in enumerate(words):
                        token = word if i == len(words) - 1 else word + " "
                        accumulated += token
                        yield _sse({"type": "response.output_text.delta", "delta": token})

            except Exception as e:
                logger.error("Stream generation failed", exc_info=True)
                yield _sse({"type": "error", "message": str(e)})
                return

            # Persist assistant message
            ai_message = models.ChatMessage(role="assistant", content=accumulated, session_id=session_id)
            db.add(ai_message)
            db.commit()

            stream_obs.update(output={"length": len(accumulated)})
            yield _sse({"type": "response.completed"})
            yield _sse({"type": "done", "session_id": session_id})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )


@router.get("/history", response_model=list[schemas.MessageResponse])
def get_history(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return (
        db.query(models.ChatMessage)
        .join(models.ChatSession, models.ChatSession.id == models.ChatMessage.session_id)
        .filter(models.ChatSession.user_id == _user.id)
        .order_by(models.ChatMessage.created_at)
        .all()
    )
