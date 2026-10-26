"""
tests/unit/test_session.py — Session Token and Authorization Tests
"""
import time
import uuid

import pytest
from jose import jwt

from app.config import get_settings
from app.security.session import (
    create_session_token,
    decode_session_token,
    hash_token,
    hash_user_agent,
    verify_conversation_access,
)


def test_token_creation_and_decoding():
    """Verify session token is properly signed and decodable."""
    tenant_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())

    token = create_session_token(tenant_id=tenant_id, conversation_id=conv_id)
    assert isinstance(token, str)

    payload = decode_session_token(token)
    assert payload is not None
    assert payload["tid"] == tenant_id
    assert payload["sub"] == conv_id
    assert payload["exp"] > time.time()


def test_token_tampering_fails():
    """Verify modifying token payload or signature fails validation."""
    tenant_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())

    token = create_session_token(tenant_id=tenant_id, conversation_id=conv_id)
    tampered_token = token[:-5] + "XXXXX"

    assert decode_session_token(tampered_token) is None
    assert verify_conversation_access(tampered_token, conv_id, tenant_id) is False


def test_conversation_access_verification():
    """Verify token grants access ONLY to authorized conversation and tenant."""
    tenant1 = str(uuid.uuid4())
    tenant2 = str(uuid.uuid4())
    conv1 = str(uuid.uuid4())
    conv2 = str(uuid.uuid4())

    token1 = create_session_token(tenant_id=tenant1, conversation_id=conv1)

    # Valid check
    assert verify_conversation_access(token1, conv1, tenant1) is True

    # Wrong conversation ID
    assert verify_conversation_access(token1, conv2, tenant1) is False

    # Wrong tenant ID
    assert verify_conversation_access(token1, conv1, tenant2) is False

    # Both wrong
    assert verify_conversation_access(token1, conv2, tenant2) is False


def test_token_hash_deterministic():
    """Verify hash_token produces consistent SHA-256 hex digest."""
    token = "some-sample-session-token"
    h1 = hash_token(token)
    h2 = hash_token(token)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256


def test_user_agent_hashing():
    """Verify user agent strings are hashed securely."""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    h = hash_user_agent(ua)
    assert h is not None
    assert len(h) == 16
    assert hash_user_agent(None) is None
