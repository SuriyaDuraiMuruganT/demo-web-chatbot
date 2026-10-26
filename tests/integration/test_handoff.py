"""
tests/integration/test_handoff.py — Human Escalation Handoff Endpoint Tests
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.conversation import Conversation
from app.schemas.handoff import HandoffResponse
from app.security.session import create_session_token
from app.services.handoff_service import HandoffService, get_handoff_service


def test_handoff_requires_explicit_consent(client: TestClient):
    """POST handoff without explicit consent fails schema validation."""
    conv_id = str(uuid.uuid4())
    response = client.post(
        f"/api/conversations/{conv_id}/handoff",
        headers={"Authorization": "Bearer some-token"},
        json={
            "conversation_id": conv_id,
            "issue_summary": "Need help with billing invoice",
            "consent_given": False,  # No consent
            "consent_text": "I agree to provide details",
        },
    )
    # Pydantic schema validation or auth failure
    assert response.status_code in (400, 422)


def test_handoff_mismatched_conversation_id_rejected(client: TestClient, app):
    """POST handoff with mismatched conversation_id between URL and body is rejected."""
    url_conv_id = uuid.uuid4()
    body_conv_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_conv = MagicMock(spec=Conversation)
    mock_conv.id = url_conv_id
    mock_conv.tenant_id = tenant_id

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_conv
    mock_db.execute.return_value = mock_res
    app.dependency_overrides[get_db] = lambda: mock_db

    token = create_session_token(tenant_id=str(tenant_id), conversation_id=str(url_conv_id))

    response = client.post(
        f"/api/conversations/{url_conv_id}/handoff",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": str(body_conv_id),  # Mismatch
            "issue_summary": "Issue summary details",
            "consent_given": True,
            "consent_text": "I agree",
        },
    )
    assert response.status_code == 400
    assert "must match URL" in response.json()["detail"]


def test_handoff_successful_creation(client: TestClient, app):
    """POST handoff with consent creates record and returns honest notification status."""
    conv_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    handoff_id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_conv = MagicMock(spec=Conversation)
    mock_conv.id = conv_id
    mock_conv.tenant_id = tenant_id

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_conv
    mock_db.execute.return_value = mock_res
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_handoff_svc = AsyncMock(spec=HandoffService)
    mock_handoff_svc.create_handoff.return_value = HandoffResponse(
        handoff_id=handoff_id,
        status="pending",
        message="Your support request has been recorded. Our team will review it shortly.",
        notification_sent=False,
    )
    app.dependency_overrides[get_handoff_service] = lambda: mock_handoff_svc

    token = create_session_token(tenant_id=str(tenant_id), conversation_id=str(conv_id))

    response = client.post(
        f"/api/conversations/{conv_id}/handoff",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": str(conv_id),
            "customer_name": "Jane Doe",
            "customer_email": "jane@example.com",
            "issue_summary": "Need help setting up custom domain",
            "consent_given": True,
            "consent_text": "I agree to share contact info",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["notification_sent"] is False  # Never claims sent when not configured
    assert "recorded" in data["message"].lower()


def test_website_enquiry_submission(client: TestClient, app):
    """POST /api/enquiries accepts valid website leads and sends notifications."""
    mock_handoff_svc = AsyncMock(spec=HandoffService)
    mock_handoff_svc.send_website_enquiry.return_value = {"sent": True}
    app.dependency_overrides[get_handoff_service] = lambda: mock_handoff_svc

    response = client.post(
        "/api/enquiries",
        json={
            "name": "Rahul Sharma",
            "email": "rahul@example.com",
            "phone": "+91 98765 43210",
            "course": "Full-Stack Web & Cloud Development",
            "message": "Interested in the upcoming weekend batch.",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["notification_sent"] is True
    assert "received" in data["message"].lower()

