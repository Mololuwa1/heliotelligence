"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.db.health import get_db_version
from heliotelligence.db.session import get_db

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Return application liveness and TimescaleDB version."""
    version = await get_db_version(db)
    return {"status": "ok", "db": "ok", "version": version}
