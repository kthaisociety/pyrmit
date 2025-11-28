from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
import models
import schemas
import os
import yaml
from pathlib import Path
from openai import OpenAI

router = APIRouter()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/chat", response_model=schemas.MessageResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db)):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

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
    user_message = models.ChatMessage(role=last_message.role, content=last_message.content)
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # Call OpenAI Chat
    try:
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
    ai_message = models.ChatMessage(role="assistant", content=ai_response_content)
    db.add(ai_message)
    db.commit()
    db.refresh(ai_message)

    return ai_message

@router.get("/history", response_model=list[schemas.MessageResponse])
def get_history(db: Session = Depends(get_db)):
    return db.query(models.ChatMessage).order_by(models.ChatMessage.created_at).all()