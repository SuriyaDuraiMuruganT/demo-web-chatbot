"""
app/models/analytics.py — Analytics Events Model

Stores operational events for monitoring and reporting.
Sensitive personal data is NOT logged here — only aggregate metrics.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalyticsEvent(Base):
    """
    A single operational event for metrics tracking.

    Event types:
      - chat_request: A chat message was processed
      - chat_fallback: No relevant context found, fallback returned
      - chat_error: An error occurred during chat processing
      - handoff_created: A human handoff was requested
      - handoff_notified: Handoff notification sent
      - handoff_notification_failed: Notification failed
      - document_ingested: A document was ingested
      - document_approved: A document was approved
    """

    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_tenant_type_time", "tenant_id", "event_type", "created_at"),
        Index("ix_analytics_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Aggregate/non-personal payload
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Event data: latency_ms, token_usage, similarity_score, etc.",
    )

    # Pre-aggregated counters for efficient querying
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AnalyticsEvent id={self.id} type={self.event_type}>"
