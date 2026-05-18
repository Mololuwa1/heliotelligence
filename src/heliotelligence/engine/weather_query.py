"""Fetch weather_readings from TimescaleDB for a site+time window.

Public API
----------
fetch_weather(site, start, end, session, *, max_quality=1) -> pd.DataFrame

DHI/DNI fallback
----------------
Bracon Ash weather station does not record DHI or DNI directly.  When
both columns are NULL in the DB, this module derives them from GHI using
the Erbs decomposition model (pvlib.irradiance.erbs).  Rows where GHI is
also NULL are dropped.

Quality filtering
-----------------
Only rows with quality < max_quality are returned (default: quality < 2,
i.e. 'good' rows only; gap-filled rows excluded).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.config.site import SiteConfig
from heliotelligence.models.orm import WeatherReading

logger = logging.getLogger(__name__)

# Columns fetched from DB → DataFrame column names
_SELECT_COLS = [
    WeatherReading.time,
    WeatherReading.ghi_wm2,
    WeatherReading.dhi_wm2,
    WeatherReading.dni_wm2,
    WeatherReading.poa_wm2,
    WeatherReading.temp_amb_c,
    WeatherReading.temp_mod_avg_c,
    WeatherReading.wind_speed_ms,
    WeatherReading.quality,
]


async def fetch_weather(
    site: SiteConfig,
    start: datetime,
    end: datetime,
    session: AsyncSession,
    *,
    max_quality: int = 1,
) -> pd.DataFrame:
    """Fetch weather_readings for a site over a time window.

    Parameters
    ----------
    site : SiteConfig
    start : datetime
        Inclusive lower bound (UTC).
    end : datetime
        Exclusive upper bound (UTC).
    session : AsyncSession
        Live async DB session.
    max_quality : int
        Exclude rows with quality >= max_quality.  Default 1 (good only).
        Pass 2 to include gap-filled rows.

    Returns
    -------
    pd.DataFrame
        DatetimeIndex (UTC), one row per timestamp.  Columns:
          ghi_wm2, dhi_wm2, dni_wm2, poa_wm2,
          temp_amb_c, temp_mod_avg_c, wind_speed_ms

        When dhi_wm2 and dni_wm2 are NULL and ghi_wm2 is available,
        they are derived via pvlib.irradiance.erbs().  Rows where ghi_wm2
        is also NULL are dropped.

        Returns an empty DataFrame (columns present, zero rows) if no
        rows exist in the window.
    """
    stmt = (
        select(*_SELECT_COLS)
        .where(WeatherReading.site_id == str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)))
        .where(WeatherReading.time >= start)
        .where(WeatherReading.time < end)
        .where(WeatherReading.quality < max_quality)
        .order_by(WeatherReading.time)
    )

    result = await session.execute(stmt)
    rows = result.fetchall()

    _empty_cols = [
        "ghi_wm2", "dhi_wm2", "dni_wm2", "poa_wm2",
        "temp_amb_c", "temp_mod_avg_c", "wind_speed_ms",
    ]

    if not rows:
        logger.debug(
            "No weather rows for site %s in [%s, %s).", site.id, start, end
        )
        return pd.DataFrame(columns=_empty_cols)

    df = pd.DataFrame(rows, columns=[c.key for c in _SELECT_COLS])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df = df.drop(columns=["quality"])

    # ------------------------------------------------------------------
    # DHI / DNI derivation via Erbs decomposition
    # ------------------------------------------------------------------
    need_erbs = df["dhi_wm2"].isna() & df["dni_wm2"].isna()
    has_ghi = df["ghi_wm2"].notna()

    # Rows where GHI is also NULL cannot be modelled — drop them if they
    # have no poa_wm2 either (nothing useful for the physics pipeline).
    unusable = need_erbs & ~has_ghi & df["poa_wm2"].isna()
    if unusable.any():
        logger.debug(
            "Dropping %d rows for site %s: GHI, DHI, DNI and POA all NULL.",
            int(unusable.sum()), site.id,
        )
        df = df[~unusable]

    # Recompute masks after the unusable-row filter so lengths stay aligned.
    need_erbs = df["dhi_wm2"].isna() & df["dni_wm2"].isna()
    erbs_rows = need_erbs & df["ghi_wm2"].notna()
    if erbs_rows.any():
        df = _apply_erbs(df, erbs_rows, site)

    logger.info(
        "Fetched %d weather rows for site %s in [%s, %s).",
        len(df), site.id, start, end,
    )
    return df


def _apply_erbs(
    df: pd.DataFrame,
    mask: pd.Series,
    site: SiteConfig,
) -> pd.DataFrame:
    """Derive DHI and DNI from GHI using the Erbs decomposition model.

    Uses pvlib.irradiance.erbs(ghi, zenith, datetime_index).
    Solar zenith is computed from site location for the affected timestamps.

    Parameters
    ----------
    df : pd.DataFrame
        Full weather DataFrame with DatetimeIndex (UTC).
    mask : pd.Series[bool]
        True for rows that need Erbs derivation.
    site : SiteConfig

    Returns
    -------
    pd.DataFrame
        Same DataFrame with dhi_wm2 and dni_wm2 filled for masked rows.
    """
    import pvlib
    import pvlib.irradiance

    location = pvlib.location.Location(
        latitude=site.latitude,
        longitude=site.longitude,
        tz="UTC",
        altitude=site.altitude_m,
    )

    erbs_index = df.index[mask]
    solar_pos = location.get_solarposition(erbs_index)
    zenith = solar_pos["apparent_zenith"]

    ghi_sub = df.loc[mask, "ghi_wm2"]
    erbs_result = pvlib.irradiance.erbs(ghi_sub, zenith, erbs_index)

    df.loc[mask, "dhi_wm2"] = erbs_result["dhi"].values
    df.loc[mask, "dni_wm2"] = erbs_result["dni"].values

    logger.info(
        "Erbs decomposition applied to %d rows for site %s.",
        int(mask.sum()), site.id,
    )
    return df


async def get_latest_expected_energy_time(
    site_id: str,
    session: AsyncSession,
) -> datetime | None:
    """Return the latest time in expected_energy for a site, or None.

    Parameters
    ----------
    site_id : str
    session : AsyncSession

    Returns
    -------
    datetime (UTC-aware) or None if no rows exist for this site.
    """
    result = await session.execute(
        text(
            "SELECT MAX(time) FROM expected_energy WHERE site_id = :site_id"
        ),
        {"site_id": site_id},
    )
    row = result.fetchone()
    if row and row[0] is not None:
        ts = row[0]
        if ts.tzinfo is None:
            import pytz
            ts = pytz.utc.localize(ts)
        return ts
    return None


async def get_latest_weather_time(
    site_id: str,
    session: AsyncSession,
) -> datetime | None:
    """Return the latest time in weather_readings for a site, or None.

    Parameters
    ----------
    site_id : str
    session : AsyncSession

    Returns
    -------
    datetime (UTC-aware) or None if no rows exist for this site.
    """
    result = await session.execute(
        text(
            "SELECT MAX(time) FROM weather_readings WHERE site_id = :site_id"
        ),
        {"site_id": site_id},
    )
    row = result.fetchone()
    if row and row[0] is not None:
        ts = row[0]
        if ts.tzinfo is None:
            import pytz
            ts = pytz.utc.localize(ts)
        return ts
    return None
