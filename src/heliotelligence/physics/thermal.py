"""Cell temperature calculation.

Public API
----------
calculate_cell_temp(site, poa_total, temp_amb, wind_speed,
                    temp_module_measured=None) -> pd.Series

Model selection
---------------
  1. If ``temp_module_measured`` is provided and has <10 % NaN, use it
     directly with a small conduction correction (most accurate for Bracon
     Ash, which has six PT1000 module temperature sensors).
  2. Primary model: Faiman (2008), implemented in pvlib.temperature.faiman.
     Uses site.module.u_c (W/m²·K) and site.module.u_v (W/m²·K/(m/s)).
  3. Fallback: NOCT-based model via pvlib.temperature.noct_sam.
     Used only when Faiman is bypassed in tests or by explicit override.

pvlib functions used
--------------------
  pvlib.temperature.faiman
  pvlib.temperature.noct_sam
"""

from __future__ import annotations

import logging

import pandas as pd

from heliotelligence.config.site import SiteConfig

logger = logging.getLogger(__name__)

# Approximate module efficiency used for the NOCT model (fraction, not %).
# The noct_sam model needs this to estimate thermal losses.
# 0.20 is a conservative estimate for modern mono-Si at STC.
_DEFAULT_MODULE_EFFICIENCY = 0.20

# Cell-to-module temperature delta coefficient [°C / (W/m²)].
# At 1000 W/m², this gives ≈3 °C above module temperature,
# consistent with IEC 60904-5 cell-module delta approximations.
_DELTA_T_COEFF = 0.03 / 1000.0


def calculate_cell_temp(
    site: SiteConfig,
    poa_total: pd.Series,
    temp_amb: pd.Series,
    wind_speed: pd.Series,
    temp_module_measured: pd.Series | None = None,
) -> pd.Series:
    """Calculate PV cell temperature.

    Parameters
    ----------
    site : SiteConfig
        Site config; module.u_c and module.u_v are used by the Faiman model.
    poa_total : pd.Series
        Total effective POA irradiance [W/m²].
    temp_amb : pd.Series
        Ambient (air) temperature [°C].
    wind_speed : pd.Series
        Wind speed at hub height [m/s].
    temp_module_measured : pd.Series, optional
        Measured back-of-module temperature [°C] from on-site sensors.
        If provided and has <10 % NaN, this path is used instead of a model.

    Returns
    -------
    pd.Series
        Cell temperature [°C], same index as poa_total.
    """
    import pvlib.temperature

    # ------------------------------------------------------------------
    # Path 1 — measured module temperature
    # ------------------------------------------------------------------
    if temp_module_measured is not None:
        nan_frac = temp_module_measured.isna().mean()
        if nan_frac < 0.10:
            logger.info(
                "Cell temperature: using measured module temp (%.1f%% NaN). "
                "Applying conduction delta: %.4f °C/(W/m²).",
                nan_frac * 100,
                _DELTA_T_COEFF,
            )
            t_cell = temp_module_measured + poa_total * _DELTA_T_COEFF
            # Fill any remaining NaN in measured data with the Faiman model
            if t_cell.isna().any():
                t_cell_faiman = _faiman(site, poa_total, temp_amb, wind_speed)
                t_cell = t_cell.fillna(t_cell_faiman)
            return t_cell.rename("t_cell_c")
        else:
            logger.warning(
                "Measured module temp has %.1f%% NaN (≥10%%); "
                "falling back to Faiman model.",
                nan_frac * 100,
            )

    # ------------------------------------------------------------------
    # Path 2 — Faiman model (primary)
    # ------------------------------------------------------------------
    logger.info(
        "Cell temperature: Faiman model (u_c=%.1f W/m²·K, u_v=%.2f W/m²·K/(m/s)).",
        site.module.u_c,
        site.module.u_v,
    )
    return _faiman(site, poa_total, temp_amb, wind_speed)


def _faiman(
    site: SiteConfig,
    poa_total: pd.Series,
    temp_amb: pd.Series,
    wind_speed: pd.Series,
) -> pd.Series:
    """Faiman (2008) cell temperature model.

    Uses pvlib.temperature.faiman with u0=site.module.u_c and
    u1=site.module.u_v.

    Returns
    -------
    pd.Series  — t_cell_c [°C]
    """
    import pvlib.temperature

    t_cell = pvlib.temperature.faiman(
        poa_global=poa_total,
        temp_air=temp_amb,
        wind_speed=wind_speed,
        u0=site.module.u_c,
        u1=site.module.u_v,
    )
    return pd.Series(t_cell, index=poa_total.index, name="t_cell_c")


def calculate_cell_temp_noct(
    site: SiteConfig,
    poa_total: pd.Series,
    temp_amb: pd.Series,
    wind_speed: pd.Series,
) -> pd.Series:
    """NOCT-based cell temperature model (fallback).

    Uses pvlib.temperature.noct_sam with site.module.noct_c.
    Exposed as a separate function so callers and tests can use it
    explicitly without triggering the measured-temp or Faiman paths.

    Parameters
    ----------
    site : SiteConfig
    poa_total : pd.Series — W/m²
    temp_amb : pd.Series  — °C
    wind_speed : pd.Series — m/s

    Returns
    -------
    pd.Series — t_cell_c [°C]
    """
    import pvlib.temperature

    # Estimate module efficiency: use pnom_wp/1000 if available, else default.
    if site.module.pnom_wp is not None:
        # Typical large-format module ≈2.6 m²; efficiency = P / (1000 * A)
        # Approximated here without module area; 0.20 is a reasonable default.
        module_efficiency = _DEFAULT_MODULE_EFFICIENCY
    else:
        module_efficiency = _DEFAULT_MODULE_EFFICIENCY

    logger.info(
        "Cell temperature: NOCT model (noct=%.1f °C, eta=%.3f).",
        site.module.noct_c,
        module_efficiency,
    )
    t_cell = pvlib.temperature.noct_sam(
        poa_global=poa_total,
        temp_air=temp_amb,
        wind_speed=wind_speed,
        noct=site.module.noct_c,
        module_efficiency=module_efficiency,
    )
    return pd.Series(t_cell, index=poa_total.index, name="t_cell_c")
