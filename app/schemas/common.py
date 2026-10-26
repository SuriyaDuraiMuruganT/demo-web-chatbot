"""
app/schemas/common.py — Shared Pydantic Schemas

Common response models used across multiple API endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str


class ReadinessResponse(BaseModel):
    status: str  # "ready" | "not_ready"
    timestamp: datetime
    checks: dict[str, bool]


class ErrorResponse(BaseModel):
    """Standard error response — never includes secrets or stack traces."""
    error: str
    detail: str | None = None
    request_id: str | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


class SuccessResponse(BaseModel):
    message: str
    data: dict[str, Any] | None = None
