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

@router.post("/chat", response_model=schemas.MessageResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # --- 0. Session & History Management ---
    last_msg_content = request.messages[-1].content
    session_id = request.session_id
    
    if not session_id:
        session_id = str(uuid.uuid4())
        title = (last_msg_content[:30] + '...') if len(last_msg_content) > 30 else last_msg_content
        new_session = models.ChatSession(id=session_id, title=title, user_id=user.id)
        db.add(new_session)
        db.commit()
    
    user_message = models.ChatMessage(role="user", content=last_msg_content, session_id=session_id)
    db.add(user_message)
    db.commit()

    try:
        # =========================================================
        # STEP 1: REFORMULATION (The "Translator")
        # =========================================================
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

        # =========================================================
        # STEP 2: EMBEDDING (Generates the Search Key)
        # =========================================================
        # We keep this running to verify your OpenAI Key allows embeddings
        emb_response = client.embeddings.create(
            input=reformulated_query, 
            model="text-embedding-3-small"
        )
        search_vector = emb_response.data[0].embedding

        # =========================================================
        # STEP 3: [MOCK] RETRIEVAL (The Teammate's Placeholder)
        # =========================================================
        
        # TODO: When teammate merges the vector DB branch, uncomment this block:
        # ------------------------------------------------------------------
        # results = db.scalars(
        #    select(models.Document)
        #    .order_by(models.Document.embedding.l2_distance(search_vector))
        #    .limit(4)
        # ).all()
        # context_text = "\n\n".join([doc.content for doc in results])
        # ------------------------------------------------------------------
        
        # [MOCK DATA] For now, we simulate finding a relevant Swedish law
        print("⚠️ USING MOCK CONTEXT (Database branch not merged yet)")
        context_text = (
            "Här är ett exempel från Jordabalken (JB) 3 kap 1 §:\n"
            "'Var och en skall vid nyttjande av sin eller annans fasta egendom "
            "taga skälig hänsyn till omgivningen.'"
        )

        # =========================================================
        # STEP 4: FINAL GENERATION (The "Advisor")
        # =========================================================
        
        final_system_prompt = (
            "Du är en hjälpsam svensk jurist. "
            "Svara på användarens fråga enbart baserat på nedanstående Lagtext (Context). "
            "Om svaret inte finns i texten, säg att du inte vet."
        )

        final_messages = [
            {"role": "system", "content": final_system_prompt},
            # We inject the MOCK context here
            {"role": "user", "content": f"Lagtext (Context):\n{context_text}\n\nAnvändarens Fråga:\n{last_msg_content}"}
        ]

        final_completion = client.chat.completions.create(
            model="gpt-3.5-turbo", # Use GPT-4 if budget allows
            messages=final_messages,
            temperature=0.5
        )
        final_answer = final_completion.choices[0].message.content

    except Exception as e:
        print(f"Pipeline Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # --- 5. Save & Return Final Answer ---
    ai_message = models.ChatMessage(role="assistant", content=final_answer, session_id=session_id)
    db.add(ai_message)
    db.commit()
    
    return ai_message
