"""Benchmarking API endpoint.

GET /api/v1/benchmarking/{site_id}
    Query params:
      start   ISO-8601 datetime (required)
      end     ISO-8601 datetime (required)

Returns a single JSON object containing all four benchmarking metric groups:
  performance_ratio, losses, availability, yield_metrics

Each group is the raw dict returned by the corresponding calculate_* function.

All four functions are executed in parallel via asyncio.gather, each with its
own AsyncSession to avoid concurrent access on a shared connection.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from heliotelligence.db.session import get_session_factory
from heliotelligence.config.settings import settings
from heliotelligence.config.site import load_sites
from heliotelligence.benchmarking.performance_ratio import calculate_pr
from heliotelligence.benchmarking.losses import calculate_losses
from heliotelligence.benchmarking.availability import calculate_availability
from heliotelligence.benchmarking.yield_metrics import calculate_yield

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/benchmarking", tags=["benchmarking"])


def _get_capacity_kwp(site_id: str) -> float | None:
    """Load capacity_kwp for a site from the YAML config."""
    sites = load_sites(settings.site_config_path)
    for site in sites:
        if site.id == site_id:
            return site.capacity_kwp
    return None


@router.get("/{site_id}")
async def get_benchmarking(
    site_id: str,
    start: datetime = Query(..., description="Start datetime (ISO-8601, UTC)"),
    end: datetime = Query(..., description="End datetime (ISO-8601, UTC)"),
) -> dict:
    """Return all benchmarking metrics for a site over a time window.

    Parameters
    ----------
    site_id : str   UUID of the site.
    start   : datetime  Inclusive lower bound.
    end     : datetime  Exclusive upper bound.

    Returns
    -------
    dict with keys:
        site_id, start, end,
        performance_ratio, losses, availability, yield_metrics

    Raises
    ------
    422  if start >= end
    404  if no expected_energy data exists for the site in the window
    """
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")

    factory = get_session_factory()

    # Check that the site has data in the requested window before spawning
    # four sessions (cheap guard to return a clean 404).
    async with factory() as check_session:
        exists = await check_session.execute(
            text("""
                SELECT 1 FROM expected_energy
                WHERE site_id = :site_id
                  AND time >= :start AND time < :end
                LIMIT 1
            """),
            {"site_id": site_id, "start": start, "end": end},
        )
        if exists.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail=f"No expected_energy data found for site {site_id} "
                       f"in [{start.isoformat()}, {end.isoformat()})",
            )

    capacity_kwp = _get_capacity_kwp(site_id)

    # Each benchmarking function gets its own session so they can run concurrently.
    async def _pr():
        async with factory() as s:
            return await calculate_pr(site_id, start, end, s)

    async def _losses():
        async with factory() as s:
            return await calculate_losses(site_id, start, end, s)

    async def _avail():
        async with factory() as s:
            return await calculate_availability(site_id, start, end, s)

    async def _yield():
        async with factory() as s:
            return await calculate_yield(
                site_id, start, end, s, capacity_kwp=capacity_kwp
            )

    pr_result, losses_result, avail_result, yield_result = await asyncio.gather(
        _pr(), _losses(), _avail(), _yield()
    )

    return dict(
        site_id=site_id,
        start=start,
        end=end,
        performance_ratio=pr_result,
        losses=losses_result,
        availability=avail_result,
        yield_metrics=yield_result,
    )
