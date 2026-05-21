"""Loss waterfall decomposition.

All loss buckets are expressed as a percentage of E_exp_stc (nameplate DC at STC
conditions × irradiance × interval, summed over the window).

Loss buckets
────────────
optical_pct       config-based: soiling_loss_pct + lid_loss_pct
temperature_pct   data-derived: residual DC gap after optical + dc_losses removed
dc_losses_pct     config-based: wiring_loss_dc_pct + mismatch_loss_pct
inverter_pct      data-derived: (E_exp_dc − E_exp_ac) / E_exp_stc − clipping
clipping_pct      data-derived: estimated energy lost to inverter/grid clipping
availability_pct  data-derived: energy lost to inverter unavailability
                  (note: this is an energy-loss %, not a plant-availability %)
unaccounted_pct   residual not attributed to any modelled cause — may be positive
                  (underperformance) or negative (overperformance relative to model)

When site config cannot be resolved, optical_pct, dc_losses_pct, clipping_pct,
and unaccounted_pct are returned as None.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.config.settings import settings
from heliotelligence.config.site import SiteConfig, load_sites
from heliotelligence.benchmarking.availability import (
    _fetch_avail_df,
    _compute_availability,
)

logger = logging.getLogger(__name__)

_GAMMA_PMP = -0.29  # %/°C — temperature coefficient of maximum power (Pmax)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_site_config(site_id: str) -> SiteConfig | None:
    sites = load_sites(settings.site_config_path)
    for site in sites:
        if str(uuid.uuid5(uuid.NAMESPACE_DNS, site.id)) == site_id:
            return site
    return None


def _interval_hours(index: pd.DatetimeIndex) -> np.ndarray:
    """Per-row forward interval in hours; last row repeats second-to-last.

    Uses dt.total_seconds() to be independent of pandas datetime resolution
    (ns vs us), which varies across pandas versions.
    """
    n = len(index)
    if n == 0:
        return np.array([], dtype=float)
    if n == 1:
        return np.array([1.0])
    diffs_s = pd.Series(index).diff().dt.total_seconds().values
    diffs_h = diffs_s / 3600.0
    diffs_h[0] = diffs_h[1]
    return diffs_h


def _integrate(series: pd.Series, intervals_h: np.ndarray) -> float:
    """Rectangular integration of power (kW) → energy (kWh)."""
    return float((series.fillna(0.0).values * intervals_h).sum())


def _e_actual_from_meter(
    meter_df: pd.DataFrame,
    aligned_index: pd.DatetimeIndex,
    intervals_h: np.ndarray,
) -> float:
    """Compute E_actual (kWh) from meter_df aligned to expected_df index.

    Prefers e_exported_kwh; falls back to integrate p_ac_kw for NULL rows.
    """
    if meter_df.empty:
        return 0.0

    aligned = meter_df.reindex(aligned_index)
    e_actual = 0.0

    has_export = aligned["e_exported_kwh"].notna()
    if has_export.any():
        e_actual += float(aligned.loc[has_export, "e_exported_kwh"].sum())

    fallback = ~has_export & aligned["p_ac_kw"].notna()
    if fallback.any():
        power = aligned.loc[fallback, "p_ac_kw"].values
        ivh = intervals_h[fallback.values]
        e_actual += float((power * ivh).sum())

    return e_actual


def _compute_losses(
    expected_df: pd.DataFrame,
    meter_df: pd.DataFrame,
    site: SiteConfig | None,
    availability_level_pct: float | None,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Compute loss waterfall metrics from pre-fetched data (no DB access).

    Parameters
    ----------
    expected_df : pd.DataFrame
        DatetimeIndex (UTC), columns: p_dc_stc_kw, p_dc_kw, p_ac_kw.
    meter_df : pd.DataFrame
        DatetimeIndex (UTC), columns: p_ac_kw, e_exported_kwh.
    site : SiteConfig | None
        Config-based loss percentages and inverter parameters.
    availability_level_pct : float | None
        Mean plant availability (0–100 %) from inverter_readings.
        Used to estimate the energy-loss share attributable to downtime.
    start, end : datetime

    Returns
    -------
    dict
        optical_pct, temperature_pct, dc_losses_pct, inverter_pct,
        clipping_pct, availability_pct (energy loss, not availability level),
        unaccounted_pct, e_exp_stc_kwh, e_exp_kwh, e_actual_kwh, start, end
    """
    _null_result: dict[str, Any] = dict(
        optical_pct=None, temperature_pct=None, dc_losses_pct=None,
        inverter_pct=None, clipping_pct=None, availability_pct=None,
        unaccounted_pct=None, e_exp_stc_kwh=0.0, e_exp_kwh=0.0,
        e_actual_kwh=0.0, start=start, end=end,
    )

    if expected_df.empty:
        return _null_result

    expected_df = expected_df.sort_index()
    intervals_h = _interval_hours(expected_df.index)

    e_exp_stc_kwh = _integrate(expected_df["p_dc_stc_kw"], intervals_h)
    e_exp_dc_kwh = _integrate(expected_df["p_dc_kw"], intervals_h)
    e_exp_ac_kwh = _integrate(expected_df["p_ac_kw"], intervals_h)
    e_actual_kwh = _e_actual_from_meter(meter_df, expected_df.index, intervals_h)

    if e_exp_stc_kwh <= 0.0:
        return _null_result

    # ------------------------------------------------------------------
    # Config-based DC loss buckets (known from module design parameters)
    # ------------------------------------------------------------------
    if site is not None:
        optical_pct = site.module.soiling_loss_pct + site.module.lid_loss_pct
        dc_losses_pct = (
            site.module.wiring_loss_dc_pct + site.module.mismatch_loss_pct
        )
    else:
        optical_pct = None
        dc_losses_pct = None

    # ------------------------------------------------------------------
    # Temperature: physics-correct formula using mean cell temperature.
    # Loss = |gamma_pmp| × (t_cell - 25°C), clamped to 0 when t_cell ≤ 25°C.
    # ------------------------------------------------------------------
    if "t_cell_c" in expected_df.columns:
        t_cell_valid = expected_df["t_cell_c"].dropna()
        if len(t_cell_valid) > 0:
            mean_t_cell = float(t_cell_valid.mean())
            temperature_pct = max(
                0.0,
                (-_GAMMA_PMP / 100.0) * (mean_t_cell - 25.0) * 100.0,
            )
        else:
            temperature_pct = None
    else:
        temperature_pct = None

    # ------------------------------------------------------------------
    # Inverter conversion + clipping (data-derived from expected_energy)
    # ------------------------------------------------------------------
    inverter_and_clip_pct = (e_exp_dc_kwh - e_exp_ac_kwh) / e_exp_stc_kwh * 100.0

    if site is not None:
        eta = site.inverter.eta_nom
        wiring_f = 1.0 - site.inverter.wiring_loss_ac_pct / 100.0
        # Estimate the AC power before wiring loss was applied
        p_ac_before_wiring = expected_df["p_ac_kw"] / wiring_f
        # Unclipped AC = what the inverter would produce without capacity limits
        p_ac_unclipped = expected_df["p_dc_kw"] * eta
        # Clipping loss = gap between unclipped and actual-before-wiring
        clipped_kw = (p_ac_unclipped - p_ac_before_wiring).clip(lower=0.0)
        e_clipped_kwh = _integrate(clipped_kw, intervals_h)
        clipping_pct = e_clipped_kwh / e_exp_stc_kwh * 100.0
        inverter_pct = max(0.0, inverter_and_clip_pct - clipping_pct)
    else:
        clipping_pct = None
        inverter_pct = inverter_and_clip_pct

    # ------------------------------------------------------------------
    # Availability loss % (convert availability level → energy-loss %)
    # ------------------------------------------------------------------
    if availability_level_pct is not None:
        # If the plant was X% available, (100-X)% of expected AC was lost
        avail_loss_pct = (
            (1.0 - availability_level_pct / 100.0)
            * (e_exp_ac_kwh / e_exp_stc_kwh)
            * 100.0
        )
    else:
        avail_loss_pct = None

    # ------------------------------------------------------------------
    # Unaccounted residual
    # ------------------------------------------------------------------
    have_all = (
        optical_pct is not None
        and temperature_pct is not None
        and dc_losses_pct is not None
        and clipping_pct is not None
    )
    if have_all:
        total_gap_pct = (e_exp_stc_kwh - e_actual_kwh) / e_exp_stc_kwh * 100.0
        avail = avail_loss_pct if avail_loss_pct is not None else 0.0
        unaccounted_pct = (
            total_gap_pct
            - optical_pct
            - temperature_pct
            - dc_losses_pct
            - inverter_pct
            - clipping_pct
            - avail
        )
    else:
        unaccounted_pct = None

    def _r(v: float | None) -> float | None:
        return round(v, 3) if v is not None else None

    return dict(
        optical_pct=_r(optical_pct),
        temperature_pct=_r(temperature_pct),
        dc_losses_pct=_r(dc_losses_pct),
        inverter_pct=_r(inverter_pct),
        clipping_pct=_r(clipping_pct),
        availability_pct=_r(avail_loss_pct),
        unaccounted_pct=_r(unaccounted_pct),
        e_exp_stc_kwh=round(e_exp_stc_kwh, 3),
        e_exp_kwh=round(e_exp_ac_kwh, 3),
        e_actual_kwh=round(e_actual_kwh, 3),
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
            SELECT time, p_dc_stc_kw, p_dc_kw, p_ac_kw, t_cell_c
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
        return pd.DataFrame(columns=["p_dc_stc_kw", "p_dc_kw", "p_ac_kw", "t_cell_c"])
    df = pd.DataFrame(rows, columns=["time", "p_dc_stc_kw", "p_dc_kw", "p_ac_kw", "t_cell_c"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


async def _fetch_meter_df(
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
# Public API
# ---------------------------------------------------------------------------

async def calculate_losses(
    site_id: str,
    start: datetime,
    end: datetime,
    session: AsyncSession,
) -> dict:
    """Compute loss waterfall for a site over a time window.

    Parameters
    ----------
    site_id : str
    start   : datetime  Inclusive lower bound (UTC).
    end     : datetime  Exclusive upper bound (UTC).
    session : AsyncSession

    Returns
    -------
    dict
        optical_pct, temperature_pct, dc_losses_pct, inverter_pct,
        clipping_pct, availability_pct (energy loss %), unaccounted_pct,
        e_exp_stc_kwh, e_exp_kwh, e_actual_kwh, start, end
    """
    site = _load_site_config(site_id)

    expected_df = await _fetch_expected_df(site_id, start, end, session)
    meter_df = await _fetch_meter_df(site_id, start, end, session)
    avail_df = await _fetch_avail_df(site_id, start, end, session)

    avail_result = _compute_availability(avail_df, site, start, end)
    availability_level_pct = avail_result.get("availability_pct")

    return _compute_losses(
        expected_df, meter_df, site, availability_level_pct, start, end
    )
