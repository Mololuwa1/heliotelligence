"""Yield and capacity factor metrics.

specific_yield_kwh_kwp  = E_actual_kwh / capacity_kwp
capacity_factor_pct     = E_actual_kwh / (capacity_kwp × hours_in_window) × 100
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_yield(
    e_actual_kwh: float,
    capacity_kwp: float | None,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Compute yield metrics from pre-fetched energy total (no DB access).

    Parameters
    ----------
    e_actual_kwh  : float
    capacity_kwp  : float | None
        DC nameplate capacity.  When None, specific_yield and capacity_factor
        are returned as None.
    start, end    : datetime

    Returns
    -------
    dict
        specific_yield_kwh_kwp      float | None
        capacity_factor_pct         float | None
        target_specific_yield_kwh_kwp  None  (reserved for future use)
        e_actual_kwh                float
        hours_in_window             float
        start, end                  datetime
    """
    hours_in_window = (end - start).total_seconds() / 3600.0

    if capacity_kwp is not None and capacity_kwp > 0.0:
        specific_yield = round(e_actual_kwh / capacity_kwp, 4)
        denominator = capacity_kwp * hours_in_window
        capacity_factor_pct = (
            round(e_actual_kwh / denominator * 100.0, 4)
            if denominator > 0.0
            else None
        )
    else:
        specific_yield = None
        capacity_factor_pct = None

    return dict(
        specific_yield_kwh_kwp=specific_yield,
        capacity_factor_pct=capacity_factor_pct,
        target_specific_yield_kwh_kwp=None,
        e_actual_kwh=round(e_actual_kwh, 3),
        hours_in_window=round(hours_in_window, 3),
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------------
# DB fetcher
# ---------------------------------------------------------------------------

async def _fetch_e_actual_kwh(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> float:
    """Sum E_actual from meter_readings.

    Prefers e_exported_kwh; falls back to integrating p_ac_kw × interval_h
    for rows where e_exported_kwh is NULL.
    """
    # Fetch both columns; integration is done in Python to handle mixed rows.
    result = await session.execute(
        text("""
            SELECT ts AS time, p_ac_kw, e_exported_kwh
            FROM meter_readings
            WHERE site_id = :site_id
              AND ts >= :start
              AND ts < :end
            ORDER BY ts ASC
        """),
        {"site_id": site_id, "start": start, "end": end},
    )
    rows = result.fetchall()
    if not rows:
        return 0.0

    df = pd.DataFrame(rows, columns=["time", "p_ac_kw", "e_exported_kwh"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()

    e_actual = 0.0

    has_export = df["e_exported_kwh"].notna()
    if has_export.any():
        e_actual += float(df.loc[has_export, "e_exported_kwh"].sum())

    fallback = ~has_export & df["p_ac_kw"].notna()
    if fallback.any():
        idx = df.index
        n = len(idx)
        if n > 1:
            diffs_s = pd.Series(idx).diff().dt.total_seconds().values
            diffs_h = diffs_s / 3600.0
            diffs_h[0] = diffs_h[1]
            intervals_h = pd.Series(diffs_h, index=idx)
        else:
            intervals_h = pd.Series([1.0], index=idx)
        fb_power = df.loc[fallback, "p_ac_kw"]
        fb_intervals = intervals_h.reindex(fb_power.index)
        e_actual += float((fb_power * fb_intervals).sum())

    return e_actual


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def calculate_yield(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
    capacity_kwp: float | None = None,
) -> dict:
    """Calculate yield and capacity factor for a site over a time window.

    Parameters
    ----------
    site_id      : str
    start        : datetime  Inclusive lower bound (UTC).
    end          : datetime  Exclusive upper bound (UTC).
    session      : AsyncSession
    capacity_kwp : float | None
        DC nameplate capacity (kWp).  Typically provided by the API caller
        from SiteConfig.capacity_kwp.

    Returns
    -------
    dict
        specific_yield_kwh_kwp, capacity_factor_pct,
        target_specific_yield_kwh_kwp, e_actual_kwh,
        hours_in_window, start, end
    """
    e_actual_kwh = await _fetch_e_actual_kwh(site_id, start, end, session)
    return _compute_yield(e_actual_kwh, capacity_kwp, start, end)
