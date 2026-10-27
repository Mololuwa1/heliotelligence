"""Analysis API endpoints.

Endpoints
---------
GET /api/v1/analysis/{site_id}/degradation
    Query params: start, end
GET /api/v1/analysis/{site_id}/anomalies
    Query params: start, end, threshold_sigma (default 2.0)
GET /api/v1/analysis/{site_id}/string-health
    Query params: start, end, threshold_sigma (default 2.0)
GET /api/v1/analysis/{site_id}/inverter-health
    Query params: start, end

All return 404 when no data exists for the site in the window.
All return 422 when start >= end.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from heliotelligence.analysis.anomaly import detect_anomalies
from heliotelligence.analysis.degradation import calculate_degradation
from heliotelligence.analysis.inverter_health import analyse_inverter_health
from heliotelligence.analysis.string_health import analyse_string_health
from heliotelligence.db.session import get_session_factory
from heliotelligence.engine.expected_energy_source import (
    LEGACY_EXPECTED_ENERGY_SOURCE,
    validate_expected_energy_source,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


async def _check_expected_energy_data(
    site_id: str,
    start: datetime,
    end: datetime,
    *,
    source: str = LEGACY_EXPECTED_ENERGY_SOURCE,
) -> None:
    """Require the selected model series for expected-energy analyses."""
    source = validate_expected_energy_source(source)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT 1 FROM expected_energy
                WHERE site_id = :site_id
                  AND source = :source
                  AND time >= :start AND time < :end
                LIMIT 1
            """),
            {"site_id": site_id, "start": start, "end": end, "source": source},
        )
        if result.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail=f"No expected_energy data found for site {site_id} "
                f"for source {source} "
                f"in [{start.isoformat()}, {end.isoformat()})",
            )


async def _check_any_expected_energy_data(site_id: str, start: datetime, end: datetime) -> None:
    """Preserve the pre-P0 existence gate for telemetry-only analyses.

    This checks existence only, without reading or combining model values.
    """
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT 1 FROM expected_energy
                WHERE site_id = :site_id
                  AND time >= :start AND time < :end
                LIMIT 1
            """),
            {"site_id": site_id, "start": start, "end": end},
        )
        if result.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for site {site_id} "
                f"in [{start.isoformat()}, {end.isoformat()})",
            )


def _validate_window(start: datetime, end: datetime) -> None:
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")


@router.get("/{site_id}/degradation")
async def get_degradation(
    site_id: str,
    start: datetime = Query(..., description="Start datetime (ISO-8601, UTC)"),
    end: datetime = Query(..., description="End datetime (ISO-8601, UTC)"),
    source: str = LEGACY_EXPECTED_ENERGY_SOURCE,
) -> dict:
    """Return long-run PR degradation analysis for a site."""
    try:
        source = validate_expected_energy_source(source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _validate_window(start, end)
    await _check_expected_energy_data(site_id, start, end, source=source)
    factory = get_session_factory()
    async with factory() as session:
        result = await calculate_degradation(site_id, start, end, session, source=source)
        result["expected_energy_source"] = source
        return result


@router.get("/{site_id}/anomalies")
async def get_anomalies(
    site_id: str,
    start: datetime = Query(..., description="Start datetime (ISO-8601, UTC)"),
    end: datetime = Query(..., description="End datetime (ISO-8601, UTC)"),
    threshold_sigma: float = Query(2.0, description="Flag threshold in std deviations"),
    source: str = LEGACY_EXPECTED_ENERGY_SOURCE,
) -> dict:
    """Return AC power anomaly flags for a site."""
    try:
        source = validate_expected_energy_source(source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _validate_window(start, end)
    await _check_expected_energy_data(site_id, start, end, source=source)
    factory = get_session_factory()
    async with factory() as session:
        result = await detect_anomalies(
            site_id, start, end, session, threshold_sigma, source=source
        )
        result["expected_energy_source"] = source
        return result


@router.get("/{site_id}/string-health")
async def get_string_health(
    site_id: str,
    start: datetime = Query(..., description="Start datetime (ISO-8601, UTC)"),
    end: datetime = Query(..., description="End datetime (ISO-8601, UTC)"),
    threshold_sigma: float = Query(2.0, description="Flag threshold in std deviations"),
) -> dict:
    """Return per-string current health analysis for a site."""
    _validate_window(start, end)
    await _check_any_expected_energy_data(site_id, start, end)
    factory = get_session_factory()
    async with factory() as session:
        return await analyse_string_health(site_id, start, end, session, threshold_sigma)


@router.get("/{site_id}/inverter-health")
async def get_inverter_health(
    site_id: str,
    start: datetime = Query(..., description="Start datetime (ISO-8601, UTC)"),
    end: datetime = Query(..., description="End datetime (ISO-8601, UTC)"),
) -> dict:
    """Return per-inverter fault event analysis for a site."""
    _validate_window(start, end)
    await _check_any_expected_energy_data(site_id, start, end)
    factory = get_session_factory()
    async with factory() as session:
        return await analyse_inverter_health(site_id, start, end, session)
