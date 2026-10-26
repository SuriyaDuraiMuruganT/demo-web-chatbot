"""
tests/conftest.py — Global Test Fixtures and Configurations

Provides:
- FastAPI TestClient / AsyncClient fixtures
- Mock Database Sessions and Repositories
- Mock EmbeddingService and LLMService (deterministic, no external API calls)
- Authenticated admin headers and signed user session tokens
- Sample tenant and document fixtures
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# Set testing environment before importing app
os.environ["APP_ENV"] = "testing"
os.environ["OPENAI_API_KEY"] = "sk-mock-test-key-for-automated-tests"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-chars-long-security-requirement"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"

from app.config import Settings, get_settings
from app.database import get_db
from app.main import create_app
from app.models.conversation import Conversation, Message
from app.models.knowledge import DocumentChunk, KnowledgeDocument
from app.models.tenant import Tenant
from app.security.session import create_session_token, hash_token
from app.services.analytics_service import AnalyticsService, get_analytics_service
from app.services.chat_service import ChatService, get_chat_service
from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.services.handoff_service import HandoffService, get_handoff_service
from app.services.ingestion_service import IngestionService, get_ingestion_service
from app.services.llm_service import LLMResponse, LLMService, get_llm_service
from app.services.rag_service import RAGService, RetrievedChunk, get_rag_service


# ─── Mock Services ─────────────────────────────────────────────────────────────

class MockEmbeddingService(EmbeddingService):
    """Deterministic mock embedding service returning 1536-dim dummy vectors."""

    def __init__(self) -> None:
        super().__init__()

    async def embed_text(self, text: str) -> list[float]:
        # Generate deterministic vector based on text length and char codes
        val = (len(text) % 100) / 100.0
        vec = [val] * 1536
        return vec

    async def embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]

    async def health_check(self) -> bool:
        return True


class MockLLMService(LLMService):
    """Deterministic mock LLM service returning grounded answers or fallbacks."""

    def __init__(self) -> None:
        super().__init__()

    async def generate_response(
        self,
        question: str,
        context_chunks: list[dict],
        conversation_history: list[dict],
        company_name: str = "Demo Company",
        assistant_name: str = "Support Assistant",
        use_fallback: bool = False,
    ) -> LLMResponse:
        if use_fallback or not context_chunks:
            from app.services.llm_service import FALLBACK_MESSAGE
            return LLMResponse(
                content=FALLBACK_MESSAGE,
                prompt_tokens=25,
                completion_tokens=35,
                model="mock-gpt-4o-mini",
                latency_ms=12,
                is_fallback=True,
            )

        # Build grounded response referencing the top chunk title
        top_title = context_chunks[0].get("title", "company documentation")
        content = (
            f"Based on our {top_title}, we offer flexible options. "
            f"Regarding '{question}': our documentation confirms full support."
        )

        return LLMResponse(
            content=content,
            prompt_tokens=120,
            completion_tokens=45,
            model="mock-gpt-4o-mini",
            latency_ms=18,
            is_fallback=False,
        )

    async def health_check(self) -> bool:
        return True


# ─── Pytest Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_embedding_service() -> EmbeddingService:
    return MockEmbeddingService()


@pytest.fixture
def mock_llm_service() -> LLMService:
    return MockLLMService()


@pytest.fixture
def test_tenant_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def other_tenant_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def test_conversation_id() -> uuid.UUID:
    return uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def sample_tenant(test_tenant_id: uuid.UUID) -> Tenant:
    return Tenant(
        id=test_tenant_id,
        name="Demo Company",
        slug="demo-company",
        description="Demo SaaS provider",
        config={
            "company_name": "Demo Company",
            "assistant_name": "Demo Assistant",
            "welcome_message": "Hello from Demo Company!",
            "suggested_questions": ["What plans do you offer?"],
        },
        is_active=True,
    )


@pytest.fixture
def sample_session_token(test_tenant_id: uuid.UUID, test_conversation_id: uuid.UUID) -> str:
    return create_session_token(
        tenant_id=str(test_tenant_id),
        conversation_id=str(test_conversation_id),
    )


@pytest.fixture
def admin_auth_header() -> dict[str, str]:
    import base64
    creds = base64.b64encode(b"admin:test-admin-password").decode("utf-8")
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def app(mock_embedding_service: EmbeddingService, mock_llm_service: LLMService):
    """Create test application with dependency overrides."""
    application = create_app()

    # Override AI services
    application.dependency_overrides[get_embedding_service] = lambda: mock_embedding_service
    application.dependency_overrides[get_llm_service] = lambda: mock_llm_service

    yield application

    application.dependency_overrides.clear()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
async def async_client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac
