"""
Read-only browser over the RAG chunks: the pgvector tables (law_chunks, document_chunks) or,
with store=local, the offline corpus used by RETRIEVAL_BACKEND=local (loaded by localrag.service).
User/auth tables are intentionally not exposed.
"""

from collections import Counter

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


def _local_store():
    """The disk store (SQLite) when the local backend serves from it, else None (in-memory chunks)."""
    from localrag.service import get_retriever

    return getattr(get_retriever(), "store", None)


def _local_chunks() -> list[dict]:
    from localrag.service import get_retriever

    return get_retriever().chunks


def _local_source(chunk: dict) -> str:
    return chunk["title"] if chunk["kind"] == "law" else (chunk.get("kommun") or "unknown")


def _overview_table(counts: dict[str, int]) -> schemas.ChunkTableOverview:
    total = sum(counts.values())
    return schemas.ChunkTableOverview(
        total=total,
        with_embedding=total,  # the local service only serves indexed chunks
        sources=[schemas.SourceCount(name=name, count=count) for name, count in sorted(counts.items())],
    )


def _local_overview() -> schemas.DbOverview:
    store = _local_store()
    if store is not None:
        law = {r[0]: r[1] for r in store.query("SELECT title, COUNT(*) FROM chunks WHERE kind = 'law' GROUP BY title")}
        local = {r[0] or "unknown": r[1] for r in store.query(
            "SELECT kommun, COUNT(*) FROM chunks WHERE kind != 'law' GROUP BY kommun")}
        return schemas.DbOverview(law=_overview_table(law), document=_overview_table(local))
    tables = {"law": Counter(), "document": Counter()}
    for chunk in _local_chunks():
        tables["law" if chunk["kind"] == "law" else "document"][_local_source(chunk)] += 1
    return schemas.DbOverview(law=_overview_table(tables["law"]), document=_overview_table(tables["document"]))


def _row_from_chunk(chunk: dict) -> schemas.ChunkRow:
    return schemas.ChunkRow(
        id=chunk["chunk_id"],
        source=_local_source(chunk),
        chunk_index=chunk.get("chunk_index"),
        chapter=chunk.get("chapter"),
        chapter_title=None,
        section=chunk.get("section"),
        content=f"{chunk['header']}\n\n{chunk['text']}",
        has_embedding=True,
    )


def _local_page(table: str, source: str | None, q: str | None, offset: int, limit: int) -> schemas.ChunkPage:
    store = _local_store()
    if store is not None:
        where = ["kind = 'law'" if table == "law" else "kind != 'law'"]
        params: list = []
        if source:
            where.append("title = ?" if table == "law" else "kommun = ?")
            params.append(source)
        if q:
            where.append("(text LIKE ? OR header LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        condition = " AND ".join(where)
        total = store.query(f"SELECT COUNT(*) FROM chunks WHERE {condition}", tuple(params))[0][0]
        rows = store.query(f"SELECT * FROM chunks WHERE {condition} ORDER BY title, CAST(chunk_index AS INTEGER) "
                           f"LIMIT ? OFFSET ?", (*params, limit, offset))
        items = [_row_from_chunk(store._chunk(row)) for row in rows]
        return schemas.ChunkPage(total=total, offset=offset, limit=limit, items=items)
    needle = q.lower() if q else None
    rows = [
        chunk for chunk in _local_chunks()
        if (chunk["kind"] == "law") == (table == "law")
        and (not source or _local_source(chunk) == source)
        and (not needle or needle in chunk["text"].lower() or needle in chunk["header"].lower())
    ]
    items = [_row_from_chunk(chunk) for chunk in rows[offset:offset + limit]]
    return schemas.ChunkPage(total=len(rows), offset=offset, limit=limit, items=items)


@router.get("/db/overview", response_model=schemas.DbOverview)
def overview(
    store: schemas.ChunkStore = "neon",
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    if store == "local":
        return _local_overview()
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
    store: schemas.ChunkStore = "neon",
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    if store == "local":
        return _local_page(table, source, q, offset, limit)
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
    """Run the same retrieval the chat uses, without calling the LLM."""
    if request.store == "local":
        from localrag.service import retrieve

        # No LLM rewrite here: the typed query is used as is (Swedish works best)
        law, local, kommuner = retrieve(request.query, request.query, k=request.k)

        def to_local_matches(rows):
            return [
                schemas.ChunkSearchMatch(source=row["source"], chunk_index=row["chunk_index"], distance=None,
                                         content=row["content"])
                for row in rows
            ]

        return schemas.ChunkSearchResponse(embedding_ok=True, kommuner=kommuner, law=to_local_matches(law),
                                           document=to_local_matches(local))
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
