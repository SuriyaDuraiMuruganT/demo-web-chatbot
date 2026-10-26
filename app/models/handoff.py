"""
app/models/handoff.py — Human Support Handoff Request Model

When the AI cannot adequately help a customer, they can request
human support. This model stores those requests with their status
and explicit consent records.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HandoffRequest(Base):
    """
    A customer's request for human support.

    Status lifecycle:
      pending → notified (email/ticket sent)
              → contacted (staff has responded)
              → resolved
              → closed
    """

    __tablename__ = "handoff_requests"
    __table_args__ = (
        Index("ix_handoff_tenant_status", "tenant_id", "status"),
        Index("ix_handoff_conversation", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Contact information (collected only with consent)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_summary: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Customer's description of their issue"
    )

    # Explicit GDPR/privacy consent
    consent_given: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Customer explicitly agreed to contact info storage"
    )
    consent_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="The exact consent statement shown to the customer"
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | notified | contacted | resolved | closed",
    )
    notification_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notification_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="Error message if notification failed"
    )

    staff_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(  # noqa: F821
        "Conversation", back_populates="handoff_requests"
    )

    def __repr__(self) -> str:
        return f"<HandoffRequest id={self.id} status={self.status}>"
