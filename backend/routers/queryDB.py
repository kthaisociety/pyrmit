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
from sqlalchemy.sql import func, select
from sqlalchemy import text
from dependencies import get_current_user
from Models import DocumentChunk

def RAG(db: Session, query_embedding: list[float], k: int = 10):
    """
    Retrieve top k most similar document chunks using the SQLAlchemy ORM.

    :param db: The SQLAlchemy session.
    :param query_embedding: The input list[float] (the embedding).
    :param k: The number of results to return (LIMIT).
    """
    

    # 1. Build the select statement
    # The .cosine_distance() method translates directly to the <=> operator in SQL.
    # We ORDER BY the distance ascending (ASC) because smaller distance means greater similarity.
    stmt = select(DocumentChunk.content).where(
        DocumentChunk.embedding.is_not(None)
    ).order_by(
        DocumentChunk.embedding.cosine_distance(query_embedding)
    ).limit(k)

    # 2. Execute the query
    result = db.execute(stmt)

    # 3. Fetch the content
    return [row[0] for row in result.fetchall()]
