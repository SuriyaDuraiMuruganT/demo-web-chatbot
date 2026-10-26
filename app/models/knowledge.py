"""
app/models/knowledge.py — Knowledge Document and Chunk Models

KnowledgeDocument tracks uploaded company documents.
DocumentChunk stores the actual text segments with pgvector embeddings
used for semantic similarity search during RAG retrieval.

Document approval workflow:
  pending → approved (available for retrieval)
          → rejected (not searchable)
  approved → archived (hidden but kept)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class KnowledgeDocument(Base):
    """
    Tracks an uploaded knowledge document for a specific tenant.
    Only 'approved' documents are returned in RAG retrieval.
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="txt | md | pdf"
    )
    file_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 of file content"
    )
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Approval workflow
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | approved | rejected | archived",
    )
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Extracted text (stored for re-ingestion without re-upload)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} title={self.title!r} status={self.status}>"


class DynamicVector(sa.types.TypeDecorator):
    """
    Adapts seamlessly to Vector(1536) when pgvector is present,
    or FLOAT[] when running on standard PostgreSQL.
    """
    impl = Vector(1536)
    cache_ok = True

    @property
    def comparator_factory(self):
        return Vector.comparator_factory

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if hasattr(value, "tolist"):
            return value.tolist()
        if isinstance(value, str):
            clean = value.strip("[]")
            if not clean:
                return []
            return [float(x) for x in clean.split(",")]
        return list(value)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return list(value)


class DocumentChunk(Base):
    """
    A text segment from a KnowledgeDocument with its pgvector embedding.
    These are the units retrieved during RAG similarity search.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_tenant_status", "tenant_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Position in document (0-based)"
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Embedding vector — Vector(1536) if pgvector installed, FLOAT[] if standard Postgres
    embedding: Mapped[list[float]] = mapped_column(
        DynamicVector, nullable=True, comment="Embedding vector from embedding model"
    )

    # Metadata for source attribution
    metadata_: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        name="metadata",
        comment="page_number, section, char_start, char_end",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    document: Mapped["KnowledgeDocument"] = relationship(
        "KnowledgeDocument", back_populates="chunks"
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} doc={self.document_id} idx={self.chunk_index}>"
        )
