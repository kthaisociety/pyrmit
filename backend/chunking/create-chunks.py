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

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Add parent directory to PYTHONPATH
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

def safe_get(d: dict, key: str, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default

def safe_text(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            return str(text)
        except Exception:
            return ""
    return text

def load_documents(path: str):
    folder = Path(path)
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder.resolve()}")

    docs = SimpleDirectoryReader(path).load_data()
    if not docs:
        raise ValueError(f"No documents loaded from: {path}")

    return docs


def main():
    # -------------------------------
    # 1. Load documents and chunking
    # -------------------------------
    try:
        documents = load_documents("../data")
    except Exception as e:
        print(f"Error loading documents: {e}")
        return

    splitter = SentenceSplitter(chunk_size=500, chunk_overlap=100)

    try:
        nodes = splitter.get_nodes_from_documents(documents)
    except Exception as e:
        print(f"Error splitting documents: {e}")
        return

    print(f"Chunking complete. {len(nodes)} chunks created.")

    # Prepare raw chunks (NO embeddings yet)
    raw_chunks = []
    file_id_map = {}
    current_doc_id = 1

    for idx, node in enumerate(nodes):
        metadata = node.metadata or {}
        file_name = safe_get(metadata, "file_name", "unknown")

        # enumerate documents
        if file_name not in file_id_map:
            file_id_map[file_name] = current_doc_id
            current_doc_id += 1

        doc_id = file_id_map[file_name]

        raw_chunks.append({
            "id": str(uuid.uuid4()),
            "document_id": doc_id,
            "document_name": file_name,
            "chunk_index": idx,
            "content": safe_text(node.get_content()),
            "metadata": metadata,
        })

    print("Raw chunks prepared. Beginning embedding + DB write pass...")

    # -------------------------------
    # 2. Embedding + DB Storage
    # -------------------------------

    db = SessionLocal()
    structured_chunks = []

    try:
        for chunk in raw_chunks:
            try:
                # Generate embedding
                embedding = embed_text(chunk["content"])

                item = {
                    **chunk,
                    "embedding": embedding,
                    "created_at": datetime.now().isoformat()
                }

                structured_chunks.append(item)

                # Save to DB
                db_chunk = models.DocumentChunk(
                    id=item["id"],
                    document_name=item["document_name"],
                    chunk_index=item["chunk_index"],
                    content=item["content"],
                    embedding=item["embedding"],
                )
                db.add(db_chunk)

            except Exception as e:
                print(f"Error processing chunk {chunk['chunk_index']}: {e}")
                continue

        # Commit all chunks at once
        db.commit()
        print(f"Saved {len(structured_chunks)} chunks to database")

    except Exception as e:
        print("DB error:", e)
        db.rollback()
    finally:
        db.close()

    # -------------------------------
    # 3. Save JSON backup
    # -------------------------------
    with open("chunks.json", "w", encoding="utf-8") as f:
        json.dump(structured_chunks, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(structured_chunks)} chunks → chunks.json")


if __name__ == "__main__":
    main()
