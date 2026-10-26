"""
app/schemas/chat.py — Chat Request and Response Schemas
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.schemas.conversation import SourceReference


class ChatRequest(BaseModel):
    """A customer's question submitted to the chatbot."""

    conversation_id: uuid.UUID
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The customer's question",
    )

    @field_validator("question", mode="before")
    @classmethod
    def sanitize_question(cls, v: str) -> str:
        """Strip excessive whitespace. Content validation happens in the service layer."""
        return " ".join(v.split()).strip()


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None


class ChatResponse(BaseModel):
    """The AI assistant's response to a customer question."""

    message_id: uuid.UUID
    answer: str
    sources: list[SourceReference] = Field(default_factory=list)
    is_fallback: bool = False
    confidence: str = Field(
        default="medium",
        description="low | medium | high — based on retrieval similarity scores"
    )
    suggested_followups: list[str] = Field(default_factory=list)
    token_usage: TokenUsage | None = None
    response_time_ms: int | None = None
