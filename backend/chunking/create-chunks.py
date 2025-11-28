import json
import uuid
from datetime import datetime
from pathlib import Path

from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter

from openai import OpenAI

import dotenv
client = OpenAI(api_key="")

def embed_text(text: str):
    response = client.embeddings.create(
        model="text-embedding-3-large",
        input=text
    )
    return response.data[0].embedding

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

    for i, node in enumerate(nodes):
        try:
            content = safe_text(node.get_content())
            embedding = embedding = embed_text(content)
            metadata = node.metadata or {}

            # enumerate documents, for now its just 1
            file_name = safe_get(metadata, "file_name", "unknown")
            if file_name not in file_id_map:
                file_id_map[file_name] = current_doc_id
                current_doc_id += 1

            doc_id = file_id_map[file_name]

            item = {
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "document_name": safe_get(metadata, "file_name", "unknown"),
                "chunk_index": i,
                "content": content,
                "embedding": embedding,
                "created_at": datetime.now().isoformat(),
            }

            structured_chunks.append(item)

        except Exception as e:
            print(f"Error processing chunk {i}: {e}")
            continue

    try:
        with open("chunks.json", "w", encoding="utf-8") as f:
            json.dump(structured_chunks, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(structured_chunks)} chunks → chunks.json")

    except Exception as e:
        print(f"Error writing JSON: {e}")


if __name__ == "__main__":
    main()

