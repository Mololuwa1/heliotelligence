"""Single-diode model DC power calculation.

Public API
----------
calculate_module_operating_point(...)
    Resolve module parameters, apply spectral correction, and solve the module
    electrical model at each timestep.

calculate_module_iv_curves(...)
    Evaluate one module's voltage-dependent current and power at each
    timestep using the same physical single-diode parameters as the module MPP.

scale_module_iv_to_string(module_iv_curves, modules_per_string)
    Apply ideal homogeneous series scaling to a voltage-dependent module curve.

calculate_topology_string_iv_curves(topology, module_iv_curves_by_string_id)
    Scale explicit per-string module I-V curves into physical string I-V curves
    using each configured StringConfig.modules_per_string.

calculate_common_voltage_mppt(string_iv_curves)
    Combine supplied string I-V curves at one shared voltage and select their
    aggregate maximum-power operating point.

calculate_physical_mismatch(string_iv_curves)
    Derive shared-MPPT mismatch from an IV-consistent independent-string
    counterfactual and the actual common-voltage operating point.

calculate_topology_mppt_mismatch(topology, string_iv_curves_by_id)
    Route explicit Inverter → MPPT → String connectivity into the canonical
    physical shared-MPPT mismatch calculation.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from heliotelligence.config.site import ElectricalTopologyConfig, SiteConfig
from heliotelligence.physics.module_lookup import resolve_module_params

logger = logging.getLogger(__name__)

_IV_CURVE_COLUMNS = [
    "timestamp",
    "curve_point",
    "voltage_v",
    "current_a",
    "power_w",
    "effective_irradiance_wm2",
    "tier_used",
    "fit_quality",
]
_NUMERICAL_NEGATIVE_TOLERANCE = 1e-7


@dataclass(frozen=True)
class _SdmOperatingParameters:
    """Timestamp-level parameters for pvlib's single-diode solver."""

    photocurrent: pd.Series
    saturation_current: pd.Series
    resistance_series: pd.Series
    resistance_shunt: pd.Series
    n_ns_vth: pd.Series

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


def calculate_module_iv_curves(
    site: SiteConfig,
    poa_total: pd.Series,
    t_cell: pd.Series,
    *,
    solar_zenith: pd.Series | None = None,
    precipitable_water: pd.Series | None = None,
    voltage_points: int = 201,
) -> pd.DataFrame:
    """Evaluate a physical module I-V curve for every input timestamp.

    The result is long-form, with exactly ``voltage_points`` rows per input
    timestamp. Physical CEC and fitted-datasheet tiers use the same De Soto
    operating parameters as :func:`calculate_module_operating_point`. PVWatts
    fallbacks are rejected because they do not contain enough information to
    define a defensible voltage-dependent curve.
    """
    _validate_iv_curve_inputs(
        poa_total,
        t_cell,
        solar_zenith,
        precipitable_water,
        voltage_points,
    )

    resolution, effective_irradiance = _resolve_module_electrical_inputs(
        site,
        poa_total,
        solar_zenith=solar_zenith,
        precipitable_water=precipitable_water,
    )
    params = resolution["params"]
    tier = resolution["tier"]
    fit_quality = resolution["fit_quality"]

    if tier == 5:
        raise ValueError(
            "Voltage-dependent module I-V is unavailable for Tier 5 "
            "PVWatts fallback parameters"
        )

    curve_irradiance = effective_irradiance.clip(lower=0.0)
    if not np.isfinite(curve_irradiance.to_numpy(dtype=float)).all():
        raise ValueError("effective irradiance must contain only finite values")
    sdm_parameters = _calculate_sdm_operating_parameters(
        params,
        site.module.technology,
        curve_irradiance,
        t_cell,
        tier,
    )
    if sdm_parameters is None:
        raise ValueError(
            "Voltage-dependent module I-V is unavailable because the "
            "datasheet parameters do not produce a physical single-diode fit; "
            "the scalar model can only use its PVWatts fallback"
        )

    if poa_total.empty:
        return pd.DataFrame(columns=_IV_CURVE_COLUMNS)

    curves: list[pd.DataFrame] = []
    for position, timestamp in enumerate(poa_total.index):
        irradiance = float(curve_irradiance.iloc[position])
        if irradiance <= 0.0:
            voltage = np.zeros(voltage_points)
            current = np.zeros(voltage_points)
        else:
            voltage = _voltage_grid(
                _open_circuit_voltage(sdm_parameters, position),
                voltage_points,
            )
            current = _current_from_voltage(voltage, sdm_parameters, position)

        power = _validated_nonnegative(voltage * current, "power")
        curves.append(
            pd.DataFrame(
                {
                    "timestamp": [timestamp] * voltage_points,
                    "curve_point": np.arange(voltage_points),
                    "voltage_v": voltage,
                    "current_a": current,
                    "power_w": power,
                    "effective_irradiance_wm2": [irradiance] * voltage_points,
                    "tier_used": [tier] * voltage_points,
                    "fit_quality": [fit_quality] * voltage_points,
                }
            )
        )

    return pd.concat(curves, ignore_index=True)[_IV_CURVE_COLUMNS]


def scale_module_iv_to_string(
    module_iv_curves: pd.DataFrame,
    modules_per_string: int,
) -> pd.DataFrame:
    """Scale module I-V points to an ideal homogeneous series string.

    Corresponding curve points retain module current while voltage and power
    scale by the number of identical series-connected modules. All columns and
    row ordering are preserved, and the input frame is not mutated.
    This ideal homogeneous transformation does not model non-uniform module
    conditions, bypass-diode behavior, mismatch, cable losses, or MPPT interaction.
    """
    if modules_per_string <= 0:
        raise ValueError("modules_per_string must be greater than 0")

    required = {"timestamp", "curve_point", "voltage_v", "current_a", "power_w"}
    missing = required.difference(module_iv_curves.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"module_iv_curves missing columns: {missing_text}")

    result = module_iv_curves.copy(deep=True)
    result["voltage_v"] = module_iv_curves["voltage_v"] * modules_per_string
    result["power_w"] = module_iv_curves["power_w"] * modules_per_string
    return result


def calculate_topology_string_iv_curves(
    topology: ElectricalTopologyConfig,
    module_iv_curves_by_string_id: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Scale explicit per-string module curves using configured string lengths.

    Connectivity and processing order come only from ``topology``. Supplied
    module curves must exactly match its configured string IDs and are scaled
    independently by :func:`scale_module_iv_to_string`. This function does not
    generate module curves, infer environmental conditions, or run MPPT physics.
    """
    configured_ids = {
        string.id
        for inverter in topology.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    }
    supplied_ids = set(module_iv_curves_by_string_id)
    missing_ids = sorted(configured_ids - supplied_ids)
    unexpected_ids = sorted(supplied_ids - configured_ids)
    if missing_ids or unexpected_ids:
        details: list[str] = []
        if missing_ids:
            details.append(f"missing string ids: {', '.join(missing_ids)}")
        if unexpected_ids:
            details.append(f"unexpected string ids: {', '.join(unexpected_ids)}")
        raise ValueError(
            "module_iv_curves_by_string_id does not match electrical topology: "
            + "; ".join(details)
        )

    results: dict[str, pd.DataFrame] = {}
    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            for string in mppt.strings:
                try:
                    results[string.id] = scale_module_iv_to_string(
                        module_iv_curves_by_string_id[string.id],
                        string.modules_per_string,
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"inverter '{inverter.id}' MPPT '{mppt.id}' "
                        f"string '{string.id}': {exc}"
                    ) from exc
    return results


def calculate_common_voltage_mppt(
    string_iv_curves: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    """Calculate a shared-voltage MPPT point for supplied parallel strings.

    Each input frame represents one string. For every timestamp, candidate
    voltages are the sorted union of supplied voltage samples within the common
    overlap ``0 <= V <= min(sampled Voc)``. String currents are linearly
    interpolated inside that domain, summed, and multiplied by the common
    voltage. The first (lowest-voltage) maximum is selected.

    Mixed active and all-zero curves are rejected because the all-zero night
    representation does not define dark-string current under an externally
    imposed voltage. This function does not extrapolate or model topology,
    reverse current, blocking devices, mismatch, cables, or inverter limits.
    """
    if not string_iv_curves:
        raise ValueError("string_iv_curves must contain at least one string curve")

    required = {"timestamp", "curve_point", "voltage_v", "current_a", "power_w"}
    ordered_timestamps: list[list[object]] = []
    for string_position, curve in enumerate(string_iv_curves):
        missing = required.difference(curve.columns)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(
                f"string_iv_curves[{string_position}] missing columns: {missing_text}"
            )
        ordered_timestamps.append(pd.unique(curve["timestamp"]).tolist())

    reference_timestamps = ordered_timestamps[0]
    for string_position, timestamps in enumerate(ordered_timestamps[1:], start=1):
        if timestamps != reference_timestamps:
            raise ValueError(
                f"string_iv_curves[{string_position}] timestamps must exactly match "
                "string_iv_curves[0] in first-occurrence order"
            )

    results: list[dict[str, object]] = []
    for timestamp in reference_timestamps:
        timestamp_curves = [
            _validated_common_mppt_curve(curve, timestamp, string_position)
            for string_position, curve in enumerate(string_iv_curves)
        ]
        all_zero = [bool(curve["all_zero"]) for curve in timestamp_curves]
        if all(all_zero):
            results.append(
                {
                    "timestamp": timestamp,
                    "v_common_mppt_v": 0.0,
                    "i_common_mppt_a": 0.0,
                    "p_common_mppt_w": 0.0,
                    "string_count": len(string_iv_curves),
                }
            )
            continue
        if any(all_zero):
            raise ValueError(
                f"timestamp {timestamp!r} mixes active and all-zero string curves; "
                "a reverse-current or blocking-device model is required"
            )

        common_vmax = min(float(curve["voltage"][-1]) for curve in timestamp_curves)
        candidates = np.unique(
            np.concatenate(
                [
                    curve["voltage"][curve["voltage"] <= common_vmax]
                    for curve in timestamp_curves
                ]
                + [np.array([0.0, common_vmax])]
            )
        )
        total_current = np.zeros_like(candidates)
        for curve in timestamp_curves:
            total_current += np.interp(
                candidates,
                curve["voltage"],
                curve["current"],
            )
        total_power = candidates * total_current
        maximum_position = int(np.argmax(total_power))
        results.append(
            {
                "timestamp": timestamp,
                "v_common_mppt_v": float(candidates[maximum_position]),
                "i_common_mppt_a": float(total_current[maximum_position]),
                "p_common_mppt_w": float(total_power[maximum_position]),
                "string_count": len(string_iv_curves),
            }
        )

    return pd.DataFrame(
        results,
        columns=[
            "timestamp",
            "v_common_mppt_v",
            "i_common_mppt_a",
            "p_common_mppt_w",
            "string_count",
        ],
    )


def calculate_physical_mismatch(
    string_iv_curves: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    """Calculate the physical penalty from strings sharing one MPPT voltage.

    The actual operating point comes from
    :func:`calculate_common_voltage_mppt`. The independent counterfactual uses
    the sorted union of all supplied string voltage samples at each timestamp;
    every string independently maximizes ``V * I(V)`` over candidates inside
    its own ``0 <= V <= sampled Voc`` domain, using the same linear current
    interpolation basis as the common-voltage calculation.

    Tiny negative mismatch caused by floating-point roundoff is normalized to
    zero. A common result materially above the independent counterfactual is an
    internal-consistency error. This one-MPPT primitive does not integrate
    topology or replace the legacy static mismatch calculation.
    """
    common = calculate_common_voltage_mppt(string_iv_curves)
    independent_power: list[float] = []
    mismatch_power: list[float] = []

    for timestamp_position, timestamp in enumerate(common["timestamp"]):
        timestamp_curves = [
            _validated_common_mppt_curve(curve, timestamp, string_position)
            for string_position, curve in enumerate(string_iv_curves)
        ]
        if all(bool(curve["all_zero"]) for curve in timestamp_curves):
            independent_power.append(0.0)
            mismatch_power.append(0.0)
            continue

        master_candidates = np.unique(
            np.concatenate([curve["voltage"] for curve in timestamp_curves])
        )
        timestamp_independent_power = 0.0
        for curve in timestamp_curves:
            voltage = curve["voltage"]
            candidates = master_candidates[
                (master_candidates >= 0.0) & (master_candidates <= voltage[-1])
            ]
            candidates = np.unique(
                np.concatenate([candidates, np.array([0.0, voltage[-1]])])
            )
            current = np.interp(candidates, voltage, curve["current"])
            timestamp_independent_power += float(np.max(candidates * current))

        common_power = float(common.iloc[timestamp_position]["p_common_mppt_w"])
        powers_close = bool(np.isclose(
            common_power,
            timestamp_independent_power,
            rtol=1e-12,
            atol=1e-9,
        ))
        if common_power > timestamp_independent_power and not powers_close:
            raise ValueError(
                f"timestamp {timestamp!r} common MPPT power exceeds the "
                "IV-consistent independent-string power"
            )
        independent_power.append(timestamp_independent_power)
        mismatch_power.append(
            0.0
            if powers_close
            else timestamp_independent_power - common_power
        )

    result = common.copy(deep=True)
    result["p_independent_mp_w"] = independent_power
    result["p_mismatch_w"] = mismatch_power
    result["mismatch_pct"] = np.where(
        result["p_independent_mp_w"] > 0.0,
        100.0 * result["p_mismatch_w"] / result["p_independent_mp_w"],
        0.0,
    )
    return result[
        [
            "timestamp",
            "v_common_mppt_v",
            "i_common_mppt_a",
            "p_common_mppt_w",
            "p_independent_mp_w",
            "p_mismatch_w",
            "mismatch_pct",
            "string_count",
        ]
    ]


def calculate_topology_mppt_mismatch(
    topology: ElectricalTopologyConfig,
    string_iv_curves_by_id: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Route configured strings into physical mismatch results per MPPT.

    Connectivity and traversal order come only from ``topology``. Supplied
    curves must exactly match its configured string IDs and must already
    represent complete physical strings. Each populated MPPT is delegated once
    to :func:`calculate_physical_mismatch`; empty MPPTs produce no rows.
    """
    output_columns = [
        "timestamp",
        "inverter_id",
        "mppt_id",
        "v_common_mppt_v",
        "i_common_mppt_a",
        "p_common_mppt_w",
        "p_independent_mp_w",
        "p_mismatch_w",
        "mismatch_pct",
        "string_count",
    ]
    configured_ids = {
        string.id
        for inverter in topology.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    }
    supplied_ids = set(string_iv_curves_by_id)
    missing_ids = sorted(configured_ids - supplied_ids)
    unexpected_ids = sorted(supplied_ids - configured_ids)
    if missing_ids or unexpected_ids:
        details: list[str] = []
        if missing_ids:
            details.append(f"missing string ids: {', '.join(missing_ids)}")
        if unexpected_ids:
            details.append(f"unexpected string ids: {', '.join(unexpected_ids)}")
        raise ValueError(
            "string_iv_curves_by_id does not match electrical topology: "
            + "; ".join(details)
        )

    results: list[pd.DataFrame] = []
    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            if not mppt.strings:
                continue
            mppt_curves = [
                string_iv_curves_by_id[string.id] for string in mppt.strings
            ]
            try:
                physical = calculate_physical_mismatch(mppt_curves)
            except ValueError as exc:
                raise ValueError(
                    f"inverter '{inverter.id}' MPPT '{mppt.id}': {exc}"
                ) from exc
            if physical.empty:
                continue
            result = physical.copy(deep=True)
            result.insert(1, "inverter_id", inverter.id)
            result.insert(2, "mppt_id", mppt.id)
            results.append(result[output_columns])

    if not results:
        return pd.DataFrame(columns=output_columns)
    return pd.concat(results, ignore_index=True)[output_columns]


def _validated_common_mppt_curve(
    curve: pd.DataFrame,
    timestamp: object,
    string_position: int,
) -> dict[str, object]:
    """Return validated numeric arrays for one string and timestamp."""
    rows = curve.loc[curve["timestamp"] == timestamp]
    context = f"string_iv_curves[{string_position}] at timestamp {timestamp!r}"
    if rows.empty:
        raise ValueError(f"{context} must contain at least one curve point")
    if rows["curve_point"].duplicated().any():
        raise ValueError(f"{context} must contain unique curve_point values")

    values: dict[str, np.ndarray] = {}
    for column in ("voltage_v", "current_a", "power_w"):
        numeric = rows[column].to_numpy(dtype=float, copy=True)
        if not np.isfinite(numeric).all():
            raise ValueError(f"{context} {column} must contain only finite values")
        if (numeric < -_NUMERICAL_NEGATIVE_TOLERANCE).any():
            raise ValueError(f"{context} {column} must be non-negative")
        numeric[numeric < 0.0] = 0.0
        values[column] = numeric

    voltage = values["voltage_v"]
    current = values["current_a"]
    power = values["power_w"]
    all_zero = bool(
        np.all(voltage == 0.0)
        and np.all(current == 0.0)
        and np.all(power == 0.0)
    )
    if not all_zero:
        if voltage[-1] <= 0.0:
            raise ValueError(f"{context} active curve maximum voltage must be positive")
        if voltage[0] != 0.0:
            raise ValueError(f"{context} active curve must begin at 0 V")
        if not np.all(np.diff(voltage) > 0.0):
            raise ValueError(
                f"{context} active voltage samples must be strictly increasing"
            )

    return {"voltage": voltage, "current": current, "all_zero": all_zero}


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
    resolution, effective_irradiance = _resolve_module_electrical_inputs(
        site,
        poa_total,
        solar_zenith=solar_zenith,
        precipitable_water=precipitable_water,
    )
    params = resolution["params"]
    tier = resolution["tier"]
    fit_quality = resolution["fit_quality"]

    sdm_parameters = None
    if tier != 5:
        sdm_parameters = _calculate_sdm_operating_parameters(
            params,
            module_cfg.technology,
            effective_irradiance,
            t_cell,
            tier,
        )

    if sdm_parameters is None:
        if tier in (3, 4):
            logger.warning(
                "Datasheet fitting produced non-physical parameters for '%s'. "
                "Falling back to PVWatts model.",
                params.get("model", "unknown"),
            )
            params = _pvwatts_fallback_params(params)
        p_module, v_mp_series, i_mp_series = _pvwatts(
            params,
            effective_irradiance,
            t_cell,
        )
    else:
        iv = _solve_sdm(sdm_parameters)
        p_module = pd.Series(iv["p_mp"], index=effective_irradiance.index).clip(
            lower=0.0
        )
        v_mp_series = pd.Series(iv["v_mp"], index=effective_irradiance.index)
        i_mp_series = pd.Series(iv["i_mp"], index=effective_irradiance.index)

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

def _resolve_module_electrical_inputs(
    site: SiteConfig,
    poa_total: pd.Series,
    *,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
) -> tuple[dict, pd.Series]:
    """Resolve module metadata and spectrally corrected irradiance."""
    module_cfg = site.module
    if module_cfg.technology in _NON_CSI:
        logger.warning(
            "Non c-Si technology detected (%s). SDM accuracy may be "
            "reduced. Consider a technology-specific model.",
            module_cfg.technology,
        )

    resolution = resolve_module_params(module_cfg)
    spectral_factor = _compute_spectral_factor(
        module_cfg.technology,
        solar_zenith,
        precipitable_water,
        site,
    )
    return resolution, poa_total * spectral_factor


def _validate_iv_curve_inputs(
    poa_total: pd.Series,
    t_cell: pd.Series,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
    voltage_points: int,
) -> None:
    """Validate fixed-shape I-V inputs without pandas auto-alignment."""
    if voltage_points < 3:
        raise ValueError("voltage_points must be at least 3")
    if not poa_total.index.is_unique:
        raise ValueError("poa_total index must contain unique timestamps")
    if not t_cell.index.is_unique:
        raise ValueError("t_cell index must contain unique timestamps")
    if not poa_total.index.equals(t_cell.index):
        raise ValueError("poa_total and t_cell indexes must align exactly")

    for name, series in (
        ("solar_zenith", solar_zenith),
        ("precipitable_water", precipitable_water),
    ):
        if series is not None:
            if not series.index.is_unique:
                raise ValueError(f"{name} index must contain unique timestamps")
            if not poa_total.index.equals(series.index):
                raise ValueError(f"{name} index must align exactly with poa_total")

    if not np.isfinite(poa_total.to_numpy(dtype=float)).all():
        raise ValueError("poa_total must contain only finite values")
    if not np.isfinite(t_cell.to_numpy(dtype=float)).all():
        raise ValueError("t_cell must contain only finite values")


def _calculate_sdm_operating_parameters(
    params: dict,
    technology: str,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
    tier: int,
) -> _SdmOperatingParameters | None:
    """Calculate the shared De Soto parameters used by MPP and I-V paths."""
    if tier in (1, 2):
        return _sdm_cec_parameters(params, effective_irradiance, t_cell)
    if tier in (3, 4):
        return _sdm_datasheet_parameters(
            params,
            technology,
            effective_irradiance,
            t_cell,
        )
    return None


def _compute_spectral_factor(
    technology: str,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
    site: SiteConfig,
) -> float | pd.Series:
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


def _sdm_cec_parameters(
    params: dict,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
) -> _SdmOperatingParameters:
    """Calculate timestamp-level De Soto parameters from CEC coefficients."""
    import pvlib.pvsystem

    alpha_sc = params["alpha_sc"]
    adjust = params.get("Adjust", 0.0)
    alpha_sc_adj = alpha_sc * (1.0 + adjust / 100.0)

    values = pvlib.pvsystem.calcparams_desoto(
        effective_irradiance=effective_irradiance,
        temp_cell=t_cell,
        alpha_sc=alpha_sc_adj,
        a_ref=params["a_ref"],
        I_L_ref=params["I_L_ref"],
        I_o_ref=params["I_o_ref"],
        R_sh_ref=params["R_sh_ref"],
        R_s=params["R_s"],
    )
    return _as_sdm_parameters(values, effective_irradiance.index)


def _sdm_datasheet_parameters(
    params: dict,
    technology: str,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
) -> _SdmOperatingParameters | None:
    """Calculate De Soto parameters fitted from datasheet STC values."""
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
        return None

    values = pvlib.pvsystem.calcparams_desoto(
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
    return _as_sdm_parameters(values, effective_irradiance.index)


def _as_sdm_parameters(
    values: tuple,
    index: pd.Index,
) -> _SdmOperatingParameters:
    """Normalize pvlib De Soto outputs to indexed Series."""
    return _SdmOperatingParameters(
        *(pd.Series(value, index=index) for value in values)
    )


def _solve_sdm(parameters: _SdmOperatingParameters) -> dict:
    """Solve canonical single-diode points from operating parameters."""
    import pvlib.pvsystem

    return pvlib.pvsystem.singlediode(
        photocurrent=parameters.photocurrent,
        saturation_current=parameters.saturation_current,
        resistance_series=parameters.resistance_series,
        resistance_shunt=parameters.resistance_shunt,
        nNsVth=parameters.n_ns_vth,
    )


def _pvwatts_fallback_params(params: dict) -> dict:
    """Extract the existing datasheet-to-PVWatts fallback parameters."""
    gamma_pmp = params.get("gamma_pmp")
    pnom = params.get("pnom_wp")
    if pnom is None:
        pnom = float(params["v_mp"]) * float(params["i_mp"])
    if gamma_pmp is None:
        raise ValueError(
            "Batzelis fitting failed (non-physical R_sh) and no "
            "gamma_pmp available for PVWatts fallback."
        )
    return {"pnom_wp": pnom, "gamma_pmp": gamma_pmp}


def _voltage_grid(open_circuit_voltage: float, voltage_points: int) -> np.ndarray:
    """Build an inclusive physical voltage grid for one daylight curve."""
    if not np.isfinite(open_circuit_voltage) or open_circuit_voltage <= 0.0:
        raise ValueError("single-diode solver produced an invalid open-circuit voltage")
    return np.linspace(0.0, open_circuit_voltage, voltage_points)


def _open_circuit_voltage(
    parameters: _SdmOperatingParameters,
    position: int,
) -> float:
    """Solve Voc for one daylight timestamp without evaluating night rows."""
    import pvlib.pvsystem

    iv = pvlib.pvsystem.singlediode(
        photocurrent=float(parameters.photocurrent.iloc[position]),
        saturation_current=float(parameters.saturation_current.iloc[position]),
        resistance_series=float(parameters.resistance_series.iloc[position]),
        resistance_shunt=float(parameters.resistance_shunt.iloc[position]),
        nNsVth=float(parameters.n_ns_vth.iloc[position]),
    )
    return float(iv["v_oc"])


def _current_from_voltage(
    voltage: np.ndarray,
    parameters: _SdmOperatingParameters,
    position: int,
) -> np.ndarray:
    """Evaluate non-negative module current across one voltage grid."""
    import pvlib.pvsystem

    current = pvlib.pvsystem.i_from_v(
        voltage=voltage,
        photocurrent=float(parameters.photocurrent.iloc[position]),
        saturation_current=float(parameters.saturation_current.iloc[position]),
        resistance_series=float(parameters.resistance_series.iloc[position]),
        resistance_shunt=float(parameters.resistance_shunt.iloc[position]),
        nNsVth=float(parameters.n_ns_vth.iloc[position]),
    )
    return _validated_nonnegative(np.asarray(current, dtype=float), "current")


def _validated_nonnegative(values: np.ndarray, quantity: str) -> np.ndarray:
    """Clamp solver noise only, rejecting material negative/non-finite values."""
    if not np.isfinite(values).all():
        raise ValueError(f"single-diode solver produced non-finite {quantity}")
    if (values < -_NUMERICAL_NEGATIVE_TOLERANCE).any():
        raise ValueError(f"single-diode solver produced negative {quantity}")
    return np.maximum(values, 0.0)


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
