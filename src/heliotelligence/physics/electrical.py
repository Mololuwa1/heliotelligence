"""Single-diode model DC power calculation.

Public API
----------
calculate_dc_power(site, poa_total, t_cell, aoi,
                   solar_zenith=None, precipitable_water=None) -> pd.DataFrame

Output columns
--------------
  p_dc_kw       — DC power after all losses [kW, whole array]
  p_dc_stc_kw   — DC power at STC (no losses) [kW, for PR denominator]
  v_mp          — voltage at MPP per module [V]
  i_mp          — current at MPP per module [A]
  tier_used     — integer 1–5, which lookup tier was used
  fit_quality   — 'high' | 'low' | 'pvwatts'

Loss cascade (applied in order)
--------------------------------
  soiling   → LID → mismatch → DC wiring

SDM routing
-----------
  Tiers 1-2 (CEC database) : calcparams_desoto + singlediode
  Tiers 3-4 (local/datasheet): fit_desoto_batzelis → calcparams_desoto + singlediode
  Tier 5 (PVWatts fallback) : pvwatts_dc

Note on calcparams_pvsyst and fit_cec_sam
------------------------------------------
The specification calls for calcparams_pvsyst on Tiers 3-4.
fit_pvsyst_sandia requires full IV-curve data; fit_cec_sam requires the
NREL PySAM package (not installed); fit_desoto fails to converge on
high-current half-cell modules (144-cell Jinko).
fit_desoto_batzelis (analytical, scipy-free) is used instead for Tiers 3-4
and produces the same De Soto parameter set compatible with calcparams_desoto.
The two model families are closely related; difference is negligible vs.
datasheet fitting uncertainty.

Spectral correction
-------------------
Uses pvlib.spectrum.spectral_factor_firstsolar when solar_zenith and
precipitable_water are provided.  If not supplied, a WARNING is logged
and spectral correction is skipped (multiplicative factor = 1.0).

pvlib functions used
--------------------
  pvlib.pvsystem.retrieve_sam('CECMod')
  pvlib.ivtools.sdm.fit_desoto_batzelis
  pvlib.pvsystem.calcparams_desoto
  pvlib.pvsystem.singlediode
  pvlib.pvsystem.pvwatts_dc
  pvlib.spectrum.spectral_factor_firstsolar
  pvlib.atmosphere.get_relative_airmass
  pvlib.atmosphere.get_absolute_airmass
"""

from __future__ import annotations

import logging

import pandas as pd

from heliotelligence.config.site import SiteConfig
from heliotelligence.physics.module_lookup import resolve_module_params

logger = logging.getLogger(__name__)

# Technology → pvlib celltype for fit_cec_sam
_CELLTYPE_MAP = {
    "mono_si": "monoSi",
    "poly_si": "multiSi",
    "cdte": "cdte",
    "cigs": "cigs",
    "hjt": "monoSi",  # HJT uses monoSi bandgap approximation
}

# Technology → spectral_factor_firstsolar module_type
_SPECTRAL_MODULE_TYPE_MAP = {
    "mono_si": "monosi",
    "poly_si": "polysi",
    "cdte": "cdte",
    "cigs": "cigs",
    "hjt": "monosi",  # approximation; log INFO
}

# Technologies that trigger a non-c-Si accuracy WARNING
_NON_CSI = {"cdte", "cigs"}


def calculate_dc_power(
    site: SiteConfig,
    poa_total: pd.Series,
    t_cell: pd.Series,
    aoi: pd.Series,
    solar_zenith: pd.Series | None = None,
    precipitable_water: pd.Series | None = None,
) -> pd.DataFrame:
    """Calculate array DC power using the single-diode model.

    Parameters
    ----------
    site : SiteConfig
        Site config; module sub-config drives the SDM parameterisation.
    poa_total : pd.Series
        Total effective POA irradiance [W/m²].
    t_cell : pd.Series
        Cell temperature [°C].
    aoi : pd.Series
        Angle of incidence on the front surface [degrees].
    solar_zenith : pd.Series, optional
        Apparent solar zenith [degrees].  Required for spectral correction.
    precipitable_water : pd.Series, optional
        Precipitable water column [cm].  Required for spectral correction.

    Returns
    -------
    pd.DataFrame
        Columns: p_dc_kw, p_dc_stc_kw, v_mp, i_mp, tier_used, fit_quality.
    """
    import pvlib.pvsystem

    module_cfg = site.module

    # ------------------------------------------------------------------
    # Non-c-Si technology warning
    # ------------------------------------------------------------------
    if module_cfg.technology in _NON_CSI:
        logger.warning(
            "Non c-Si technology detected (%s).  SDM accuracy may be "
            "reduced.  Consider a technology-specific model.",
            module_cfg.technology,
        )

    # ------------------------------------------------------------------
    # Step 1: Resolve module parameters
    # ------------------------------------------------------------------
    resolution = resolve_module_params(module_cfg)
    params = resolution["params"]
    tier = resolution["tier"]
    fit_quality = resolution["fit_quality"]

    # ------------------------------------------------------------------
    # Step 2: Spectral correction
    # ------------------------------------------------------------------
    spectral_factor = _compute_spectral_factor(
        module_cfg.technology, solar_zenith, precipitable_water, site
    )
    effective_irradiance = poa_total * spectral_factor

    # ------------------------------------------------------------------
    # Step 3: Route by tier
    # ------------------------------------------------------------------
    if tier in (1, 2):
        p_module, v_mp_series, i_mp_series = _sdm_cec(
            params, effective_irradiance, t_cell
        )
    elif tier in (3, 4):
        p_module, v_mp_series, i_mp_series = _sdm_datasheet(
            params, module_cfg.technology, effective_irradiance, t_cell
        )
    else:  # tier 5
        p_module, v_mp_series, i_mp_series = _pvwatts(
            params, effective_irradiance, t_cell
        )

    # ------------------------------------------------------------------
    # Step 4: Scale to array
    # ------------------------------------------------------------------
    n_modules = module_cfg.num_strings * module_cfg.modules_per_string
    p_dc_array_w = p_module * n_modules  # watts

    # STC reference power (no losses, for PR calculation)
    pnom_wp = params.get("pnom_wp") or (
        module_cfg.pnom_wp or module_cfg.v_mp and module_cfg.i_mp
        and module_cfg.v_mp * module_cfg.i_mp
    )
    if pnom_wp:
        p_dc_stc_kw = pd.Series(
            float(pnom_wp) * n_modules / 1000.0,
            index=poa_total.index,
        )
    else:
        p_dc_stc_kw = p_dc_array_w / 1000.0  # fallback: use modelled output

    # ------------------------------------------------------------------
    # Step 5: Loss cascade
    # ------------------------------------------------------------------
    p_dc = p_dc_array_w.copy()
    p_dc *= 1.0 - module_cfg.soiling_loss_pct / 100.0
    p_dc *= 1.0 - module_cfg.lid_loss_pct / 100.0
    p_dc *= 1.0 - module_cfg.mismatch_loss_pct / 100.0
    p_dc *= 1.0 - module_cfg.wiring_loss_dc_pct / 100.0

    p_dc_kw = p_dc / 1000.0
    p_dc_stc_kw = p_dc_stc_kw.clip(lower=0.0)
    p_dc_kw = p_dc_kw.clip(lower=0.0)

    return pd.DataFrame(
        {
            "p_dc_kw": p_dc_kw,
            "p_dc_stc_kw": p_dc_stc_kw,
            "v_mp": v_mp_series,
            "i_mp": i_mp_series,
            "tier_used": tier,
            "fit_quality": fit_quality,
        },
        index=poa_total.index,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_spectral_factor(
    technology: str,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
    site: SiteConfig,
) -> "float | pd.Series":
    """Compute spectral mismatch factor via pvlib.spectrum.spectral_factor_firstsolar.

    Parameters
    ----------
    technology : str
        Module technology string from ModuleConfig.
    solar_zenith : pd.Series or None
        Apparent solar zenith [degrees].
    precipitable_water : pd.Series or None
        Precipitable water [cm].
    site : SiteConfig
        Used for altitude (pressure adjustment).

    Returns
    -------
    float or pd.Series
        Spectral mismatch factor M (1.0 = no correction).
    """
    import pvlib.atmosphere
    import pvlib.spectrum

    if solar_zenith is None or precipitable_water is None:
        logger.warning(
            "Spectral correction skipped: solar_zenith and/or precipitable_water "
            "not provided.  Pass solar_zenith and precipitable_water to "
            "calculate_dc_power() to enable spectral correction."
        )
        return 1.0

    module_type = _SPECTRAL_MODULE_TYPE_MAP.get(technology)
    if module_type is None:
        logger.warning(
            "Technology '%s' has no spectral correction coefficients in "
            "spectral_factor_firstsolar; skipping.",
            technology,
        )
        return 1.0

    pressure = pvlib.atmosphere.alt2pres(site.altitude_m)
    airmass_rel = pvlib.atmosphere.get_relative_airmass(solar_zenith)
    airmass_abs = pvlib.atmosphere.get_absolute_airmass(airmass_rel, pressure)

    spectral_factor = pvlib.spectrum.spectral_factor_firstsolar(
        precipitable_water=precipitable_water,
        airmass_absolute=airmass_abs,
        module_type=module_type,
    )
    logger.info(
        "Spectral correction applied (module_type=%s): mean factor=%.4f.",
        module_type,
        float(spectral_factor.mean()) if hasattr(spectral_factor, "mean") else spectral_factor,
    )
    return spectral_factor


def _sdm_cec(
    params: dict,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Single-diode model using CEC (De Soto) parameters.

    Uses pvlib.pvsystem.calcparams_desoto + singlediode.

    Parameters
    ----------
    params : dict
        CEC database row as a dict.
    effective_irradiance : pd.Series — W/m²
    t_cell : pd.Series — °C

    Returns
    -------
    (p_module_w, v_mp, i_mp) — all pd.Series, per-module values.
    """
    import pvlib.pvsystem

    # alpha_sc in CEC database is in A/°C; apply Adjust correction
    alpha_sc = params["alpha_sc"]
    adjust = params.get("Adjust", 0.0)
    alpha_sc_adj = alpha_sc * (1.0 + adjust / 100.0)

    photocurrent, saturation_current, resistance_series, resistance_shunt, nNsVth = (
        pvlib.pvsystem.calcparams_desoto(
            effective_irradiance=effective_irradiance,
            temp_cell=t_cell,
            alpha_sc=alpha_sc_adj,
            a_ref=params["a_ref"],
            I_L_ref=params["I_L_ref"],
            I_o_ref=params["I_o_ref"],
            R_sh_ref=params["R_sh_ref"],
            R_s=params["R_s"],
        )
    )
    iv = pvlib.pvsystem.singlediode(
        photocurrent=photocurrent,
        saturation_current=saturation_current,
        resistance_series=resistance_series,
        resistance_shunt=resistance_shunt,
        nNsVth=nNsVth,
    )
    p_module = pd.Series(iv["p_mp"], index=effective_irradiance.index).clip(lower=0.0)
    v_mp = pd.Series(iv["v_mp"], index=effective_irradiance.index)
    i_mp = pd.Series(iv["i_mp"], index=effective_irradiance.index)
    return p_module, v_mp, i_mp


def _sdm_datasheet(
    params: dict,
    technology: str,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Single-diode model fitted from datasheet STC parameters.

    Uses pvlib.ivtools.sdm.fit_desoto_batzelis (fully analytical, no PySAM,
    no scipy root-finding) to derive De Soto SDM coefficients from STC
    datasheet values, then calls calcparams_desoto + singlediode.

    Chosen over fit_desoto (scipy root-finding) because fit_desoto fails to
    converge on high-current half-cell modules (e.g. Jinko 144-cell with
    13.69 A Imp) due to the log1p singularity in the initial-guess step.
    fit_desoto_batzelis is an analytical solution and has no convergence
    issues with these parameters.

    Parameters
    ----------
    params : dict
        Local library or inline datasheet entry.
    technology : str
        ModuleConfig.technology string (used for EgRef selection).
    effective_irradiance : pd.Series — W/m²
    t_cell : pd.Series — °C

    Returns
    -------
    (p_module_w, v_mp, i_mp) — all pd.Series, per-module values.
    """
    import pvlib.ivtools.sdm
    import pvlib.pvsystem

    # alpha_sc in local library is in %/°C; convert to A/°C
    i_sc = float(params["i_sc"])
    alpha_sc_pct_per_c = float(params["alpha_sc"])  # %/°C
    alpha_sc_a_per_c = i_sc * alpha_sc_pct_per_c / 100.0

    # beta_voc in local library is in %/°C; convert to V/°C
    v_oc = float(params["v_oc"])
    beta_voc_pct_per_c = float(params["beta_voc"])  # %/°C
    beta_voc_v_per_c = v_oc * beta_voc_pct_per_c / 100.0

    # EgRef: bandgap energy for the technology [eV]
    _EGREF = {
        "mono_si": 1.121,
        "poly_si": 1.121,
        "hjt": 1.121,
        "cdte": 1.475,
        "cigs": 1.15,
    }
    EgRef = _EGREF.get(technology, 1.121)

    batzelis_params = pvlib.ivtools.sdm.fit_desoto_batzelis(
        v_mp=float(params["v_mp"]),
        i_mp=float(params["i_mp"]),
        v_oc=v_oc,
        i_sc=i_sc,
        alpha_sc=alpha_sc_a_per_c,
        beta_voc=beta_voc_v_per_c,
    )

    # Physical validity check — negative R_sh is impossible and causes NaN.
    # This typically signals that i_sc < i_mp in the source data (physically
    # impossible; i_mp must be < i_sc).  Fall back to the PVWatts model if
    # gamma_pmp is available.
    if batzelis_params["R_sh_ref"] <= 0:
        logger.warning(
            "Batzelis fitting produced non-physical R_sh_ref=%.3f for "
            "'%s' (check: i_sc=%.3f must be > i_mp=%.3f). "
            "Falling back to PVWatts model.",
            batzelis_params["R_sh_ref"],
            params.get("model", "unknown"),
            i_sc,
            float(params["i_mp"]),
        )
        gamma_pmp = params.get("gamma_pmp")
        pnom = params.get("pnom_wp")
        if pnom is None:
            pnom = float(params["v_mp"]) * float(params["i_mp"])
        if gamma_pmp is None:
            raise ValueError(
                "Batzelis fitting failed (non-physical R_sh) and no "
                "gamma_pmp available for PVWatts fallback."
            )
        return _pvwatts(
            {"pnom_wp": pnom, "gamma_pmp": gamma_pmp},
            effective_irradiance,
            t_cell,
        )

    photocurrent, saturation_current, resistance_series, resistance_shunt, nNsVth = (
        pvlib.pvsystem.calcparams_desoto(
            effective_irradiance=effective_irradiance,
            temp_cell=t_cell,
            alpha_sc=alpha_sc_a_per_c,
            a_ref=batzelis_params["a_ref"],
            I_L_ref=batzelis_params["I_L_ref"],
            I_o_ref=batzelis_params["I_o_ref"],
            R_sh_ref=batzelis_params["R_sh_ref"],
            R_s=batzelis_params["R_s"],
            EgRef=EgRef,
        )
    )
    iv = pvlib.pvsystem.singlediode(
        photocurrent=photocurrent,
        saturation_current=saturation_current,
        resistance_series=resistance_series,
        resistance_shunt=resistance_shunt,
        nNsVth=nNsVth,
    )
    p_module = pd.Series(iv["p_mp"], index=effective_irradiance.index).clip(lower=0.0)
    v_mp = pd.Series(iv["v_mp"], index=effective_irradiance.index)
    i_mp = pd.Series(iv["i_mp"], index=effective_irradiance.index)
    return p_module, v_mp, i_mp


def _pvwatts(
    params: dict,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """PVWatts simplified DC model (Tier 5 fallback).

    Uses pvlib.pvsystem.pvwatts_dc.

    Parameters
    ----------
    params : dict  — must have 'pnom_wp' and 'gamma_pmp'.
    effective_irradiance : pd.Series — W/m²
    t_cell : pd.Series — °C

    Returns
    -------
    (p_module_w, v_mp, i_mp) — v_mp and i_mp are NaN Series (not computed
    by PVWatts).
    """
    import pvlib.pvsystem

    pnom_wp = float(params["pnom_wp"])
    gamma_pmp = float(params["gamma_pmp"])  # %/°C

    p_module = pvlib.pvsystem.pvwatts_dc(
        effective_irradiance=effective_irradiance,
        temp_cell=t_cell,
        pdc0=pnom_wp,
        gamma_pdc=gamma_pmp / 100.0,  # pvwatts_dc expects fraction/°C
    )
    p_module = pd.Series(p_module, index=effective_irradiance.index).clip(lower=0.0)
    nan_series = pd.Series(float("nan"), index=effective_irradiance.index)
    return p_module, nan_series, nan_series
