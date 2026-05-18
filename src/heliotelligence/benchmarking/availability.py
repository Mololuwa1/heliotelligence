"""Plant availability calculation from inverter_readings.

Availability is computed as the mean of inv_avail_pct across all inverters
and all timestamps in the window.

When SiteConfig is available (pnom_kwac set), inverters are grouped by ID and
their per-inverter mean is averaged across inverters (equal-capacity weighted).
When site config is absent, a simple count-average of all rows is used.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig, load_sites

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_site_config(site_id: str) -> SiteConfig | None:
    sites = load_sites(settings.site_config_path)
    for site in sites:
        if site.id == site_id:
            return site
    return None


def _compute_availability(
    avail_df: pd.DataFrame,
    site: SiteConfig | None,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Compute availability metrics from a pre-fetched DataFrame (no DB access).

    Parameters
    ----------
    avail_df : pd.DataFrame
        Columns ``inverter_id`` (str) and ``inv_avail_pct`` (float).
        DatetimeIndex (UTC).  May be empty.
    site : SiteConfig | None
        Used to determine weighting method label.
    start, end : datetime
        Window bounds.

    Returns
    -------
    dict
        availability_pct  float | None  — mean availability (0–100)
        method            str
        inverter_count    int
        start, end        datetime
    """
    if avail_df.empty or "inv_avail_pct" not in avail_df.columns:
        return dict(
            availability_pct=None,
            method="no_data",
            inverter_count=0,
            start=start,
            end=end,
        )

    valid = avail_df["inv_avail_pct"].dropna()
    if valid.empty:
        return dict(
            availability_pct=None,
            method="no_valid_readings",
            inverter_count=0,
            start=start,
            end=end,
        )

    has_id_col = "inverter_id" in avail_df.columns
    inverter_count = int(avail_df["inverter_id"].nunique()) if has_id_col else 0

    # When capacity data is available all inverters have the same pnom_kwac, so
    # weighted-by-capacity mean equals simple mean.  We group by inverter ID
    # first to give each unit equal weight regardless of its reporting frequency.
    if site is not None and site.inverter.pnom_kwac is not None and has_id_col:
        per_inverter = avail_df.groupby("inverter_id")["inv_avail_pct"].mean()
        availability_pct = float(per_inverter.mean())
        method = "weighted_equal_capacity"
    else:
        availability_pct = float(valid.mean())
        method = "count_average"

    return dict(
        availability_pct=round(availability_pct, 3),
        method=method,
        inverter_count=inverter_count,
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------------
# DB fetcher
# ---------------------------------------------------------------------------

async def _fetch_avail_df(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> pd.DataFrame:
    result = await session.execute(
        text("""
            SELECT time, inverter_id, inv_avail_pct
            FROM inverter_readings
            WHERE site_id = :site_id
              AND time >= :start
              AND time < :end
              AND inv_avail_pct IS NOT NULL
            ORDER BY time ASC
        """),
        {"site_id": site_id, "start": start, "end": end},
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["inverter_id", "inv_avail_pct"])
    df = pd.DataFrame(rows, columns=["time", "inverter_id", "inv_avail_pct"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def calculate_availability(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
) -> dict:
    """Calculate plant availability for a site over a time window.

    Parameters
    ----------
    site_id : str
    start   : datetime  Inclusive lower bound (UTC).
    end     : datetime  Exclusive upper bound (UTC).
    session : AsyncSession

    Returns
    -------
    dict
        availability_pct  float | None
        method            str
        inverter_count    int
        start, end        datetime
    """
    site = _load_site_config(site_id)
    avail_df = await _fetch_avail_df(site_id, start, end, session)
    return _compute_availability(avail_df, site, start, end)
