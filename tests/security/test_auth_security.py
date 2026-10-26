"""
tests/security/test_auth_security.py — Authentication and Session Security Tests
"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import get_settings
from app.security.auth import get_session_token_from_header
from app.security.session import decode_session_token


def test_bearer_header_extraction():
    """Verify get_session_token_from_header handles valid and malformed headers."""
    assert get_session_token_from_header("Bearer test-token-123") == "test-token-123"
    assert get_session_token_from_header("bearer lowercase-token") == "lowercase-token"
    assert get_session_token_from_header("Basic dXNlcjpwYXNz") is None
    assert get_session_token_from_header("InvalidFormat") is None
    assert get_session_token_from_header(None) is None


def test_expired_session_token_rejected():
    """Verify session tokens past their expiration are rejected."""
    settings = get_settings()
    tenant_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())

    # Create token expired 10 minutes ago
    expired_payload = {
        "tid": tenant_id,
        "sub": conv_id,
        "exp": int(time.time()) - 600,
        "iat": int(time.time()) - 1200,
    }
    expired_token = jwt.encode(
        expired_payload, settings.secret_key, algorithm=settings.session_algorithm
    )

    decoded = decode_session_token(expired_token)
    assert decoded is None  # decode_session_token catches ExpiredSignatureError


def test_conversation_uuid_alone_insufficient(client: TestClient):
    """Verify passing a valid UUID without Bearer token cannot query messages or chat."""
    conv_id = str(uuid.uuid4())

    # Chat endpoint
    resp_chat = client.post("/api/chat", json={"conversation_id": conv_id, "question": "Hi"})
    assert resp_chat.status_code == 401

    # Messages endpoint
    resp_msg = client.get(f"/api/conversations/{conv_id}/messages")
    assert resp_msg.status_code == 401

    # Handoff endpoint
    resp_handoff = client.post(
        f"/api/conversations/{conv_id}/handoff",
        json={
            "conversation_id": conv_id,
            "issue_summary": "Need urgent technical assistance",
            "consent_given": True,
            "consent_text": "I agree to provide details",
        },
    )
    assert resp_handoff.status_code == 401
