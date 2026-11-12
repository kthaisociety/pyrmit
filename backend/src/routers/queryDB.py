from sqlalchemy.orm import Session
from sqlalchemy.sql import select

from models import DocumentChunk, LawChunk


def _retrieve(db: Session, model_class, query_embedding: list[float], k: int) -> list[str]:
    stmt = (
        select(model_class.content)
        .where(model_class.embedding.is_not(None))
        .order_by(model_class.embedding.cosine_distance(query_embedding))
        .limit(k)
    )
    return [row[0] for row in db.execute(stmt).fetchall()]


def RAG(db: Session, query_embedding: list[float], k: int = 10) -> list[str]:
    """Retrieve top-k most similar document chunks (detaljplan) by cosine distance."""
    return _retrieve(db, DocumentChunk, query_embedding, k)


def RAG_law(db: Session, query_embedding: list[float], k: int = 10) -> list[str]:
    """Retrieve top-k most similar law chunks by cosine distance."""
    return _retrieve(db, LawChunk, query_embedding, k)
