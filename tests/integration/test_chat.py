"""
tests/integration/test_chat.py — Chat Endpoint and Grounding Tests
"""
import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.schemas.chat import ChatResponse, TokenUsage
from app.schemas.conversation import SourceReference
from app.services.chat_service import ChatError, ChatService, get_chat_service


def test_chat_requires_auth_header(client: TestClient):
    """POST /api/chat without Authorization header returns 401."""
    conv_id = str(uuid.uuid4())
    response = client.post(
        "/api/chat",
        json={"conversation_id": conv_id, "question": "What plans do you have?"},
    )
    assert response.status_code == 401
    assert "token required" in response.json()["detail"].lower()


def test_chat_successful_grounded_response(client: TestClient, app, sample_session_token: str):
    """POST /api/chat returns grounded response with sources and confidence."""
    conv_id = uuid.uuid4()
    mock_chat_service = AsyncMock(spec=ChatService)

    mock_chat_service.process_question.return_value = ChatResponse(
        message_id=uuid.uuid4(),
        answer="Based on our FAQ, we offer Starter, Growth, and Enterprise tiers.",
        sources=[
            SourceReference(
                title="Demo FAQ",
                chunk_id="chunk-1",
                similarity_score=0.91,
                source_url="https://example.com/faq",
                section="Services and Plans",
            )
        ],
        is_fallback=False,
        confidence="high",
        suggested_followups=["Can I try before I buy?"],
        token_usage=TokenUsage(prompt_tokens=150, completion_tokens=30, total_tokens=180),
        response_time_ms=45,
    )

    app.dependency_overrides[get_chat_service] = lambda: mock_chat_service

    response = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {sample_session_token}"},
        json={"conversation_id": str(conv_id), "question": "What plans do you offer?"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "Starter, Growth, and Enterprise" in data["answer"]
    assert data["is_fallback"] is False
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Demo FAQ"
    assert data["confidence"] == "high"


def test_chat_handles_service_error_cleanly(client: TestClient, app, sample_session_token: str):
    """POST /api/chat gracefully maps ChatError to appropriate HTTP status."""
    conv_id = uuid.uuid4()
    mock_chat_service = AsyncMock(spec=ChatService)
    mock_chat_service.process_question.side_effect = ChatError(
        "Retrieval service temporarily unavailable", status_code=503
    )

    app.dependency_overrides[get_chat_service] = lambda: mock_chat_service

    response = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {sample_session_token}"},
        json={"conversation_id": str(conv_id), "question": "Are you online?"},
    )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
