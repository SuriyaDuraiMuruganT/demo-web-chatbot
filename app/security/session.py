"""
app/security/session.py — Session Token Management

Provides signed JWT session tokens for anonymous chat sessions.
Tokens are short-lived and scoped to a specific tenant.

IMPORTANT: Session tokens are NOT the same as authentication tokens.
They provide anonymous conversation continuity only, not admin access.
Authorization for admin operations uses a separate mechanism.

Security notes:
- Only the hash of the token is stored in the database
- Tokens expire after SESSION_EXPIRE_MINUTES
- Tokens include tenant_id to prevent cross-tenant use
- Conversation UUID alone is NOT sufficient for access — token required
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.config import get_settings


def create_session_token(tenant_id: str, conversation_id: str) -> str:
    """
    Create a signed JWT session token for an anonymous chat session.

    The token encodes:
    - sub: conversation_id
    - tid: tenant_id (prevents cross-tenant use)
    - exp: expiry timestamp
    - jti: unique token ID (for future revocation support)

    Returns the encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.session_expire_minutes)

    payload = {
        "sub": str(conversation_id),
        "tid": str(tenant_id),
        "exp": expire,
        "iat": now,
        "jti": secrets.token_urlsafe(16),  # Unique token ID
    }

    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.session_algorithm,
    )


def verify_session_token(token: str) -> dict:
    """
    Verify and decode a session token.

    Returns the decoded payload dict on success.
    Raises ValueError with a safe message on failure.
    Never leaks the specific validation error to callers.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.session_algorithm],
        )
        conversation_id = payload.get("sub")
        tenant_id = payload.get("tid")

        if not conversation_id or not tenant_id:
            raise ValueError("Invalid session token")

        return payload

    except JWTError:
        raise ValueError("Invalid or expired session token")


def decode_session_token(token: str) -> dict | None:
    """
    Decode and verify a session token.
    Returns payload dict on success, None if invalid or expired.
    """
    try:
        return verify_session_token(token)
    except ValueError:
        return None


def hash_token(token: str) -> str:
    """
    Compute SHA-256 hash of a token for safe database storage.
    Only the hash is stored — the original token is never persisted.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def hash_user_agent(user_agent: str | None) -> str | None:
    """Hash user agent for anonymous analytics (no PII stored)."""
    if not user_agent:
        return None
    return hashlib.sha256(user_agent.encode()).hexdigest()[:16]


def verify_conversation_access(
    token: str, conversation_id: str, tenant_id: str
) -> bool:
    """
    Verify that a session token authorizes access to a specific conversation
    for a specific tenant.

    Returns True if authorized, False otherwise.
    Never raises — returns False for any invalid input.
    """
    try:
        payload = verify_session_token(token)
        token_conv_id = payload.get("sub", "")
        token_tenant_id = payload.get("tid", "")

        return (
            token_conv_id == str(conversation_id)
            and token_tenant_id == str(tenant_id)
        )
    except (ValueError, Exception):
        return False
