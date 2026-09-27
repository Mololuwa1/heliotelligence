"""Model-native Sandia AC potential before inverter-level limiting.

S9-3A implements the published Sandia polynomial locally.  It does not depend
on pvlib private helpers, alter S9-2 available AC, or perform loss accounting.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter import SandiaInverterParameters
from heliotelligence.physics.inverter_authority import (
    TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
    TOPOLOGY_INVERTER_AUTHORITY_SCOPE,
    TopologyInverterAuthorityResult,
)
from heliotelligence.physics.inverter_conversion import (
    INVERTER_AC_OUTPUT_REFERENCE_PLANE,
    MPPT_INPUT_REFERENCE_PLANE,
    TOPOLOGY_SANDIA_INVERTER_AC_CONTRACT_ID,
    TOPOLOGY_SANDIA_INVERTER_AC_COVERAGE_SCOPE,
    TOPOLOGY_SANDIA_INVERTER_AC_MODEL_ID,
    TOPOLOGY_SANDIA_INVERTER_AC_SCOPE,
    TopologySandiaInverterAcDiagnostics,
    TopologySandiaInverterAcResult,
    calculate_topology_sandia_inverter_ac,
)
from heliotelligence.physics.inverter_topology import (
    TOPOLOGY_INVERTER_DC_ENVELOPE_CONTRACT_ID,
    TOPOLOGY_INVERTER_DC_ENVELOPE_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID,
    TOPOLOGY_INVERTER_DC_ENVELOPE_SCOPE,
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
    evaluate_topology_inverter_dc_envelope,
)

TOPOLOGY_SANDIA_PRE_LIMIT_AC_CONTRACT_ID = "admitted_sandia_inverter_ac_to_pre_limit_potential_v1"
TOPOLOGY_SANDIA_PRE_LIMIT_AC_MODEL_ID = "published_sandia_pre_limit_single_or_multi_mppt_v1"
TOPOLOGY_SANDIA_PRE_LIMIT_AC_SCOPE = "inverter_ac_pre_paco_limit_before_loss_accounting"
TOPOLOGY_SANDIA_PRE_LIMIT_AC_COVERAGE_SCOPE = (
    "cec_sam_sandia_inverters_at_or_above_startup_threshold"
)
INVERTER_AC_PRE_PACO_LIMIT_REFERENCE_PLANE = "inverter_ac_pre_paco_limit"

_COLUMNS = (
    "p_dc_inverter_input_w",
    "p_ac_available_w",
    "inverter_conversion_state",
    "p_ac_pre_limit_w",
    "paco_w",
    "pso_w",
    "pnt_w",
    "pre_limit_ac_applicable",
    "pre_limit_ac_resolved",
    "pre_limit_ac_state",
    "would_hit_paco",
    "pre_limit_ac_exceeds_dc_input",
    "sandia_pre_limit_path",
    "inverter_model_reference",
    "sandia_parameter_source",
    "sandia_confidence",
    "source_reference_plane",
    "potential_reference_plane",
    "available_reference_plane",
    "topology_inverter_authority_contract",
    "topology_inverter_authority_model",
    "topology_inverter_authority_scope",
    "topology_inverter_authority_coverage_scope",
    "topology_inverter_dc_envelope_contract",
    "topology_inverter_dc_envelope_model",
    "topology_inverter_dc_envelope_scope",
    "topology_inverter_dc_envelope_coverage_scope",
    "topology_sandia_inverter_ac_contract",
    "topology_sandia_inverter_ac_model",
    "topology_sandia_inverter_ac_scope",
    "topology_sandia_inverter_ac_coverage_scope",
    "topology_sandia_pre_limit_ac_contract",
    "topology_sandia_pre_limit_ac_model",
    "topology_sandia_pre_limit_ac_scope",
    "topology_sandia_pre_limit_ac_coverage_scope",
    "pvlib_version",
)


@dataclass(frozen=True)
class TopologySandiaPreLimitAcDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    timestamp_count: int
    row_count: int
    applicable_count: int
    not_applicable_below_startup_count: int
    unresolved_upstream_count: int
    unresolved_nonfinite_count: int
    single_mppt_evaluation_count: int
    multi_mppt_evaluation_count: int
    would_hit_paco_count: int
    pre_limit_exceeds_dc_count: int
    resolved_count: int
    unresolved_count: int
    model: str


@dataclass(frozen=True)
class TopologySandiaPreLimitAcResult:
    operating_points: pd.DataFrame
    diagnostics: TopologySandiaPreLimitAcDiagnostics


def calculate_sandia_pre_limit_ac_power(
    v_dc_v: pd.Series,
    p_dc_w: pd.Series,
    parameters: SandiaInverterParameters,
) -> pd.Series:
    """Evaluate the published single-input Sandia pre-limit polynomial."""

    if not isinstance(v_dc_v, pd.Series) or not isinstance(p_dc_w, pd.Series):
        raise TypeError("v_dc_v and p_dc_w must be pandas Series")
    if not v_dc_v.index.equals(p_dc_w.index):
        raise ValueError("v_dc_v and p_dc_w indexes must match")
    if type(parameters) is not SandiaInverterParameters:
        raise TypeError("parameters must be exactly SandiaInverterParameters")
    voltage = v_dc_v.astype(float)
    power = p_dc_w.astype(float)
    a = parameters.pdco_w * (1.0 + parameters.c1_per_v * (voltage - parameters.vdco_v))
    b = parameters.pso_w * (1.0 + parameters.c2_per_v * (voltage - parameters.vdco_v))
    c = parameters.c0_per_w * (1.0 + parameters.c3_per_v * (voltage - parameters.vdco_v))
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        result = (parameters.paco_w / (a - b) - c * (a - b)) * (power - b) + c * (power - b) ** 2
    return pd.Series(result, index=v_dc_v.index, dtype=float)


def _calculate_multi_pre_limit(
    voltages: Sequence[pd.Series],
    powers: Sequence[pd.Series],
    total_power: pd.Series,
    parameters: SandiaInverterParameters,
) -> pd.Series:
    result = pd.Series(0.0, index=total_power.index, dtype=float)
    for voltage, power in zip(voltages, powers, strict=True):
        result += (
            power
            / total_power
            * calculate_sandia_pre_limit_ac_power(voltage, total_power, parameters)
        )
    return result


def calculate_topology_sandia_pre_limit_ac(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    cec_sam_name_by_inverter_id: Mapping[str, str],
    inverter_authority: TopologyInverterAuthorityResult,
    mppt_current_limit_by_key: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    inverter_dc_envelope: TopologyInverterDcEnvelopeResult,
    inverter_ac: TopologySandiaInverterAcResult,
) -> TopologySandiaPreLimitAcResult:
    """Calculate admitted inverter-level Sandia pre-Paco AC potential."""

    admitted_ac = _admit_s92(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        cec_sam_name_by_inverter_id,
        inverter_authority,
        mppt_current_limit_by_key,
        inverter_dc_envelope,
        inverter_ac,
    )
    admitted_envelope = evaluate_topology_inverter_dc_envelope(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        cec_sam_name_by_inverter_id,
        inverter_authority,
        mppt_current_limit_by_key,
    ).states
    populated = {
        inverter.id: [mppt.id for mppt in inverter.mppts if mppt.strings]
        for inverter in topology.inverters
        if any(mppt.strings for mppt in inverter.mppts)
    }
    records: list[dict[str, object]] = []
    for (timestamp, inverter_id), ac_row in admitted_ac.iterrows():
        model = inverter_authority.sandia_models_by_inverter_id.get(inverter_id)
        parameters = model.parameters if model else None
        pdc = ac_row["p_dc_inverter_input_w"]
        raw = np.nan
        applicable = False
        resolved = False
        would_hit: object = pd.NA
        exceeds_dc: object = pd.NA
        path = "not_evaluated"
        state = "unresolved_upstream_sandia_conversion"
        if bool(ac_row["inverter_conversion_resolved"]):
            if parameters is None:
                raise RuntimeError("resolved S9-2 row lacks Sandia authority")
            resolved = True
            if float(pdc) < parameters.pso_w:
                state = "resolved_pre_limit_not_applicable_below_startup"
                path = "not_applicable"
                if not electrical._handoff_close(
                    float(ac_row["p_ac_available_w"]), -parameters.pnt_w
                ):
                    raise RuntimeError("S9-2 night-tare closure failed")
            else:
                applicable = True
                mppt_ids = populated[inverter_id]
                rows = [
                    admitted_envelope.loc[(timestamp, inverter_id, mppt_id)] for mppt_id in mppt_ids
                ]
                eval_index = pd.DatetimeIndex([timestamp])
                voltages = [
                    pd.Series([float(row["v_mppt_input_v"])], index=eval_index) for row in rows
                ]
                powers = [
                    pd.Series([float(row["p_mppt_input_w"])], index=eval_index) for row in rows
                ]
                total = pd.Series([float(pdc)], index=eval_index)
                if len(rows) == 1:
                    raw_series = calculate_sandia_pre_limit_ac_power(voltages[0], total, parameters)
                    path = "sandia_pre_limit_single_mppt"
                else:
                    raw_series = _calculate_multi_pre_limit(voltages, powers, total, parameters)
                    path = "sandia_pre_limit_multi_mppt"
                candidate = float(raw_series.iloc[0])
                if np.isfinite(candidate):
                    raw = candidate
                    would_hit = candidate >= parameters.paco_w
                    exceeds_dc = candidate > float(pdc)
                    state = "resolved_sandia_pre_limit_potential"
                    expected = max(-parameters.pnt_w, min(parameters.paco_w, candidate))
                    if not electrical._handoff_close(expected, float(ac_row["p_ac_available_w"])):
                        raise RuntimeError("S9-3A to S9-2 Sandia closure failed")
                else:
                    resolved = False
                    applicable = False
                    path = "not_evaluated"
                    state = "unresolved_nonfinite_sandia_pre_limit_potential"
        records.append(
            {
                "p_dc_inverter_input_w": pdc,
                "p_ac_available_w": ac_row["p_ac_available_w"],
                "inverter_conversion_state": ac_row["inverter_conversion_state"],
                "p_ac_pre_limit_w": raw,
                "paco_w": parameters.paco_w if parameters else np.nan,
                "pso_w": parameters.pso_w if parameters else np.nan,
                "pnt_w": parameters.pnt_w if parameters else np.nan,
                "pre_limit_ac_applicable": applicable,
                "pre_limit_ac_resolved": resolved,
                "pre_limit_ac_state": state,
                "would_hit_paco": would_hit,
                "pre_limit_ac_exceeds_dc_input": exceeds_dc,
                "sandia_pre_limit_path": path,
                "inverter_model_reference": ac_row["inverter_model_reference"],
                "sandia_parameter_source": ac_row["sandia_parameter_source"],
                "sandia_confidence": ac_row["sandia_confidence"],
                "source_reference_plane": MPPT_INPUT_REFERENCE_PLANE,
                "potential_reference_plane": INVERTER_AC_PRE_PACO_LIMIT_REFERENCE_PLANE,
                "available_reference_plane": INVERTER_AC_OUTPUT_REFERENCE_PLANE,
                "topology_inverter_authority_contract": TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID,
                "topology_inverter_authority_model": TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
                "topology_inverter_authority_scope": TOPOLOGY_INVERTER_AUTHORITY_SCOPE,
                "topology_inverter_authority_coverage_scope": (
                    TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE
                ),
                "topology_inverter_dc_envelope_contract": TOPOLOGY_INVERTER_DC_ENVELOPE_CONTRACT_ID,
                "topology_inverter_dc_envelope_model": TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID,
                "topology_inverter_dc_envelope_scope": TOPOLOGY_INVERTER_DC_ENVELOPE_SCOPE,
                "topology_inverter_dc_envelope_coverage_scope": (
                    TOPOLOGY_INVERTER_DC_ENVELOPE_COVERAGE_SCOPE
                ),
                "topology_sandia_inverter_ac_contract": TOPOLOGY_SANDIA_INVERTER_AC_CONTRACT_ID,
                "topology_sandia_inverter_ac_model": TOPOLOGY_SANDIA_INVERTER_AC_MODEL_ID,
                "topology_sandia_inverter_ac_scope": TOPOLOGY_SANDIA_INVERTER_AC_SCOPE,
                "topology_sandia_inverter_ac_coverage_scope": (
                    TOPOLOGY_SANDIA_INVERTER_AC_COVERAGE_SCOPE
                ),
                "topology_sandia_pre_limit_ac_contract": TOPOLOGY_SANDIA_PRE_LIMIT_AC_CONTRACT_ID,
                "topology_sandia_pre_limit_ac_model": TOPOLOGY_SANDIA_PRE_LIMIT_AC_MODEL_ID,
                "topology_sandia_pre_limit_ac_scope": TOPOLOGY_SANDIA_PRE_LIMIT_AC_SCOPE,
                "topology_sandia_pre_limit_ac_coverage_scope": (
                    TOPOLOGY_SANDIA_PRE_LIMIT_AC_COVERAGE_SCOPE
                ),
                "pvlib_version": pvlib.__version__,
            }
        )
    output = pd.DataFrame(records, index=admitted_ac.index.copy(), columns=_COLUMNS)
    for column in ("would_hit_paco", "pre_limit_ac_exceeds_dc_input"):
        output[column] = output[column].astype("boolean")
    diagnostics = _diagnostics(topology, output)
    _validate_result(admitted_ac, output, diagnostics)
    return TopologySandiaPreLimitAcResult(output.copy(deep=True), diagnostics)


def _admit_s92(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    names: Mapping[str, str],
    authority: TopologyInverterAuthorityResult,
    limits: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    envelope: TopologyInverterDcEnvelopeResult,
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologySandiaInverterAcResult:
        raise ValueError("S9-2 result type is invalid")
    if type(supplied.diagnostics) is not TopologySandiaInverterAcDiagnostics:
        raise ValueError("S9-2 diagnostics type is invalid")
    replayed = calculate_topology_sandia_inverter_ac(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        authority,
        limits,
        envelope,
    )
    try:
        pd.testing.assert_frame_equal(
            supplied.operating_points, replayed.operating_points, check_exact=True
        )
    except AssertionError as error:
        raise ValueError("S9-2 operating points do not match canonical replay") from error
    if supplied.diagnostics != replayed.diagnostics:
        raise ValueError("S9-2 diagnostics do not match canonical replay")
    return replayed.operating_points.copy(deep=True)


def _diagnostics(
    topology: ElectricalTopologyConfig, output: pd.DataFrame
) -> TopologySandiaPreLimitAcDiagnostics:
    counts = output["pre_limit_ac_state"].value_counts()
    represented = len(output.index.get_level_values("inverter_id").unique()) if len(output) else 0
    resolved = int(output["pre_limit_ac_resolved"].sum()) if len(output) else 0
    return TopologySandiaPreLimitAcDiagnostics(
        inverter_count=topology.inverter_count,
        represented_inverter_count=represented,
        timestamp_count=len(output.index.get_level_values("timestamp").unique())
        if len(output)
        else 0,
        row_count=len(output),
        applicable_count=int(output["pre_limit_ac_applicable"].sum()) if len(output) else 0,
        not_applicable_below_startup_count=int(
            counts.get("resolved_pre_limit_not_applicable_below_startup", 0)
        ),
        unresolved_upstream_count=int(counts.get("unresolved_upstream_sandia_conversion", 0)),
        unresolved_nonfinite_count=int(
            counts.get("unresolved_nonfinite_sandia_pre_limit_potential", 0)
        ),
        single_mppt_evaluation_count=int(
            (output["sandia_pre_limit_path"] == "sandia_pre_limit_single_mppt").sum()
        ),
        multi_mppt_evaluation_count=int(
            (output["sandia_pre_limit_path"] == "sandia_pre_limit_multi_mppt").sum()
        ),
        would_hit_paco_count=int(output["would_hit_paco"].fillna(False).sum())
        if len(output)
        else 0,
        pre_limit_exceeds_dc_count=int(output["pre_limit_ac_exceeds_dc_input"].fillna(False).sum())
        if len(output)
        else 0,
        resolved_count=resolved,
        unresolved_count=len(output) - resolved,
        model=TOPOLOGY_SANDIA_PRE_LIMIT_AC_MODEL_ID,
    )


def _validate_result(
    admitted: pd.DataFrame,
    output: pd.DataFrame,
    diagnostics: TopologySandiaPreLimitAcDiagnostics,
) -> None:
    if tuple(output.columns) != _COLUMNS or not output.index.equals(admitted.index):
        raise RuntimeError("S9-3A schema or S9-2 alignment is invalid")
    if output.index.has_duplicates or output.index.names != ["timestamp", "inverter_id"]:
        raise RuntimeError("S9-3A index is invalid")
    if diagnostics.row_count != diagnostics.resolved_count + diagnostics.unresolved_count:
        raise RuntimeError("S9-3A resolution counts do not close")
    for _, row in output.iterrows():
        applicable = bool(row["pre_limit_ac_applicable"])
        resolved = bool(row["pre_limit_ac_resolved"])
        raw = row["p_ac_pre_limit_w"]
        if applicable and resolved:
            if not np.isfinite(raw):
                raise RuntimeError("applicable S9-3A potential must be finite")
        elif not pd.isna(raw):
            raise RuntimeError("non-applicable or unresolved potential must be NaN")
