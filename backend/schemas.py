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


class PlacePin(BaseModel):
    """The place pinned on the chat's map: the question is about it (place/, ADR-0004)."""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = None  # e.g. "Uppsala Kungsängen 7:8", as the chip shows it


class ChatRequest(BaseModel):
    session_id: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    place: PlacePin | None = None
    answer_to_question: bool = False  # the message is the user's answer to the agent's question (a clicked option)


class MessageResponse(ChatMessage):
    id: int
    session_id: str | None = None
    created_at: datetime
    trace: list[dict] | None = None
    status: str | None = None

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


# --- Database browser schemas ---

ChunkTableName = Literal["law", "document"]
# "neon": pgvector tables; "local": the offline corpus served by localrag (data/corpus/chunks.jsonl)
ChunkStore = Literal["neon", "local"]


class TypeCount(BaseModel):
    doc_type: str
    documents: int
    chunks: int
    pdfs: int = 0
    pages: int = 0


class SourceCount(BaseModel):
    name: str
    count: int
    key: str | None = None            # value to filter on when it differs from the name (local corpus: kommun code)
    documents: int | None = None
    types: list[TypeCount] | None = None  # local corpus: documents per type within the kommun


class ChunkTableOverview(BaseModel):
    total: int
    with_embedding: int
    sources: list[SourceCount]


class DbOverview(BaseModel):
    law: ChunkTableOverview
    document: ChunkTableOverview


class ChunkRow(BaseModel):
    id: str
    source: str
    chunk_index: int | None = None
    chapter: str | None = None
    chapter_title: str | None = None
    section: str | None = None
    content: str
    has_embedding: bool
    created_at: datetime | None = None
    # Local corpus documents
    doc_id: str | None = None
    kind: str | None = None
    doc_type: str | None = None
    kommun: str | None = None
    url: str | None = None


class DocumentRow(BaseModel):
    doc_id: str
    title: str
    kind: str
    doc_type: str | None = None
    url: str | None = None
    chunks: int


class DocumentPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[DocumentRow]


class ChunkPage(BaseModel):
    total: int | None  # None: not counted (text filter over the whole local corpus)
    has_more: bool | None = None
    offset: int
    limit: int
    items: list[ChunkRow]


class ChunkSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)
    store: ChunkStore = "neon"


class ChunkSearchMatch(BaseModel):
    source: str
    chunk_index: int | None = None
    distance: float | None = None
    content: str
    # Local corpus: to open the original document (/api/docs/locate)
    chunk_id: str | None = None
    doc_id: str | None = None
    kind: str | None = None
    url: str | None = None


class ChunkSearchResponse(BaseModel):
    embedding_ok: bool
    kommuner: list[str] = []
    law: list[ChunkSearchMatch]
    document: list[ChunkSearchMatch]
