from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
import models
import schemas
import os
from openai import OpenAI

router = APIRouter()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/chat", response_model=schemas.MessageResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db)):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    last_message = request.messages[-1]

    # --- STEP 1: Generate Embedding (New Addition) ---
    # We put this in a try/except block so chat keeps working even if embedding fails
    embedding_vector = None
    try:
        response = client.embeddings.create(
            input=last_message.content,
            model="text-embedding-3-small"
        )
        embedding_vector = response.data[0].embedding
        # For now, we print it to logs to verify it works without crashing the DB
        print(f"✅ Embedding generated successfully. Dimensions: {len(embedding_vector)}")
    except Exception as e:
        print(f"⚠️ Embedding failed: {e}")
    # ------------------------------------------------

    # Save user message
    # Note: We are NOT passing embedding_vector here yet to avoid DB errors
    user_message = models.ChatMessage(role=last_message.role, content=last_message.content)
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # Call OpenAI Chat
    try:
        # Prepare messages for OpenAI
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        # Add system prompt if not present
        if not any(m["role"] == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": "You are a helpful building permit assistant."})

        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        ai_response_content = completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Save AI response
    ai_message = models.ChatMessage(role="assistant", content=ai_response_content)
    db.add(ai_message)
    db.commit()
    db.refresh(ai_message)

    return ai_message

@router.get("/history", response_model=list[schemas.MessageResponse])
def get_history(db: Session = Depends(get_db)):
    return db.query(models.ChatMessage).order_by(models.ChatMessage.created_at).all()