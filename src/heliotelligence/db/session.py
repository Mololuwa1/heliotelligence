"""Async SQLAlchemy engine and session factory.

This is the canonical module for database connectivity.
db/engine.py re-exports everything from here for backward compatibility.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from heliotelligence.config.settings import settings

# ---------------------------------------------------------------------------
# Engine singleton
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None


def get_engine(*, use_null_pool: bool = False) -> AsyncEngine:
    """Return the shared async engine, creating it on first call."""
    global _engine
    if _engine is None:
        pool_class = NullPool if use_null_pool else AsyncAdaptedQueuePool
        pool_kwargs: dict = (
            {}
            if use_null_pool
            else {"pool_size": 5, "max_overflow": 10, "pool_pre_ping": True}
        )
        # asyncpg requires ssl via connect_args, not via the URL query string.
        # sslmode=require (libpq) means "encrypt, don't verify cert".
        # asyncpg ssl=True does full verification; we replicate require semantics
        # by creating an SSL context with cert verification disabled.
        connect_args: dict = {}
        if settings.database_ssl:
            import ssl as _ssl
            ssl_ctx = _ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = _ssl.CERT_NONE
            connect_args = {"ssl": ssl_ctx}

        _engine = create_async_engine(
            settings.database_url,
            poolclass=pool_class,
            echo=(settings.app_env == "development"),
            connect_args=connect_args,
            **pool_kwargs,
        )
    return _engine


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the live engine."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,   # prevents implicit lazy-loads in async context
        autoflush=False,
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for use as a FastAPI dependency."""
    async with get_session_factory()() as session:
        yield session
