"""
app/schemas/knowledge.py — Knowledge Document Admin Schemas
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """Response after uploading a knowledge document."""

    document_id: uuid.UUID
    title: str
    status: str  # always "pending" after upload
    chunk_count: int
    message: str


class DocumentListResponse(BaseModel):
    """A document in the admin document list."""

    document_id: uuid.UUID
    title: str
    file_name: str
    file_type: str
    status: str
    chunk_count: int
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None

    model_config = {"from_attributes": True}


class ApproveDocumentRequest(BaseModel):
    """Admin request to approve a pending document."""

    approved: bool = True
    rejection_reason: str | None = Field(
        default=None,
        max_length=500,
        description="Required when approved=False",
    )


class DocumentStatusResponse(BaseModel):
    """Response after approving/rejecting a document."""

    document_id: uuid.UUID
    status: str
    message: str


class AnalyticsSummaryResponse(BaseModel):
    """Summary analytics for admin dashboard."""

    tenant_slug: str
    period_days: int
    total_questions: int
    fallback_rate: float
    avg_latency_ms: float | None
    handoffs_created: int
    errors: int
    top_event_types: list[dict]
