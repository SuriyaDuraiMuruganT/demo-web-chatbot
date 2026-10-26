"""
app/api/routes/admin.py — Admin Document Management Endpoints

All endpoints require HTTP Basic authentication (admin credentials from config).
These endpoints must NEVER be publicly accessible.

Endpoints:
  POST   /admin/tenants                      — Create a tenant
  GET    /admin/tenants                      — List tenants
  POST   /admin/{tenant_slug}/documents      — Upload and ingest a document
  GET    /admin/{tenant_slug}/documents      — List documents
  POST   /admin/{tenant_slug}/documents/{id}/approve — Approve/reject document
  DELETE /admin/{tenant_slug}/documents/{id} — Delete a document
"""
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.tenant import Tenant
from app.schemas.knowledge import (
    ApproveDocumentRequest,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.security.auth import require_admin
from app.security.rate_limit import limiter
from app.services.ingestion_service import IngestionService, get_ingestion_service

router = APIRouter(prefix="/admin", tags=["Admin"])


# ─── Tenant Management ─────────────────────────────────────────────────────────


@router.post("/tenants", status_code=status.HTTP_201_CREATED, summary="Create a tenant")
async def create_tenant(
    name: str = Form(..., max_length=200),
    slug: str = Form(..., max_length=100, pattern=r"^[a-z0-9\-]+$"),
    description: str | None = Form(default=None, max_length=500),
    website_url: str | None = Form(default=None, max_length=500),
    assistant_name: str = Form(default="Support Assistant", max_length=100),
    welcome_message: str | None = Form(default=None, max_length=500),
    admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new tenant (company)."""
    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant with slug '{slug}' already exists",
        )

    tenant = Tenant(
        name=name,
        slug=slug,
        description=description,
        config={
            "company_name": name,
            "assistant_name": assistant_name,
            "welcome_message": welcome_message or f"Hello! I'm {assistant_name}. How can I help you today?",
            "website_url": website_url or "",
            "suggested_questions": [
                "What services do you offer?",
                "How can I get started?",
                "How do I contact support?",
            ],
        },
    )
    db.add(tenant)
    await db.flush()

    return {
        "tenant_id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "message": f"Tenant '{name}' created successfully",
    }


@router.get("/tenants", summary="List all tenants")
async def list_tenants(
    admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all tenants."""
    result = await db.execute(select(Tenant).order_by(Tenant.created_at))
    tenants = result.scalars().all()
    return [
        {
            "tenant_id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat(),
        }
        for t in tenants
    ]


# ─── Document Management ────────────────────────────────────────────────────────


async def _get_tenant_by_slug(slug: str, db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{slug}' not found",
        )
    return tenant


@router.post(
    "/{tenant_slug}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a knowledge document",
)
@limiter.limit("5/minute")
async def upload_document(
    request: Request,
    tenant_slug: str,
    file: UploadFile = File(..., description="Document file (.txt, .md, or .pdf)"),
    title: str = Form(..., max_length=500),
    source_url: str | None = Form(default=None, max_length=2000),
    auto_approve: bool = Form(
        default=False,
        description="Approve immediately (use only for trusted admin uploads)",
    ),
    admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
) -> DocumentUploadResponse:
    """
    Upload a knowledge document for RAG ingestion.

    Documents are stored with status 'pending' by default and must be
    approved before they appear in customer-facing retrieval.

    Supported formats: .txt, .md, .pdf
    Max file size: configured by MAX_UPLOAD_SIZE_MB
    """
    settings = get_settings()
    tenant = await _get_tenant_by_slug(tenant_slug, db)

    # Read file content
    file_content = await file.read()

    # Validate size (double-check here, also validated in service)
    if len(file_content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds {settings.max_upload_size_mb}MB limit",
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required",
        )

    try:
        result = await ingestion_service.ingest_document(
            file_content=file_content,
            file_name=file.filename,
            title=title,
            tenant_id=tenant.id,
            db=db,
            source_url=source_url,
            auto_approve=auto_approve,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Ingestion service error: {str(e)}",
        )

    return DocumentUploadResponse(
        document_id=uuid.UUID(result.document_id),
        title=result.title,
        status="pending" if not auto_approve else "approved",
        chunk_count=result.chunk_count,
        message=result.message,
    )


@router.get(
    "/{tenant_slug}/documents",
    response_model=list[DocumentListResponse],
    summary="List knowledge documents for a tenant",
)
async def list_documents(
    tenant_slug: str,
    status_filter: str | None = None,
    admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentListResponse]:
    """List all documents for a tenant, optionally filtered by status."""
    tenant = await _get_tenant_by_slug(tenant_slug, db)

    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.tenant_id == tenant.id
    )
    if status_filter:
        stmt = stmt.where(KnowledgeDocument.status == status_filter)
    stmt = stmt.order_by(KnowledgeDocument.created_at.desc())

    result = await db.execute(stmt)
    docs = result.scalars().all()

    return [
        DocumentListResponse(
            document_id=doc.id,
            title=doc.title,
            file_name=doc.file_name,
            file_type=doc.file_type,
            status=doc.status,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at,
            approved_at=doc.approved_at,
            approved_by=doc.approved_by,
        )
        for doc in docs
    ]


@router.post(
    "/{tenant_slug}/documents/{document_id}/approve",
    response_model=DocumentStatusResponse,
    summary="Approve or reject a pending document",
)
async def approve_document(
    tenant_slug: str,
    document_id: uuid.UUID,
    body: ApproveDocumentRequest,
    admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
) -> DocumentStatusResponse:
    """
    Approve or reject a pending document.

    Only approved documents are returned in customer-facing RAG retrieval.
    Rejecting a document with a reason is recommended for auditability.
    """
    tenant = await _get_tenant_by_slug(tenant_slug, db)

    if not body.approved and not body.rejection_reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rejection_reason is required when rejecting a document",
        )

    doc = await ingestion_service.approve_document(
        document_id=document_id,
        tenant_id=tenant.id,
        approved_by=admin,
        db=db,
        approved=body.approved,
        rejection_reason=body.rejection_reason,
    )

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    action = "approved" if body.approved else "rejected"
    return DocumentStatusResponse(
        document_id=doc.id,
        status=doc.status,
        message=f"Document '{doc.title}' has been {action}",
    )


@router.delete(
    "/{tenant_slug}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge document",
)
async def delete_document(
    tenant_slug: str,
    document_id: uuid.UUID,
    admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
) -> None:
    """Delete a document and all its chunks. This cannot be undone."""
    tenant = await _get_tenant_by_slug(tenant_slug, db)

    deleted = await ingestion_service.delete_document(
        document_id=document_id,
        tenant_id=tenant.id,
        db=db,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
