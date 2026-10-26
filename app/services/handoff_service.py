"""
app/services/handoff_service.py — Human Support Handoff Service

Handles customer requests to speak with a human support agent.

Design:
- Stores handoff requests in DB always (regardless of notification status)
- Attempts email notification if configured
- NEVER claims notification was sent if it failed
- Prevents duplicate submissions from the same conversation
- Consent is mandatory before storing contact information
"""
from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.handoff import HandoffRequest
from app.schemas.handoff import HandoffRequest as HandoffSchema
from app.schemas.handoff import HandoffResponse

logger = logging.getLogger(__name__)


class HandoffService:
    """Manages customer-to-human escalation requests."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def create_handoff(
        self,
        request: HandoffSchema,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        db: AsyncSession,
    ) -> HandoffResponse:
        """
        Create a human support handoff request.

        1. Check for duplicate from this conversation
        2. Validate consent (enforced by schema, double-checked here)
        3. Store in DB
        4. Attempt notification if configured
        5. Return status — never lies about notification success

        Args:
            request: Validated handoff request schema
            tenant_id: Authenticated tenant ID
            conversation_id: Conversation requesting handoff
            db: Async database session

        Returns:
            HandoffResponse with actual notification status
        """
        # 1. Check for existing pending handoff from this conversation
        existing = await self._find_existing_handoff(conversation_id, db)
        if existing and existing.status in ("pending", "notified"):
            return HandoffResponse(
                handoff_id=existing.id,
                status=existing.status,
                message=(
                    "A support request from this conversation is already being processed. "
                    "Our team will be in touch shortly."
                ),
                notification_sent=existing.notification_sent,
            )

        # 2. Double-check consent (already validated by schema)
        if not request.consent_given:
            raise ValueError("Explicit consent is required before storing contact information")

        # 3. Store in database
        handoff = HandoffRequest(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            customer_name=request.customer_name,
            customer_email=str(request.customer_email) if request.customer_email else None,
            issue_summary=request.issue_summary,
            consent_given=True,
            consent_text=request.consent_text,
            status="pending",
            notification_sent=False,
        )
        db.add(handoff)
        await db.flush()  # Get handoff.id

        # 4. Attempt notification (best-effort, never required)
        notification_sent = False
        notification_error = None

        if self._is_email_configured():
            try:
                await self._send_email_notification(handoff, tenant_id)
                notification_sent = True
                handoff.status = "notified"
                handoff.notification_sent = True
                logger.info("Handoff notification sent: handoff_id=%s", handoff.id)
            except Exception as e:
                notification_error = str(e)[:500]
                handoff.notification_error = notification_error
                logger.warning(
                    "Handoff notification failed: handoff_id=%s error=%s",
                    handoff.id, type(e).__name__
                )

        await db.flush()

        # 5. Build honest response
        if notification_sent:
            message = (
                "Your support request has been received and our team has been notified. "
                "We'll be in touch soon."
            )
        elif self._is_email_configured() and not notification_sent:
            message = (
                "Your support request has been recorded. There was a problem notifying "
                "our team automatically, but your request is saved and will be reviewed. "
                "You can also contact us directly."
            )
        else:
            message = (
                "Your support request has been recorded. Our team will review it shortly. "
                "Please note: automated notifications are not currently configured, "
                "but your request is saved in our system."
            )

        return HandoffResponse(
            handoff_id=handoff.id,
            status=handoff.status,
            message=message,
            notification_sent=notification_sent,
        )

    async def _find_existing_handoff(
        self,
        conversation_id: uuid.UUID,
        db: AsyncSession,
    ) -> HandoffRequest | None:
        stmt = select(HandoffRequest).where(
            HandoffRequest.conversation_id == conversation_id
        ).order_by(HandoffRequest.created_at.desc())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    def _is_email_configured(self) -> bool:
        settings = self._settings
        return bool(
            settings.handoff_email_to
            and (settings.resend_api_key or (settings.smtp_host and settings.smtp_username))
        )

    async def _dispatch_email(self, subject: str, body: str, msg: MIMEMultipart) -> None:
        settings = self._settings
        if settings.resend_api_key:
            import httpx
            sender = settings.handoff_email_from
            if not sender or "gmail.com" in sender or "yourdomain.com" in sender:
                sender = "XYZ Admissions Desk <onboarding@resend.dev>"
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": sender,
                        "to": [settings.handoff_email_to],
                        "subject": subject,
                        "text": body,
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"Resend API error {res.status_code}: {res.text}")
                return

        # Fallback to direct SMTP
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_smtp, msg)

    async def _send_email_notification(
        self,
        handoff: HandoffRequest,
        tenant_id: uuid.UUID,
    ) -> None:
        """Send email notification to support team. Raises on failure."""
        settings = self._settings

        subject = f"[Support Request] {handoff.issue_summary[:60]}..."
        body = f"""
New customer support request received.

Issue Summary:
{handoff.issue_summary}

Customer Contact:
Name: {handoff.customer_name or 'Not provided'}
Email: {handoff.customer_email or 'Not provided'}

Conversation ID: {handoff.conversation_id}
Handoff ID: {handoff.id}
Submitted: {datetime.now(timezone.utc).isoformat()}

Consent given: Yes
Consent statement: {handoff.consent_text}

---
This request was submitted via the AI Support Chatbot.
Please log in to the admin panel to update the status.
        """.strip()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.handoff_email_from
        msg["To"] = settings.handoff_email_to
        msg.attach(MIMEText(body, "plain"))

        await self._dispatch_email(subject, body, msg)

    def _send_smtp(self, msg: MIMEMultipart) -> None:
        settings = self._settings
        timeout_seconds = 5
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=timeout_seconds) as server:
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout_seconds) as server:
                if settings.smtp_tls:
                    server.starttls()
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)

    async def send_website_enquiry(
        self,
        name: str,
        email: str,
        phone: str,
        course: str,
        message: str | None = None,
    ) -> dict:
        """Send website admissions enquiry email notification to the counselor desk."""
        if not self._is_email_configured():
            logger.warning("Email notifications not configured for website enquiry")
            return {"sent": False, "reason": "email_not_configured"}

        settings = self._settings
        subject = f"[New Admissions Enquiry] {course} — {name}"
        body = f"""
New Admissions Enquiry received from XYZ Institute Website.

============================================================
Prospect Details:
Name:    {name}
Email:   {email}
Phone:   {phone}
Program: {course}

Prospect Message / Inquiries:
{message or 'No additional questions entered by prospect.'}

Submitted At: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
Source:       XYZ Institute Contact & Admissions Form
============================================================
Please follow up with the prospective student promptly.
        """.strip()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.handoff_email_from
        msg["To"] = settings.handoff_email_to
        msg.attach(MIMEText(body, "plain"))

        try:
            await self._dispatch_email(subject, body, msg)
            logger.info("Website enquiry email dispatched to %s for %s", settings.handoff_email_to, name)
            return {"sent": True}
        except Exception as e:
            logger.error("Failed to send website enquiry email: %s", e)
            return {"sent": False, "error": str(e)}


def get_handoff_service() -> HandoffService:
    return HandoffService()
