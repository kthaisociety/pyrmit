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
        
        # --- KEY CHANGE: Deep Swedish Land Law Prompt ---
        land_law_prompt = (
            "Du är en juristexpert specialiserad på svensk fastighetsrätt (Swedish Land Law). "
            "Din uppgift är att översätta användarens frågor till strikt juridisk terminologi för databassökning. "
            "Du ska prioritera begrepp från:"
            "\n1. Jordabalken (JB) - För köp, hyra, arrende och grannelagsrätt."
            "\n2. Plan- och bygglagen (PBL) - För bygglov och detaljplaner."
            "\n3. Lantmäteriförrättningar - För gränsdragning och fastighetsindelning."
            "\n\n"
            "Regler:"
            "- Svara INTE på frågan."
            "- Returnera endast en lista med juridiska termer och lagrum."
            "\n\n"
            "Exempel 1:"
            "\nIn: 'Vi bråkar om var tomtgränsen går.'"
            "\nUt: 'Fastighetsbestämning; Gränsutvisning; Jordabalken 1 kap 3 §; Lantmäteriförrättning; Rättelse av gräns.'"
            "\n\n"
            "Exempel 2:"
            "\nIn: 'Jag får använda grannens väg för att komma till min stuga.'"
            "\nUt: 'Officialservitut; Avtalsservitut; Härskande och tjänande fastighet; Jordabalken 14 kap; Vägförrättning.'"
            "\n\n"
            "Exempel 3:"
            "\nIn: 'Huset jag köpte har mögel i grunden som säljaren inte sa något om.'"
            "\nUt: 'Dolda fel i fastighet; Undersökningsplikt; Prisavdrag; Hävning av köp; Jordabalken 4 kap 19 §.'"
        )

        if not any(m["role"] == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": land_law_prompt})
        else:
            messages[0]["content"] = land_law_prompt

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