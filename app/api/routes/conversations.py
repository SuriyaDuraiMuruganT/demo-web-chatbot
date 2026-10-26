"""
app/api/routes/conversations.py — Conversation Management Endpoints

POST /api/conversations        — Create a new chat session
GET  /api/conversations/{id}/messages — Get conversation history (auth required)
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.tenant import Tenant
from app.schemas.common import ErrorResponse
from app.schemas.conversation import (
    ConversationHistoryResponse,
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    SourceReference,
)
from app.security.rate_limit import limiter
from app.security.session import (
    create_session_token,
    hash_token,
    hash_user_agent,
    verify_conversation_access,
)

router = APIRouter(prefix="/api", tags=["Conversations"])


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat session",
)
@limiter.limit("10/minute")
async def create_conversation(
    request: Request,
    body: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """
    Create a new chat session for the given tenant.

    Returns a short-lived session token that must be included as
    `Authorization: Bearer <token>` in all subsequent requests for this conversation.

    The session token is the authorization credential — conversation UUID alone
    is not sufficient to access or modify a conversation.
    """
    # Look up tenant by slug
    stmt = select(Tenant).where(
        and_(Tenant.slug == body.tenant_slug, Tenant.is_active == True)  # noqa: E712
    )
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{body.tenant_slug}' not found or inactive",
        )

    # Create conversation record
    conv_id = uuid.uuid4()
    conversation = Conversation(
        id=conv_id,
        tenant_id=tenant.id,
        session_token_hash="placeholder",  # Updated after token creation
        user_agent_hash=hash_user_agent(request.headers.get("User-Agent")),
    )
    db.add(conversation)
    await db.flush()  # Get conversation.id

    # Create signed session token
    session_token = create_session_token(
        tenant_id=str(tenant.id),
        conversation_id=str(conversation.id),
    )

    # Store only the hash — NEVER store the raw token
    conversation.session_token_hash = hash_token(session_token)
    await db.flush()

    # Extract branding config
    config = tenant.config or {}
    assistant_name = config.get("assistant_name", "Support Assistant")
    welcome_message = config.get(
        "welcome_message",
        f"Hello! I'm {assistant_name}. How can I help you today?"
    )
    suggested_questions = config.get("suggested_questions", [
        "What services do you offer?",
        "How can I get started?",
        "How do I contact support?",
    ])

    from app.config import get_settings
    settings = get_settings()

    return ConversationResponse(
        conversation_id=conversation.id,
        session_token=session_token,
        tenant_slug=tenant.slug,
        expires_in_minutes=settings.session_expire_minutes,
        welcome_message=welcome_message,
        assistant_name=assistant_name,
        suggested_questions=suggested_questions,
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationHistoryResponse,
    summary="Get conversation message history",
)
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ConversationHistoryResponse:
    """
    Retrieve the message history for a conversation.

    Requires a valid session token in the Authorization header.
    Users can only access their own conversation history.
    """
    from app.security.auth import get_session_token_from_header

    token = get_session_token_from_header(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.security.session import decode_session_token
    if not decode_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load conversation
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Verify token authorizes access to this specific conversation and tenant
    if not verify_conversation_access(
        token=token,
        conversation_id=str(conversation_id),
        tenant_id=str(conversation.tenant_id),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Load messages
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    message_responses = []
    for msg in messages:
        if msg.role not in ("user", "assistant"):
            continue
        sources = [SourceReference(**s) for s in (msg.sources or [])]
        message_responses.append(
            MessageResponse(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                sources=sources,
                is_fallback=bool(msg.is_fallback),
                created_at=msg.created_at,
            )
        )

    return ConversationHistoryResponse(
        conversation_id=conversation_id,
        messages=message_responses,
        total_messages=len(message_responses),
    )
