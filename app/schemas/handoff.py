"""
app/schemas/handoff.py — Human Support Handoff Schemas
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class HandoffRequest(BaseModel):
    """Request to escalate to human support."""

    conversation_id: uuid.UUID
    issue_summary: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Customer's description of their issue",
    )
    customer_name: str | None = Field(
        default=None,
        max_length=200,
        description="Optional: customer's name for follow-up",
    )
    customer_email: EmailStr | None = Field(
        default=None,
        description="Optional: email address for support team follow-up",
    )
    consent_given: bool = Field(
        ...,
        description="Customer must explicitly agree to contact info storage",
    )
    consent_text: str = Field(
        ...,
        max_length=500,
        description="The exact consent statement shown to the customer",
    )

    @field_validator("consent_given")
    @classmethod
    def consent_must_be_true(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "Consent must be explicitly given before submitting a handoff request"
            )
        return v

    @field_validator("customer_email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v: str | None) -> str | None:
        if v == "":
            return None
        return v


class HandoffResponse(BaseModel):
    """Response after creating a handoff request."""

    handoff_id: uuid.UUID
    status: str  # "pending" | "notified"
    message: str
    notification_sent: bool
    estimated_response_time: str | None = None


class HandoffStatusResponse(BaseModel):
    """Current status of a handoff request."""

    handoff_id: uuid.UUID
    status: str
    created_at: datetime
    notification_sent: bool

    model_config = {"from_attributes": True}


class WebsiteEnquiryRequest(BaseModel):
    """Admissions enquiry submitted from website contact form."""

    name: str = Field(..., min_length=2, max_length=200, description="Prospect's full name")
    email: EmailStr = Field(..., description="Prospect's email address")
    phone: str = Field(..., min_length=8, max_length=30, description="Prospect's contact number")
    course: str = Field(..., min_length=2, max_length=200, description="Course or program of interest")
    message: str | None = Field(default=None, max_length=2000, description="Optional questions or comments")


class WebsiteEnquiryResponse(BaseModel):
    """Response after submitting an admissions enquiry."""

    success: bool
    message: str
    notification_sent: bool
