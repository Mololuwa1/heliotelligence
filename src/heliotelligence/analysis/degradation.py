"""Long-run Performance Ratio degradation analysis.

Builds a daily PR time series from meter_readings and expected_energy,
then fits a linear regression to estimate the annual degradation rate.

Public API
----------
calculate_degradation(site_id, start, end, session) -> dict
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.benchmarking.performance_ratio import _compute_pr

logger = logging.getLogger(__name__)

_MIN_DAYS_FOR_RESULT = 30
_HIGH_CONFIDENCE_DAYS = 180
_MEDIUM_CONFIDENCE_DAYS = 90


# ---------------------------------------------------------------------------
# DB fetchers (fetch full window once; slice into days in Python)
# ---------------------------------------------------------------------------

async def _fetch_expected_full(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> pd.DataFrame:
    result = await session.execute(
        text("""
            SELECT time, p_ac_kw
            FROM expected_energy
            WHERE site_id = :site_id
              AND time >= :start
              AND time < :end
            ORDER BY time ASC
        """),
        {"site_id": site_id, "start": start, "end": end},
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["p_ac_kw"])
    df = pd.DataFrame(rows, columns=["time", "p_ac_kw"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


async def _fetch_meter_full(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> pd.DataFrame:
    result = await session.execute(
        text("""
            SELECT time, p_ac_kw, e_exported_kwh
            FROM meter_readings
            WHERE site_id = :site_id
              AND time >= :start
              AND time < :end
            ORDER BY time ASC
        """),
        {"site_id": site_id, "start": start, "end": end},
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["p_ac_kw", "e_exported_kwh"])
    df = pd.DataFrame(rows, columns=["time", "p_ac_kw", "e_exported_kwh"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


# ---------------------------------------------------------------------------
# Pure computation (no DB access — testable in isolation)
# ---------------------------------------------------------------------------

def _build_daily_pr_series(
    expected_full: pd.DataFrame,
    meter_full: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> pd.Series:
    """Compute daily PR values from full-window DataFrames.

    Returns a pd.Series indexed by date (UTC midnight), one value per calendar
    day.  Days with PR=None (coverage < 10%) are dropped.
    """
    daily_prs: dict[datetime, float] = {}
    daily_exp_energy: dict[datetime, float] = {}

    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        day_end = day + timedelta(days=1)

        exp_day = expected_full[
            (expected_full.index >= day) & (expected_full.index < day_end)
        ]
        met_day = meter_full[
            (meter_full.index >= day) & (meter_full.index < day_end)
        ] if not meter_full.empty else pd.DataFrame(columns=["p_ac_kw", "e_exported_kwh"])

        result = _compute_pr(exp_day, met_day, day, day_end)
        if result["pr"] is not None:
            daily_prs[day] = result["pr"]
            daily_exp_energy[day] = result["e_expected_kwh"] or 0.0

        day = day_end

    if not daily_prs:
        return pd.Series(dtype=float)

    # Exclude low-irradiance days: remove days where expected energy < 20% of
    # the maximum daily expected energy across the window.  This prevents
    # seasonal variation (near-zero winter PR) from being mistaken for
    # long-run degradation by the linear regression.
    max_exp = max(daily_exp_energy.values()) if daily_exp_energy else 0.0
    if max_exp > 0.0:
        threshold = 0.20 * max_exp
        daily_prs = {d: pr for d, pr in daily_prs.items()
                     if daily_exp_energy.get(d, 0.0) >= threshold}

    if not daily_prs:
        return pd.Series(dtype=float)

    return pd.Series(daily_prs).sort_index()


def _compute_degradation(
    daily_pr: pd.Series,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Fit linear regression to daily PR series and return degradation metrics.

    Parameters
    ----------
    daily_pr : pd.Series
        Daily PR values indexed by UTC datetime.
    start, end : datetime
        Window bounds (used only to populate returned dict).

    Returns
    -------
    dict
        rate_pct_per_year, r_squared, window_days, first_pr, last_pr,
        confidence, start, end
    """
    _null = dict(
        rate_pct_per_year=None, r_squared=None, window_days=len(daily_pr),
        first_pr=None, last_pr=None, confidence=None, start=start, end=end,
    )

    n = len(daily_pr)
    if n < _MIN_DAYS_FOR_RESULT:
        return _null

    # x = days since first observation (float)
    x = np.arange(n, dtype=float)
    y = daily_pr.values.astype(float)

    coeffs = np.polyfit(x, y, deg=1)
    slope_per_day = coeffs[0]
    rate_pct_per_year = slope_per_day * 365.0 * 100.0  # fraction/day → %/year

    y_pred = np.polyval(coeffs, x)
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 0.0

    if n >= _HIGH_CONFIDENCE_DAYS:
        confidence = "high"
    elif n >= _MEDIUM_CONFIDENCE_DAYS:
        confidence = "medium"
    else:
        confidence = "low"

    return dict(
        rate_pct_per_year=round(rate_pct_per_year, 4),
        r_squared=round(r_squared, 4),
        window_days=n,
        first_pr=round(float(daily_pr.iloc[0]), 4),
        last_pr=round(float(daily_pr.iloc[-1]), 4),
        confidence=confidence,
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def calculate_degradation(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
) -> dict:
    """Calculate long-run PR degradation rate for a site.

    Parameters
    ----------
    site_id : str   UUID string.
    start   : datetime  Inclusive lower bound (UTC).
    end     : datetime  Exclusive upper bound (UTC).
    session : AsyncSession

    Returns
    -------
    dict
        rate_pct_per_year  float | None  — negative = degrading
        r_squared          float | None
        window_days        int
        first_pr           float | None
        last_pr            float | None
        confidence         'high' | 'medium' | 'low' | None
        start, end         datetime
    """
    expected_full = await _fetch_expected_full(site_id, start, end, session)
    meter_full = await _fetch_meter_full(site_id, start, end, session)
    daily_pr = _build_daily_pr_series(expected_full, meter_full, start, end)
    return _compute_degradation(daily_pr, start, end)
