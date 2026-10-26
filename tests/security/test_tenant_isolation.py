"""
tests/security/test_tenant_isolation.py — Strict Multi-Tenant Isolation Security Tests
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.conversation import Conversation
from app.security.session import create_session_token, verify_conversation_access
from app.services.chat_service import ChatError, ChatService


def test_cross_tenant_token_rejection():
    """Verify session token for Tenant A is strictly rejected for Tenant B requests."""
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())

    # Token signed for Tenant A
    token_tenant_a = create_session_token(tenant_id=tenant_a, conversation_id=conv_id)

    # Verification must fail when requested under Tenant B
    assert verify_conversation_access(token_tenant_a, conv_id, tenant_b) is False


@pytest.mark.asyncio
async def test_chat_service_blocks_cross_tenant_access():
    """Verify ChatService rejects request if token tenant does not match conversation tenant."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    conv_id = uuid.uuid4()

    mock_db = AsyncMock()
    # Conversation in DB belongs to Tenant A
    mock_conv = MagicMock(spec=Conversation)
    mock_conv.id = conv_id
    mock_conv.tenant_id = tenant_a

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_conv
    mock_db.execute.return_value = mock_result

    # Token forged or created for Tenant B
    token_tenant_b = create_session_token(tenant_id=str(tenant_b), conversation_id=str(conv_id))

    chat_service = ChatService()

    with pytest.raises(ChatError) as exc_info:
        await chat_service.process_question(
            conversation_id=conv_id,
            question="What are your secret plans?",
            session_token=token_tenant_b,
            db=mock_db,
        )

    assert exc_info.value.status_code == 401
    assert "Unauthorized" in str(exc_info.value)
