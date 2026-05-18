"""Inverter AC power calculation.

Public API
----------
calculate_ac_power(site, p_dc_kw) -> pd.DataFrame

Output columns
--------------
  p_ac_kw         — AC power after efficiency, clipping, and AC wiring loss [kW]
  p_dc_kw_input   — DC power before inverter (passed through for reference) [kW]
  clipped         — True when DC power exceeded inverter AC capacity before losses

Steps (applied in order)
-------------------------
  1. PVWatts efficiency:  p_ac = p_dc * site.inverter.eta_nom
  2. Inverter clipping:   cap at site.inverter.pnom_kwac * site.inverter.num_units
  3. Grid limit:          cap at site.inverter.grid_limit_kwac (if set)
  4. AC wiring loss:      p_ac *= (1 - site.inverter.wiring_loss_ac_pct / 100)
"""

from __future__ import annotations

import logging

import pandas as pd

from heliotelligence.config.site import SiteConfig

logger = logging.getLogger(__name__)


def calculate_ac_power(
    site: SiteConfig,
    p_dc_kw: pd.Series,
) -> pd.DataFrame:
    """Calculate AC power output from DC power.

    Parameters
    ----------
    site : SiteConfig
        Site config; inverter sub-config drives all AC calculations.
    p_dc_kw : pd.Series
        DC power after loss cascade [kW].

    Returns
    -------
    pd.DataFrame
        Columns: p_ac_kw, p_dc_kw_input, clipped.
        Index matches p_dc_kw.
    """
    inv = site.inverter

    # ------------------------------------------------------------------
    # Step 1 — PVWatts efficiency
    # ------------------------------------------------------------------
    p_ac = p_dc_kw * inv.eta_nom

    # ------------------------------------------------------------------
    # Step 2 — Inverter clipping (AC nameplate capacity)
    # ------------------------------------------------------------------
    if inv.pnom_kwac is not None:
        inverter_capacity_kw = inv.pnom_kwac * inv.num_units
        clipped = p_ac > inverter_capacity_kw
        if clipped.any():
            logger.info(
                "Site %s: inverter clipping active on %d/%d timestamps "
                "(cap=%.1f kW).",
                site.id, int(clipped.sum()), len(p_ac), inverter_capacity_kw,
            )
        p_ac = p_ac.clip(upper=inverter_capacity_kw)
    else:
        clipped = pd.Series(False, index=p_dc_kw.index)
        logger.debug(
            "Site %s: no inverter pnom_kwac set — clipping skipped.", site.id
        )

    # ------------------------------------------------------------------
    # Step 3 — Grid limit curtailment
    # ------------------------------------------------------------------
    if inv.grid_limit_kwac is not None:
        grid_curtailed = p_ac > inv.grid_limit_kwac
        if grid_curtailed.any():
            logger.info(
                "Site %s: grid curtailment active on %d/%d timestamps "
                "(limit=%.1f kW).",
                site.id, int(grid_curtailed.sum()), len(p_ac),
                inv.grid_limit_kwac,
            )
        p_ac = p_ac.clip(upper=inv.grid_limit_kwac)

    # ------------------------------------------------------------------
    # Step 4 — AC wiring loss
    # ------------------------------------------------------------------
    p_ac = p_ac * (1.0 - inv.wiring_loss_ac_pct / 100.0)

    p_ac = p_ac.clip(lower=0.0)

    return pd.DataFrame(
        {
            "p_ac_kw": p_ac,
            "p_dc_kw_input": p_dc_kw,
            "clipped": clipped,
        },
        index=p_dc_kw.index,
    )
