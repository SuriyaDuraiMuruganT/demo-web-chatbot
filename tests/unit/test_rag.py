"""
tests/unit/test_rag.py — RAG Normalization, Confidence, and Fallback Unit Tests
"""
from app.services.rag_service import RAGService, RetrievedChunk


def test_question_normalization():
    """Verify customer question normalization removes control characters and extra spaces."""
    service = RAGService()

    raw_query = "  What   are   the \x00plans \x0bavailable?\r\n  "
    normalized = service._normalize_question(raw_query)

    assert "\x00" not in normalized
    assert "\x0b" not in normalized
    assert normalized == "What are the plans available?"


def test_confidence_computation():
    """Verify confidence score categories based on top similarity."""
    service = RAGService()

    # High confidence (>= 0.88)
    chunk_high = RetrievedChunk(
        chunk_id="c1", document_id="d1", title="FAQ", text="Text",
        similarity_score=0.92, chunk_index=0, source_url=None, metadata={}
    )
    assert service.compute_confidence([chunk_high]) == "high"

    # Medium confidence (>= 0.75)
    chunk_med = RetrievedChunk(
        chunk_id="c2", document_id="d1", title="FAQ", text="Text",
        similarity_score=0.78, chunk_index=1, source_url=None, metadata={}
    )
    assert service.compute_confidence([chunk_med]) == "medium"

    # Low confidence (< 0.75)
    chunk_low = RetrievedChunk(
        chunk_id="c3", document_id="d1", title="FAQ", text="Text",
        similarity_score=0.71, chunk_index=2, source_url=None, metadata={}
    )
    assert service.compute_confidence([chunk_low]) == "low"

    # None (empty list)
    assert service.compute_confidence([]) == "none"


def test_should_use_fallback():
    """Verify should_use_fallback accurately flags low similarity or missing chunks."""
    service = RAGService()

    # Empty list triggers fallback
    assert service.should_use_fallback([]) is True

    # High similarity does NOT trigger fallback
    good_chunk = RetrievedChunk(
        chunk_id="c1", document_id="d1", title="FAQ", text="Text",
        similarity_score=0.85, chunk_index=0, source_url=None, metadata={}
    )
    assert service.should_use_fallback([good_chunk]) is False

    # Low similarity below threshold triggers fallback
    poor_chunk = RetrievedChunk(
        chunk_id="c2", document_id="d1", title="FAQ", text="Text",
        similarity_score=0.62, chunk_index=0, source_url=None, metadata={}
    )
    assert service.should_use_fallback([poor_chunk]) is True
