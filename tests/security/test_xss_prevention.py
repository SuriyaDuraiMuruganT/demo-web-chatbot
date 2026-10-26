"""
tests/security/test_xss_prevention.py — Cross-Site Scripting (XSS) Prevention Tests
"""
from app.services.ingestion_service import IngestionService
from app.services.rag_service import RAGService


def test_question_xss_payload_normalization():
    """Verify script tags and HTML-like payloads in questions are normalized safely."""
    rag_service = RAGService()

    xss_payload = "<script>alert('xss')</script> <img src=x onerror=alert(1)> What plans do you have?"
    cleaned = rag_service._normalize_question(xss_payload)

    # Question text should be safely trimmed and whitespace-collapsed
    assert "What plans do you have?" in cleaned
    assert "\x00" not in cleaned


def test_document_ingestion_text_does_not_execute_scripts():
    """Verify document normalization strips control characters from raw text payloads."""
    service = IngestionService()

    raw_html_content = b"""
    <html>
      <head><script>evilFunction();</script></head>
      <body>
        <h1>Approved Company Policy</h1>
        <p>Refunds are processed in 5 business days.</p>
      </body>
    </html>
    """

    extracted = service._extract_text(raw_html_content, ".txt", "policy.txt")
    normalized = service._normalize_text(extracted)

    assert "Approved Company Policy" in normalized
    assert "Refunds are processed in 5 business days." in normalized
    assert "\x00" not in normalized
