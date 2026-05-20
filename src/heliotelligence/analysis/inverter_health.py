"""Per-inverter fault detection from inverter_readings.

Groups consecutive fault timestamps (inv_avail_pct = 0 or inv_coms_status
not 'OK') into discrete fault events per inverter.

Public API
----------
analyse_inverter_health(site_id, start, end, session) -> dict
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Status values considered healthy — anything else is a comms fault
_HEALTHY_STATUSES = {"OK", "ok"}


# ---------------------------------------------------------------------------
# DB fetcher
# ---------------------------------------------------------------------------

async def _fetch_inverter_data(
    site_id: str, start: datetime, end: datetime, session: AsyncSession
) -> pd.DataFrame:
    result = await session.execute(
        text("""
            SELECT time, inverter_id, inv_avail_pct, inv_coms_status
            FROM inverter_readings
            WHERE site_id = :site_id
              AND time >= :start
              AND time < :end
            ORDER BY inverter_id ASC, time ASC
        """),
        {"site_id": site_id, "start": start, "end": end},
    )
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame(columns=["inverter_id", "inv_avail_pct", "inv_coms_status"])
    df = pd.DataFrame(
        rows, columns=["time", "inverter_id", "inv_avail_pct", "inv_coms_status"]
    )
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------

def _classify_fault(row: pd.Series) -> str | None:
    """Return fault type for a row, or None if healthy."""
    avail = row.get("inv_avail_pct")
    status = row.get("inv_coms_status")

    if avail is not None and not pd.isna(avail) and avail == 0.0:
        return "offline"

    if status is not None and not pd.isna(status) and status not in _HEALTHY_STATUSES:
        return "comms_fault"

    return None


def _group_consecutive(
    fault_rows: pd.DataFrame,
    fault_type: str,
    inverter_id: str,
    gap_threshold_hours: float = 2.0,
) -> list[dict]:
    """Group consecutive fault timestamps into events.

    Two fault timestamps are considered part of the same event if the gap
    between them is <= gap_threshold_hours.
    """
    if fault_rows.empty:
        return []

    timestamps = fault_rows.index.sort_values()
    events = []
    event_start = timestamps[0]
    event_end = timestamps[0]

    for ts in timestamps[1:]:
        gap_h = (ts - event_end).total_seconds() / 3600.0
        if gap_h <= gap_threshold_hours:
            event_end = ts
        else:
            duration_h = (event_end - event_start).total_seconds() / 3600.0
            events.append(dict(
                inverter_id=inverter_id,
                fault_type=fault_type,
                start_time=event_start,
                end_time=event_end,
                duration_hours=round(duration_h, 3),
            ))
            event_start = ts
            event_end = ts

    duration_h = (event_end - event_start).total_seconds() / 3600.0
    events.append(dict(
        inverter_id=inverter_id,
        fault_type=fault_type,
        start_time=event_start,
        end_time=event_end,
        duration_hours=round(duration_h, 3),
    ))
    return events


def _compute_inverter_health(
    df: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Detect fault events from pre-fetched inverter data (no DB access).

    Parameters
    ----------
    df : pd.DataFrame
        DatetimeIndex (UTC), columns: inverter_id, inv_avail_pct, inv_coms_status.
    start, end : datetime

    Returns
    -------
    dict
        inverter_count, fault_event_count, fault_events (list), start, end
    """
    _empty = dict(
        inverter_count=0, fault_event_count=0,
        fault_events=[], start=start, end=end,
    )

    if df.empty:
        return _empty

    inverter_count = df["inverter_id"].nunique()
    all_events: list[dict] = []

    for inv_id, inv_df in df.groupby("inverter_id"):
        # Determine fault type per row (offline takes precedence over comms)
        inv_df = inv_df.copy()
        inv_df["fault_type"] = inv_df.apply(_classify_fault, axis=1)

        for ftype in ("offline", "comms_fault"):
            fault_rows = inv_df[inv_df["fault_type"] == ftype]
            events = _group_consecutive(fault_rows, ftype, inv_id)
            all_events.extend(events)

    # Sort chronologically
    all_events.sort(key=lambda e: (e["inverter_id"], e["start_time"]))

    return dict(
        inverter_count=inverter_count,
        fault_event_count=len(all_events),
        fault_events=all_events,
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyse_inverter_health(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
) -> dict:
    """Analyse per-inverter fault events for a site over a time window.

    Parameters
    ----------
    site_id : str   UUID string.
    start   : datetime  Inclusive lower bound (UTC).
    end     : datetime  Exclusive upper bound (UTC).
    session : AsyncSession

    Returns
    -------
    dict
        inverter_count, fault_event_count,
        fault_events (list of dicts), start, end
    """
    df = await _fetch_inverter_data(site_id, start, end, session)
    return _compute_inverter_health(df, start, end)
