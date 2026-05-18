"""Async upsert of physics pipeline output to expected_energy.

Uses PostgreSQL INSERT ... ON CONFLICT (time, site_id, source) DO UPDATE
so that re-running the pipeline for the same window is idempotent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.config.site import SiteConfig

logger = logging.getLogger(__name__)

_SOURCE = "physics_sdm"


async def upsert_expected_energy(
    site: SiteConfig,
    df: pd.DataFrame,
    session: AsyncSession,
) -> int:
    """Upsert a DataFrame of physics results to expected_energy.

    Parameters
    ----------
    site : SiteConfig
    df : pd.DataFrame
        DatetimeIndex (UTC-aware).  Expected columns:
          p_ac_kw, p_dc_kw, p_dc_stc_kw,
          poa_total_wm2, t_cell_c,
          tier_used, fit_quality
    session : AsyncSession
        Live session; caller commits.

    Returns
    -------
    int — number of rows upserted.
    """
    if df.empty:
        return 0

    rows = []
    for ts, row in df.iterrows():
        # Ensure timestamp is UTC-aware
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        rows.append(
            {
                "time": ts,
                "site_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)),
                "source": _SOURCE,
                "p_ac_kw": _float_or_none(row.get("p_ac_kw")),
                "p_dc_kw": _float_or_none(row.get("p_dc_kw")),
                "p_dc_stc_kw": _float_or_none(row.get("p_dc_stc_kw")),
                "poa_total_wm2": _float_or_none(row.get("poa_total_wm2")),
                "t_cell_c": _float_or_none(row.get("t_cell_c")),
                "tier_used": _int_or_none(row.get("tier_used")),
                "fit_quality": row.get("fit_quality") or None,
                "quality": 0,
            }
        )

    stmt = text("""
        INSERT INTO expected_energy
            (time, site_id, source,
             p_ac_kw, p_dc_kw, p_dc_stc_kw,
             poa_total_wm2, t_cell_c,
             tier_used, fit_quality, quality)
        VALUES
            (:time, :site_id, :source,
             :p_ac_kw, :p_dc_kw, :p_dc_stc_kw,
             :poa_total_wm2, :t_cell_c,
             :tier_used, :fit_quality, :quality)
        ON CONFLICT (time, site_id, source) DO UPDATE SET
            p_ac_kw       = EXCLUDED.p_ac_kw,
            p_dc_kw       = EXCLUDED.p_dc_kw,
            p_dc_stc_kw   = EXCLUDED.p_dc_stc_kw,
            poa_total_wm2 = EXCLUDED.poa_total_wm2,
            t_cell_c      = EXCLUDED.t_cell_c,
            tier_used     = EXCLUDED.tier_used,
            fit_quality   = EXCLUDED.fit_quality,
            quality       = EXCLUDED.quality
    """)

    await session.execute(stmt, rows)
    logger.debug(
        "Upserted %d rows to expected_energy for site %s.", len(rows), site.id
    )
    return len(rows)


def _float_or_none(val) -> float | None:
    """Convert a value to float, returning None for NaN/None."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _int_or_none(val) -> int | None:
    """Convert a value to int, returning None for NaN/None."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return None
