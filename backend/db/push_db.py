import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.database import engine, SessionLocal
from models import DocumentChunk, LawChunk

class PushDB:

    def __init__(self):
        self.session = SessionLocal()

    def push_chunk(self, id: str, document_id: int, document_name: str, chunk_index: int, content: str, embedding: list):
        chunk = DocumentChunk(
            id=id,
            document_id=document_id,
            document_name=document_name,
            chunk_index=chunk_index,
            content=content,
            embedding=embedding
        )
        self.session.add(chunk)
        self.session.commit()
        return {"data": [chunk.id]}

    def push_chunks(self, chunks: list[dict], batch_size: int = 100):
        if not chunks:
            return None

        # Using bulk insert mappings for best performance
        self.session.bulk_insert_mappings(DocumentChunk, chunks)
        self.session.commit()
        return {"data": chunks}

    def delete_chunks_by_document_name(self, document_name: str) -> int:
        deleted_count = self.session.query(DocumentChunk).filter(DocumentChunk.document_name == document_name).delete(synchronize_session=False)
        self.session.commit()
        return deleted_count

    def push_law_chunks(self, chunks: list[dict], batch_size: int = 100):
        if not chunks:
            return None

        self.session.bulk_insert_mappings(LawChunk, chunks)
        self.session.commit()
        return {"data": chunks}

    def delete_law_chunks_by_law_name(self, law_name: str) -> int:
        deleted_count = self.session.query(LawChunk).filter(LawChunk.law_name == law_name).delete(synchronize_session=False)
        self.session.commit()
        return deleted_count

    def close(self):
        self.session.close()



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
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
    from models import DocumentChunk
    
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