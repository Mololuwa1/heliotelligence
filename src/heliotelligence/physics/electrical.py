"""Single-diode model DC power calculation.

Public API
----------
calculate_module_operating_point(...)
    Resolve module parameters, apply spectral correction, and solve the module
    electrical model at each timestep.

scale_module_to_string(module_operating_point, modules_per_string)
    Apply ideal series-connection algebra to a module operating point.

calculate_string_operating_points(site, module_operating_point)
    Expand a representative module operating point across an explicit physical
    Site → Inverter → MPPT → String topology.

aggregate_independent_string_mppt_power(string_operating_points)
    Sum independent string MPP powers by physical MPPT as a counterfactual
    reference. This is not a common-voltage MPPT solution.

calculate_dc_power(...)
    Backwards-compatible aggregate site calculation. It now consumes the
    module operating point internally but preserves the existing output and
    legacy loss cascade until the topology-aware Stage 4 migration is complete.

Aggregate output columns
------------------------
  p_dc_kw       — DC power after all legacy losses [kW, whole array]
  p_dc_stc_kw   — DC power at STC (no losses) [kW, for PR denominator]
  v_mp          — voltage at MPP per module [V]
  i_mp          — current at MPP per module [A]
  tier_used     — integer 1–5, which lookup tier was used
  fit_quality   — 'high' | 'low' | 'pvwatts'

Legacy loss cascade (temporary)
--------------------------------
  soiling → LID → mismatch → DC wiring

Mismatch and DC wiring remain here only for backwards compatibility. The target
architecture derives mismatch from string/MPPT IV interaction and moves wiring
loss to the physical cable network.

SDM routing
-----------
  Tiers 1-2 (CEC database) : calcparams_desoto + singlediode
  Tiers 3-4 (local/datasheet): fit_desoto_batzelis → calcparams_desoto + singlediode
  Tier 5 (PVWatts fallback) : pvwatts_dc

Spectral correction
-------------------
Uses pvlib.spectrum.spectral_factor_firstsolar when solar_zenith and
precipitable_water are provided. If not supplied, a WARNING is logged and
spectral correction is skipped (multiplicative factor = 1.0).
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


def calculate_module_operating_point(
    site: SiteConfig,
    poa_total: pd.Series,
    t_cell: pd.Series,
    *,
    solar_zenith: pd.Series | None = None,
    precipitable_water: pd.Series | None = None,
) -> pd.DataFrame:
    """Calculate the expected electrical MPP for one representative module.

    The returned quantities are module-terminal values before array-level loss
    factors. They are the canonical Stage 4 handoff used to build strings and,
    later, MPPT-level electrical models.

    Returns
    -------
    pd.DataFrame
        p_mp_w                    module maximum power [W]
        v_mp_v                    module MPP voltage [V]
        i_mp_a                    module MPP current [A]
        effective_irradiance_wm2  spectrally corrected irradiance [W/m²]
        tier_used                 module parameter-resolution tier
        fit_quality               parameter/model confidence label
    """
    operating_point, _ = _calculate_module_operating_point(
        site,
        poa_total,
        t_cell,
        solar_zenith=solar_zenith,
        precipitable_water=precipitable_water,
    )
    return operating_point


def scale_module_to_string(
    module_operating_point: pd.DataFrame,
    modules_per_string: int,
) -> pd.DataFrame:
    """Scale a uniform module MPP to an ideal series-connected string.

    Series connection adds voltage while current remains unchanged. This helper
    deliberately does not model non-uniformity, bypass activation, mismatch, or
    cable losses; those belong to the later string/MPPT electrical layers.
    """
    if modules_per_string <= 0:
        raise ValueError("modules_per_string must be greater than 0")

    required = {"p_mp_w", "v_mp_v", "i_mp_a"}
    missing = required.difference(module_operating_point.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"module_operating_point missing columns: {missing_text}")

    result = pd.DataFrame(index=module_operating_point.index)
    result["p_mp_w"] = module_operating_point["p_mp_w"] * modules_per_string
    result["v_mp_v"] = module_operating_point["v_mp_v"] * modules_per_string
    result["i_mp_a"] = module_operating_point["i_mp_a"]

    for column in (
        "effective_irradiance_wm2",
        "tier_used",
        "fit_quality",
    ):
        if column in module_operating_point.columns:
            result[column] = module_operating_point[column]

    return result


def calculate_string_operating_points(
    site: SiteConfig,
    module_operating_point: pd.DataFrame,
) -> pd.DataFrame:
    """Return one ideal-series operating state per physical string and timestep.

    An explicit electrical topology is required. Each configured string is
    scaled independently from the supplied representative module MPP; this
    function does not model mismatch, bypass activation, or MPPT interaction.
    """
    topology = site.electrical_topology
    if topology is None:
        raise ValueError(
            "site.electrical_topology is required to calculate string "
            "operating points"
        )
    if not module_operating_point.index.is_unique:
        raise ValueError(
            "module_operating_point index must contain unique timestamps"
        )

    identity_columns = [
        "timestamp",
        "inverter_id",
        "mppt_id",
        "string_id",
        "zone_id",
        "modules_per_string",
    ]
    operating_columns = ["p_mp_w", "v_mp_v", "i_mp_a"]
    metadata_columns = [
        column
        for column in (
            "effective_irradiance_wm2",
            "tier_used",
            "fit_quality",
        )
        if column in module_operating_point.columns
    ]
    output_columns = identity_columns + operating_columns + metadata_columns

    string_states: list[pd.DataFrame] = []
    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            for string in mppt.strings:
                state = scale_module_to_string(
                    module_operating_point,
                    string.modules_per_string,
                ).copy()
                state.insert(0, "timestamp", state.index)
                state.insert(1, "inverter_id", inverter.id)
                state.insert(2, "mppt_id", mppt.id)
                state.insert(3, "string_id", string.id)
                state.insert(4, "zone_id", string.zone_id)
                state.insert(5, "modules_per_string", string.modules_per_string)
                string_states.append(state.reset_index(drop=True))

    if not string_states:
        return pd.DataFrame(columns=output_columns)

    return pd.concat(string_states, ignore_index=True)[output_columns]


def aggregate_independent_string_mppt_power(
    string_operating_points: pd.DataFrame,
) -> pd.DataFrame:
    """Sum independent string MPP power within each physical MPPT.

    ``string_operating_points`` is expected to contain one row per physical
    string per timestamp, as produced by :func:`calculate_string_operating_points`.
    ``p_independent_mp_w`` is a counterfactual reference in which every string
    remains at its own maximum-power voltage. It is not actual common-MPPT
    power, and no aggregate MPPT voltage or current is inferred.
    """
    group_columns = ["timestamp", "inverter_id", "mppt_id"]
    required = set(group_columns + ["p_mp_w"])
    missing = required.difference(string_operating_points.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(
            f"string_operating_points missing columns: {missing_text}"
        )

    return (
        string_operating_points.groupby(group_columns, as_index=False, sort=False)[
            "p_mp_w"
        ]
        .sum()
        .rename(columns={"p_mp_w": "p_independent_mp_w"})
    )


def calculate_dc_power(
    site: SiteConfig,
    poa_total: pd.Series,
    t_cell: pd.Series,
    aoi: pd.Series,
    solar_zenith: pd.Series | None = None,
    precipitable_water: pd.Series | None = None,
) -> pd.DataFrame:
    """Calculate backwards-compatible aggregate array DC power.

    ``aoi`` remains in the public signature for compatibility with the existing
    pipeline. The current electrical model does not consume it directly.
    """
    del aoi

    module_cfg = site.module
    module_point, params = _calculate_module_operating_point(
        site,
        poa_total,
        t_cell,
        solar_zenith=solar_zenith,
        precipitable_water=precipitable_water,
    )

    # ------------------------------------------------------------------
    # Scale representative module to the legacy whole-array aggregate.
    # ------------------------------------------------------------------
    n_modules = module_cfg.num_strings * module_cfg.modules_per_string
    p_dc_array_w = module_point["p_mp_w"] * n_modules

    # STC reference power (no losses, for PR calculation)
    pnom_wp = params.get("pnom_wp") or (
        module_cfg.pnom_wp
        or module_cfg.v_mp
        and module_cfg.i_mp
        and module_cfg.v_mp * module_cfg.i_mp
    )
    if pnom_wp:
        p_dc_stc_kw = pd.Series(
            float(pnom_wp) * n_modules / 1000.0,
            index=poa_total.index,
        )
    else:
        p_dc_stc_kw = p_dc_array_w / 1000.0

    # ------------------------------------------------------------------
    # Legacy aggregate loss cascade. Kept unchanged in this refactor.
    # ------------------------------------------------------------------
    p_dc = p_dc_array_w.copy()
    p_dc *= 1.0 - module_cfg.soiling_loss_pct / 100.0
    p_dc *= 1.0 - module_cfg.lid_loss_pct / 100.0
    p_dc *= 1.0 - module_cfg.mismatch_loss_pct / 100.0
    p_dc *= 1.0 - module_cfg.wiring_loss_dc_pct / 100.0

    p_dc_kw = (p_dc / 1000.0).clip(lower=0.0)
    p_dc_stc_kw = p_dc_stc_kw.clip(lower=0.0)

    return pd.DataFrame(
        {
            "p_dc_kw": p_dc_kw,
            "p_dc_stc_kw": p_dc_stc_kw,
            "v_mp": module_point["v_mp_v"],
            "i_mp": module_point["i_mp_a"],
            "tier_used": module_point["tier_used"],
            "fit_quality": module_point["fit_quality"],
        },
        index=poa_total.index,
    )


def _calculate_module_operating_point(
    site: SiteConfig,
    poa_total: pd.Series,
    t_cell: pd.Series,
    *,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
) -> tuple[pd.DataFrame, dict]:
    """Internal module solver returning both operating point and parameters."""
    module_cfg = site.module

    if module_cfg.technology in _NON_CSI:
        logger.warning(
            "Non c-Si technology detected (%s). SDM accuracy may be "
            "reduced. Consider a technology-specific model.",
            module_cfg.technology,
        )

    resolution = resolve_module_params(module_cfg)
    params = resolution["params"]
    tier = resolution["tier"]
    fit_quality = resolution["fit_quality"]

    spectral_factor = _compute_spectral_factor(
        module_cfg.technology,
        solar_zenith,
        precipitable_water,
        site,
    )
    effective_irradiance = poa_total * spectral_factor

    if tier in (1, 2):
        p_module, v_mp_series, i_mp_series = _sdm_cec(
            params,
            effective_irradiance,
            t_cell,
        )
    elif tier in (3, 4):
        p_module, v_mp_series, i_mp_series = _sdm_datasheet(
            params,
            module_cfg.technology,
            effective_irradiance,
            t_cell,
        )
    else:
        p_module, v_mp_series, i_mp_series = _pvwatts(
            params,
            effective_irradiance,
            t_cell,
        )

    operating_point = pd.DataFrame(
        {
            "p_mp_w": p_module,
            "v_mp_v": v_mp_series,
            "i_mp_a": i_mp_series,
            "effective_irradiance_wm2": effective_irradiance,
            "tier_used": tier,
            "fit_quality": fit_quality,
        },
        index=poa_total.index,
    )
    return operating_point, params


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_spectral_factor(
    technology: str,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
    site: SiteConfig,
) -> "float | pd.Series":
    """Compute spectral mismatch factor via First Solar coefficients."""
    import pvlib.atmosphere
    import pvlib.spectrum

    if solar_zenith is None or precipitable_water is None:
        logger.warning(
            "Spectral correction skipped: solar_zenith and/or precipitable_water "
            "not provided. Pass solar_zenith and precipitable_water to "
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

    import pvlib.atmosphere
    import pvlib.spectrum

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
        float(spectral_factor.mean())
        if hasattr(spectral_factor, "mean")
        else spectral_factor,
    )
    return spectral_factor


def _sdm_cec(
    params: dict,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Single-diode model using CEC (De Soto) parameters."""
    import pvlib.pvsystem

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
    """Single-diode model fitted from datasheet STC parameters."""
    import pvlib.ivtools.sdm
    import pvlib.pvsystem

    i_sc = float(params["i_sc"])
    alpha_sc_pct_per_c = float(params["alpha_sc"])
    alpha_sc_a_per_c = i_sc * alpha_sc_pct_per_c / 100.0

    v_oc = float(params["v_oc"])
    beta_voc_pct_per_c = float(params["beta_voc"])
    beta_voc_v_per_c = v_oc * beta_voc_pct_per_c / 100.0

    eg_ref_by_technology = {
        "mono_si": 1.121,
        "poly_si": 1.121,
        "hjt": 1.121,
        "cdte": 1.475,
        "cigs": 1.15,
    }
    eg_ref = eg_ref_by_technology.get(technology, 1.121)

    batzelis_params = pvlib.ivtools.sdm.fit_desoto_batzelis(
        v_mp=float(params["v_mp"]),
        i_mp=float(params["i_mp"]),
        v_oc=v_oc,
        i_sc=i_sc,
        alpha_sc=alpha_sc_a_per_c,
        beta_voc=beta_voc_v_per_c,
    )

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
            EgRef=eg_ref,
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
    """PVWatts simplified DC model (Tier 5 fallback)."""
    import pvlib.pvsystem

    pnom_wp = float(params["pnom_wp"])
    gamma_pmp = float(params["gamma_pmp"])

    p_module = pvlib.pvsystem.pvwatts_dc(
        effective_irradiance=effective_irradiance,
        temp_cell=t_cell,
        pdc0=pnom_wp,
        gamma_pdc=gamma_pmp / 100.0,
    )
    p_module = pd.Series(p_module, index=effective_irradiance.index).clip(lower=0.0)
    nan_series = pd.Series(float("nan"), index=effective_irradiance.index)
    return p_module, nan_series, nan_series
