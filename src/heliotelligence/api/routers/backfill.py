"""Solcast historic backfill endpoint.

POST /api/v1/backfill/{site_id}?start=&end=
    Triggers a historic Solcast data backfill for the given site and window.
    Returns the number of rows upserted and the number of 31-day chunks used.

Query params
────────────
start   ISO-8601 datetime (required)
end     ISO-8601 datetime (required)

Returns
───────
{
    "rows_upserted": int,
    "chunks": int,
    "start": str,
    "end": str,
    "site_id": str,
}
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime

from heliotelligence.config.settings import settings
from heliotelligence.config.site import load_sites
from heliotelligence.collectors.solcast import run_solcast_backfill

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backfill", tags=["backfill"])


def _find_site(site_id: str):
    """Return the SiteConfig whose uuid5 matches site_id, or None."""
    sites = load_sites(settings.site_config_path)
    for site in sites:
        if str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)) == site_id:
            return site
    return None


@router.post("/{site_id}")
async def trigger_backfill(
    site_id: str,
    start: datetime = Query(..., description="Backfill window start (ISO-8601)"),
    end: datetime = Query(..., description="Backfill window end (ISO-8601)"),
) -> dict:
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")

    site = _find_site(site_id)
    if site is None:
        raise HTTPException(
            status_code=404,
            detail=f"Site {site_id} not found in configuration",
        )

    if not settings.solcast_api_key:
        raise HTTPException(
            status_code=503,
            detail="SOLCAST_API_KEY is not configured — backfill unavailable",
        )

    try:
        rows_upserted, chunks = await run_solcast_backfill(site, start, end)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Backfill failed for site %s: %s", site_id, exc)
        raise HTTPException(status_code=502, detail=f"Solcast backfill failed: {exc}") from exc

    return {
        "rows_upserted": rows_upserted,
        "chunks": chunks,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "site_id": site_id,
    }
