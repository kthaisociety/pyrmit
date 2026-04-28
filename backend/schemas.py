from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserTable(BaseModel):
    id: str
    name: str
    email: EmailStr
    email_verified: bool = False
    image: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountTable(BaseModel):
    id: str
    account_id: str
    provider_id: str
    user_id: str
    access_token: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    scope: str | None = None
    password: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SessionTable(BaseModel):
    id: str
    expires_at: datetime
    token: str
    created_at: datetime
    updated_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    user_id: str

    class Config:
        from_attributes = True


class DocumentChunk(BaseModel):
    id: str
    document_id: int | None = None
    document_name: str | None = None
    chunk_index: int | None = None
    content: str | None = None
    embedding: list[float] | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class UserPublic(BaseModel):
    id: str
    name: str
    email: EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=2)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UpdateProfileRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=8)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatSession(BaseModel):
    id: str
    user_id: str | None = None
    title: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    session_id: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)


class MessageResponse(ChatMessage):
    id: int
    session_id: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChunkIngestRequest(BaseModel):
    input_path: str = "output.md"
    output_path: str | None = "chunks.json"
    document_name: str = "kristineberg_detaljplan"
    document_id: int = 1
    max_chars: int = Field(default=1800, ge=200, le=8000)
    clear_existing_for_document: bool = True


class ChunkIngestResponse(BaseModel):
    inserted: int
    deleted: int
    document_name: str
    document_id: int
    output_path: str | None = None


class FolderIngestItem(BaseModel):
    source_file: str
    markdown_file: str
    document_name: str
    document_id: int
    inserted: int
    deleted: int


class FolderIngestRequest(BaseModel):
    data_dir: str = "chunking/data"
    markdown_output_dir: str = "data/ocr_markdown"
    max_chars: int = Field(default=1800, ge=200, le=8000)
    clear_existing_for_document: bool = True


class FolderIngestResponse(BaseModel):
    documents_processed: int
    total_inserted: int
    total_deleted: int
    items: list[FolderIngestItem]


# --- Agent / Analyze schemas ---

class AnalyzeRequest(BaseModel):
    query: str | None = None
    location: str | None = None
    project_type: str | None = None
    units: int | None = None


class AnalyzeResponse(BaseModel):
    feasibility: str
    confidence: int
    summary: str
    law_findings: str
    case_findings: str
    requirements: list[str]
    timeline: str | int | None = None
    next_steps: list[str]
