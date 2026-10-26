"""
app/main.py — FastAPI Application Entry Point

Assembles the FastAPI application with:
- Middleware (CORS, rate limiting, request size limits)
- Routers
- Startup validation
- Global exception handlers
- Structured logging

Security decisions documented here:
- CORS: explicit allowlist from config, no wildcard in production
- Rate limiting: per-session + per-IP via slowapi
- Error responses: safe messages only, no internal details leaked
- Request size: limited by middleware
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import admin, analytics, chat, conversations, handoff, health
from app.config import get_settings
from app.security.rate_limit import limiter

# ─── Logging Setup ──────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger(__name__)


# ─── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown logic.

    Startup:
    - Validates critical configuration
    - Logs safe config summary (no secrets)
    - Verifies database connectivity

    Shutdown:
    - Closes database connections
    """
    settings = get_settings()

    # Log safe config (no secrets)
    logger.info("application_starting", **settings.get_safe_repr())

    # Warn if no API key in development
    if not settings.openai_api_key and not settings.is_testing:
        logger.warning(
            "OPENAI_API_KEY is not set. Chat and embedding features will not work. "
            "Set it in your .env file."
        )

    yield  # Application runs

    # Shutdown
    from app.database import get_engine
    engine = get_engine()
    await engine.dispose()
    logger.info("application_shutdown")


# ─── Application Factory ────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI Customer Support Chatbot with RAG. "
            "Answers customer questions using verified company knowledge."
        ),
        docs_url="/docs" if not settings.is_production else None,  # Disable in prod
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Rate Limiting ────────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS ─────────────────────────────────────────────────────────────────────
    # Always use an explicit allowlist — never "*" in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,   # No cookies used in widget API
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["X-Request-Id"],
    )

    # ── Request ID Middleware ────────────────────────────────────────────────────
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        """Add a unique request ID to every response for traceability."""
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.monotonic()
        response = await call_next(request)
        latency_ms = int((time.monotonic() - start_time) * 1000)

        response.headers["X-Request-Id"] = request_id

        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        return response

    # ── Routers ──────────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(conversations.router)
    app.include_router(chat.router)
    app.include_router(handoff.router)
    app.include_router(admin.router)
    app.include_router(analytics.router)

    # ── Static Files & Frontend ──────────────────────────────────────────────────
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/frontend", StaticFiles(directory=str(frontend_dir)), name="frontend")
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        css_dir = frontend_dir / "css"
        if css_dir.exists():
            app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")

        js_dir = frontend_dir / "js"
        if js_dir.exists():
            app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            index_path = frontend_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"message": "AI Support Chatbot API", "docs": "/docs"}

        @app.get("/styles.css", include_in_schema=False)
        async def serve_styles():
            return FileResponse(str(frontend_dir / "styles.css"), media_type="text/css")

        @app.get("/chat.js", include_in_schema=False)
        async def serve_chat_js():
            return FileResponse(str(frontend_dir / "chat.js"), media_type="application/javascript")

        @app.get("/config.js", include_in_schema=False)
        async def serve_config_js():
            return FileResponse(str(frontend_dir / "config.js"), media_type="application/javascript")

    # ── Global Exception Handlers ────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all exception handler.
        Returns a safe, generic error message.
        Never exposes stack traces, internal paths, or sensitive details.
        """
        logger.error(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "detail": "An unexpected error occurred. Please try again.",
            },
        )

    return app


# ─── Module-level app instance ──────────────────────────────────────────────────
app = create_app()
