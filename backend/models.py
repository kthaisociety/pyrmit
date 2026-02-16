from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from db.database import Base
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

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, index=True)
    document_id = Column(Integer, nullable=True)
    document_name = Column(String, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    content = Column(Text, nullable=True)
    embedding = Column(Vector(3072), nullable=True)
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")

if __name__ == "__main__":
    load_dotenv()

    # Use the Connection String from Settings > Database
    # It looks like: postgresql://postgres:[password]@db.[id].supabase.co:5432/postgres
    DATABASE_URL = os.environ["SUPABASE_DB_URL"] 

    # Create the engine using the Postgres protocol
    engine = create_engine(DATABASE_URL)

    # Use the metadata of your base class (usually Base) to create tables
    # If DocumentChunk is a class, use DocumentChunk.metadata
    Base.metadata.create_all(engine)
    
    print("Tables created successfully!")