"""
app/api/routes/analytics.py — Analytics Endpoint (Admin Only)

GET /admin/analytics/{tenant_slug} — Aggregate metrics summary
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.knowledge import AnalyticsSummaryResponse
from app.security.auth import require_admin
from app.services.analytics_service import AnalyticsService, get_analytics_service

router = APIRouter(prefix="/admin", tags=["Analytics"])


@router.get(
    "/analytics/{tenant_slug}",
    response_model=AnalyticsSummaryResponse,
    summary="Get aggregate analytics for a tenant",
)
async def get_analytics(
    tenant_slug: str,
    days: int = 30,
    admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsSummaryResponse:
    """
    Get aggregate operational metrics for a tenant.

    Returns counts, rates, and averages — no individual request details or PII.
    """
    if days < 1 or days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="days must be between 1 and 365",
        )

    result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' not found",
        )

    summary = await analytics_service.get_summary(
        tenant_id=tenant.id,
        db=db,
        days=days,
    )

    return AnalyticsSummaryResponse(
        tenant_slug=tenant_slug,
        period_days=days,
        total_questions=summary["total_questions"],
        fallback_rate=summary["fallback_rate"],
        avg_latency_ms=summary["avg_latency_ms"],
        handoffs_created=summary["handoffs_created"],
        errors=summary["errors"],
        top_event_types=summary["top_event_types"],
    )
