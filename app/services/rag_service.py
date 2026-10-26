"""
app/services/rag_service.py — Retrieval-Augmented Generation Pipeline

This is the core retrieval module. For every customer question:
1. Normalize and validate the question
2. Generate a question embedding
3. Query pgvector for the most similar chunks from the correct tenant
4. Filter by similarity threshold (configurable)
5. Return ranked chunks with source metadata

Design principles:
- Tenant isolation is ENFORCED at query level — always filter by tenant_id
- Only APPROVED documents are retrieved
- Cosine similarity is used (1 = identical, 0 = orthogonal, -1 = opposite)
- Threshold tuning: start at 0.70, adjust based on evaluation
- A returned chunk is supporting context, not a guaranteed correct answer
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.knowledge import DocumentChunk, KnowledgeDocument
from app.services.embedding_service import EmbeddingService, get_embedding_service

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A document chunk retrieved by semantic similarity search."""

    chunk_id: str
    document_id: str
    title: str
    text: str
    similarity_score: float
    chunk_index: int
    source_url: str | None
    metadata: dict
    section: str | None = None


class RAGService:
    """
    Retrieval-Augmented Generation pipeline.

    Retrieves the most relevant approved knowledge chunks for a question,
    always scoped to the correct tenant. Returns structured chunks with
    source metadata for answer generation and citation.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._embedding_service = embedding_service or get_embedding_service()
        self._settings = get_settings()

    def _normalize_question(self, question: str) -> str:
        """
        Normalize a customer question for embedding.

        - Strip whitespace
        - Collapse internal spaces
        - Remove null bytes and control characters (injection mitigation)
        - Truncate to safe length
        """
        # Remove null bytes and control chars (keep newlines for readability)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", question)
        # Collapse whitespace
        cleaned = " ".join(cleaned.split())
        # Truncate
        max_len = self._settings.max_question_length
        return cleaned[:max_len]

    async def retrieve(
        self,
        question: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """
        Retrieve the most relevant knowledge chunks for a question.

        SECURITY: tenant_id is always enforced. Only approved documents
        are returned. These cannot be bypassed by the question content.

        Args:
            question: Raw customer question (will be normalized internally)
            tenant_id: The authenticated tenant's ID
            db: Async database session
            top_k: Max chunks to retrieve (default from config)
            similarity_threshold: Min similarity score (default from config)

        Returns:
            List of RetrievedChunk, ordered by similarity descending.
            Returns empty list if no relevant context found.
        """
        settings = self._settings
        top_k = top_k or settings.rag_top_k
        threshold = similarity_threshold or settings.rag_similarity_threshold

        # 1. Normalize question
        normalized = self._normalize_question(question)
        if not normalized:
            logger.warning("RAG: empty question after normalization")
            return []

        logger.debug("RAG: retrieving for tenant=%s top_k=%d threshold=%.2f",
                     tenant_id, top_k, threshold)

        # 2. Embed the question
        try:
            query_embedding = await self._embedding_service.embed_text(normalized)
        except RuntimeError as e:
            logger.error("RAG: embedding failed: %s", e)
            raise

        # 3. pgvector cosine similarity search
        # The <=> operator computes cosine distance (0 = identical, 2 = opposite)
        # We convert to similarity: similarity = 1 - (distance / 2) in range [0,1]
        # Only retrieves chunks from:
        #   a) The correct tenant (tenant_id filter)
        #   b) Approved documents (status = 'approved')

        embedding_vector = query_embedding  # list[float]

        # Check if native pgvector is available
        has_pgvector = False
        try:
            ext_check = await db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
            has_pgvector = (ext_check.scalar() == "vector")
        except Exception:
            has_pgvector = False

        if has_pgvector:
            stmt = (
                select(
                    DocumentChunk,
                    KnowledgeDocument.title,
                    KnowledgeDocument.source_url,
                    # Cosine similarity: 1 - cosine_distance (pgvector uses <=> for cosine distance)
                    (1 - DocumentChunk.embedding.cosine_distance(embedding_vector)).label(
                        "similarity"
                    ),
                )
                .join(
                    KnowledgeDocument,
                    DocumentChunk.document_id == KnowledgeDocument.id,
                )
                .where(
                    and_(
                        # CRITICAL: tenant isolation — always enforced
                        DocumentChunk.tenant_id == tenant_id,
                        KnowledgeDocument.tenant_id == tenant_id,
                        # CRITICAL: only approved documents
                        KnowledgeDocument.status == "approved",
                    )
                )
                .order_by(
                    DocumentChunk.embedding.cosine_distance(embedding_vector)
                )
                .limit(top_k * 2)  # Fetch extra to filter by threshold
            )
            result = await db.execute(stmt)
            rows = result.all()
        else:
            stmt = (
                select(
                    DocumentChunk,
                    KnowledgeDocument.title,
                    KnowledgeDocument.source_url,
                )
                .join(
                    KnowledgeDocument,
                    DocumentChunk.document_id == KnowledgeDocument.id,
                )
                .where(
                    and_(
                        DocumentChunk.tenant_id == tenant_id,
                        KnowledgeDocument.tenant_id == tenant_id,
                        KnowledgeDocument.status == "approved",
                    )
                )
            )
            result = await db.execute(stmt)
            candidates = result.all()

            import numpy as np
            q_vec = np.array(embedding_vector, dtype=np.float32)
            q_norm = float(np.linalg.norm(q_vec))

            scored = []
            for chunk, title, source_url in candidates:
                if chunk.embedding is not None and q_norm > 0:
                    c_vec = np.array(chunk.embedding, dtype=np.float32)
                    c_norm = float(np.linalg.norm(c_vec))
                    sim = float(np.dot(q_vec, c_vec) / (q_norm * c_norm)) if c_norm > 0 else 0.0
                else:
                    sim = 0.0
                scored.append((chunk, title, source_url, sim))

            scored.sort(key=lambda x: x[3], reverse=True)
            rows = scored[:top_k * 2]

        # 4. Apply similarity threshold and limit to top_k
        chunks: list[RetrievedChunk] = []
        for chunk, title, source_url, similarity in rows:
            if similarity < threshold:
                continue
            if len(chunks) >= top_k:
                break

            meta = chunk.metadata_ or {}
            chunks.append(
                RetrievedChunk(
                    chunk_id=str(chunk.id),
                    document_id=str(chunk.document_id),
                    title=title,
                    text=chunk.chunk_text,
                    similarity_score=round(float(similarity), 4),
                    chunk_index=chunk.chunk_index,
                    source_url=source_url,
                    metadata=meta,
                    section=meta.get("section"),
                )
            )

        logger.info(
            "RAG: retrieved %d chunks (threshold=%.2f, tenant=%s)",
            len(chunks),
            threshold,
            tenant_id,
        )

        return chunks

    def compute_confidence(self, chunks: list[RetrievedChunk]) -> str:
        """
        Compute an overall confidence level based on retrieved chunks.

        Returns "high" | "medium" | "low" | "none"

        This is advisory only — the LLM grounding is the primary safety mechanism.
        """
        if not chunks:
            return "none"

        top_score = chunks[0].similarity_score
        if top_score >= 0.88:
            return "high"
        elif top_score >= 0.75:
            return "medium"
        else:
            return "low"

    def should_use_fallback(self, chunks: list[RetrievedChunk]) -> bool:
        """
        Determine if a fallback response should be used instead of LLM generation.

        Returns True when:
        - No chunks were retrieved
        - All chunks are below the threshold (already filtered above, so empty list)
        - Confidence is too low to trust a generated answer

        Note: The threshold in retrieve() already filters low-quality chunks.
        This provides an additional check on the result set.
        """
        if not chunks:
            return True
        # Even if chunks pass threshold, if top score is very low, use fallback
        return chunks[0].similarity_score < self._settings.rag_similarity_threshold


def get_rag_service() -> RAGService:
    """Return RAGService instance. Use as FastAPI dependency."""
    return RAGService()
