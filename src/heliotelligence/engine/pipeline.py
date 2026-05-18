"""Layer 4 expected-energy pipeline orchestrator.

Public API
----------
run_pipeline(site, session, *, chunk_hours=24, lookback_days=30) -> dict

Catch-up logic
--------------
On each run the pipeline:
  1. Queries the latest time in expected_energy for the site.
     If no rows exist, defaults to (now - lookback_days).
  2. Queries the latest time in weather_readings for the site.
     If no rows exist, returns early.
  3. Processes the window [catch_up_from, catch_up_to] in chunks of
     chunk_hours to cap memory usage.
  4. Upserts each chunk to expected_energy before moving to the next.

Physics chain (per chunk)
--------------------------
  fetch_weather → calculate_poa → calculate_cell_temp
  → calculate_dc_power → calculate_ac_power → upsert_expected_energy
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.config.site import SiteConfig
from heliotelligence.engine.inverter import calculate_ac_power
from heliotelligence.engine.upsert import upsert_expected_energy
from heliotelligence.engine.weather_query import (
    fetch_weather,
    get_latest_expected_energy_time,
    get_latest_weather_time,
)
from heliotelligence.physics.electrical import calculate_dc_power
from heliotelligence.physics.irradiance import calculate_poa
from heliotelligence.physics.thermal import calculate_cell_temp

logger = logging.getLogger(__name__)


async def run_pipeline(
    site: SiteConfig,
    session: AsyncSession,
    *,
    chunk_hours: int = 24,
    lookback_days: int = 30,
) -> dict:
    """Run the catch-up expected-energy pipeline for one site.

    Parameters
    ----------
    site : SiteConfig
    session : AsyncSession
        Live async DB session; caller is responsible for commit/rollback.
    chunk_hours : int
        Size of each processing window in hours. Default 24.
    lookback_days : int
        How far back to start when no prior expected_energy rows exist.

    Returns
    -------
    dict with keys:
        site_id       str
        rows_upserted int   — total rows written to expected_energy
        chunks_run    int   — number of chunks processed
        start_time    datetime | None — earliest timestamp processed
        end_time      datetime | None — latest timestamp processed
    """
    now_utc = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Determine catch-up window
    # ------------------------------------------------------------------
    latest_expected = await get_latest_expected_energy_time(str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)), session)
    catch_up_from = (
        latest_expected
        if latest_expected is not None
        else now_utc - timedelta(days=lookback_days)
    )

    latest_weather = await get_latest_weather_time(str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)), session)
    if latest_weather is None:
        logger.info(
            "Site %s: no weather_readings found — pipeline skipped.", site.id
        )
        return _result(site.id, 0, 0, None, None)

    catch_up_to = latest_weather

    if catch_up_from >= catch_up_to:
        logger.info(
            "Site %s: expected_energy already up to date (latest=%s).",
            site.id, catch_up_from.isoformat(),
        )
        return _result(site.id, 0, 0, None, None)

    logger.info(
        "Site %s: running pipeline from %s to %s in %dh chunks.",
        site.id,
        catch_up_from.isoformat(),
        catch_up_to.isoformat(),
        chunk_hours,
    )

    # ------------------------------------------------------------------
    # Chunk loop
    # ------------------------------------------------------------------
    total_rows = 0
    chunks_run = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    chunk_start = catch_up_from
    chunk_delta = timedelta(hours=chunk_hours)

    while chunk_start < catch_up_to:
        chunk_end = min(chunk_start + chunk_delta, catch_up_to)

        rows = await _run_chunk(site, session, chunk_start, chunk_end)

        if rows > 0:
            total_rows += rows
            chunks_run += 1
            if first_ts is None:
                first_ts = chunk_start
            last_ts = chunk_end

        chunk_start = chunk_end

    logger.info(
        "Site %s: pipeline complete — %d rows upserted across %d chunks.",
        site.id, total_rows, chunks_run,
    )
    return _result(site.id, total_rows, chunks_run, first_ts, last_ts)


async def _run_chunk(
    site: SiteConfig,
    session: AsyncSession,
    start: datetime,
    end: datetime,
) -> int:
    """Run one physics chunk and upsert results.

    Parameters
    ----------
    site : SiteConfig
    session : AsyncSession
    start : datetime — inclusive
    end : datetime   — exclusive

    Returns
    -------
    int — number of rows upserted (0 if weather data was empty).
    """
    # --- Fetch ---------------------------------------------------------------
    weather_df = await fetch_weather(site, start, end, session)
    if weather_df.empty:
        logger.debug(
            "Site %s: empty weather window [%s, %s) — skipping chunk.",
            site.id, start.isoformat(), end.isoformat(),
        )
        return 0

    # Fill any missing wind/temp with conservative defaults so downstream
    # models don't NaN-out entirely on partial data.
    wind = weather_df["wind_speed_ms"].fillna(1.0)
    temp_amb = weather_df["temp_amb_c"].fillna(15.0)
    temp_mod = weather_df.get("temp_mod_avg_c")

    # --- Irradiance ----------------------------------------------------------
    poa_df = calculate_poa(site, weather_df)
    poa_total = poa_df["poa_total"].fillna(0.0)
    aoi = poa_df["aoi"]
    solar_zenith = poa_df["solar_zenith"]

    # --- Thermal -------------------------------------------------------------
    t_cell = calculate_cell_temp(
        site,
        poa_total=poa_total,
        temp_amb=temp_amb,
        wind_speed=wind,
        temp_module_measured=temp_mod,
    )

    # --- DC electrical -------------------------------------------------------
    dc_df = calculate_dc_power(
        site,
        poa_total=poa_total,
        t_cell=t_cell,
        aoi=aoi,
        solar_zenith=solar_zenith,
    )

    # --- AC inverter ---------------------------------------------------------
    ac_df = calculate_ac_power(site, dc_df["p_dc_kw"])

    # --- Merge results -------------------------------------------------------
    merged = pd.DataFrame(
        {
            "p_ac_kw": ac_df["p_ac_kw"],
            "p_dc_kw": dc_df["p_dc_kw"],
            "p_dc_stc_kw": dc_df["p_dc_stc_kw"],
            "poa_total_wm2": poa_total,
            "t_cell_c": t_cell,
            "tier_used": dc_df["tier_used"],
            "fit_quality": dc_df["fit_quality"],
        },
        index=weather_df.index,
    )

    # --- Upsert --------------------------------------------------------------
    rows = await upsert_expected_energy(site, merged, session)
    logger.debug(
        "Site %s: chunk [%s, %s) → %d rows upserted.",
        site.id, start.isoformat(), end.isoformat(), rows,
    )
    return rows


def _result(
    site_id: str,
    rows_upserted: int,
    chunks_run: int,
    start_time: datetime | None,
    end_time: datetime | None,
) -> dict:
    return {
        "site_id": site_id,
        "rows_upserted": rows_upserted,
        "chunks_run": chunks_run,
        "start_time": start_time,
        "end_time": end_time,
    }
