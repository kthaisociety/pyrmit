from pathlib import Path

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from chunking.ingest_pipeline import ensure_markdown_source, ingest_folder, ingest_markdown_document
from db.push_db import PushDB
import schemas


router = APIRouter()


def _resolve_workspace_path(path_value: str) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate

    backend_root = Path(__file__).resolve().parent.parent
    repo_root = backend_root.parent
    search_paths = [
        Path.cwd() / candidate,
        backend_root / candidate,
        repo_root / candidate,
    ]

    for path in search_paths:
        if path.exists():
            return path.resolve()

    return (backend_root / candidate).resolve()


@router.post("/chunks/ingest-detaljplan", response_model=schemas.ChunkIngestResponse)
def ingest_detaljplan_chunks(request: schemas.ChunkIngestRequest):
    input_path = _resolve_workspace_path(request.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {input_path}")

    output_path = _resolve_workspace_path(request.output_path) if request.output_path else None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        markdown_output_dir = Path(__file__).resolve().parent.parent / "data" / "ocr_markdown"
        source_markdown_path = ensure_markdown_source(input_path, markdown_output_dir)
        push_db = PushDB()
        client = OpenAI()

        inserted, deleted = ingest_markdown_document(
            push_db=push_db,
            client=client,
            markdown_path=source_markdown_path,
            output_path=output_path,
            document_name=request.document_name,
            document_id=request.document_id,
            max_chars=request.max_chars,
            clear_existing_for_document=request.clear_existing_for_document,
        )

        if inserted == 0:
            raise HTTPException(status_code=400, detail="No chunks were generated from the input file")

        return schemas.ChunkIngestResponse(
            inserted=inserted,
            deleted=deleted,
            document_name=request.document_name,
            document_id=request.document_id,
            output_path=str(output_path) if output_path else None,
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=500, detail=f"Chunk ingestion failed: {exc}")


@router.post("/chunks/ingest-data-folder", response_model=schemas.FolderIngestResponse)
def ingest_data_folder_route(request: schemas.FolderIngestRequest):
    data_dir = _resolve_workspace_path(request.data_dir)
    if not data_dir.exists() or not data_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Data directory not found: {data_dir}")

    markdown_output_dir = _resolve_workspace_path(request.markdown_output_dir)
    markdown_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = ingest_folder(
            data_dir=data_dir,
            markdown_output_dir=markdown_output_dir,
            max_chars=request.max_chars,
            clear_existing_for_document=request.clear_existing_for_document,
        )

        if result["documents_processed"] == 0:
            raise HTTPException(status_code=400, detail="No supported files found in data directory")

        items = [schemas.FolderIngestItem(**item) for item in result["items"]]
        return schemas.FolderIngestResponse(
            documents_processed=result["documents_processed"],
            total_inserted=result["total_inserted"],
            total_deleted=result["total_deleted"],
            items=items,
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=500, detail=f"Folder ingestion failed: {exc}")
