"""
app/api/routes/chat.py — Chat Endpoint

POST /api/chat — Submit a question and receive a grounded AI answer.

Security:
- Requires valid Bearer session token
- Enforces per-session and per-IP rate limits
- Input length limited by config
- Never exposes internal errors to clients
"""
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.security.auth import get_session_token_from_header
from app.security.rate_limit import limiter
from app.services.chat_service import ChatError, ChatService, get_chat_service

router = APIRouter(prefix="/api", tags=["Chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Submit a question and receive an AI answer",
)
@limiter.limit("10/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """
    Submit a customer question to the AI assistant.

    The question is processed through the RAG pipeline:
    1. Retrieves relevant approved knowledge from the vector store
    2. Generates a grounded answer using the configured LLM
    3. Returns the answer with source references

    When no relevant information is found, a helpful fallback is returned
    instead of an invented answer.

    **Required header**: `Authorization: Bearer <session_token>`
    The session token is obtained from `POST /api/conversations`.
    """
    # Extract and validate session token
    token = get_session_token_from_header(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization token required. Obtain one from POST /api/conversations.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from app.security.session import decode_session_token
    if not decode_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        response = await chat_service.process_question(
            conversation_id=body.conversation_id,
            question=body.question,
            session_token=token,
            db=db,
        )
        return response

    except ChatError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        # Never expose internal error details to the client
        import logging
        logging.getLogger(__name__).error(
            "Unexpected chat error: %s", type(e).__name__, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again.",
        )
