import os
from supabase import create_client, Client
from dotenv import load_dotenv

class PushDB:

    def __init__(self):
        self.supabase_url = os.environ["SUPABASE_URL"]
        self.supabase_key = os.environ["SUPABASE_KEY"]
        self.client: Client = create_client(self.supabase_url, self.supabase_key)

    def push_chunk(self, id: str, document_id: int, document_name: str, chunk_index: int, content: str, embedding: list):
        data = {
            "id": id,
            "document_id": document_id,
            "document_name": document_name,
            "chunk_index": chunk_index,
            "content": content,
            "embedding": embedding
        }
        response = self.client.table("document_chunks").insert(data).execute()
        return response


'''
class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, index=True)
    document_id = Column(Integer, nullable=True)
    document_name = Column(String, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    content = Column(Text, nullable=True)
    embedding = Column(Vector(3072), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    push a dummy chunk into this table following the model
'''

if __name__ == "__main__":
    load_dotenv()
    push_db = PushDB()
    response = push_db.push_chunk(
        id="gabagool",
        document_id=1,
        document_name="test_document",
        chunk_index=0,
        content="This is a test chunk.",
        embedding=[0.1]*3072
    )
    print(response)