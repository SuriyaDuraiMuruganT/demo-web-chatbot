"""
app/api/routes/handoff.py — Human Support Handoff Endpoints

POST /api/conversations/{id}/handoff — Request human assistance
"""
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.conversation import Conversation
from app.models.handoff import WebsiteEnquiry
from app.schemas.handoff import (
    HandoffRequest,
    HandoffResponse,
    WebsiteEnquiryRequest,
    WebsiteEnquiryResponse,
)
from app.config import get_settings
from app.security.auth import get_session_token_from_header
from app.security.rate_limit import limiter
from app.security.session import verify_conversation_access
from app.services.handoff_service import HandoffService, get_handoff_service

import structlog
logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Handoff"])


@router.post(
    "/conversations/{conversation_id}/handoff",
    response_model=HandoffResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request human support",
)
@limiter.limit("3/minute")
async def create_handoff(
    request: Request,
    conversation_id: uuid.UUID,
    body: HandoffRequest,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    handoff_service: HandoffService = Depends(get_handoff_service),
) -> HandoffResponse:
    """
    Request escalation to a human support agent.

    - Customer must provide explicit consent before contact info is stored.
    - Duplicate submissions from the same conversation are prevented.
    - Notification status reflects reality — we never lie about whether
      an email was sent.

    **Required header**: `Authorization: Bearer <session_token>`
    """
    # Auth check
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

    # Load and verify conversation ownership
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if not verify_conversation_access(
        token=token,
        conversation_id=str(conversation_id),
        tenant_id=str(conversation.tenant_id),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Verify the conversation_id in the body matches the URL
    if body.conversation_id != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="conversation_id in request body must match URL",
        )

    try:
        response = await handoff_service.create_handoff(
            request=body,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation_id,
            db=db,
        )
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/enquiries",
    response_model=WebsiteEnquiryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a public admissions enquiry from the website contact form",
)
@limiter.limit("10/minute")
async def create_website_enquiry(
    request: Request,
    body: WebsiteEnquiryRequest,
    db: AsyncSession = Depends(get_db),
    handoff_service: HandoffService = Depends(get_handoff_service),
) -> WebsiteEnquiryResponse:
    """
    Submit an admissions enquiry from the website contact form.
    Persists prospect to Supabase ('website_enquiries' table) and dispatches email notification.
    """
    # 1. Save directly to Supabase
    enquiry = WebsiteEnquiry(
        name=body.name,
        email=str(body.email),
        phone=body.phone,
        course=body.course,
        message=body.message,
        status="new",
    )
    db.add(enquiry)
    await db.commit()
    await db.refresh(enquiry)

    # 2. Sync directly to Google Sheets if configured
    settings = get_settings()
    if settings.google_sheet_webhook_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                await client.post(
                    settings.google_sheet_webhook_url,
                    json={
                        "name": body.name,
                        "email": str(body.email),
                        "phone": body.phone,
                        "course": body.course,
                        "message": body.message,
                    },
                )
                logger.info("google_sheets_sync_success", name=body.name)
        except Exception as e:
            logger.warning("google_sheets_sync_failed", error=str(e))

    # 3. Attempt email notification
    result = await handoff_service.send_website_enquiry(
        name=body.name,
        email=str(body.email),
        phone=body.phone,
        course=body.course,
        message=body.message,
    )

    if result.get("sent"):
        msg = "Your admissions enquiry has been received and our admissions counselors have been notified via email."
    else:
        msg = "Your enquiry has been successfully recorded in our admissions system. Our counselors will reach out to you shortly."

    return WebsiteEnquiryResponse(
        success=True,
        message=msg,
        notification_sent=bool(result.get("sent")),
        enquiry_id=enquiry.id,
    )
