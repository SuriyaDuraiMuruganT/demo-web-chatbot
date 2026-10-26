"""
tests/unit/test_rate_limit.py — Rate Limiting Logic Tests
"""
from unittest.mock import MagicMock
from fastapi import Request

from app.security.rate_limit import (
    get_chat_rate_limit,
    get_general_rate_limit,
    get_rate_limit_key,
    get_upload_rate_limit,
)


def test_rate_limit_key_with_bearer_token():
    """Verify session token takes priority in rate limiting key."""
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer sample-jwt-token-xyz-1234567890"}
    request.client.host = "192.168.1.10"

    key = get_rate_limit_key(request)
    assert key.startswith("session:sample-jwt-token-xyz")


def test_rate_limit_key_fallback_to_ip():
    """Verify rate limit key falls back to remote IP when no Bearer header is present."""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.client.host = "10.0.0.42"

    key = get_rate_limit_key(request)
    assert "ip:" in key


def test_rate_limit_string_generators():
    """Verify rate limit strings format properly from config settings."""
    chat_limit = get_chat_rate_limit()
    assert "/minute" in chat_limit

    gen_limit = get_general_rate_limit()
    assert "/minute" in gen_limit

    upload_limit = get_upload_rate_limit()
    assert "/minute" in upload_limit
