import os
import psycopg2
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv


class PushDB:

    def __init__(self):
        self.db_url = os.environ["DATABASE_URL"]

    def _get_conn(self):
        conn = psycopg2.connect(self.db_url)
        register_vector(conn)
        return conn

    def push_chunk(self, id: str, document_id: int, document_name: str, chunk_index: int, content: str, embedding: list):
        return self.push_chunks([{
            "id": id,
            "document_id": document_id,
            "document_name": document_name,
            "chunk_index": chunk_index,
            "content": content,
            "embedding": embedding
        }])

    def push_chunks(self, chunks: list[dict]):
        if not chunks:
            return None

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for chunk in chunks:
                    cur.execute(
                        "INSERT INTO document_chunks (id, document_id, document_name, chunk_index, content, embedding) VALUES (%s, %s, %s, %s, %s, %s)",
                        (chunk["id"], chunk["document_id"], chunk["document_name"], chunk["chunk_index"], chunk["content"], chunk["embedding"])
                    )
            conn.commit()
        finally:
            conn.close()

    def delete_chunks_by_document_name(self, document_name: str) -> int:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM document_chunks WHERE document_name = %s", (document_name,))
                count = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        return count

    def push_law_chunks(self, chunks: list[dict]):
        if not chunks:
            return None

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for chunk in chunks:
                    cur.execute(
                        "INSERT INTO law_chunks (id, law_name, source_file, chapter, chapter_title, section, chunk_index, content, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (chunk["id"], chunk["law_name"], chunk.get("source_file"), chunk.get("chapter"), chunk.get("chapter_title"), chunk.get("section"), chunk["chunk_index"], chunk["content"], chunk["embedding"])
                    )
            conn.commit()
        finally:
            conn.close()

    def delete_law_chunks_by_law_name(self, law_name: str) -> int:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM law_chunks WHERE law_name = %s", (law_name,))
                count = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        return count


if __name__ == "__main__":
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
    from models import DocumentChunk
    
    load_dotenv()
    push_db = PushDB()
    push_db.push_chunk(
        id="gabagool",
        document_id=1,
        document_name="test_document",
        chunk_index=0,
        content="This is a test chunk.",
        embedding=[0.1] * 3072
    )
    print("Test chunk inserted successfully.")
