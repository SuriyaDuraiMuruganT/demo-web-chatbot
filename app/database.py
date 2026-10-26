"""
app/database.py — Database Engine, Session Factory, and Base

Provides async SQLAlchemy engine, session factory, and declarative base.
All database interactions should use the async session from get_db().
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# Naming convention for constraints — important for Alembic autogenerate
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine_and_session() -> (
    tuple[Any, async_sessionmaker[AsyncSession]]
):
    """Create the async engine and session factory from current settings."""
    settings = get_settings()

    engine = create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,   # Detect stale connections
        echo=settings.app_env == "development",
    )

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    return engine, session_factory


# Module-level engine and session factory — initialized once
_engine, _session_factory = create_engine_and_session()


def get_engine() -> Any:
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session per request.
    Automatically commits on success and rolls back on exception.
    """
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connection() -> bool:
    """Health check: verify database is reachable."""
    try:
        async with _session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_pgvector() -> bool:
    """Readiness check: verify vector support (pgvector or fallback) is ready."""
    try:
        async with _session_factory() as session:
            result = await session.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            if result.scalar() == "vector":
                return True
            # Fallback: check if document_chunks table is created and ready
            table_check = await session.execute(
                text("SELECT to_regclass('public.document_chunks')")
            )
            return table_check.scalar() is not None
    except Exception:
        return False
