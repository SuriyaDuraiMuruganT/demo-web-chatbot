"""
app/api/routes/health.py — Health and Readiness Endpoints

GET /health — Basic liveness check. Returns 200 if the app is running.
GET /ready  — Readiness check. Returns 200 only if DB + pgvector are accessible.

These are used by Docker health checks, load balancers, and monitoring tools.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import check_db_connection, check_pgvector
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
async def health() -> HealthResponse:
    """
    Basic liveness check.
    Returns 200 if the application is running.
    Does NOT check external dependencies.
    """
    settings = get_settings()
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
        version=settings.app_version,
    )


@router.get("/ready", summary="Readiness check")
async def readiness() -> JSONResponse:
    """
    Readiness check for load balancers and orchestrators.
    Returns 200 only when all critical dependencies are healthy.

    Checks:
    - Database connection
    - pgvector extension
    """
    db_ok = await check_db_connection()
    pgvector_ok = await check_pgvector()

    checks = {
        "database": db_ok,
        "pgvector": pgvector_ok,
    }

    all_ok = all(checks.values())
    status_code = 200 if all_ok else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "not_ready",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        },
    )
