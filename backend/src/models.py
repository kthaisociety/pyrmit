from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from db.database import Base
from embeddings import embedding_dim
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    email_verified = Column(Boolean, default=False)
    image = Column(String, nullable=True)
    # owner | developer | user (roles.py, issue #112); added to existing tables by main._create_tables
    role = Column(String, nullable=False, default="user", server_default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    accounts = relationship("Account", back_populates="user")
    sessions = relationship("Session", back_populates="user")
    chat_sessions = relationship("ChatSession", back_populates="user")

class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(String) # Provider's account ID
    provider_id = Column(String)
    user_id = Column(String, ForeignKey("users.id"))
    access_token = Column(String, nullable=True)
    refresh_token = Column(String, nullable=True)
    id_token = Column(String, nullable=True)
    access_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    refresh_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    scope = Column(String, nullable=True)
    password = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="accounts")

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, index=True)
    expires_at = Column(DateTime(timezone=True))
    token = Column(String, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    user_id = Column(String, ForeignKey("users.id"))

    user = relationship("User", back_populates="sessions")

class UserApiKey(Base):
    """A user's own API key for a model provider (issue #108, user_keys.py): Fernet-encrypted under
    API_KEY_ENCRYPTION_KEY, with its last 4 characters, the only part shown back. One key per user and provider."""
    __tablename__ = "user_api_keys"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider = Column(String, primary_key=True)  # "openrouter"
    encrypted_key = Column(Text, nullable=False)
    last4 = Column(String(4), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:  # never the encrypted key
        return f"UserApiKey(user_id={self.user_id!r}, provider={self.provider!r}, last4={self.last4!r})"

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, index=True)
    document_id = Column(Integer, nullable=True)
    document_name = Column(String, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    content = Column(Text, nullable=True)
    embedding = Column(Vector(embedding_dim()), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LawChunk(Base):
    __tablename__ = "law_chunks"

    id = Column(String, primary_key=True, index=True)
    law_name = Column(String, nullable=False, index=True)
    source_file = Column(String, nullable=True)
    chapter = Column(String, nullable=True)
    chapter_title = Column(String, nullable=True)
    section = Column(String, nullable=True, index=True)
    chunk_index = Column(Integer, nullable=True)
    content = Column(Text, nullable=True)
    embedding = Column(Vector(embedding_dim()), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=True)
    role = Column(String, index=True)
    content = Column(Text)
    # Pipeline inspector events (prompts, API calls, retrieved chunks) for assistant messages
    trace = Column(JSONB, nullable=True)
    # Assistant messages: "streaming" while the answer is generated in the background, then "done" or "error"
    status = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


class CorpusVersion(Base):
    """History of the corpus (issue #114, corpus_admin.py): every replace, roll back and download, who did it and how it
    went. A replace row is also its background job: status running -> done / failed, `progress` polled by the panel.
    In public, beside the users: it outlives the corpus schemas it describes."""
    __tablename__ = "corpus_versions"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)  # replace | rollback | download
    status = Column(String, nullable=False)  # running | done | failed
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_email = Column(String, nullable=True)  # kept when the account goes
    file_name = Column(String, nullable=True)
    model = Column(String, nullable=True)
    chunks = Column(Integer, nullable=True)
    kommuner = Column(Integer, nullable=True)
    built = Column(String, nullable=True)
    progress = Column(JSONB, nullable=True)  # {"phase", "percent", "message"}
    detail = Column(Text, nullable=True)  # the result, or the error
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

if __name__ == "__main__":
    load_dotenv()

    # Use the Connection String from Settings > Database
    # It looks like: postgresql://postgres:[password]@db.[id].supabase.co:5432/postgres
    DATABASE_URL = os.environ["DATABASE_URL"]

    # Create the engine using the Postgres protocol
    DATABASE_URL = os.environ.get("DATABASE_URL")
    engine = create_engine(DATABASE_URL)

    # Use the metadata of your base class (usually Base) to create tables
    # If DocumentChunk is a class, use DocumentChunk.metadata
    Base.metadata.create_all(engine)
    
    print("Tables created successfully!")