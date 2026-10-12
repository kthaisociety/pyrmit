import os
import re
import uuid
from pathlib import Path

from openai import OpenAI

from chunking.chunk_detaljplan import DetaljplanChunker
from db.push_db import PushDB
from llm import get_openai_client
from ocr.detaljplan_ocr import MistralOCR

def slugify_document_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\-_\.]+", "_", name.strip().lower())
    return normalized.strip("_") or "document"


def ensure_markdown_source(input_path: Path, markdown_output_dir: Path) -> Path:
    suffix = input_path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return input_path

    if suffix != ".pdf":
        raise ValueError(f"Unsupported file type: {input_path.suffix}")

    mistral_key = os.getenv("MISTRAL_API_KEY") or os.getenv("AI_GATEWAY_API_KEY")
    if not mistral_key:
        raise RuntimeError("MISTRAL_API_KEY or AI_GATEWAY_API_KEY is required for PDF OCR")

    markdown_output_dir.mkdir(parents=True, exist_ok=True)
    md_path = markdown_output_dir / f"{input_path.stem}.md"
    if md_path.exists():
        return md_path

    ocr = MistralOCR()
    ocr_result = ocr.main(str(input_path))
    markdown_text = "\n\n---\n\n".join(page.markdown for page in ocr_result.pages)
    md_path.write_text(markdown_text, encoding="utf-8")
    return md_path


def embed_texts_batch(client: OpenAI, texts: list[str], batch_size: int = 100) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        response = client.embeddings.create(model="openai/text-embedding-3-large", input=batch)
        all_embeddings.extend(item.embedding for item in response.data)
    return all_embeddings


def ingest_markdown_document(
    push_db: PushDB,
    client: OpenAI,
    markdown_path: Path,
    output_path: Path | None,
    document_name: str,
    document_id: int,
    max_chars: int,
    clear_existing_for_document: bool,
) -> tuple[int, int]:
    chunker = DetaljplanChunker(max_chunk_chars=max_chars)
    chunks = chunker.chunk_file(input_path=markdown_path, output_path=output_path)

    if not chunks:
        return 0, 0

    texts_for_embedding = [
        f"Section: {chunk.get('section', 'Document')}\n\n{chunk['content']}"
        for chunk in chunks
    ]
    embeddings = embed_texts_batch(client, texts_for_embedding)

    deleted = 0
    if clear_existing_for_document:
        deleted = push_db.delete_chunks_by_document_name(document_name)

    rows = [
        {
            "id": str(uuid.uuid4()),
            "document_id": document_id,
            "document_name": document_name,
            "chunk_index": index,
            "content": texts_for_embedding[index],
            "embedding": embedding,
        }
        for index, embedding in enumerate(embeddings)
    ]
    push_db.push_chunks(rows)

    return len(chunks), deleted


def ingest_folder(
    data_dir: Path,
    markdown_output_dir: Path,
    max_chars: int,
    clear_existing_for_document: bool,
) -> dict:
    supported_files = sorted(
        path for path in data_dir.iterdir() if path.is_file() and path.suffix.lower() in {".pdf", ".md", ".txt"}
    )
    if not supported_files:
        return {
            "documents_processed": 0,
            "total_inserted": 0,
            "total_deleted": 0,
            "items": [],
        }

    push_db = PushDB()
    client = get_openai_client()

    items: list[dict] = []
    total_inserted = 0
    total_deleted = 0

    for document_id, source_file in enumerate(supported_files, start=1):
        markdown_path = ensure_markdown_source(source_file, markdown_output_dir)
        chunk_output_path = markdown_output_dir / f"{source_file.stem}.chunks.json"
        document_name = slugify_document_name(source_file.stem)

        inserted, deleted = ingest_markdown_document(
            push_db=push_db,
            client=client,
            markdown_path=markdown_path,
            output_path=chunk_output_path,
            document_name=document_name,
            document_id=document_id,
            max_chars=max_chars,
            clear_existing_for_document=clear_existing_for_document,
        )

        total_inserted += inserted
        total_deleted += deleted
        items.append(
            {
                "source_file": str(source_file),
                "markdown_file": str(markdown_path),
                "document_name": document_name,
                "document_id": document_id,
                "inserted": inserted,
                "deleted": deleted,
            }
        )

    return {
        "documents_processed": len(items),
        "total_inserted": total_inserted,
        "total_deleted": total_deleted,
        "items": items,
    }
