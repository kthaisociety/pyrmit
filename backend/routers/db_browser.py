"""
Read-only browser over the RAG chunk tables (law_chunks, document_chunks).
User/auth tables are intentionally not exposed.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from agents.document_agent import DocumentAgent
from agents.law_agent import LawAgent
from db.database import get_db
from dependencies import get_current_user
import models
from observability import get_openai_client
import schemas

router = APIRouter()

_TABLES = {
    "law": (models.LawChunk, models.LawChunk.law_name),
    "document": (models.DocumentChunk, models.DocumentChunk.document_name),
}


def _table_overview(db: Session, model, source_col) -> schemas.ChunkTableOverview:
    total = db.query(func.count(model.id)).scalar() or 0
    with_embedding = db.query(func.count(model.id)).filter(model.embedding.is_not(None)).scalar() or 0
    sources = (
        db.query(source_col, func.count(model.id))
        .group_by(source_col)
        .order_by(source_col)
        .all()
    )
    return schemas.ChunkTableOverview(
        total=total,
        with_embedding=with_embedding,
        sources=[schemas.SourceCount(name=name or "unknown", count=count) for name, count in sources],
    )


@router.get("/db/overview", response_model=schemas.DbOverview)
def overview(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return schemas.DbOverview(
        law=_table_overview(db, *_TABLES["law"]),
        document=_table_overview(db, *_TABLES["document"]),
    )


@router.get("/db/chunks", response_model=schemas.ChunkPage)
def list_chunks(
    table: schemas.ChunkTableName,
    source: str | None = None,
    q: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    model, source_col = _TABLES[table]
    # Select explicit columns so the 3072-dim embeddings are never loaded
    columns = [
        model.id,
        source_col.label("source"),
        model.chunk_index,
        model.content,
        model.embedding.is_not(None).label("has_embedding"),
        model.created_at,
    ]
    if table == "law":
        columns += [model.chapter, model.chapter_title, model.section]

    query = db.query(*columns)
    if source:
        query = query.filter(source_col == source)
    if q:
        query = query.filter(model.content.ilike(f"%{q}%"))

    total = query.order_by(None).count()
    rows = query.order_by(source_col, model.chunk_index).offset(offset).limit(limit).all()

    items = [
        schemas.ChunkRow(
            id=row.id,
            source=row.source or "unknown",
            chunk_index=row.chunk_index,
            chapter=getattr(row, "chapter", None),
            chapter_title=getattr(row, "chapter_title", None),
            section=getattr(row, "section", None),
            content=row.content or "",
            has_embedding=bool(row.has_embedding),
            created_at=row.created_at,
        )
        for row in rows
    ]
    return schemas.ChunkPage(total=total, offset=offset, limit=limit, items=items)


@router.post("/db/search", response_model=schemas.ChunkSearchResponse)
def semantic_search(
    request: schemas.ChunkSearchRequest,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Run the same embedding + cosine retrieval the chat uses, without calling the LLM."""
    client = get_openai_client()
    law_agent = LawAgent(db, client)
    document_agent = DocumentAgent(db, client)
    embedding = law_agent._embed(request.query)

    def to_matches(rows):
        return [
            schemas.ChunkSearchMatch(
                source=row["source"],
                chunk_index=row["chunk_index"],
                distance=row["distance"],
                content=row["content"] or "",
            )
            for row in rows
        ]

    return schemas.ChunkSearchResponse(
        embedding_ok=embedding is not None,
        law=to_matches(law_agent._retrieve_debug_rows_from_embedding(embedding, k=request.k)),
        document=to_matches(document_agent._retrieve_debug_rows_from_embedding(embedding, k=request.k)),
    )
