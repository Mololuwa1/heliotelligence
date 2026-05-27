"""Performance Ratio calculation.

PR = Σ E_actual / Σ E_expected over the requested window.

E_actual comes from meter_readings:
  - primary:  sum(e_exported_kwh) for rows where it is non-NULL
  - fallback: integrate p_ac_kw × interval_h for rows where e_exported_kwh is NULL

E_expected is derived by integrating p_ac_kw from expected_energy.

Coverage = (timestamps with both actual and expected data) /
           (timestamps in expected_energy) × 100.

PR is set to None when coverage < 10 %.
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Threshold below which PR is reported as None rather than a misleading number.
_MIN_COVERAGE_PCT = 10.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _interval_hours(index: pd.DatetimeIndex) -> np.ndarray:
    """Return per-row forward interval in hours.

    For each row i the interval is (time[i+1] - time[i]).
    The last row repeats the second-to-last interval.

    Uses dt.total_seconds() to be independent of pandas datetime resolution
    (ns vs us), which varies across pandas versions.
    """
    n = len(index)
    if n == 0:
        return np.array([], dtype=float)
    if n == 1:
        return np.array([1.0])
    # pd.Series.diff() → Timedelta; dt.total_seconds() is resolution-independent
    diffs_s = pd.Series(index).diff().dt.total_seconds().values  # shape (n,), [0] = NaN
    diffs_h = diffs_s / 3600.0
    diffs_h[0] = diffs_h[1]   # forward-fill first element from second
    return diffs_h


def _compute_pr(
    expected_df: pd.DataFrame,
    meter_df: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> dict:
    """Compute PR metrics from pre-fetched DataFrames (no DB access).

    Parameters
    ----------
    expected_df : pd.DataFrame
        DatetimeIndex (UTC), column ``p_ac_kw``.  From expected_energy.
    meter_df : pd.DataFrame
        DatetimeIndex (UTC), columns ``p_ac_kw`` and ``e_exported_kwh``.
        From meter_readings.
    start, end : datetime
        Window bounds (used only to populate the returned dict).

    Returns
    -------
    dict with keys:
        pr              float | None  — None if coverage < 10 %
        e_actual_kwh    float
        e_expected_kwh  float
        coverage_pct    float
        start           datetime
        end             datetime
    """
    _empty = dict(
        pr=None, e_actual_kwh=0.0, e_expected_kwh=0.0,
        coverage_pct=0.0, start=start, end=end,
    )

    if expected_df.empty or "p_ac_kw" not in expected_df.columns:
        return _empty

    expected_df = expected_df.sort_index()
    intervals_h = _interval_hours(expected_df.index)
    e_expected_kwh = float(
        (expected_df["p_ac_kw"].fillna(0.0).values * intervals_h).sum()
    )

    if meter_df.empty:
        return dict(
            pr=None, e_actual_kwh=0.0, e_expected_kwh=round(e_expected_kwh, 3),
            coverage_pct=0.0, start=start, end=end,
        )

    # Align meter onto expected timestamps (left join).
    meter_aligned = meter_df.reindex(expected_df.index)

    total_count = len(expected_df)
    has_actual = (
        meter_aligned["p_ac_kw"].notna()
        | meter_aligned["e_exported_kwh"].notna()
    )
    matched_count = int(has_actual.sum())
    coverage_pct = matched_count / total_count * 100.0 if total_count > 0 else 0.0

    # ------------------------------------------------------------------
    # E_actual: prefer e_exported_kwh; fall back to integrate p_ac_kw
    # ------------------------------------------------------------------
    e_actual_kwh = 0.0

    has_export = meter_aligned["e_exported_kwh"].notna()
    if has_export.any():
        e_actual_kwh += float(meter_aligned.loc[has_export, "e_exported_kwh"].sum())

    fallback_mask = ~has_export & meter_aligned["p_ac_kw"].notna()
    if fallback_mask.any():
        fallback_power = meter_aligned.loc[fallback_mask, "p_ac_kw"].values
        fallback_intervals = intervals_h[fallback_mask.values]
        e_actual_kwh += float((fallback_power * fallback_intervals).sum())

    # ------------------------------------------------------------------
    # PR
    # ------------------------------------------------------------------
    if coverage_pct < _MIN_COVERAGE_PCT or e_expected_kwh <= 0.0:
        pr = None
    else:
        pr = round(e_actual_kwh / e_expected_kwh, 4)

    return dict(
        pr=pr,
        e_actual_kwh=round(e_actual_kwh, 3),
        e_expected_kwh=round(e_expected_kwh, 3),
        coverage_pct=round(coverage_pct, 1),
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------------
# DB fetchers
# ---------------------------------------------------------------------------

async def _fetch_expected_df(
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


async def _fetch_meter_df(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> pd.DataFrame:
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
        return pd.DataFrame(columns=["p_ac_kw", "e_exported_kwh"])
    df = pd.DataFrame(rows, columns=["time", "p_ac_kw", "e_exported_kwh"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def calculate_pr(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
) -> dict:
    """Calculate Performance Ratio for a site over a time window.

    Parameters
    ----------
    site_id : str   UUID of the site.
    start   : datetime  Inclusive lower bound (UTC).
    end     : datetime  Exclusive upper bound (UTC).
    session : AsyncSession

    Returns
    -------
    dict
        pr, e_actual_kwh, e_expected_kwh, coverage_pct, start, end
    """
    expected_df = await _fetch_expected_df(site_id, start, end, session)
    meter_df = await _fetch_meter_df(site_id, start, end, session)
    return _compute_pr(expected_df, meter_df, start, end)
