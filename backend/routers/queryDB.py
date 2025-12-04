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
from sqlalchemy import text
from dependencies import get_current_user

def RAG(db: Session, completion: list[float], k: int = 10):
    """Retrieve top k most similar document chunks using PostgreSQL cosine similarity."""
    
    embedding_str = "[" + ",".join(map(str, completion)) + "]"
    
    # Use PostgreSQL's <=> operator for cosine distance (1 - cosine_similarity)
    query = text("""
        SELECT content
        FROM document_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :k
    """)
    
    result = db.execute(query, {"embedding": embedding_str, "k": k})
    return [row[0] for row in result.fetchall()]