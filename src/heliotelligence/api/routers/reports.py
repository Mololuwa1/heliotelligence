"""Reports API endpoint.

POST /api/v1/reports/{site_id}
    Query params:
      start   ISO-8601 datetime (required)
      end     ISO-8601 datetime (required)
      sections  comma-separated list of section names (optional — defaults to all)

Returns application/pdf bytes of the generated report.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text

from heliotelligence.db.session import get_session_factory
from heliotelligence.config.settings import settings
from heliotelligence.config.site import load_sites
from heliotelligence.benchmarking.performance_ratio import calculate_pr
from heliotelligence.benchmarking.losses import calculate_losses
from heliotelligence.benchmarking.availability import calculate_availability
from heliotelligence.benchmarking.yield_metrics import calculate_yield
from heliotelligence.analysis.degradation import calculate_degradation
from heliotelligence.analysis.anomaly import detect_anomalies
from heliotelligence.analysis.string_health import analyse_string_health
from heliotelligence.analysis.inverter_health import analyse_inverter_health
from heliotelligence.reporting.report_data import ReportData
from heliotelligence.reporting.renderer import render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _site_name(site_id: str) -> str:
    sites = load_sites(settings.site_config_path)
    for site in sites:
        if str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)) == site_id:
            return site.name or site.id
    return site_id


async def _safe_fetch(coro):
    """Run a metric coroutine, returning None on any error."""
    try:
        return await coro
    except Exception as exc:
        logger.debug("Metric fetch failed: %s", exc)
        return None


@router.post("/{site_id}")
async def generate_report(
    site_id: str,
    start: datetime = Query(..., description="Report window start (ISO-8601)"),
    end: datetime = Query(..., description="Report window end (ISO-8601)"),
    sections: str | None = Query(
        None,
        description="Comma-separated section names to include (default: all)",
    ),
) -> Response:
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")

    # 404 guard — ensure site has data in this window
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

    # Fetch all metrics in parallel, each with its own session
    async def _pr():
        async with factory() as s:
            return await _safe_fetch(calculate_pr(site_id, start, end, s))

    async def _losses():
        async with factory() as s:
            return await _safe_fetch(calculate_losses(site_id, start, end, s))

    async def _avail():
        async with factory() as s:
            return await _safe_fetch(calculate_availability(site_id, start, end, s))

    async def _yield():
        async with factory() as s:
            return await _safe_fetch(calculate_yield(site_id, start, end, s))

    async def _deg():
        async with factory() as s:
            return await _safe_fetch(calculate_degradation(site_id, start, end, s))

    async def _anom():
        async with factory() as s:
            return await _safe_fetch(detect_anomalies(site_id, start, end, s))

    async def _str_health():
        async with factory() as s:
            return await _safe_fetch(analyse_string_health(site_id, start, end, s))

    async def _inv_health():
        async with factory() as s:
            return await _safe_fetch(analyse_inverter_health(site_id, start, end, s))

    (
        pr_data, losses_data, avail_data, yield_data,
        deg_data, anom_data, str_data, inv_data,
    ) = await asyncio.gather(
        _pr(), _losses(), _avail(), _yield(),
        _deg(), _anom(), _str_health(), _inv_health(),
    )

    section_list = None
    if sections:
        section_list = [s.strip() for s in sections.split(",") if s.strip()]

    data = ReportData(
        site_id=site_id,
        site_name=_site_name(site_id),
        report_start=start,
        report_end=end,
        generated_at=datetime.now(timezone.utc),
        performance_ratio=pr_data,
        losses=losses_data,
        availability=avail_data,
        yield_metrics=yield_data,
        degradation=deg_data,
        anomalies=anom_data,
        string_health=str_data,
        inverter_health=inv_data,
        sections=section_list,
    )

    try:
        pdf_bytes = render(data)
    except Exception as exc:
        logger.exception("PDF render failed for site %s: %s", site_id, exc)
        raise HTTPException(status_code=500, detail="PDF generation failed") from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="report_{site_id}_{start.date()}_{end.date()}.pdf"'
            )
        },
    )
