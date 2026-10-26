"""
app/services/analytics_service.py — Analytics and Metrics Service

Records operational events for monitoring. Sensitive personal data
is never stored here — only aggregate operational metrics.
"""
from __future__ import annotations

import logging
import uuid
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import AnalyticsEvent

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Records and queries operational analytics events."""

    async def record_event(
        self,
        event_type: str,
        payload: dict,
        db: AsyncSession,
        tenant_id: uuid.UUID | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        """
        Record an operational event. Fails silently to avoid disrupting chat.

        Never stores: API keys, tokens, full question text, or email addresses.
        """
        try:
            event = AnalyticsEvent(
                tenant_id=tenant_id,
                event_type=event_type,
                payload=payload,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            db.add(event)
            await db.flush()
        except Exception as e:
            # Analytics failure must never break the chat flow
            logger.warning("Analytics recording failed: %s", type(e).__name__)

    async def get_summary(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        days: int = 30,
    ) -> dict:
        """
        Get aggregate analytics summary for a tenant.

        Returns aggregate counts, rates, and averages.
        No individual request details or PII.
        """
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import and_, func, select

        since = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(
                AnalyticsEvent.event_type,
                func.count(AnalyticsEvent.id).label("count"),
                func.avg(AnalyticsEvent.latency_ms).label("avg_latency"),
                func.sum(AnalyticsEvent.prompt_tokens).label("total_prompt_tokens"),
                func.sum(AnalyticsEvent.completion_tokens).label("total_completion_tokens"),
            )
            .where(
                and_(
                    AnalyticsEvent.tenant_id == tenant_id,
                    AnalyticsEvent.created_at >= since,
                )
            )
            .group_by(AnalyticsEvent.event_type)
        )

        result = await db.execute(stmt)
        rows = result.all()

        summary: dict = {
            "period_days": days,
            "total_questions": 0,
            "fallback_rate": 0.0,
            "avg_latency_ms": None,
            "handoffs_created": 0,
            "errors": 0,
            "top_event_types": [],
        }

        total_latency_sum = 0.0
        total_latency_count = 0
        chat_total = 0
        fallback_count = 0

        for row in rows:
            event_type, count, avg_latency, prompt_tokens, completion_tokens = row
            summary["top_event_types"].append({
                "type": event_type,
                "count": count,
                "avg_latency_ms": round(float(avg_latency), 1) if avg_latency else None,
            })

            if event_type in ("chat_request", "chat_fallback"):
                chat_total += count
                summary["total_questions"] += count
                if avg_latency:
                    total_latency_sum += float(avg_latency) * count
                    total_latency_count += count

            if event_type == "chat_fallback":
                fallback_count += count

            if event_type == "handoff_created":
                summary["handoffs_created"] = count

            if event_type == "chat_error":
                summary["errors"] = count

        if chat_total > 0:
            summary["fallback_rate"] = round(fallback_count / chat_total, 3)

        if total_latency_count > 0:
            summary["avg_latency_ms"] = round(total_latency_sum / total_latency_count, 1)

        return summary


@lru_cache(maxsize=1)
def get_analytics_service() -> AnalyticsService:
    return AnalyticsService()
