"""Per-string current health analysis.

For each inverter, compares mean str_current_a per string against the
inverter-wide mean.  Flags strings that are consistently under-performing.
Only uses timestamps where POA irradiance > 200 W/m² to avoid low-light noise.

Public API
----------
analyse_string_health(site_id, start, end, session, threshold_sigma=2.0) -> dict
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MIN_POA_WM2 = 200.0


# ---------------------------------------------------------------------------
# DB fetchers
# ---------------------------------------------------------------------------

async def _fetch_string_data(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> pd.DataFrame:
    """Fetch string current data filtered to irradiance > threshold."""
    result = await session.execute(
        text("""
            SELECT sr.ts AS time, sr.inverter_id, sr.string_id, sr.str_current_a
            FROM string_readings sr
            JOIN weather_readings wr
                ON wr.site_id = sr.site_id
               AND wr.ts      = sr.ts
            WHERE sr.site_id = :site_id
              AND sr.ts >= :start
              AND sr.ts < :end
              AND sr.str_current_a IS NOT NULL
              AND wr.poa_wm2 > :min_poa
            ORDER BY sr.ts ASC
        """),
        {
            "site_id": site_id,
            "start": start,
            "end": end,
            "min_poa": _MIN_POA_WM2,
        },
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["inverter_id", "string_id", "str_current_a"])
    df = pd.DataFrame(rows, columns=["time", "inverter_id", "string_id", "str_current_a"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------

def _compute_string_health(
    df: pd.DataFrame,
    threshold_sigma: float,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Detect under-performing strings from pre-fetched data (no DB access).

    Parameters
    ----------
    df : pd.DataFrame
        DatetimeIndex (UTC), columns: inverter_id, string_id, str_current_a.
    threshold_sigma : float
    start, end : datetime

    Returns
    -------
    dict
        inverter_count, string_count, flagged_strings (list), start, end
    """
    _empty = dict(
        inverter_count=0, string_count=0,
        flagged_strings=[], start=start, end=end,
    )

    if df.empty:
        return _empty

    inverter_count = df["inverter_id"].nunique()
    string_count = df.groupby(["inverter_id", "string_id"]).ngroups

    # Compute mean current per (inverter_id, string_id) over the full window
    string_means = (
        df.groupby(["inverter_id", "string_id"])["str_current_a"]
        .mean()
        .rename("mean_current_a")
        .reset_index()
    )

    flagged_strings = []

    for inv_id, inv_group in string_means.groupby("inverter_id"):
        # Skip inverters with only one string — no peer comparison possible
        if len(inv_group) < 2:
            continue

        inv_mean = float(inv_group["mean_current_a"].mean())
        inv_std = float(inv_group["mean_current_a"].std())

        if inv_std == 0.0:
            continue

        for _, row in inv_group.iterrows():
            deviation = (inv_mean - row["mean_current_a"]) / inv_std
            if deviation > threshold_sigma:
                flagged_strings.append(dict(
                    inverter_id=inv_id,
                    string_id=row["string_id"],
                    mean_current_a=round(float(row["mean_current_a"]), 4),
                    inverter_mean_a=round(inv_mean, 4),
                    deviation_sigma=round(float(deviation), 4),
                ))

    return dict(
        inverter_count=inverter_count,
        string_count=string_count,
        flagged_strings=flagged_strings,
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyse_string_health(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
    threshold_sigma: float = 2.0,
) -> dict:
    """Analyse per-string current health for a site over a time window.

    Parameters
    ----------
    site_id         : str   UUID string.
    start           : datetime  Inclusive lower bound (UTC).
    end             : datetime  Exclusive upper bound (UTC).
    session         : AsyncSession
    threshold_sigma : float  Flag threshold. Default 2.0.

    Returns
    -------
    dict
        inverter_count, string_count,
        flagged_strings (list of dicts), start, end
    """
    df = await _fetch_string_data(site_id, start, end, session)
    return _compute_string_health(df, threshold_sigma, start, end)
