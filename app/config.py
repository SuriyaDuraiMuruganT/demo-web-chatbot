"""
app/config.py — Application Configuration

Uses pydantic-settings to load and validate all configuration from
environment variables. Fails loudly at startup if required settings
are missing or invalid. No secrets are logged.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import (
    AliasChoices,
    AnyHttpUrl,
    Field,
    PostgresDsn,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration validated at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: Literal["development", "production", "testing"] = "development"
    app_name: str = "AI Support Chatbot"
    app_version: str = "1.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- Security ---
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(64))
    admin_username: str = "admin"
    admin_password: str = Field(default="changeme-set-in-env")

    # --- LLM Provider ---
    openai_api_key: str = Field(default="")
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.1
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 2

    # --- Embeddings ---
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_provider: Literal["openai", "local"] = "openai"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://chatbot_user:chatbot_password@localhost:5432/chatbot_db"
    )
    database_sync_url: str = Field(
        default="postgresql+psycopg2://chatbot_user:chatbot_password@localhost:5432/chatbot_db"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20

    @field_validator("database_url", mode="before")
    @classmethod
    def ensure_async_driver(cls, v: str) -> str:
        """Ensure database_url uses postgresql+asyncpg:// for SQLAlchemy async engine."""
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("postgresql://"):
                return v.replace("postgresql://", "postgresql+asyncpg://", 1)
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    # --- CORS ---
    allowed_origins: list[str] | str = ["http://localhost:8000", "http://127.0.0.1:8000"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list[str]) -> list[str]:
        """Accept comma-separated string, JSON string, or list."""
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # --- RAG ---
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.70
    rag_max_context_chunks: int = 4

    # --- Session ---
    session_expire_minutes: int = 60
    session_algorithm: str = "HS256"

    # --- Rate Limiting ---
    rate_limit_per_minute: int = 20
    rate_limit_chat_per_minute: int = 10
    rate_limit_upload_per_minute: int = 5

    # --- Request Limits ---
    max_question_length: int = 2000
    max_upload_size_mb: int = 10
    max_conversation_history: int = 20

    # --- Handoff / Email ---
    handoff_email_to: str = Field(
        default="",
        validation_alias=AliasChoices("handoff_email_to", "support_notification_email"),
    )
    handoff_email_from: str = Field(
        default="noreply@yourdomain.com",
        validation_alias=AliasChoices("handoff_email_from", "smtp_from"),
    )
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(
        default="",
        validation_alias=AliasChoices("smtp_username", "smtp_user"),
    )
    smtp_password: str = Field(
        default="",
        validation_alias=AliasChoices("smtp_password", "smtp_pass"),
    )
    smtp_tls: bool = Field(default=True)
    resend_api_key: str = Field(default="")
    google_sheet_webhook_url: str = Field(
        default="https://script.google.com/macros/s/AKfycbyfVnA1fanZw1C45T5iE6Bqm9FkpLga4sUr3JWSgwChK--zU9yu0HrjjlUHZFfMziFs/exec",
        validation_alias=AliasChoices("google_sheet_webhook_url", "sheets_webhook_url"),
    )

    # --- Analytics ---
    analytics_retention_days: int = 90

    # --- Computed Properties ---
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Enforce stricter validation in production."""
        if self.is_production:
            if not self.openai_api_key or self.openai_api_key.startswith("sk-your"):
                raise ValueError(
                    "OPENAI_API_KEY must be set to a real value in production"
                )
            if self.admin_password in ("changeme-set-in-env", "changeme", "password"):
                raise ValueError(
                    "ADMIN_PASSWORD must be set to a strong value in production"
                )
            if len(self.secret_key) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters in production"
                )
        return self

    def get_safe_repr(self) -> dict:
        """Return config dict safe for logging — no secrets."""
        return {
            "app_env": self.app_env,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "log_level": self.log_level,
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "embedding_provider": self.embedding_provider,
            "rag_top_k": self.rag_top_k,
            "rag_similarity_threshold": self.rag_similarity_threshold,
            "rate_limit_chat_per_minute": self.rate_limit_chat_per_minute,
            "max_question_length": self.max_question_length,
            "allowed_origins": self.allowed_origins,
            "openai_api_key": "***set***" if self.openai_api_key else "***NOT SET***",
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings. Use as FastAPI dependency."""
    return Settings()
