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

    # =========================================================================
    # PART 1: TEAMMATE'S SESSION MANAGEMENT (DO NOT TOUCH)
    # This ensures the frontend stays connected to the correct session ID
    # =========================================================================
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
    
    # Save user message to DB immediately
    last_message = request.messages[-1]
    user_message = models.ChatMessage(
        role=last_message.role, 
        content=last_message.content,
        session_id=session_id
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # =========================================================================
    # PART 2: YOUR RAG PIPELINE (Replaces Teammate's basic logic)
    # =========================================================================
    
    ai_response_content = ""
    
    try:
        # --- STEP 1: REFORMULATION (The "Translator") ---
        prompt_path = Path(__file__).parent.parent / 'prompts' / 'land_law_prompt.yaml'
        with open(prompt_path, 'r', encoding='utf-8') as f:
            translator_system_prompt = yaml.safe_load(f)

        translator_messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        # Insert System Prompt safely
        if isinstance(translator_system_prompt, dict):
             translator_messages.insert(0, translator_system_prompt)
        else:
             translator_messages.insert(0, {"role": "system", "content": str(translator_system_prompt)})

        reformulation_response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=translator_messages,
            temperature=0.2 
        )
        reformulated_query = reformulation_response.choices[0].message.content
        print(f"⚖️ Reformulated Search Query: {reformulated_query}")

        # --- STEP 2: EMBEDDING (Generates the Search Key) ---
        emb_response = client.embeddings.create(
            input=reformulated_query, 
            model="text-embedding-3-small"
        )
        search_vector = emb_response.data[0].embedding

        # --- STEP 3: [MOCK] RETRIEVAL ---
        # TODO: Uncomment DB search when vector branch is merged
        print("⚠️ USING MOCK CONTEXT (Database branch not merged yet)")
        context_text = (
            "Här är ett exempel från Jordabalken (JB) 3 kap 1 §:\n"
            "'Var och en skall vid nyttjande av sin eller annans fasta egendom "
            "taga skälig hänsyn till omgivningen.'"
        )

        # --- STEP 4: FINAL GENERATION (The "Advisor") ---
        final_system_prompt = (
            "Du är en hjälpsam svensk jurist. "
            "Svara på användarens fråga enbart baserat på nedanstående Lagtext (Context). "
            "Om svaret inte finns i texten, säg att du inte vet."
        )

        final_messages = [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": f"Lagtext (Context):\n{context_text}\n\nAnvändarens Fråga:\n{last_message.content}"}
        ]

        final_completion = client.chat.completions.create(
            model="gpt-3.5-turbo", 
            messages=final_messages,
            temperature=0.5
        )
        ai_response_content = final_completion.choices[0].message.content

    except Exception as e:
        print(f"Pipeline Error: {e}")
        # Ideally log this, but return a generic error or re-raise
        raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # PART 3: SAVE AI RESPONSE (Teammate's standard logic)
    # =========================================================================
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