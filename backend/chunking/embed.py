import json
import uuid
from datetime import datetime
from pathlib import Path
import sys
import os

from dotenv import load_dotenv
from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter

from openai import OpenAI

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Add parent directory to path to import from backend
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import SessionLocal
import models

client = OpenAI()

def embed_text(text: str):
    response = client.embeddings.create(
        model="text-embedding-3-large",
        input=text
    )
    return response.data[0].embedding

def embed_texts_batch(texts: list[str], batch_size: int = 100):
    """Embed multiple texts in batches for efficiency."""
    all_embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model="text-embedding-3-large",
            input=batch
        )
        all_embeddings.extend([item.embedding for item in response.data])
    
    return all_embeddings

def safe_get(d: dict, key: str, default=None):
    """Safely fetch metadata values."""
    try:
        return d.get(key, default)
    except Exception:
        return default

def safe_text(text):
    """Ensure text value is always a valid string."""
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            return str(text)
        except Exception:
            return ""
    return text

def load_documents(path: str):
    """Load documents with safety checks."""
    folder = Path(path)
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder.resolve()}")

    docs = SimpleDirectoryReader(path).load_data()
    if not docs:
        raise ValueError(f"No documents loaded from: {path}")

    return docs

def main():
    try:
        documents = load_documents("../data")
    except Exception as e:
        print(f"Error loading documents: {e}")
        return

    splitter = SentenceSplitter(
        chunk_size=500,
        chunk_overlap=100,
    )

    try:
        nodes = splitter.get_nodes_from_documents(documents)
    except Exception as e:
        print(f"Error splitting documents: {e}")
        return

    structured_chunks = []

    file_id_map = {}
    current_doc_id = 1
    db = SessionLocal()

    try:
        # First pass: collect all content and metadata
        node_data = []
        for i, node in enumerate(nodes):
            try:
                content = safe_text(node.get_content())
                metadata = node.metadata or {}

                # enumerate documents
                file_name = safe_get(metadata, "file_name", "unknown")
                if file_name not in file_id_map:
                    file_id_map[file_name] = current_doc_id
                    current_doc_id += 1

                doc_id = file_id_map[file_name]

                node_data.append({
                    "content": content,
                    "metadata": metadata,
                    "doc_id": doc_id,
                    "chunk_index": i,
                })

            except Exception as e:
                print(f"Error processing node {i}: {e}")
                continue

        # Second pass: generate embeddings in batches
        print(f"Generating embeddings for {len(node_data)} chunks...")
        contents = [item["content"] for item in node_data]
        embeddings = embed_texts_batch(contents)

        # Third pass: create structured chunks with embeddings
        for i, (data, embedding) in enumerate(zip(node_data, embeddings)):
            try:
                item = {
                    "id": str(uuid.uuid4()),
                    "document_id": data["doc_id"],
                    "document_name": safe_get(data["metadata"], "file_name", "unknown"),
                    "chunk_index": data["chunk_index"],
                    "content": data["content"],
                    "embedding": embedding,
                    "created_at": datetime.now().isoformat(),
                }

                structured_chunks.append(item)

                # Save to database
                db_chunk = models.DocumentChunk(
                    id=item["id"],
                    document_id=item["document_id"],
                    document_name=item["document_name"],
                    chunk_index=item["chunk_index"],
                    content=item["content"],
                    embedding=item["embedding"],
                    created_at=datetime.fromisoformat(item["created_at"]),
                )
                db.add(db_chunk)

            except Exception as e:
                print(f"Error creating chunk {i}: {e}")
                continue

        # Commit all chunks to database
        db.commit()
        print(f"Saved {len(structured_chunks)} chunks to database")

        # Also save to JSON for backup
        with open("chunks.json", "w", encoding="utf-8") as f:
            json.dump(structured_chunks, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(structured_chunks)} chunks → chunks.json")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()

