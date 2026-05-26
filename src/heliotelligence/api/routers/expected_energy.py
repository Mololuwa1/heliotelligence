"""Expected energy query endpoint.

Endpoints
---------
GET /api/v1/expected-energy/{site_id}
    Query params:
      start       ISO-8601 datetime (required)
      end         ISO-8601 datetime (required)
      resolution  'raw' | 'hourly' | 'daily'  (default: 'raw')

Returns an array of expected energy records for the requested window and
resolution.  'hourly' and 'daily' return time-bucket averages for power
and sums for energy (not yet: energy columns will be added in Layer 5).
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/expected-energy", tags=["expected_energy"])


class Resolution(str, Enum):
    raw = "raw"
    hourly = "hourly"
    daily = "daily"


@router.get("/{site_id}")
async def get_expected_energy(
    site_id: str,
    start: datetime = Query(..., description="Start datetime (ISO-8601, UTC)"),
    end: datetime = Query(..., description="End datetime (ISO-8601, UTC)"),
    resolution: Resolution = Query(Resolution.raw, description="Aggregation resolution"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return expected energy records for a site over a time window.

    Parameters
    ----------
    site_id : str
        UUID of the site.
    start : datetime
        Inclusive lower bound.
    end : datetime
        Exclusive upper bound.
    resolution : Resolution
        'raw' returns one row per timestamp from expected_energy.
        'hourly' / 'daily' return time-bucketed averages using
        TimescaleDB time_bucket().

    Returns
    -------
    list[dict]
        Each dict has keys:
          time, p_ac_kw, p_dc_kw, p_dc_stc_kw,
          poa_total_wm2, t_cell_c, tier_used, fit_quality, source
    """
    if end <= start:
        raise HTTPException(
            status_code=422, detail="end must be after start"
        )

    if resolution == Resolution.raw:
        stmt = text("""
            SELECT
                time, p_ac_kw, p_dc_kw, p_dc_stc_kw,
                poa_total_wm2, t_cell_c, tier_used, fit_quality, source
            FROM expected_energy
            WHERE site_id = :site_id
              AND time >= :start
              AND time < :end
            ORDER BY time ASC
        """)
    elif resolution == Resolution.hourly:
        stmt = text("""
            SELECT
                date_trunc('hour', time) AS time,
                AVG(p_ac_kw)       AS p_ac_kw,
                AVG(p_dc_kw)       AS p_dc_kw,
                AVG(p_dc_stc_kw)   AS p_dc_stc_kw,
                AVG(poa_total_wm2) AS poa_total_wm2,
                AVG(t_cell_c)      AS t_cell_c,
                MIN(tier_used)     AS tier_used,
                MIN(fit_quality)   AS fit_quality,
                MIN(source)        AS source
            FROM expected_energy
            WHERE site_id = :site_id
              AND time >= :start
              AND time < :end
            GROUP BY 1
            ORDER BY 1 ASC
        """)
    else:  # daily
        stmt = text("""
            SELECT
                date_trunc('day', time) AS time,
                AVG(p_ac_kw)       AS p_ac_kw,
                AVG(p_dc_kw)       AS p_dc_kw,
                AVG(p_dc_stc_kw)   AS p_dc_stc_kw,
                AVG(poa_total_wm2) AS poa_total_wm2,
                AVG(t_cell_c)      AS t_cell_c,
                MIN(tier_used)     AS tier_used,
                MIN(fit_quality)   AS fit_quality,
                MIN(source)        AS source
            FROM expected_energy
            WHERE site_id = :site_id
              AND time >= :start
              AND time < :end
            GROUP BY 1
            ORDER BY 1 ASC
        """)

    result = await db.execute(
        stmt,
        {"site_id": site_id, "start": start, "end": end},
    )
    rows = result.fetchall()
    keys = result.keys()

    return [dict(zip(keys, row)) for row in rows]
