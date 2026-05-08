"""Database health and version introspection."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_version(session: AsyncSession) -> str:
    """Return a combined PostgreSQL + TimescaleDB version string.

    Example return value:
        "PostgreSQL 16.2 on x86_64-pc-linux-gnu | TimescaleDB 2.14.2"
    """
    pg_result = await session.execute(text("SELECT version()"))
    pg_version: str = pg_result.scalar_one()
    # Extract just the short version tag (e.g. "PostgreSQL 16.2") from the
    # full build string that version() returns.
    pg_short = pg_version.split(",")[0].strip()

    ts_result = await session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
    )
    ts_version: str | None = ts_result.scalar_one_or_none()

    if ts_version:
        return f"{pg_short} | TimescaleDB {ts_version}"
    return pg_short
