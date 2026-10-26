"""
app/security/rate_limit.py — Rate Limiting Configuration

Uses slowapi (Starlette/FastAPI wrapper around limits library).
Limits are applied per-IP by default, but also per session token
for chat endpoints to prevent abuse from behind shared IPs.

Note: IP-based rate limiting alone is NOT sufficient protection.
Consider adding per-API-key limits and monitoring for production.
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings


def get_rate_limit_key(request: Request) -> str:
    """
    Rate limit key: prefer session token if present, fall back to IP.
    This prevents one abusive session from consuming all IP budget.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:50]  # First 43 chars of token (truncated)
        if token:
            return f"session:{token}"
    return f"ip:{get_remote_address(request)}"


# Global limiter instance — used as a FastAPI state object
limiter = Limiter(key_func=get_rate_limit_key)


def get_chat_rate_limit() -> str:
    """Return chat-specific rate limit string from settings."""
    settings = get_settings()
    return f"{settings.rate_limit_chat_per_minute}/minute"


def get_general_rate_limit() -> str:
    """Return general rate limit string from settings."""
    settings = get_settings()
    return f"{settings.rate_limit_per_minute}/minute"


def get_upload_rate_limit() -> str:
    """Return upload-specific rate limit string from settings."""
    settings = get_settings()
    return f"{settings.rate_limit_upload_per_minute}/minute"
