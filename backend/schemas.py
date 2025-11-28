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


class SessionResponse(BaseModel):
    session_id: str
    user: UserPublic


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=2)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


class MessageResponse(ChatMessage):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

