"""Short-run anomaly detection on AC power residuals.

Compares meter_readings.p_ac_kw against expected_energy.p_ac_kw at each
matching timestamp.  Flags timestamps where the absolute residual exceeds
threshold_sigma standard deviations.  Nighttime rows (expected < 1.0 kW)
are excluded to avoid false positives from night-time noise.

Public API
----------
detect_anomalies(site_id, start, end, session, threshold_sigma=2.0) -> dict
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DAYTIME_THRESHOLD_KW = 1.0  # expected p_ac_kw must exceed this to flag


# ---------------------------------------------------------------------------
# DB fetchers
# ---------------------------------------------------------------------------

async def _fetch_joined(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> pd.DataFrame:
    """Fetch aligned (time, actual_kw, expected_kw) for the window."""
    result = await session.execute(
        text("""
            SELECT
                ee.time,
                mr.p_ac_kw  AS actual_kw,
                ee.p_ac_kw  AS expected_kw
            FROM expected_energy ee
            LEFT JOIN meter_readings mr
                ON mr.site_id = ee.site_id
               AND mr.ts      = ee.time
            WHERE ee.site_id = :site_id
              AND ee.time >= :start
              AND ee.time < :end
            ORDER BY ee.time ASC
        """),
        {"site_id": site_id, "start": start, "end": end},
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["actual_kw", "expected_kw"])
    df = pd.DataFrame(rows, columns=["time", "actual_kw", "expected_kw"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------

def _compute_anomalies(
    joined: pd.DataFrame,
    threshold_sigma: float,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Detect anomalies from a pre-joined DataFrame (no DB access).

    Parameters
    ----------
    joined : pd.DataFrame
        DatetimeIndex (UTC), columns: actual_kw, expected_kw.
    threshold_sigma : float
    start, end : datetime

    Returns
    -------
    dict
        flagged_count, total_count, flag_rate_pct,
        flags (list of dicts), start, end
    """
    _empty = dict(
        flagged_count=0, total_count=0, flag_rate_pct=0.0,
        flags=[], start=start, end=end,
    )

    if joined.empty:
        return _empty

    # Only daytime rows with both actual and expected present
    daytime = joined[
        joined["expected_kw"].notna()
        & (joined["expected_kw"] > _DAYTIME_THRESHOLD_KW)
        & joined["actual_kw"].notna()
    ].copy()

    total_count = len(daytime)
    if total_count == 0:
        return _empty

    daytime["residual"] = daytime["actual_kw"] - daytime["expected_kw"]
    residual_std = float(daytime["residual"].std())

    if residual_std == 0.0:
        return dict(
            flagged_count=0, total_count=total_count, flag_rate_pct=0.0,
            flags=[], start=start, end=end,
        )

    daytime["sigma"] = daytime["residual"].abs() / residual_std
    flagged = daytime[daytime["sigma"] > threshold_sigma]

    flags = []
    for ts, row in flagged.iterrows():
        flags.append(dict(
            time=ts,
            actual_kw=round(float(row["actual_kw"]), 3),
            expected_kw=round(float(row["expected_kw"]), 3),
            residual_kw=round(float(row["residual"]), 3),
            sigma=round(float(row["sigma"]), 3),
        ))

    flagged_count = len(flags)
    flag_rate_pct = round(flagged_count / total_count * 100.0, 2)

    return dict(
        flagged_count=flagged_count,
        total_count=total_count,
        flag_rate_pct=flag_rate_pct,
        flags=flags,
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def detect_anomalies(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
    threshold_sigma: float = 2.0,
) -> dict:
    """Detect AC power anomalies for a site over a time window.

    Parameters
    ----------
    site_id         : str   UUID string.
    start           : datetime  Inclusive lower bound (UTC).
    end             : datetime  Exclusive upper bound (UTC).
    session         : AsyncSession
    threshold_sigma : float  Flag threshold in std deviations. Default 2.0.

    Returns
    -------
    dict
        flagged_count, total_count, flag_rate_pct,
        flags (list), start, end
    """
    joined = await _fetch_joined(site_id, start, end, session)
    return _compute_anomalies(joined, threshold_sigma, start, end)
