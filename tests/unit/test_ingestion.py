"""
tests/unit/test_ingestion.py — Document Ingestion and Chunking Tests
"""
import uuid
import pytest

from app.services.ingestion_service import IngestionService


def test_extension_validation():
    """Verify supported and unsupported extensions."""
    service = IngestionService()

    assert service._get_extension("faq.md") == ".md"
    assert service._get_extension("handbook.TXT") == ".txt"
    assert service._get_extension("specs.pdf") == ".pdf"
    assert service._get_extension("exploit.exe") == ".exe"
    assert service._get_extension("no_extension") == ""


def test_text_normalization():
    """Verify normalization strips null bytes and collapses excessive blank lines."""
    service = IngestionService()

    raw_text = "Line 1\x00with null\r\n\r\n\r\n\r\nLine 2 with trailing spaces   "
    normalized = service._normalize_text(raw_text)

    assert "\x00" not in normalized
    assert "\r\n" not in normalized
    assert "\n\n\n" not in normalized
    assert "Line 1with null\n\nLine 2 with trailing spaces" == normalized


def test_text_chunking_overlap():
    """Verify sentence-aware splitting preserves context overlap across boundaries."""
    service = IngestionService()

    long_text = (
        "This is sentence one. "
        "Here is sentence two with important information about services. "
        "Sentence three covers pricing tiers and plan details. "
        "Sentence four discusses technical support and response SLAs. "
        "And sentence five concludes the document."
    )

    chunks = service._split_text(long_text, chunk_size=80, overlap=20)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert "text" in chunk
        assert "char_start" in chunk
        assert "char_end" in chunk
        assert len(chunk["text"]) > 0

    # Verify overlap exists between consecutive chunks
    assert chunks[1]["char_start"] < chunks[0]["char_end"]


@pytest.mark.asyncio
async def test_disallowed_file_type_rejected():
    """Verify ingest_document rejects unauthorized file extensions."""
    service = IngestionService()
    db_mock = None
    tenant_id = uuid.uuid4()

    with pytest.raises(ValueError, match="File type '.exe' is not allowed"):
        await service.ingest_document(
            file_content=b"malicious payload",
            file_name="virus.exe",
            title="Dangerous",
            tenant_id=tenant_id,
            db=db_mock,
        )


@pytest.mark.asyncio
async def test_oversized_file_rejected():
    """Verify files exceeding max upload size are rejected."""
    service = IngestionService()
    db_mock = None
    tenant_id = uuid.uuid4()

    huge_content = b"A" * (11 * 1024 * 1024)  # 11MB exceeds default 10MB limit

    with pytest.raises(ValueError, match="exceeds limit"):
        await service.ingest_document(
            file_content=huge_content,
            file_name="large.txt",
            title="Too Big",
            tenant_id=tenant_id,
            db=db_mock,
        )
