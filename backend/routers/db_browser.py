"""
Read-only browser over the RAG chunks: the pgvector tables (law_chunks, document_chunks) or,
with store=local, the offline corpus used by RETRIEVAL_BACKEND=local (loaded by localrag.service).
User/auth tables are intentionally not exposed.
"""

from collections import Counter, defaultdict

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


# Document types of corpus.extract, in the order the Database view lists them within a kommun
DOC_TYPE_ORDER = ("detaljplan", "oversiktsplan", "bygglov", "strandskydd", "avlopp", "taxa", "other")
_TYPE_RANK = "CASE doc_type " + " ".join(f"WHEN '{t}' THEN {i}" for i, t in enumerate(DOC_TYPE_ORDER)) + " ELSE 99 END"


def _local_source(chunk: dict) -> str:
    """Law chunks: the statute; kommun chunks: the kommun code (the filter key; the name is shown)."""
    return chunk["title"] if chunk["kind"] == "law" else (chunk.get("kommun_code") or "unknown")


def _overview_table(counts: dict[str, int]) -> schemas.ChunkTableOverview:
    total = sum(counts.values())
    return schemas.ChunkTableOverview(
        total=total,
        with_embedding=total,  # the local service only serves indexed chunks
        sources=[schemas.SourceCount(name=name, count=count) for name, count in sorted(counts.items())],
    )


def _kommun_overview(rows: list[dict]) -> schemas.ChunkTableOverview:
    """rows: documents / chunks per (kommun, kind, doc_type) -> one source per kommun with its document types."""
    kommuner: dict[str, dict] = {}
    for row in rows:
        kommun = kommuner.setdefault(row["kommun_code"] or "unknown",
                                     {"name": row["kommun"] or "unknown", "types": defaultdict(Counter)})
        counts = kommun["types"][row["doc_type"] or "other"]
        counts.update(documents=row["documents"], chunks=row["chunks"],
                      **{"pdfs" if row["kind"] == "pdf" else "pages": row["documents"]})
    sources = []
    for code, kommun in kommuner.items():
        types = [schemas.TypeCount(doc_type=t, **c) for t, c in kommun["types"].items()]
        types.sort(key=lambda t: DOC_TYPE_ORDER.index(t.doc_type) if t.doc_type in DOC_TYPE_ORDER else 99)
        sources.append(schemas.SourceCount(name=kommun["name"], key=code, count=sum(t.chunks for t in types),
                                           documents=sum(t.documents for t in types), types=types,
                                           scanned=len(_scanned_doc_ids(code))))
    sources.sort(key=lambda s: s.name)
    total = sum(s.count for s in sources)
    return schemas.ChunkTableOverview(total=total, with_embedding=total, sources=sources)


def _local_overview() -> schemas.DbOverview:
    store = _local_store()
    if store is not None:
        law = {r[0]: r[1] for r in store.query("SELECT title, COUNT(*) FROM chunks WHERE kind = 'law' GROUP BY title")}
        return schemas.DbOverview(law=_overview_table(law), document=_kommun_overview(store.summary()))
    law, local = Counter(), defaultdict(lambda: {"documents": set(), "chunks": 0})
    for chunk in _local_chunks():
        if chunk["kind"] == "law":
            law[chunk["title"]] += 1
            continue
        group = local[(chunk.get("kommun_code"), chunk.get("kommun"), chunk["kind"], chunk.get("doc_type"))]
        group["documents"].add(chunk["doc_id"])
        group["chunks"] += 1
    rows = [{"kommun_code": code, "kommun": name, "kind": kind, "doc_type": doc_type,
             "documents": len(g["documents"]), "chunks": g["chunks"]} for (code, name, kind, doc_type), g in local.items()]
    return schemas.DbOverview(law=_overview_table(law), document=_kommun_overview(rows))


def _row_from_chunk(chunk: dict) -> schemas.ChunkRow:
    law = chunk["kind"] == "law"
    return schemas.ChunkRow(
        id=chunk["chunk_id"],
        source=chunk["title"] if law else (chunk.get("title") or chunk["doc_id"]),
        chunk_index=chunk.get("chunk_index"),
        chapter=chunk.get("chapter"),
        chapter_title=None,
        section=chunk.get("section"),
        content=f"{chunk['header']}\n\n{chunk['text']}",
        has_embedding=True,
        doc_id=chunk["doc_id"],
        kind=chunk["kind"],
        doc_type=None if law else chunk.get("doc_type"),
        kommun=None if law else chunk.get("kommun"),
        url=chunk.get("url"),
    )


def _local_page(table: str, source: str | None, doc_type: str | None, q: str | None, offset: int,
                limit: int, doc_id: str | None = None) -> schemas.ChunkPage:
    store = _local_store()
    if store is not None:
        return _store_page(store, table, source, doc_type, q, offset, limit, doc_id)
    needle = q.lower() if q else None
    rows = [
        chunk for chunk in _local_chunks()
        if (chunk["kind"] == "law") == (table == "law")
        and (not doc_id or chunk["doc_id"] == doc_id)
        and (not source or _local_source(chunk) == source)
        and (not doc_type or chunk.get("doc_type") == doc_type)
        and (not needle or needle in chunk["text"].lower() or needle in chunk["header"].lower())
    ]
    if table == "document":
        rows.sort(key=lambda c: (DOC_TYPE_ORDER.index(c.get("doc_type")) if c.get("doc_type") in DOC_TYPE_ORDER else 99,
                                 c.get("title") or "", c["doc_id"], c.get("chunk_index") or 0))
    items = [_row_from_chunk(chunk) for chunk in rows[offset:offset + limit]]
    return schemas.ChunkPage(total=len(rows), offset=offset, limit=limit, items=items)


def _scanned_doc_ids(code: str) -> set[str]:
    """doc_ids of the kommun's scanned PDFs whose text comes from the OCR: corpus.ocr writes an output for scans only
    (the store has no OCR column)."""
    from corpus.common import WEB_DIR

    folder = WEB_DIR / code / "ocr"
    return {f"pdf:{code}:{path.stem}" for path in folder.glob("*.json")} if folder.is_dir() else set()


def _store_documents(store, source: str, doc_type: str | None, q: str | None, offset: int,
                     limit: int, scanned: bool = False) -> schemas.DocumentPage:
    """A kommun's documents (from its chunks: the store has no document table), by type then title; `scanned`: only
    the scanned PDFs read by the OCR."""
    where, params = ["kind IN ('page', 'pdf')", "kommun_code = ?"], [source]
    scanned_ids = _scanned_doc_ids(source)
    if scanned:
        if not scanned_ids:
            return schemas.DocumentPage(total=0, offset=offset, limit=limit, items=[])
        where.append(f"doc_id IN ({', '.join('?' * len(scanned_ids))})")
        params += sorted(scanned_ids)
    if doc_type:
        where.append("doc_type = ?")
        params.append(doc_type)
    if q:
        where.append("title LIKE ?")
        params.append(f"%{q}%")
    condition = " AND ".join(where)
    total = store.query(f"SELECT COUNT(DISTINCT doc_id) FROM chunks WHERE {condition}", tuple(params))[0][0]
    rows = store.query(f"SELECT doc_id, MIN(title), MIN(kind), MIN(doc_type), MIN(url), COUNT(*) FROM chunks "
                       f"WHERE {condition} GROUP BY doc_id ORDER BY MIN({_TYPE_RANK}), MIN(title), doc_id "
                       f"LIMIT ? OFFSET ?", (*params, limit, offset))
    items = [schemas.DocumentRow(doc_id=doc_id, title=title or doc_id, kind=kind, doc_type=dtype, url=url, chunks=n,
                                 scanned=doc_id in scanned_ids)
             for doc_id, title, kind, dtype, url, n in rows]
    return schemas.DocumentPage(total=total, offset=offset, limit=limit, items=items)


def _store_page(store, table: str, source: str | None, doc_type: str | None, q: str | None, offset: int,
                limit: int, doc_id: str | None = None) -> schemas.ChunkPage:
    """Kommun chunks of the disk store (1.9M rows): filtered on the (kind, kommun_code) index. Sorting or counting
    the whole table takes ~20 s, so without a kommun the rows come in store order and the total from the cached
    summary; a text filter over every kommun is not counted."""
    # kind IN uses the (kind, kommun_code) index (with a kommun); kind != 'law' reads the table in rowid order and
    # stops at the page's last row (without one: through the index, every row was sorted first, 17-26 s)
    where = ["kind = 'law'" if table == "law" else "kind IN ('page', 'pdf')" if source else "kind != 'law'"]
    params: list = []
    if doc_id:  # one document's chunks (chunks_doc index)
        rows = store.query("SELECT * FROM chunks WHERE doc_id = ? ORDER BY CAST(chunk_index AS INTEGER) LIMIT ? OFFSET ?",
                           (doc_id, limit + 1, offset))
        total = store.query("SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (doc_id,))[0][0]
        return schemas.ChunkPage(total=total, has_more=len(rows) > limit, offset=offset, limit=limit,
                                 items=[_row_from_chunk(store._chunk(row)) for row in rows[:limit]])
    if source:
        where.append("title = ?" if table == "law" else "kommun_code = ?")
        params.append(source)
    if doc_type and table == "document":
        where.append("doc_type = ?")
        params.append(doc_type)
    if q:
        where.append("(text LIKE ? OR header LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    condition = " AND ".join(where)
    if table == "law":
        order = "title, CAST(chunk_index AS INTEGER)"
    elif source:
        order = f"{_TYPE_RANK}, title, doc_id, CAST(chunk_index AS INTEGER)"
    else:
        order = "rowid"
    rows = store.query(f"SELECT * FROM chunks WHERE {condition} ORDER BY {order} LIMIT ? OFFSET ?",
                       (*params, limit + 1, offset))
    items = [_row_from_chunk(store._chunk(row)) for row in rows[:limit]]
    if table == "document" and not q:
        total = sum(r["chunks"] for r in store.summary()
                    if (not source or r["kommun_code"] == source) and (not doc_type or r["doc_type"] == doc_type))
    elif table == "document" and not source:
        total = None
    else:
        total = store.query(f"SELECT COUNT(*) FROM chunks WHERE {condition}", tuple(params))[0][0]
    return schemas.ChunkPage(total=total, has_more=len(rows) > limit, offset=offset, limit=limit, items=items)


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
    doc_type: str | None = None,
    doc_id: str | None = None,
    q: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    store: schemas.ChunkStore = "neon",
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    if store == "local":
        return _local_page(table, source, doc_type, q, offset, limit, doc_id)
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


@router.get("/db/documents", response_model=schemas.DocumentPage)
def list_documents(
    source: str,
    doc_type: str | None = None,
    q: str | None = None,
    scanned: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _user: models.User = Depends(get_current_user),
):
    """Local disk store only: a kommun's documents by type, then title (q filters the title, scanned keeps the
    scanned PDFs read by the OCR)."""
    store = _local_store()
    if store is None:
        return schemas.DocumentPage(total=0, offset=offset, limit=limit, items=[])
    return _store_documents(store, source, doc_type, q, offset, limit, scanned)


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
                                         content=row["content"], chunk_id=row["chunk_id"], doc_id=row["doc_id"],
                                         kind=row["kind"], url=row["url"])
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
