"""Module electrical calculations for canonical and legacy irradiance inputs.

Public API
----------
calculate_receiver_module_operating_points_from_spectral_response(...)
    Canonical receiver-resolved S7E handoff. It consumes already spectrally
    resolved electrical-equivalent irradiance and never applies spectral
    mismatch itself.

calculate_topology_module_iv_curves_from_receiver_electrical(...)
    Canonical S8-0 routing from validated receiver module electrical states to
    explicit homogeneous-string module-I-V inputs. It evaluates each referenced
    receiver once and performs no spectral correction or string scaling.

calculate_module_operating_point(...)
    Legacy representative-module path. It resolves module parameters, applies
    its internal spectral correction, and solves each timestep.

calculate_module_iv_curves(...)
    Evaluate one module's voltage-dependent current and power at each
    timestep using the same physical single-diode parameters as the module MPP.

StringModuleIVInputs
    Attribute-frozen container for one string's explicit module-level
    environmental inputs; it performs no inference or calculation.

calculate_topology_module_iv_curves(site, topology, module_iv_inputs_by_string_id)
    Generate canonical module I-V curves from explicit per-string inputs in
    topology order, without string scaling or topology inference.

calculate_topology_module_iv_curves_from_environment_states(...)
    Evaluate each explicit runtime environmental state once, then route
    independent module-level I-V frames to strings in topology order.

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

Legacy spectral correction
--------------------------
The legacy aggregate path uses pvlib.spectrum.spectral_factor_firstsolar when
solar_zenith and precipitable_water are supplied. The canonical S7E path instead
consumes SpectralResponseResult and does not call this helper.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any, Literal

import numpy as np
import pandas as pd

from heliotelligence.config.site import ElectricalTopologyConfig, SiteConfig
from heliotelligence.geometry import PVReceiver, ReceiverKind
from heliotelligence.physics.module_lookup import resolve_module_params
from heliotelligence.physics.spectral_response import (
    FIRST_SOLAR_MODEL_ID,
    SPECTRAL_RESPONSE_CONTRACT_ID,
    SPECTRAL_RESPONSE_COVERAGE_SCOPE,
    SPECTRAL_RESPONSE_MODEL_ID,
    SPECTRAL_RESPONSE_SCOPE,
    SpectralResponseResult,
)

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

SPECTRAL_ELECTRICAL_HANDOFF_CONTRACT_ID = "spectral_response_to_module_electrical_v1"
SPECTRAL_ELECTRICAL_HANDOFF_MODEL_ID = "spectral_electrical_equivalent_direct_module_solver_v1"
SPECTRAL_ELECTRICAL_HANDOFF_SCOPE = "receiver_resolved_module_electrical_before_topology"

RECEIVER_STRING_MODULE_IV_CONTRACT_ID = "receiver_module_electrical_to_topology_module_iv_v1"
RECEIVER_STRING_MODULE_IV_MODEL_ID = "explicit_receiver_to_homogeneous_string_module_iv_v1"
RECEIVER_STRING_MODULE_IV_SCOPE = "receiver_resolved_module_iv_before_string_series_scaling"
RECEIVER_STRING_MODULE_IV_COVERAGE_SCOPE = (
    "explicit_fixed_table_receiver_to_string_assignment"
)

ReceiverCoveragePolicy = Literal[
    "require_all_receivers",
    "allow_unassigned_receivers",
]

_SPECTRAL_HANDOFF_REQUIRED_COLUMNS = (
    "poa_front_effective_optical_wm2",
    "poa_rear_effective_optical_wm2",
    "bifacial_enabled",
    "isc_bifaciality_factor",
    "front_spectral_activation_state",
    "front_spectral_mismatch_factor",
    "front_spectral_factor_resolved",
    "front_spectral_factor_state",
    "front_spectral_electrical_equivalent_irradiance_wm2",
    "front_spectral_electrical_equivalent_resolved",
    "front_spectral_electrical_equivalent_state",
    "rear_spectral_treatment",
    "rear_spectral_mismatch_factor",
    "rear_spectral_factor_resolved",
    "rear_spectral_factor_state",
    "poa_rear_spectral_effective_irradiance_wm2",
    "rear_spectral_effective_resolved",
    "rear_spectral_effective_state",
    "rear_spectral_electrical_equivalent_irradiance_wm2",
    "rear_spectral_electrical_equivalent_resolved",
    "rear_spectral_electrical_equivalent_state",
    "spectral_electrical_equivalent_irradiance_wm2",
    "spectral_electrical_equivalent_resolved",
    "spectral_electrical_equivalent_state",
    "pvlib_version",
    "firstsolar_model",
    "spectral_response_contract",
    "spectral_response_model",
    "spectral_response_coverage_scope",
    "spectral_response_scope",
)
_SPECTRAL_HANDOFF_OUTPUT_COLUMNS = (
    "spectral_electrical_equivalent_irradiance_wm2",
    "spectral_electrical_equivalent_resolved",
    "spectral_electrical_equivalent_state",
    "cell_temperature_c",
    "p_mp_w",
    "v_mp_v",
    "i_mp_a",
    "module_electrical_resolved",
    "module_electrical_state",
    "tier_used",
    "fit_quality",
    "spectral_response_contract",
    "spectral_response_model",
    "spectral_response_coverage_scope",
    "spectral_response_scope",
    "electrical_handoff_contract",
    "electrical_handoff_model",
    "electrical_handoff_scope",
)
_RECEIVER_STRING_MODULE_IV_STATE_COLUMNS = (
    "inverter_id",
    "mppt_id",
    "receiver_id",
    "receiver_module_electrical_resolved",
    "receiver_module_electrical_state",
    "spectral_electrical_equivalent_irradiance_wm2",
    "cell_temperature_c",
    "module_iv_resolved",
    "module_iv_state",
    "tier_used",
    "fit_quality",
    "receiver_string_module_iv_contract",
    "receiver_string_module_iv_model",
    "receiver_string_module_iv_scope",
    "receiver_string_module_iv_coverage_scope",
)


@dataclass(frozen=True)
class ReceiverModuleElectricalDiagnostics:
    """Deterministic summary of the receiver-resolved electrical handoff."""

    receiver_count: int
    timestamp_count: int
    row_count: int
    resolved_row_count: int
    unresolved_row_count: int
    zero_irradiance_row_count: int
    solver_row_count: int
    tier_used: int
    fit_quality: str
    electrical_handoff_model: str


@dataclass(frozen=True)
class ReceiverModuleElectricalResult:
    """Representative module operating points for each receiver and timestamp."""

    operating_points: pd.DataFrame
    diagnostics: ReceiverModuleElectricalDiagnostics


@dataclass(frozen=True)
class ReceiverStringModuleIVDiagnostics:
    """Deterministic summary of explicit receiver-to-string module-I-V routing."""

    receiver_count: int
    referenced_receiver_count: int
    unreferenced_receiver_count: int
    shared_receiver_count: int
    inverter_count: int
    mppt_count: int
    string_count: int
    timestamp_count: int
    state_row_count: int
    resolved_iv_state_count: int
    unresolved_iv_state_count: int
    zero_iv_state_count: int
    solved_iv_state_count: int
    power_only_iv_unavailable_count: int
    voltage_points: int
    tier_used: int
    fit_quality: str
    receiver_coverage_policy: str
    module_iv_model: str


@dataclass(frozen=True)
class ReceiverStringModuleIVResult:
    """Module-level I-V states routed to each explicitly assigned string."""

    module_iv_curves_by_string_id: Mapping[str, pd.DataFrame]
    states: pd.DataFrame
    diagnostics: ReceiverStringModuleIVDiagnostics


@dataclass(frozen=True)
class _SdmOperatingParameters:
    """Timestamp-level parameters for pvlib's single-diode solver."""

    photocurrent: pd.Series
    saturation_current: pd.Series
    resistance_series: pd.Series
    resistance_shunt: pd.Series
    n_ns_vth: pd.Series


@dataclass(frozen=True)
class _DatasheetSdmReference:
    """Environment-independent De Soto reference parameters from a datasheet."""

    alpha_sc_a_per_c: float
    a_ref: float
    i_l_ref: float
    i_o_ref: float
    r_sh_ref: float
    r_s: float
    eg_ref: float


@dataclass(frozen=True)
class StringModuleIVInputs:
    """Attribute-frozen inputs for one string's representative module."""

    poa_total: pd.Series
    t_cell: pd.Series
    solar_zenith: pd.Series | None = None
    precipitable_water: pd.Series | None = None


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


def calculate_receiver_module_operating_points_from_spectral_response(
    site: SiteConfig,
    receivers: Sequence[PVReceiver],
    spectral_response: SpectralResponseResult,
    *,
    cell_temperature_c: pd.Series,
) -> ReceiverModuleElectricalResult:
    """Convert canonical S7E irradiance directly to receiver module MPP states."""
    receiver_ids = _spectral_handoff_receiver_ids(receivers)
    spectral = _admit_spectral_response(spectral_response, receiver_ids)
    temperature = _admit_cell_temperature(cell_temperature_c, spectral.index)
    resolution = _resolve_module_configuration(site)
    tier = int(resolution["tier"])
    fit_quality = str(resolution["fit_quality"])

    output = pd.DataFrame(index=spectral.index, columns=_SPECTRAL_HANDOFF_OUTPUT_COLUMNS)
    output["spectral_electrical_equivalent_irradiance_wm2"] = spectral[
        "spectral_electrical_equivalent_irradiance_wm2"
    ].astype(float)
    output["spectral_electrical_equivalent_resolved"] = spectral[
        "spectral_electrical_equivalent_resolved"
    ].astype(bool)
    output["spectral_electrical_equivalent_state"] = spectral[
        "spectral_electrical_equivalent_state"
    ].astype("string")
    output["cell_temperature_c"] = temperature.astype(float)
    output[["p_mp_w", "v_mp_v", "i_mp_a"]] = np.nan
    output["module_electrical_resolved"] = False
    output["module_electrical_state"] = "unresolved_spectral_electrical_equivalent_irradiance"
    output["tier_used"] = tier
    output["fit_quality"] = fit_quality
    output["spectral_response_contract"] = SPECTRAL_RESPONSE_CONTRACT_ID
    output["spectral_response_model"] = SPECTRAL_RESPONSE_MODEL_ID
    output["spectral_response_coverage_scope"] = SPECTRAL_RESPONSE_COVERAGE_SCOPE
    output["spectral_response_scope"] = SPECTRAL_RESPONSE_SCOPE
    output["electrical_handoff_contract"] = SPECTRAL_ELECTRICAL_HANDOFF_CONTRACT_ID
    output["electrical_handoff_model"] = SPECTRAL_ELECTRICAL_HANDOFF_MODEL_ID
    output["electrical_handoff_scope"] = SPECTRAL_ELECTRICAL_HANDOFF_SCOPE

    spectral_resolved = output["spectral_electrical_equivalent_resolved"].astype(bool)
    irradiance = output["spectral_electrical_equivalent_irradiance_wm2"].astype(float)
    zero_mask = spectral_resolved & irradiance.eq(0.0)
    positive_mask = spectral_resolved & irradiance.gt(0.0)
    finite_temperature = np.isfinite(temperature.to_numpy(dtype=float))
    temperature_mask = pd.Series(finite_temperature, index=output.index)
    solver_mask = positive_mask & temperature_mask

    output.loc[zero_mask, ["p_mp_w", "v_mp_v", "i_mp_a"]] = 0.0
    output.loc[zero_mask, "module_electrical_resolved"] = True
    output.loc[zero_mask, "module_electrical_state"] = (
        "resolved_zero_spectral_electrical_irradiance"
    )
    output.loc[positive_mask & ~temperature_mask, "module_electrical_state"] = (
        "unresolved_cell_temperature"
    )
    output.loc[~spectral_resolved & ~temperature_mask, "module_electrical_state"] = (
        "unresolved_spectral_and_cell_temperature"
    )

    if solver_mask.any():
        solver_input = irradiance.loc[solver_mask].copy()
        solver_temperature = temperature.loc[solver_mask].copy()
        solved, _ = _calculate_module_operating_point_from_electrical_irradiance(
            site,
            solver_input,
            solver_temperature,
            resolution=resolution,
        )
        output.loc[solver_mask, ["p_mp_w", "v_mp_v", "i_mp_a"]] = solved[
            ["p_mp_w", "v_mp_v", "i_mp_a"]
        ]
        output.loc[solver_mask, "module_electrical_resolved"] = True
        output.loc[solver_mask, "module_electrical_state"] = (
            "resolved_pvwatts_power_only" if tier == 5 else "resolved"
        )

    _validate_module_handoff_output(output, tier)
    output = _typed_spectral_handoff_output(output)
    resolved_count = int(output["module_electrical_resolved"].sum()) if len(output) else 0
    diagnostics = ReceiverModuleElectricalDiagnostics(
        receiver_count=len(receiver_ids),
        timestamp_count=len(pd.DatetimeIndex(output.index.get_level_values("timestamp").unique())),
        row_count=len(output),
        resolved_row_count=resolved_count,
        unresolved_row_count=len(output) - resolved_count,
        zero_irradiance_row_count=int(zero_mask.sum()),
        solver_row_count=int(solver_mask.sum()),
        tier_used=tier,
        fit_quality=fit_quality,
        electrical_handoff_model=SPECTRAL_ELECTRICAL_HANDOFF_MODEL_ID,
    )
    if diagnostics.row_count != diagnostics.resolved_row_count + diagnostics.unresolved_row_count:
        raise RuntimeError("receiver electrical diagnostic resolution counts do not close")
    if diagnostics.resolved_row_count != (
        diagnostics.zero_irradiance_row_count + diagnostics.solver_row_count
    ):
        raise RuntimeError("receiver electrical resolved-path counts do not close")
    return ReceiverModuleElectricalResult(output, diagnostics)


def calculate_topology_module_iv_curves_from_receiver_electrical(
    site: SiteConfig,
    receivers: Sequence[PVReceiver],
    topology: ElectricalTopologyConfig,
    receiver_module_electrical: ReceiverModuleElectricalResult,
    *,
    receiver_id_by_string_id: Mapping[str, str],
    receiver_coverage_policy: ReceiverCoveragePolicy,
    voltage_points: int = 201,
) -> ReceiverStringModuleIVResult:
    """Route canonical receiver electrical states to module-level string inputs.

    Assignment is explicit and independent of geometry and ``StringConfig.zone_id``.
    The returned curves remain representative-module curves; this function does
    not perform series scaling, mismatch, MPPT, cable, loss, or inverter physics.
    """
    if voltage_points < 3:
        raise ValueError("voltage_points must be at least 3")
    receiver_ids = _spectral_handoff_receiver_ids(receivers)
    ordered_strings = _receiver_string_topology_rows(topology)
    assignments, referenced_ids = _admit_receiver_string_assignments(
        ordered_strings,
        receiver_ids,
        receiver_id_by_string_id,
        receiver_coverage_policy,
    )
    electrical = _admit_receiver_module_electrical(
        receiver_module_electrical,
        receiver_ids,
    )
    resolution = _resolve_module_configuration(site)
    tier = int(resolution["tier"])
    fit_quality = str(resolution["fit_quality"])
    datasheet_reference: _DatasheetSdmReference | None = None
    voltage_dependent_available = tier != 5
    if tier in (3, 4):
        try:
            datasheet_reference = _fit_datasheet_sdm_reference(
                resolution["params"], site.module.technology
            )
        except ValueError:
            datasheet_reference = None
        voltage_dependent_available = datasheet_reference is not None
    _crosscheck_receiver_module_resolution(
        receiver_module_electrical,
        electrical,
        len(receiver_ids),
        tier,
        fit_quality,
    )
    _replay_receiver_module_operating_points(
        site,
        electrical,
        resolution,
        datasheet_reference=datasheet_reference,
        datasheet_reference_is_precomputed=tier in (3, 4),
    )

    timestamps = pd.DatetimeIndex(
        electrical.index.get_level_values("timestamp").unique()
    )
    curves_by_receiver: dict[str, pd.DataFrame] = {}
    states_by_receiver: dict[str, dict[pd.Timestamp, tuple[bool, str]]] = {}
    for receiver_id in referenced_ids:
        if not len(electrical):
            curves_by_receiver[receiver_id] = pd.DataFrame(columns=_IV_CURVE_COLUMNS)
            states_by_receiver[receiver_id] = {}
            continue
        receiver_rows = electrical.xs(receiver_id, level="receiver_id")
        receiver_states: dict[pd.Timestamp, tuple[bool, str]] = {}
        curve_parts: list[pd.DataFrame] = []
        positive_timestamps: list[pd.Timestamp] = []
        for timestamp, row in receiver_rows.iterrows():
            upstream_state = str(row["module_electrical_state"])
            if upstream_state == "resolved_zero_spectral_electrical_irradiance":
                receiver_states[timestamp] = (True, "resolved_zero_module_iv")
                curve_parts.append(
                    _zero_module_iv_curve(
                        timestamp,
                        voltage_points,
                        tier,
                        fit_quality,
                    )
                )
            elif not bool(row["module_electrical_resolved"]):
                receiver_states[timestamp] = (
                    False,
                    "unresolved_receiver_module_electrical",
                )
            elif tier == 5:
                receiver_states[timestamp] = (
                    False,
                    "unresolved_tier5_voltage_dependent_iv_unavailable",
                )
            elif not voltage_dependent_available:
                receiver_states[timestamp] = (
                    False,
                    "unresolved_voltage_dependent_iv_unavailable",
                )
            else:
                receiver_states[timestamp] = (True, "resolved_module_iv")
                positive_timestamps.append(timestamp)

        if positive_timestamps:
            positive = receiver_rows.loc[positive_timestamps]
            curve_parts.append(
                _evaluate_module_iv_curves_from_electrical_irradiance(
                    site,
                    positive["spectral_electrical_equivalent_irradiance_wm2"].astype(float),
                    positive["cell_temperature_c"].astype(float),
                    resolution,
                    voltage_points,
                    datasheet_reference=datasheet_reference,
                )
            )
        curves = (
            pd.concat(curve_parts, ignore_index=True)
            .sort_values(["timestamp", "curve_point"], kind="stable")
            .reset_index(drop=True)
            if curve_parts
            else pd.DataFrame(columns=_IV_CURVE_COLUMNS)
        )
        curves_by_receiver[receiver_id] = curves[_IV_CURVE_COLUMNS]
        states_by_receiver[receiver_id] = receiver_states

    string_curves: dict[str, pd.DataFrame] = {}
    state_records: list[dict[str, object]] = []
    state_index: list[tuple[pd.Timestamp, str]] = []
    for timestamp in timestamps:
        for inverter_id, mppt_id, string_id in ordered_strings:
            receiver_id = assignments[string_id]
            row = electrical.loc[(timestamp, receiver_id)]
            resolved, state = states_by_receiver[receiver_id][timestamp]
            state_index.append((timestamp, string_id))
            state_records.append(
                {
                    "inverter_id": inverter_id,
                    "mppt_id": mppt_id,
                    "receiver_id": receiver_id,
                    "receiver_module_electrical_resolved": bool(
                        row["module_electrical_resolved"]
                    ),
                    "receiver_module_electrical_state": row["module_electrical_state"],
                    "spectral_electrical_equivalent_irradiance_wm2": row[
                        "spectral_electrical_equivalent_irradiance_wm2"
                    ],
                    "cell_temperature_c": row["cell_temperature_c"],
                    "module_iv_resolved": resolved,
                    "module_iv_state": state,
                    "tier_used": tier,
                    "fit_quality": fit_quality,
                    "receiver_string_module_iv_contract": (
                        RECEIVER_STRING_MODULE_IV_CONTRACT_ID
                    ),
                    "receiver_string_module_iv_model": RECEIVER_STRING_MODULE_IV_MODEL_ID,
                    "receiver_string_module_iv_scope": RECEIVER_STRING_MODULE_IV_SCOPE,
                    "receiver_string_module_iv_coverage_scope": (
                        RECEIVER_STRING_MODULE_IV_COVERAGE_SCOPE
                    ),
                }
            )
    states = pd.DataFrame(
        state_records,
        index=pd.MultiIndex.from_tuples(
            state_index,
            names=["timestamp", "string_id"],
        ),
        columns=_RECEIVER_STRING_MODULE_IV_STATE_COLUMNS,
    )
    for _, _, string_id in ordered_strings:
        receiver_id = assignments[string_id]
        string_curves[string_id] = curves_by_receiver[receiver_id].copy(deep=True)

    resolved_count = int(states["module_iv_resolved"].sum()) if len(states) else 0
    zero_count = int((states["module_iv_state"] == "resolved_zero_module_iv").sum())
    solved_count = int((states["module_iv_state"] == "resolved_module_iv").sum())
    power_only_count = int(
        (
            states["module_iv_state"]
            == "unresolved_tier5_voltage_dependent_iv_unavailable"
        ).sum()
    )
    references_per_receiver = {
        receiver_id: sum(value == receiver_id for value in assignments.values())
        for receiver_id in referenced_ids
    }
    diagnostics = ReceiverStringModuleIVDiagnostics(
        receiver_count=len(receiver_ids),
        referenced_receiver_count=len(referenced_ids),
        unreferenced_receiver_count=len(receiver_ids) - len(referenced_ids),
        shared_receiver_count=sum(count > 1 for count in references_per_receiver.values()),
        inverter_count=topology.inverter_count,
        mppt_count=topology.mppt_count,
        string_count=topology.string_count,
        timestamp_count=len(timestamps),
        state_row_count=len(states),
        resolved_iv_state_count=resolved_count,
        unresolved_iv_state_count=len(states) - resolved_count,
        zero_iv_state_count=zero_count,
        solved_iv_state_count=solved_count,
        power_only_iv_unavailable_count=power_only_count,
        voltage_points=voltage_points,
        tier_used=tier,
        fit_quality=fit_quality,
        receiver_coverage_policy=receiver_coverage_policy,
        module_iv_model=RECEIVER_STRING_MODULE_IV_MODEL_ID,
    )
    _validate_receiver_string_module_iv_result(string_curves, states, diagnostics)
    return ReceiverStringModuleIVResult(string_curves, states, diagnostics)


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

    resolution = _resolve_module_configuration(site)
    effective_irradiance = _calculate_effective_irradiance(
        site,
        poa_total,
        solar_zenith=solar_zenith,
        precipitable_water=precipitable_water,
    )
    datasheet_reference = None
    if resolution["tier"] in (3, 4):
        datasheet_reference = _fit_datasheet_sdm_reference(
            resolution["params"], site.module.technology
        )
        if datasheet_reference is None:
            raise ValueError(
                "Voltage-dependent module I-V is unavailable because the "
                "datasheet parameters do not produce a physical single-diode fit; "
                "the scalar model can only use its PVWatts fallback"
            )
    return _evaluate_module_iv_curves(
        site,
        poa_total,
        t_cell,
        resolution,
        effective_irradiance,
        voltage_points,
        datasheet_reference=datasheet_reference,
    )


def calculate_topology_module_iv_curves(
    site: SiteConfig,
    topology: ElectricalTopologyConfig,
    module_iv_inputs_by_string_id: Mapping[str, StringModuleIVInputs],
    *,
    voltage_points: int = 201,
) -> dict[str, pd.DataFrame]:
    """Generate module I-V curves from explicit per-string input states.

    The supplied ``topology`` determines string identity and processing order;
    ``site.electrical_topology`` is not inspected. Every configured input state
    is validated before the site's module parameters are resolved once. Each
    string is then evaluated independently with the canonical module I-V
    physics. This function does not infer environmental state, scale strings,
    or run MPPT physics.
    """
    if voltage_points < 3:
        raise ValueError("voltage_points must be at least 3")

    configured_ids = {
        string.id
        for inverter in topology.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    }
    supplied_ids = set(module_iv_inputs_by_string_id)
    missing_ids = sorted(configured_ids - supplied_ids)
    unexpected_ids = sorted(supplied_ids - configured_ids)
    if missing_ids or unexpected_ids:
        details: list[str] = []
        if missing_ids:
            details.append(f"missing string ids: {', '.join(missing_ids)}")
        if unexpected_ids:
            details.append(f"unexpected string ids: {', '.join(unexpected_ids)}")
        raise ValueError(
            "module_iv_inputs_by_string_id does not match electrical topology: "
            + "; ".join(details)
        )

    ordered_inputs: list[tuple[str, str, str, StringModuleIVInputs]] = []
    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            for string in mppt.strings:
                inputs = module_iv_inputs_by_string_id[string.id]
                try:
                    _validate_iv_curve_inputs(
                        inputs.poa_total,
                        inputs.t_cell,
                        inputs.solar_zenith,
                        inputs.precipitable_water,
                        voltage_points,
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"inverter '{inverter.id}' MPPT '{mppt.id}' string '{string.id}': {exc}"
                    ) from exc
                ordered_inputs.append((inverter.id, mppt.id, string.id, inputs))

    if not ordered_inputs:
        return {}

    resolution = _resolve_module_configuration(site)
    if resolution["tier"] == 5:
        raise ValueError(
            "Voltage-dependent module I-V is unavailable for Tier 5 PVWatts fallback parameters"
        )
    datasheet_reference = None
    if resolution["tier"] in (3, 4):
        try:
            datasheet_reference = _fit_datasheet_sdm_reference(
                resolution["params"], site.module.technology
            )
        except ValueError as exc:
            raise ValueError(
                "Voltage-dependent module I-V is unavailable because the "
                f"site/module datasheet fit failed: {exc}"
            ) from exc
        if datasheet_reference is None:
            raise ValueError(
                "Voltage-dependent module I-V is unavailable because the "
                "site/module datasheet parameters do not produce a physical "
                "single-diode fit; the scalar model can only use its PVWatts "
                "fallback"
            )
    results: dict[str, pd.DataFrame] = {}
    for inverter_id, mppt_id, string_id, inputs in ordered_inputs:
        try:
            effective_irradiance = _calculate_effective_irradiance(
                site,
                inputs.poa_total,
                solar_zenith=inputs.solar_zenith,
                precipitable_water=inputs.precipitable_water,
            )
            results[string_id] = _evaluate_module_iv_curves(
                site,
                inputs.poa_total,
                inputs.t_cell,
                resolution,
                effective_irradiance,
                voltage_points,
                datasheet_reference=datasheet_reference,
            )
        except ValueError as exc:
            raise ValueError(
                f"inverter '{inverter_id}' MPPT '{mppt_id}' string '{string_id}': {exc}"
            ) from exc
    return results


def calculate_topology_module_iv_curves_from_environment_states(
    site: SiteConfig,
    topology: ElectricalTopologyConfig,
    environment_state_id_by_string_id: Mapping[str, str],
    module_iv_inputs_by_state_id: Mapping[str, StringModuleIVInputs],
    *,
    voltage_points: int = 201,
) -> dict[str, pd.DataFrame]:
    """Route shared explicit environmental states into module I-V curves.

    The runtime string-to-state mapping is explicit: no topology metadata is
    interpreted as environmental state. Unique states are validated and
    evaluated in first-use topology order. Physics is computed once per state,
    while each returned string receives an independent mutable DataFrame.
    """
    if voltage_points < 3:
        raise ValueError("voltage_points must be at least 3")

    ordered_string_ids = [
        string.id
        for inverter in topology.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    ]
    configured_ids = set(ordered_string_ids)
    supplied_ids = set(environment_state_id_by_string_id)
    missing_ids = sorted(configured_ids - supplied_ids)
    unexpected_ids = sorted(supplied_ids - configured_ids)
    if missing_ids or unexpected_ids:
        details: list[str] = []
        if missing_ids:
            details.append(f"missing string ids: {', '.join(missing_ids)}")
        if unexpected_ids:
            details.append(f"unexpected string ids: {', '.join(unexpected_ids)}")
        raise ValueError(
            "environment_state_id_by_string_id does not match electrical topology: "
            + "; ".join(details)
        )

    referenced_state_ids = set(environment_state_id_by_string_id.values())
    supplied_state_ids = set(module_iv_inputs_by_state_id)
    missing_state_ids = sorted(referenced_state_ids - supplied_state_ids)
    unexpected_state_ids = sorted(supplied_state_ids - referenced_state_ids)
    if missing_state_ids or unexpected_state_ids:
        details = []
        if missing_state_ids:
            details.append(f"missing environment state ids: {', '.join(missing_state_ids)}")
        if unexpected_state_ids:
            details.append("unexpected environment state ids: " + ", ".join(unexpected_state_ids))
        raise ValueError(
            "module_iv_inputs_by_state_id does not match referenced environment "
            "states: " + "; ".join(details)
        )

    ordered_state_ids = list(
        dict.fromkeys(
            environment_state_id_by_string_id[string_id] for string_id in ordered_string_ids
        )
    )
    for state_id in ordered_state_ids:
        inputs = module_iv_inputs_by_state_id[state_id]
        try:
            _validate_iv_curve_inputs(
                inputs.poa_total,
                inputs.t_cell,
                inputs.solar_zenith,
                inputs.precipitable_water,
                voltage_points,
            )
        except ValueError as exc:
            raise ValueError(f"environment state '{state_id}': {exc}") from exc

    if not ordered_state_ids:
        return {}

    resolution = _resolve_module_configuration(site)
    if resolution["tier"] == 5:
        raise ValueError(
            "Voltage-dependent module I-V is unavailable for Tier 5 PVWatts fallback parameters"
        )
    datasheet_reference = None
    if resolution["tier"] in (3, 4):
        try:
            datasheet_reference = _fit_datasheet_sdm_reference(
                resolution["params"], site.module.technology
            )
        except ValueError as exc:
            raise ValueError(
                "Voltage-dependent module I-V is unavailable because the "
                f"site/module datasheet fit failed: {exc}"
            ) from exc
        if datasheet_reference is None:
            raise ValueError(
                "Voltage-dependent module I-V is unavailable because the "
                "site/module datasheet parameters do not produce a physical "
                "single-diode fit; the scalar model can only use its PVWatts "
                "fallback"
            )

    curves_by_state_id: dict[str, pd.DataFrame] = {}
    for state_id in ordered_state_ids:
        inputs = module_iv_inputs_by_state_id[state_id]
        try:
            effective_irradiance = _calculate_effective_irradiance(
                site,
                inputs.poa_total,
                solar_zenith=inputs.solar_zenith,
                precipitable_water=inputs.precipitable_water,
            )
            curves_by_state_id[state_id] = _evaluate_module_iv_curves(
                site,
                inputs.poa_total,
                inputs.t_cell,
                resolution,
                effective_irradiance,
                voltage_points,
                datasheet_reference=datasheet_reference,
            )
        except ValueError as exc:
            raise ValueError(f"environment state '{state_id}': {exc}") from exc

    return {
        string_id: curves_by_state_id[environment_state_id_by_string_id[string_id]].copy(deep=True)
        for string_id in ordered_string_ids
    }


def _evaluate_module_iv_curves_from_electrical_irradiance(
    site: SiteConfig,
    electrical_irradiance: pd.Series,
    t_cell: pd.Series,
    resolution: dict[str, Any],
    voltage_points: int,
    *,
    datasheet_reference: _DatasheetSdmReference | None = None,
) -> pd.DataFrame:
    """Evaluate module I-V from final spectral electrical irradiance."""
    return _evaluate_module_iv_curves(
        site,
        electrical_irradiance,
        t_cell,
        resolution,
        electrical_irradiance,
        voltage_points,
        datasheet_reference=datasheet_reference,
    )


def _evaluate_module_iv_curves(
    site: SiteConfig,
    poa_total: pd.Series,
    t_cell: pd.Series,
    resolution: dict,
    effective_irradiance: pd.Series,
    voltage_points: int,
    *,
    datasheet_reference: _DatasheetSdmReference | None = None,
) -> pd.DataFrame:
    """Evaluate canonical long-form module I-V curves from resolved inputs."""
    params = resolution["params"]
    tier = resolution["tier"]
    fit_quality = resolution["fit_quality"]

    if tier == 5:
        raise ValueError(
            "Voltage-dependent module I-V is unavailable for Tier 5 PVWatts fallback parameters"
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
        datasheet_reference=datasheet_reference,
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
                        f"inverter '{inverter.id}' MPPT '{mppt.id}' string '{string.id}': {exc}"
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
            raise ValueError(f"string_iv_curves[{string_position}] missing columns: {missing_text}")
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
                [curve["voltage"][curve["voltage"] <= common_vmax] for curve in timestamp_curves]
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
            candidates = np.unique(np.concatenate([candidates, np.array([0.0, voltage[-1]])]))
            current = np.interp(candidates, voltage, curve["current"])
            timestamp_independent_power += float(np.max(candidates * current))

        common_power = float(common.iloc[timestamp_position]["p_common_mppt_w"])
        powers_close = bool(
            np.isclose(
                common_power,
                timestamp_independent_power,
                rtol=1e-12,
                atol=1e-9,
            )
        )
        if common_power > timestamp_independent_power and not powers_close:
            raise ValueError(
                f"timestamp {timestamp!r} common MPPT power exceeds the "
                "IV-consistent independent-string power"
            )
        independent_power.append(timestamp_independent_power)
        mismatch_power.append(0.0 if powers_close else timestamp_independent_power - common_power)

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
            "string_iv_curves_by_id does not match electrical topology: " + "; ".join(details)
        )

    results: list[pd.DataFrame] = []
    for inverter in topology.inverters:
        for mppt in inverter.mppts:
            if not mppt.strings:
                continue
            mppt_curves = [string_iv_curves_by_id[string.id] for string in mppt.strings]
            try:
                physical = calculate_physical_mismatch(mppt_curves)
            except ValueError as exc:
                raise ValueError(f"inverter '{inverter.id}' MPPT '{mppt.id}': {exc}") from exc
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
    all_zero = bool(np.all(voltage == 0.0) and np.all(current == 0.0) and np.all(power == 0.0))
    if not all_zero:
        if voltage[-1] <= 0.0:
            raise ValueError(f"{context} active curve maximum voltage must be positive")
        if voltage[0] != 0.0:
            raise ValueError(f"{context} active curve must begin at 0 V")
        if not np.all(np.diff(voltage) > 0.0):
            raise ValueError(f"{context} active voltage samples must be strictly increasing")

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
            "site.electrical_topology is required to calculate string operating points"
        )
    if not module_operating_point.index.is_unique:
        raise ValueError("module_operating_point index must contain unique timestamps")

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
        raise ValueError(f"string_operating_points missing columns: {missing_text}")

    return (
        string_operating_points.groupby(group_columns, as_index=False, sort=False)["p_mp_w"]
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
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Legacy wrapper applying its spectral helper before electrical solving."""
    resolution, effective_irradiance = _resolve_module_electrical_inputs(
        site,
        poa_total,
        solar_zenith=solar_zenith,
        precipitable_water=precipitable_water,
    )
    return _calculate_module_operating_point_from_electrical_irradiance(
        site,
        effective_irradiance,
        t_cell,
        resolution=resolution,
    )


def _calculate_module_operating_point_from_electrical_irradiance(
    site: SiteConfig,
    electrical_irradiance: pd.Series,
    t_cell: pd.Series,
    *,
    resolution: dict[str, Any] | None = None,
    datasheet_reference: _DatasheetSdmReference | None = None,
    datasheet_reference_is_precomputed: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Solve a module from irradiance whose spectral response is already final."""
    module_cfg = site.module
    if resolution is None:
        resolution = _resolve_module_configuration(site)
    params = resolution["params"]
    tier = resolution["tier"]
    fit_quality = resolution["fit_quality"]

    sdm_parameters = None
    if tier != 5:
        if tier in (3, 4) and datasheet_reference_is_precomputed:
            if datasheet_reference is not None:
                sdm_parameters = _sdm_datasheet_operating_parameters(
                    datasheet_reference,
                    electrical_irradiance,
                    t_cell,
                )
        else:
            sdm_parameters = _calculate_sdm_operating_parameters(
                params,
                module_cfg.technology,
                electrical_irradiance,
                t_cell,
                tier,
                datasheet_reference=datasheet_reference,
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
            electrical_irradiance,
            t_cell,
        )
    else:
        iv = _solve_sdm(sdm_parameters)
        p_module = pd.Series(iv["p_mp"], index=electrical_irradiance.index).clip(lower=0.0)
        v_mp_series = pd.Series(iv["v_mp"], index=electrical_irradiance.index)
        i_mp_series = pd.Series(iv["i_mp"], index=electrical_irradiance.index)

    operating_point = pd.DataFrame(
        {
            "p_mp_w": p_module,
            "v_mp_v": v_mp_series,
            "i_mp_a": i_mp_series,
            "effective_irradiance_wm2": electrical_irradiance,
            "tier_used": tier,
            "fit_quality": fit_quality,
        },
        index=electrical_irradiance.index,
    )
    return operating_point, params


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _receiver_string_topology_rows(
    topology: ElectricalTopologyConfig,
) -> list[tuple[str, str, str]]:
    if type(topology) is not ElectricalTopologyConfig:
        raise ValueError("topology must be an exact ElectricalTopologyConfig")
    return [
        (inverter.id, mppt.id, string.id)
        for inverter in topology.inverters
        for mppt in inverter.mppts
        for string in mppt.strings
    ]


def _admit_receiver_string_assignments(
    ordered_strings: list[tuple[str, str, str]],
    receiver_ids: tuple[str, ...],
    value: Mapping[str, str],
    policy: object,
) -> tuple[dict[str, str], tuple[str, ...]]:
    if policy not in {"require_all_receivers", "allow_unassigned_receivers"}:
        raise ValueError("receiver_coverage_policy is invalid")
    if not isinstance(value, Mapping):
        raise ValueError("receiver_id_by_string_id must be a mapping")
    ordered_string_ids = [item[2] for item in ordered_strings]
    if set(value) != set(ordered_string_ids):
        raise ValueError("receiver assignment keys must exactly match topology string IDs")
    receiver_set = set(receiver_ids)
    admitted: dict[str, str] = {}
    for string_id in ordered_string_ids:
        receiver_id = value[string_id]
        if type(receiver_id) is not str or not receiver_id.strip():
            raise ValueError("assigned receiver IDs must be non-empty strings")
        if receiver_id not in receiver_set:
            raise ValueError(f"string '{string_id}' references an unknown receiver")
        admitted[string_id] = receiver_id
    referenced = tuple(
        receiver_id for receiver_id in receiver_ids if receiver_id in set(admitted.values())
    )
    if policy == "require_all_receivers" and len(referenced) != len(receiver_ids):
        raise ValueError("receiver coverage policy requires every receiver to be assigned")
    return admitted, referenced


def _admit_receiver_module_electrical(
    value: object,
    receiver_ids: tuple[str, ...],
) -> pd.DataFrame:
    if type(value) is not ReceiverModuleElectricalResult:
        raise ValueError("receiver_module_electrical must be an exact result type")
    frame = value.operating_points
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("receiver module electrical state must use a MultiIndex")
    if frame.index.nlevels != 2 or frame.index.names != ["timestamp", "receiver_id"]:
        raise ValueError("receiver module electrical index must be timestamp/receiver_id")
    if not set(_SPECTRAL_HANDOFF_OUTPUT_COLUMNS).issubset(frame.columns):
        raise ValueError("receiver module electrical state is missing required columns")
    timestamps = frame.index.get_level_values("timestamp")
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError("receiver module electrical timestamps must be timezone-aware")
    if timestamps.hasnans or frame.index.has_duplicates:
        raise ValueError("receiver module electrical index contains NaT or duplicates")
    unique_timestamps = pd.DatetimeIndex(timestamps.unique()).sort_values()
    expected = pd.MultiIndex.from_product(
        (unique_timestamps, receiver_ids),
        names=["timestamp", "receiver_id"],
    )
    if len(frame) != len(expected) or set(frame.index) != set(expected):
        raise ValueError("receiver module electrical state must contain the complete grid")
    canonical = frame.reindex(expected).copy(deep=True)
    expected_provenance = {
        "spectral_response_contract": SPECTRAL_RESPONSE_CONTRACT_ID,
        "spectral_response_model": SPECTRAL_RESPONSE_MODEL_ID,
        "spectral_response_coverage_scope": SPECTRAL_RESPONSE_COVERAGE_SCOPE,
        "spectral_response_scope": SPECTRAL_RESPONSE_SCOPE,
        "electrical_handoff_contract": SPECTRAL_ELECTRICAL_HANDOFF_CONTRACT_ID,
        "electrical_handoff_model": SPECTRAL_ELECTRICAL_HANDOFF_MODEL_ID,
        "electrical_handoff_scope": SPECTRAL_ELECTRICAL_HANDOFF_SCOPE,
    }
    for column, expected_value in expected_provenance.items():
        if len(canonical) and not canonical[column].eq(expected_value).all():
            raise ValueError(f"receiver module electrical {column} provenance is invalid")
    for _, row in canonical.iterrows():
        _replay_receiver_module_electrical_row(row)
    return canonical


def _replay_receiver_module_electrical_row(row: pd.Series) -> None:
    spectral_resolved = _handoff_bool(
        row["spectral_electrical_equivalent_resolved"],
        "spectral electrical equivalent resolved",
    )
    irradiance = _handoff_optional_nonnegative(
        row["spectral_electrical_equivalent_irradiance_wm2"],
        "spectral electrical equivalent irradiance",
    )
    spectral_state = row["spectral_electrical_equivalent_state"]
    if spectral_resolved:
        if irradiance is None or spectral_state != "resolved":
            raise ValueError("resolved spectral electrical input is invalid")
    elif irradiance is not None or spectral_state not in {
        "unresolved_front_spectral_response",
        "unresolved_rear_spectral_response",
        "unresolved_front_and_rear_spectral_response",
    }:
        raise ValueError("unresolved spectral electrical input is invalid")
    temperature = (
        None
        if pd.isna(row["cell_temperature_c"])
        else _handoff_finite(row["cell_temperature_c"], "cell temperature")
    )
    resolved = _handoff_bool(row["module_electrical_resolved"], "module electrical resolved")
    tier = int(_handoff_finite(row["tier_used"], "tier_used"))
    state = row["module_electrical_state"]
    values = (row["p_mp_w"], row["v_mp_v"], row["i_mp_a"])
    unresolved_states = {
        "unresolved_spectral_electrical_equivalent_irradiance",
        "unresolved_cell_temperature",
        "unresolved_spectral_and_cell_temperature",
    }
    if state == "resolved_zero_spectral_electrical_irradiance":
        if not spectral_resolved or irradiance != 0.0 or not resolved:
            raise ValueError("zero receiver module electrical state is invalid")
        if not all(_handoff_close(item, 0.0) for item in values):
            raise ValueError("zero receiver module MPP values are invalid")
    elif state == "resolved":
        if (
            not spectral_resolved
            or irradiance is None
            or irradiance <= 0.0
            or temperature is None
            or not resolved
            or tier == 5
        ):
            raise ValueError("resolved SDM receiver module state is invalid")
        numeric = [_handoff_finite(item, "resolved module MPP") for item in values]
        if any(item < -_NUMERICAL_NEGATIVE_TOLERANCE for item in numeric):
            raise ValueError("resolved module MPP values must be non-negative")
    elif state == "resolved_pvwatts_power_only":
        if (
            not spectral_resolved
            or irradiance is None
            or irradiance <= 0.0
            or temperature is None
            or not resolved
            or tier != 5
            or _handoff_finite(row["p_mp_w"], "PVWatts power")
            < -_NUMERICAL_NEGATIVE_TOLERANCE
            or not pd.isna(row["v_mp_v"])
            or not pd.isna(row["i_mp_a"])
        ):
            raise ValueError("PVWatts power-only receiver module state is invalid")
    elif state in unresolved_states:
        if resolved or not all(pd.isna(item) for item in values):
            raise ValueError("unresolved receiver module values are invalid")
        expected = (
            "unresolved_spectral_and_cell_temperature"
            if not spectral_resolved and temperature is None
            else "unresolved_spectral_electrical_equivalent_irradiance"
            if not spectral_resolved
            else "unresolved_cell_temperature"
        )
        if state != expected:
            raise ValueError("unresolved receiver module state condition is invalid")
    else:
        raise ValueError("receiver module electrical state is not canonical")


def _crosscheck_receiver_module_resolution(
    value: ReceiverModuleElectricalResult,
    frame: pd.DataFrame,
    receiver_count: int,
    tier: int,
    fit_quality: str,
) -> None:
    diagnostics = value.diagnostics
    timestamps = pd.DatetimeIndex(frame.index.get_level_values("timestamp").unique())
    resolved = int(frame["module_electrical_resolved"].sum()) if len(frame) else 0
    zero = int(
        (frame["module_electrical_state"] == "resolved_zero_spectral_electrical_irradiance").sum()
    )
    solver = int(
        frame["module_electrical_state"].isin(["resolved", "resolved_pvwatts_power_only"]).sum()
    )
    expected = (
        receiver_count,
        len(timestamps),
        len(frame),
        resolved,
        len(frame) - resolved,
        zero,
        solver,
        tier,
        fit_quality,
        SPECTRAL_ELECTRICAL_HANDOFF_MODEL_ID,
    )
    actual = (
        diagnostics.receiver_count,
        diagnostics.timestamp_count,
        diagnostics.row_count,
        diagnostics.resolved_row_count,
        diagnostics.unresolved_row_count,
        diagnostics.zero_irradiance_row_count,
        diagnostics.solver_row_count,
        diagnostics.tier_used,
        diagnostics.fit_quality,
        diagnostics.electrical_handoff_model,
    )
    if actual != expected:
        raise ValueError("receiver module electrical diagnostics or module authority are stale")
    if len(frame) and (
        not frame["tier_used"].eq(tier).all()
        or not frame["fit_quality"].eq(fit_quality).all()
    ):
        raise ValueError("receiver module electrical module configuration is stale")


def _replay_receiver_module_operating_points(
    site: SiteConfig,
    frame: pd.DataFrame,
    resolution: dict[str, Any],
    *,
    datasheet_reference: _DatasheetSdmReference | None,
    datasheet_reference_is_precomputed: bool,
) -> None:
    """Bind positive S7E-1 MPP states to the current resolved module authority."""
    solver_mask = frame["module_electrical_state"].isin(
        ["resolved", "resolved_pvwatts_power_only"]
    )
    if not solver_mask.any():
        return
    positive = frame.loc[solver_mask]
    replayed, _ = _calculate_module_operating_point_from_electrical_irradiance(
        site,
        positive["spectral_electrical_equivalent_irradiance_wm2"].astype(float),
        positive["cell_temperature_c"].astype(float),
        resolution=resolution,
        datasheet_reference=datasheet_reference,
        datasheet_reference_is_precomputed=datasheet_reference_is_precomputed,
    )
    for index, supplied in positive.iterrows():
        replay = replayed.loc[index]
        columns = (
            ("p_mp_w",)
            if supplied["module_electrical_state"] == "resolved_pvwatts_power_only"
            else ("p_mp_w", "v_mp_v", "i_mp_a")
        )
        if any(
            not _handoff_close(supplied[column], float(replay[column]))
            for column in columns
        ):
            raise ValueError(
                "receiver module electrical operating point is stale or "
                "inconsistent with current module authority"
            )


def _zero_module_iv_curve(
    timestamp: pd.Timestamp,
    voltage_points: int,
    tier: int,
    fit_quality: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [timestamp] * voltage_points,
            "curve_point": np.arange(voltage_points),
            "voltage_v": np.zeros(voltage_points),
            "current_a": np.zeros(voltage_points),
            "power_w": np.zeros(voltage_points),
            "effective_irradiance_wm2": np.zeros(voltage_points),
            "tier_used": [tier] * voltage_points,
            "fit_quality": [fit_quality] * voltage_points,
        },
        columns=_IV_CURVE_COLUMNS,
    )


def _validate_receiver_string_module_iv_result(
    curves: Mapping[str, pd.DataFrame],
    states: pd.DataFrame,
    diagnostics: ReceiverStringModuleIVDiagnostics,
) -> None:
    if diagnostics.state_row_count != (
        diagnostics.resolved_iv_state_count + diagnostics.unresolved_iv_state_count
    ):
        raise RuntimeError("module-I-V state resolution counts do not close")
    if diagnostics.resolved_iv_state_count != (
        diagnostics.zero_iv_state_count + diagnostics.solved_iv_state_count
    ):
        raise RuntimeError("resolved module-I-V state counts do not close")
    expected_rows = diagnostics.resolved_iv_state_count * diagnostics.voltage_points
    actual_rows = sum(len(curve) for curve in curves.values())
    if actual_rows != expected_rows:
        raise RuntimeError("module-I-V curve rows do not close against resolved states")
    for (timestamp, string_id), row in states.iterrows():
        curve = curves[string_id]
        count = int(curve["timestamp"].eq(timestamp).sum()) if len(curve) else 0
        expected = diagnostics.voltage_points if bool(row["module_iv_resolved"]) else 0
        if count != expected:
            raise RuntimeError("module-I-V curve/state closure failed")


def _spectral_handoff_receiver_ids(receivers: object) -> tuple[str, ...]:
    if isinstance(receivers, (str, bytes)) or not isinstance(receivers, Sequence) or not receivers:
        raise ValueError("receivers must be a non-empty sequence")
    if any(type(receiver) is not PVReceiver for receiver in receivers):
        raise ValueError("receivers must contain exact PVReceiver values")
    receiver_ids = tuple(receiver.id for receiver in receivers)
    if len(receiver_ids) != len(set(receiver_ids)):
        raise ValueError("receiver IDs must be unique")
    for receiver in receivers:
        if receiver.receiver_kind is ReceiverKind.TRACKER_TABLE:
            raise ValueError("S6C runtime tracker pose is required before electrical handoff")
        if receiver.receiver_kind is not ReceiverKind.FIXED_TABLE:
            raise ValueError("spectral electrical handoff supports FIXED_TABLE receivers only")
    return tuple(sorted(receiver_ids))


def _admit_spectral_response(value: object, receiver_ids: tuple[str, ...]) -> pd.DataFrame:
    if type(value) is not SpectralResponseResult:
        raise ValueError("spectral_response must be an exact SpectralResponseResult")
    frame = value.irradiance
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("spectral response must use a timestamp/receiver_id MultiIndex")
    if frame.index.nlevels != 2 or frame.index.names != ["timestamp", "receiver_id"]:
        raise ValueError("spectral response index must be timestamp/receiver_id")
    if not set(_SPECTRAL_HANDOFF_REQUIRED_COLUMNS).issubset(frame.columns):
        raise ValueError("spectral response is missing required handoff columns")
    timestamps = frame.index.get_level_values("timestamp")
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError("spectral response timestamps must be timezone-aware")
    if timestamps.hasnans or frame.index.has_duplicates:
        raise ValueError("spectral response index contains NaT or duplicate rows")
    unique_timestamps = pd.DatetimeIndex(timestamps.unique()).sort_values()
    expected = pd.MultiIndex.from_product(
        (unique_timestamps, receiver_ids), names=["timestamp", "receiver_id"]
    )
    if len(frame) != len(expected) or set(frame.index) != set(expected):
        raise ValueError("spectral response must contain the complete canonical grid")
    canonical = frame.reindex(expected).copy(deep=True)
    _replay_spectral_constants(canonical)
    for _, row in canonical.iterrows():
        _replay_spectral_row(row)
    _replay_spectral_diagnostics(value, canonical, receiver_ids, unique_timestamps)
    return canonical


def _replay_spectral_constants(frame: pd.DataFrame) -> None:
    expected = {
        "spectral_response_contract": SPECTRAL_RESPONSE_CONTRACT_ID,
        "spectral_response_model": SPECTRAL_RESPONSE_MODEL_ID,
        "spectral_response_coverage_scope": SPECTRAL_RESPONSE_COVERAGE_SCOPE,
        "spectral_response_scope": SPECTRAL_RESPONSE_SCOPE,
        "firstsolar_model": FIRST_SOLAR_MODEL_ID,
    }
    for column, required in expected.items():
        if (
            len(frame)
            and not (
                frame[column].map(lambda item: type(item) is str).all()
                and frame[column].eq(required).all()
            )
        ):
            raise ValueError(f"spectral response {column} provenance is invalid")
    if (
        len(frame)
        and not frame["pvlib_version"]
        .map(lambda item: type(item) is str and bool(item.strip()))
        .all()
    ):
        raise ValueError("spectral response pvlib_version provenance is invalid")


def _replay_spectral_diagnostics(
    value: SpectralResponseResult,
    frame: pd.DataFrame,
    receiver_ids: tuple[str, ...],
    timestamps: pd.DatetimeIndex,
) -> None:
    diagnostics = value.diagnostics
    if len(frame):
        identities: dict[str, tuple[bool, str, str]] = {}
        for receiver_id in receiver_ids:
            rows = frame.xs(receiver_id, level="receiver_id")
            bifacial = tuple(
                _handoff_bool(item, "bifacial_enabled") for item in rows["bifacial_enabled"]
            )
            activations = tuple(str(item) for item in rows["front_spectral_activation_state"])
            treatments = tuple(str(item) for item in rows["rear_spectral_treatment"])
            if len(set(bifacial)) != 1 or len(set(activations)) != 1 or len(set(treatments)) != 1:
                raise ValueError("spectral receiver identity changes across timestamps")
            identities[receiver_id] = (bifacial[0], activations[0], treatments[0])
        bifacial_count = sum(item[0] for item in identities.values())
        front_enabled = sum(item[1] == "enabled" for item in identities.values())
        front_disabled = sum(item[1] == "disabled" for item in identities.values())
        front_unknown = sum(item[1] == "unknown" for item in identities.values())
        rear_disabled = sum(item[0] and item[2] == "disabled" for item in identities.values())
        rear_explicit = sum(
            item[0] and item[2] == "explicit_factor" for item in identities.values()
        )
        rear_unknown = sum(item[0] and item[2] == "unknown" for item in identities.values())
    else:
        bifacial_count = diagnostics.bifacial_receiver_count
        front_enabled = diagnostics.front_enabled_receiver_count
        front_disabled = diagnostics.front_disabled_receiver_count
        front_unknown = diagnostics.front_unknown_receiver_count
        rear_disabled = diagnostics.rear_disabled_receiver_count
        rear_explicit = diagnostics.rear_explicit_receiver_count
        rear_unknown = diagnostics.rear_unknown_receiver_count
    front_factor_resolved = sum(
        _handoff_bool(item, "front_spectral_factor_resolved")
        for item in frame["front_spectral_factor_resolved"]
    )
    rear_factor_resolved = sum(
        _handoff_bool(item, "rear_spectral_factor_resolved")
        for item in frame["rear_spectral_factor_resolved"]
    )
    rear_not_applicable = int(
        (frame["rear_spectral_factor_state"] == "not_applicable_monofacial").sum()
    )
    total_resolved = sum(
        _handoff_bool(item, "spectral_electrical_equivalent_resolved")
        for item in frame["spectral_electrical_equivalent_resolved"]
    )
    expected = (
        len(receiver_ids),
        bifacial_count,
        len(receiver_ids) - bifacial_count,
        len(timestamps),
        len(frame),
        front_enabled,
        front_disabled,
        front_unknown,
        rear_disabled,
        rear_explicit,
        rear_unknown,
        front_factor_resolved,
        len(frame) - front_factor_resolved,
        rear_factor_resolved,
        len(frame) - rear_factor_resolved - rear_not_applicable,
        rear_not_applicable,
        total_resolved,
        len(frame) - total_resolved,
        SPECTRAL_RESPONSE_MODEL_ID,
    )
    actual = (
        diagnostics.receiver_count,
        diagnostics.bifacial_receiver_count,
        diagnostics.monofacial_receiver_count,
        diagnostics.timestamp_count,
        diagnostics.row_count,
        diagnostics.front_enabled_receiver_count,
        diagnostics.front_disabled_receiver_count,
        diagnostics.front_unknown_receiver_count,
        diagnostics.rear_disabled_receiver_count,
        diagnostics.rear_explicit_receiver_count,
        diagnostics.rear_unknown_receiver_count,
        diagnostics.front_factor_resolved_row_count,
        diagnostics.front_factor_unresolved_row_count,
        diagnostics.rear_factor_resolved_row_count,
        diagnostics.rear_factor_unresolved_row_count,
        diagnostics.rear_factor_not_applicable_row_count,
        diagnostics.spectral_total_resolved_row_count,
        diagnostics.spectral_total_unresolved_row_count,
        diagnostics.spectral_response_model,
    )
    if actual != expected:
        raise ValueError("spectral response diagnostics do not replay the admitted frame")
    if front_enabled + front_disabled + front_unknown != len(receiver_ids):
        raise ValueError("front spectral activation receiver counts do not close")
    if rear_disabled + rear_explicit + rear_unknown != bifacial_count:
        raise ValueError("rear spectral treatment receiver counts do not close")


def _replay_spectral_row(row: pd.Series) -> None:
    front_input = _handoff_optional_nonnegative(
        row["poa_front_effective_optical_wm2"], "front effective optical irradiance"
    )
    front_factor_resolved = _handoff_bool(
        row["front_spectral_factor_resolved"], "front spectral factor resolved"
    )
    front_factor = _handoff_factor(
        row["front_spectral_mismatch_factor"], front_factor_resolved, "front spectral factor"
    )
    front_activation = row["front_spectral_activation_state"]
    if front_activation not in {"enabled", "disabled", "unknown"}:
        raise ValueError("front spectral activation state is invalid")
    front_factor_state = row["front_spectral_factor_state"]
    if front_activation == "disabled":
        if (
            not front_factor_resolved
            or front_factor is None
            or not _handoff_close(front_factor, 1.0)
            or front_factor_state != "resolved_spectral_correction_disabled"
        ):
            raise ValueError("disabled front spectral authority is invalid")
    elif front_activation == "unknown":
        if (
            front_factor_resolved
            or front_factor is not None
            or front_factor_state != "unresolved_spectral_activation_unknown"
        ):
            raise ValueError("unknown front spectral authority is invalid")
    elif front_factor_resolved:
        if front_factor_state != "resolved_firstsolar":
            raise ValueError("resolved enabled front spectral authority is invalid")
    elif front_factor_state not in {
        "not_applicable_no_above_horizon_sun",
        "unresolved_missing_atmospheric_input",
        "unresolved_firstsolar_precipitable_water_above_max",
    }:
        raise ValueError("unresolved enabled front spectral authority is invalid")
    front_resolved = _handoff_bool(
        row["front_spectral_electrical_equivalent_resolved"], "front spectral contribution resolved"
    )
    _replay_contribution(
        input_value=front_input,
        factor=front_factor,
        factor_resolved=front_factor_resolved,
        contribution=row["front_spectral_electrical_equivalent_irradiance_wm2"],
        contribution_resolved=front_resolved,
        state=row["front_spectral_electrical_equivalent_state"],
        zero_state="resolved_zero_front_effective_irradiance",
        unresolved_factor_state="unresolved_front_spectral_factor",
        unresolved_input_state="unresolved_front_effective_irradiance",
        label="front",
    )
    bifacial = _handoff_bool(row["bifacial_enabled"], "bifacial_enabled")
    phi = _handoff_finite(row["isc_bifaciality_factor"], "isc_bifaciality_factor")
    rear_input = _handoff_optional_nonnegative(
        row["poa_rear_effective_optical_wm2"], "rear effective optical irradiance"
    )
    rear_factor_resolved = _handoff_bool(
        row["rear_spectral_factor_resolved"], "rear spectral factor resolved"
    )
    rear_factor = _handoff_factor(
        row["rear_spectral_mismatch_factor"], rear_factor_resolved, "rear spectral factor"
    )
    rear_treatment = row["rear_spectral_treatment"]
    rear_factor_state = row["rear_spectral_factor_state"]
    rear_resolved = _handoff_bool(
        row["rear_spectral_effective_resolved"], "rear spectral contribution resolved"
    )
    rear_equivalent_resolved = _handoff_bool(
        row["rear_spectral_electrical_equivalent_resolved"],
        "rear spectral electrical equivalent resolved",
    )
    if not bifacial:
        if rear_treatment != "not_applicable_monofacial":
            raise ValueError("monofacial rear spectral treatment is invalid")
        if phi != 0.0 or rear_input is not None or rear_factor_resolved or rear_factor is not None:
            raise ValueError("monofacial spectral rear identity is invalid")
        if rear_factor_state != "not_applicable_monofacial":
            raise ValueError("monofacial rear factor state is invalid")
        for value, resolved, state, label in (
            (
                row["poa_rear_spectral_effective_irradiance_wm2"],
                rear_resolved,
                row["rear_spectral_effective_state"],
                "monofacial rear spectral",
            ),
            (
                row["rear_spectral_electrical_equivalent_irradiance_wm2"],
                rear_equivalent_resolved,
                row["rear_spectral_electrical_equivalent_state"],
                "monofacial rear electrical equivalent",
            ),
        ):
            if (
                not resolved
                or not _handoff_close(value, 0.0)
                or state != "resolved_monofacial_zero"
            ):
                raise ValueError(f"{label} closure failed")
    else:
        if phi <= 0.0 or phi > 1.0:
            raise ValueError("bifacial phi_Isc must satisfy 0 < factor <= 1")
        if rear_treatment not in {"disabled", "explicit_factor", "unknown"}:
            raise ValueError("bifacial rear spectral treatment is invalid")
        if rear_treatment == "disabled":
            if (
                not rear_factor_resolved
                or rear_factor is None
                or not _handoff_close(rear_factor, 1.0)
                or rear_factor_state != "resolved_rear_spectral_correction_disabled"
            ):
                raise ValueError("disabled rear spectral authority is invalid")
        elif rear_treatment == "unknown":
            if (
                rear_factor_resolved
                or rear_factor is not None
                or rear_factor_state != "unresolved_rear_spectral_treatment_unknown"
            ):
                raise ValueError("unknown rear spectral authority is invalid")
        elif rear_factor_resolved:
            if rear_factor_state != "resolved_explicit_rear_spectral_factor":
                raise ValueError("resolved explicit rear spectral authority is invalid")
        elif rear_factor_state != "unresolved_explicit_rear_spectral_factor":
            raise ValueError("unresolved explicit rear spectral authority is invalid")
        _replay_contribution(
            input_value=rear_input,
            factor=rear_factor,
            factor_resolved=rear_factor_resolved,
            contribution=row["poa_rear_spectral_effective_irradiance_wm2"],
            contribution_resolved=rear_resolved,
            state=row["rear_spectral_effective_state"],
            zero_state="resolved_zero_rear_effective_irradiance",
            unresolved_factor_state="unresolved_rear_spectral_factor",
            unresolved_input_state="unresolved_rear_effective_irradiance",
            label="rear",
        )
        if rear_resolved:
            if not rear_equivalent_resolved or not _handoff_close(
                row["rear_spectral_electrical_equivalent_irradiance_wm2"],
                phi * float(row["poa_rear_spectral_effective_irradiance_wm2"]),
            ):
                raise ValueError("rear phi_Isc electrical-equivalent closure failed")
            if (
                row["rear_spectral_electrical_equivalent_state"]
                != row["rear_spectral_effective_state"]
            ):
                raise ValueError(
                    "rear electrical-equivalent state does not replay rear spectral state"
                )
        elif (
            rear_equivalent_resolved
            or not pd.isna(row["rear_spectral_electrical_equivalent_irradiance_wm2"])
            or row["rear_spectral_electrical_equivalent_state"]
            != row["rear_spectral_effective_state"]
        ):
            raise ValueError("unresolved rear electrical-equivalent closure failed")
    total_resolved = _handoff_bool(
        row["spectral_electrical_equivalent_resolved"], "spectral total resolved"
    )
    expected_resolved = front_resolved and rear_equivalent_resolved
    if total_resolved != expected_resolved:
        raise ValueError("spectral total resolution does not match component resolution")
    if total_resolved:
        expected_total = float(row["front_spectral_electrical_equivalent_irradiance_wm2"]) + float(
            row["rear_spectral_electrical_equivalent_irradiance_wm2"]
        )
        total = _handoff_finite(
            row["spectral_electrical_equivalent_irradiance_wm2"], "spectral total"
        )
        if total < 0.0 or not _handoff_close(total, expected_total):
            raise ValueError("resolved spectral total closure failed")
        if row["spectral_electrical_equivalent_state"] != "resolved":
            raise ValueError("resolved spectral total state is invalid")
    else:
        expected_state = (
            "unresolved_front_and_rear_spectral_response"
            if not front_resolved and not rear_equivalent_resolved
            else "unresolved_front_spectral_response"
            if not front_resolved
            else "unresolved_rear_spectral_response"
        )
        if not pd.isna(row["spectral_electrical_equivalent_irradiance_wm2"]):
            raise ValueError("unresolved spectral total must be NaN")
        if row["spectral_electrical_equivalent_state"] != expected_state:
            raise ValueError("unresolved spectral total state is invalid")


def _replay_contribution(
    *,
    input_value: float | None,
    factor: float | None,
    factor_resolved: bool,
    contribution: object,
    contribution_resolved: bool,
    state: object,
    zero_state: str,
    unresolved_factor_state: str,
    unresolved_input_state: str,
    label: str,
) -> None:
    if input_value is None:
        expected_value, expected_resolved, expected_state = np.nan, False, unresolved_input_state
    elif input_value == 0.0:
        expected_value, expected_resolved, expected_state = 0.0, True, zero_state
    elif factor_resolved:
        assert factor is not None
        expected_value, expected_resolved, expected_state = input_value * factor, True, "resolved"
    else:
        expected_value, expected_resolved, expected_state = np.nan, False, unresolved_factor_state
    if contribution_resolved != expected_resolved or state != expected_state:
        raise ValueError(f"{label} spectral contribution state closure failed")
    if expected_resolved:
        if not _handoff_close(contribution, expected_value):
            raise ValueError(f"{label} spectral contribution algebra failed")
    elif not pd.isna(contribution):
        raise ValueError(f"unresolved {label} spectral contribution must be NaN")


def _admit_cell_temperature(value: object, expected_index: pd.MultiIndex) -> pd.Series:
    if not isinstance(value, pd.Series) or not isinstance(value.index, pd.MultiIndex):
        raise ValueError("cell_temperature_c must be a MultiIndex Series")
    if value.index.nlevels != 2 or value.index.names != list(expected_index.names):
        raise ValueError("cell temperature index names must match the spectral grid")
    timestamps = value.index.get_level_values("timestamp")
    expected_timestamps = expected_index.get_level_values("timestamp")
    if not isinstance(timestamps, pd.DatetimeIndex) or timestamps.tz is None:
        raise ValueError("cell temperature timestamps must be timezone-aware")
    if timestamps.hasnans or value.index.has_duplicates:
        raise ValueError("cell temperature index contains NaT or duplicate rows")
    if str(timestamps.tz) != str(expected_timestamps.tz):
        raise ValueError("cell temperature timezone must exactly match the spectral grid")
    if len(value) != len(expected_index) or set(value.index) != set(expected_index):
        raise ValueError("cell temperature must contain the exact spectral grid")
    result = value.reindex(expected_index).copy(deep=True)
    normalized: list[float] = []
    for item in result:
        if pd.isna(item):
            normalized.append(np.nan)
        else:
            normalized.append(_handoff_finite(item, "cell temperature"))
    return pd.Series(normalized, index=expected_index, dtype=float, name=value.name)


def _validate_module_handoff_output(output: pd.DataFrame, tier: int) -> None:
    for _, row in output.iterrows():
        resolved = _handoff_bool(row["module_electrical_resolved"], "module electrical resolved")
        values = (row["p_mp_w"], row["v_mp_v"], row["i_mp_a"])
        if not resolved:
            if not all(pd.isna(item) for item in values):
                raise RuntimeError(
                    "unresolved module electrical output must contain NaN MPP values"
                )
            continue
        if tier == 5 and row["module_electrical_state"] == "resolved_pvwatts_power_only":
            power = _handoff_finite(row["p_mp_w"], "module MPP power")
            if (
                power < -_NUMERICAL_NEGATIVE_TOLERANCE
                or not pd.isna(row["v_mp_v"])
                or not pd.isna(row["i_mp_a"])
            ):
                raise RuntimeError("resolved Tier-5 output violates power-only contract")
        else:
            numeric = [_handoff_finite(item, "module MPP output") for item in values]
            if any(item < -_NUMERICAL_NEGATIVE_TOLERANCE for item in numeric):
                raise RuntimeError("module solver produced materially negative MPP output")


def _typed_spectral_handoff_output(frame: pd.DataFrame) -> pd.DataFrame:
    if tuple(frame.columns) != _SPECTRAL_HANDOFF_OUTPUT_COLUMNS:
        raise RuntimeError("spectral electrical handoff output schema changed unexpectedly")
    result = frame.copy(deep=True)
    float_columns = (
        "spectral_electrical_equivalent_irradiance_wm2",
        "cell_temperature_c",
        "p_mp_w",
        "v_mp_v",
        "i_mp_a",
    )
    string_columns = tuple(
        column
        for column in _SPECTRAL_HANDOFF_OUTPUT_COLUMNS
        if column not in float_columns
        and column
        not in (
            "spectral_electrical_equivalent_resolved",
            "module_electrical_resolved",
            "tier_used",
        )
    )
    for column in float_columns:
        result[column] = result[column].astype(float)
    for column in string_columns:
        result[column] = result[column].astype("string")
    result["spectral_electrical_equivalent_resolved"] = result[
        "spectral_electrical_equivalent_resolved"
    ].astype(bool)
    result["module_electrical_resolved"] = result["module_electrical_resolved"].astype(bool)
    result["tier_used"] = result["tier_used"].astype("int64")
    return result


def _handoff_bool(value: object, label: str) -> bool:
    if type(value) not in (bool, np.bool_):
        raise ValueError(f"{label} must be Boolean")
    return bool(value)


def _handoff_finite(value: object, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real value")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{label} must be a finite real value")
    return result


def _handoff_optional_nonnegative(value: object, label: str) -> float | None:
    if pd.isna(value):
        return None
    result = _handoff_finite(value, label)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative or NaN")
    return result


def _handoff_factor(value: object, resolved: bool, label: str) -> float | None:
    if resolved:
        result = _handoff_finite(value, label)
        if result <= 0.0:
            raise ValueError(f"resolved {label} must be positive")
        return result
    if not pd.isna(value):
        raise ValueError(f"unresolved {label} must be NaN")
    return None


def _handoff_close(value: object, expected: float) -> bool:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return False
    candidate = float(value)
    return bool(np.isfinite(candidate) and np.isclose(candidate, expected, rtol=1e-10, atol=1e-10))


def _resolve_module_electrical_inputs(
    site: SiteConfig,
    poa_total: pd.Series,
    *,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
) -> tuple[dict[str, Any], pd.Series]:
    """Resolve module metadata and spectrally corrected irradiance."""
    resolution = _resolve_module_configuration(site)
    effective_irradiance = _calculate_effective_irradiance(
        site,
        poa_total,
        solar_zenith=solar_zenith,
        precipitable_water=precipitable_water,
    )
    return resolution, effective_irradiance


def _resolve_module_configuration(site: SiteConfig) -> dict[str, Any]:
    """Resolve one site's module parameters and emit its technology warning."""
    module_cfg = site.module
    if module_cfg.technology in _NON_CSI:
        logger.warning(
            "Non c-Si technology detected (%s). SDM accuracy may be "
            "reduced. Consider a technology-specific model.",
            module_cfg.technology,
        )
    return resolve_module_params(module_cfg)


def _calculate_effective_irradiance(
    site: SiteConfig,
    poa_total: pd.Series,
    *,
    solar_zenith: pd.Series | None,
    precipitable_water: pd.Series | None,
) -> pd.Series:
    """Apply the canonical spectral factor to explicit POA irradiance."""
    spectral_factor = _compute_spectral_factor(
        site.module.technology,
        solar_zenith,
        precipitable_water,
        site,
    )
    return poa_total * spectral_factor


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
    *,
    datasheet_reference: _DatasheetSdmReference | None = None,
) -> _SdmOperatingParameters | None:
    """Calculate the shared De Soto parameters used by MPP and I-V paths."""
    if tier in (1, 2):
        return _sdm_cec_parameters(params, effective_irradiance, t_cell)
    if tier in (3, 4):
        if datasheet_reference is None:
            return _sdm_datasheet_parameters(
                params,
                technology,
                effective_irradiance,
                t_cell,
            )
        return _sdm_datasheet_operating_parameters(
            datasheet_reference,
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
        float(spectral_factor.mean()) if hasattr(spectral_factor, "mean") else spectral_factor,
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
    reference = _fit_datasheet_sdm_reference(params, technology)
    if reference is None:
        return None
    return _sdm_datasheet_operating_parameters(reference, effective_irradiance, t_cell)


def _fit_datasheet_sdm_reference(
    params: dict,
    technology: str,
) -> _DatasheetSdmReference | None:
    """Fit environment-independent De Soto reference parameters once."""
    import pvlib.ivtools.sdm

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

    return _DatasheetSdmReference(
        alpha_sc_a_per_c=alpha_sc_a_per_c,
        a_ref=batzelis_params["a_ref"],
        i_l_ref=batzelis_params["I_L_ref"],
        i_o_ref=batzelis_params["I_o_ref"],
        r_sh_ref=batzelis_params["R_sh_ref"],
        r_s=batzelis_params["R_s"],
        eg_ref=eg_ref,
    )


def _sdm_datasheet_operating_parameters(
    reference: _DatasheetSdmReference,
    effective_irradiance: pd.Series,
    t_cell: pd.Series,
) -> _SdmOperatingParameters:
    """Calculate dynamic De Soto parameters from a fitted static reference."""
    import pvlib.pvsystem

    values = pvlib.pvsystem.calcparams_desoto(
        effective_irradiance=effective_irradiance,
        temp_cell=t_cell,
        alpha_sc=reference.alpha_sc_a_per_c,
        a_ref=reference.a_ref,
        I_L_ref=reference.i_l_ref,
        I_o_ref=reference.i_o_ref,
        R_sh_ref=reference.r_sh_ref,
        R_s=reference.r_s,
        EgRef=reference.eg_ref,
    )
    return _as_sdm_parameters(values, effective_irradiance.index)


def _as_sdm_parameters(
    values: tuple,
    index: pd.Index,
) -> _SdmOperatingParameters:
    """Normalize pvlib De Soto outputs to indexed Series."""
    return _SdmOperatingParameters(*(pd.Series(value, index=index) for value in values))


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
