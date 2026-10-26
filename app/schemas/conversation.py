"""
app/schemas/conversation.py — Conversation and Session Schemas
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    """Request to start a new chat session."""
    tenant_slug: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9\-]+$",
        examples=["demo-company"],
    )


class ConversationResponse(BaseModel):
    """Response after creating a conversation. Includes the session token."""
    conversation_id: uuid.UUID
    session_token: str = Field(
        ...,
        description="Bearer token — include in Authorization header for subsequent requests"
    )
    tenant_slug: str
    expires_in_minutes: int
    welcome_message: str
    assistant_name: str
    suggested_questions: list[str]


class MessageResponse(BaseModel):
    """A single message in conversation history."""
    id: uuid.UUID
    role: str  # "user" | "assistant"
    content: str
    sources: list[SourceReference]
    is_fallback: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceReference(BaseModel):
    """A source document referenced in an AI response."""
    title: str
    chunk_id: str | None = None
    similarity_score: float | None = None
    source_url: str | None = None
    section: str | None = None


class ConversationHistoryResponse(BaseModel):
    """Paginated conversation history."""
    conversation_id: uuid.UUID
    messages: list[MessageResponse]
    total_messages: int


# Resolve forward reference
MessageResponse.model_rebuild()
