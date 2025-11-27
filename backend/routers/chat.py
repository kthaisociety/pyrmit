from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
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

    # Save user message (assuming the last one is the new one)
    last_message = request.messages[-1]
    user_message = models.ChatMessage(role=last_message.role, content=last_message.content)
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # Call OpenAI
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
