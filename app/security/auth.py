"""
app/security/auth.py — Admin Authentication

Provides HTTP Basic Auth for admin endpoints.
In production, replace or augment with JWT-based auth or OAuth2.

Admin credentials are read from environment variables only.
Passwords are never logged or exposed in error responses.
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import Settings, get_settings

security = HTTPBasic()


def _safe_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(
        hashlib.sha256(a.encode()).digest(),
        hashlib.sha256(b.encode()).digest(),
    )


def require_admin(
    credentials: HTTPBasicCredentials = Depends(security),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    FastAPI dependency that enforces admin HTTP Basic Auth.

    Returns the admin username on success.
    Raises 401 on invalid credentials.

    Usage:
        @router.get("/admin/endpoint")
        async def admin_endpoint(admin: str = Depends(require_admin)):
            ...
    """
    username_ok = _safe_compare(credentials.username, settings.admin_username)
    password_ok = _safe_compare(credentials.password, settings.admin_password)

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


def get_session_token_from_header(authorization: str | None) -> str | None:
    """
    Extract Bearer session token from Authorization header.
    Returns None if header is missing or malformed.
    """
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
