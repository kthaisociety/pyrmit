import argparse
import logging
import os
import uuid
from pathlib import Path
import sys

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from chunking.chunk_laws import LawChunker
from db.push_db import PushDB


def embed_texts_batch(client, texts: list[str], batch_size: int = 100) -> list[list[float]]:
    all_embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        response = client.embeddings.create(model="text-embedding-3-large", input=batch)
        all_embeddings.extend(item.embedding for item in response.data)
    return all_embeddings


def ingest_laws(
    laws_dir: Path,
    output_dir: Path,
    max_chars: int,
    clear_existing_for_law: bool,
) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")

    law_files = sorted(p for p in laws_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt")
    if not law_files:
        logger.warning("No law text files found in %s", laws_dir)
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    chunker = LawChunker(max_chunk_chars=max_chars)
    push_db = PushDB()
    client = OpenAI()

    total_inserted = 0
    total_deleted = 0

    for law_file in law_files:
        law_name = law_file.stem
        chunk_output = output_dir / f"{law_name}.chunks.json"
        chunks = chunker.chunk_file(law_file, chunk_output)

        if not chunks:
            logger.warning("Skipped %s: no legal sections found", law_file.name)
            continue

        deleted = 0
        if clear_existing_for_law:
            deleted = push_db.delete_law_chunks_by_law_name(law_name)

        texts_for_embedding = [
            (
                f"Lag: {chunk['law_name']}\n"
                f"Kapitel: {chunk.get('chapter') or '-'}\n"
                f"Paragraf: {chunk.get('section') or '-'}\n\n"
                f"{chunk['content']}"
            )
            for chunk in chunks
        ]
        embeddings = embed_texts_batch(client, texts_for_embedding)

        rows = []
        for index, embedding in enumerate(embeddings):
            chunk = chunks[index]
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "law_name": law_name,
                    "source_file": law_file.name,
                    "chapter": chunk.get("chapter"),
                    "chapter_title": chunk.get("chapter_title"),
                    "section": chunk.get("section"),
                    "chunk_index": index,
                    "content": texts_for_embedding[index],
                    "embedding": embedding,
                }
            )

        push_db.push_law_chunks(rows)

        total_inserted += len(rows)
        total_deleted += deleted
        logger.info("Ingested %s: inserted=%d, deleted=%d", law_file.name, len(rows), deleted)

    logger.info("Done. laws=%d inserted=%d deleted=%d", len(law_files), total_inserted, total_deleted)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk, embed and ingest law texts into law_chunks")
    parser.add_argument("--laws-dir", type=Path, default=Path("chunking/laws"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/law_chunks"))
    parser.add_argument("--max-chars", type=int, default=2400)
    parser.add_argument("--keep-existing", action="store_true")
    args = parser.parse_args()

    ingest_laws(
        laws_dir=args.laws_dir,
        output_dir=args.output_dir,
        max_chars=args.max_chars,
        clear_existing_for_law=not args.keep_existing,
    )


if __name__ == "__main__":
    main()
