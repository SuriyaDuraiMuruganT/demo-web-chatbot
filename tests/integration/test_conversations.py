"""
tests/integration/test_conversations.py — Conversation Session Lifecycle Tests
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.tenant import Tenant
from app.security.session import create_session_token


def test_create_conversation_tenant_not_found(client: TestClient, app):
    """POST /api/conversations with non-existent tenant slug returns 404."""
    # Mock DB returning None for tenant lookup
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/api/conversations",
        json={"tenant_slug": "non-existent-tenant-slug"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_create_conversation_success(client: TestClient, app, sample_tenant: Tenant):
    """POST /api/conversations creates conversation and returns session token."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_tenant
    mock_db.execute.return_value = mock_result
    mock_db.flush = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/api/conversations",
        json={"tenant_slug": "demo-company"},
    )
    assert response.status_code == 201

    data = response.json()
    assert "conversation_id" in data
    assert "session_token" in data
    assert data["assistant_name"] == "Demo Assistant"
    assert data["welcome_message"] == "Hello from Demo Company!"
    assert len(data["suggested_questions"]) > 0


def test_get_messages_requires_authorization(client: TestClient):
    """GET /api/conversations/{id}/messages without Authorization header returns 401."""
    conv_id = str(uuid.uuid4())
    response = client.get(f"/api/conversations/{conv_id}/messages")
    assert response.status_code == 401
    assert "token required" in response.json()["detail"].lower()


def test_get_messages_with_invalid_token_fails(client: TestClient):
    """GET /api/conversations/{id}/messages with forged or invalid token returns 401/403."""
    conv_id = str(uuid.uuid4())
    response = client.get(
        f"/api/conversations/{conv_id}/messages",
        headers={"Authorization": "Bearer invalid-token-forged"},
    )
    assert response.status_code in (401, 403)
