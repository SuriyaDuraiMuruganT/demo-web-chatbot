"""
app/models/__init__.py — Export all models for Alembic discovery.
"""
from app.models.analytics import AnalyticsEvent
from app.models.conversation import Conversation, Message
from app.models.handoff import HandoffRequest, WebsiteEnquiry
from app.models.knowledge import DocumentChunk, KnowledgeDocument
from app.models.tenant import Tenant

__all__ = [
    "Tenant",
    "KnowledgeDocument",
    "DocumentChunk",
    "Conversation",
    "Message",
    "HandoffRequest",
    "WebsiteEnquiry",
    "AnalyticsEvent",
]
