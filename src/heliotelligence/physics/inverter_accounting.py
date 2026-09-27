"""Sandia inverter conversion, clipping, and tare power accounting.

S9-3B performs accounting algebra over exactly replayed S9-3A authority.  It
does not calculate a Sandia operating point, alter one, or claim that its
signed empirical-model terms are measured heat or energy losses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter_authority import TopologyInverterAuthorityResult
from heliotelligence.physics.inverter_conversion import TopologySandiaInverterAcResult
from heliotelligence.physics.inverter_potential import (
    TopologySandiaPreLimitAcDiagnostics,
    TopologySandiaPreLimitAcResult,
    calculate_topology_sandia_pre_limit_ac,
)
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
)

TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_CONTRACT_ID = (
    "admitted_sandia_pre_limit_to_inverter_power_accounting_v1"
)
TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_MODEL_ID = (
    "sandia_conversion_clipping_and_tare_power_accounting_v1"
)
TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_SCOPE = (
    "inverter_power_accounting_before_thermal_reactive_ac_network_and_dispatch"
)
TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_COVERAGE_SCOPE = (
    "resolved_cec_sam_sandia_conversion_and_pre_limit_states"
)
_ACCOUNTING_ABS_TOL = 1e-8

_COLUMNS = (
    "p_dc_inverter_input_w",
    "p_ac_pre_limit_w",
    "p_ac_available_w",
    "paco_w",
    "pso_w",
    "pnt_w",
    "conversion_delta_w",
    "conversion_loss_w",
    "conversion_gain_w",
    "clipping_loss_w",
    "sandia_tare_ac_consumption_w",
    "net_dc_to_available_ac_delta_w",
    "conversion_clipping_accounting_applicable",
    "tare_accounting_applicable",
    "clipping_active",
    "conversion_gain_present",
    "pre_limit_ac_negative",
    "accounting_resolved",
    "accounting_state",
    "accounting_path",
    "would_hit_paco",
    "pre_limit_ac_exceeds_dc_input",
    "pre_limit_ac_state",
    "inverter_conversion_state",
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
    "topology_sandia_inverter_accounting_contract",
    "topology_sandia_inverter_accounting_model",
    "topology_sandia_inverter_accounting_scope",
    "topology_sandia_inverter_accounting_coverage_scope",
    "pvlib_version",
)


@dataclass(frozen=True)
class TopologySandiaInverterPowerAccountingDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    timestamp_count: int
    row_count: int
    resolved_count: int
    unresolved_count: int
    conversion_clipping_accounting_count: int
    tare_accounting_count: int
    clipping_active_count: int
    paco_boundary_without_clipping_count: int
    conversion_loss_positive_count: int
    conversion_gain_count: int
    pre_limit_negative_count: int
    unresolved_upstream_count: int
    unresolved_nonfinite_pre_limit_count: int
    model: str


@dataclass(frozen=True)
class TopologySandiaInverterPowerAccountingResult:
    accounting: pd.DataFrame
    diagnostics: TopologySandiaInverterPowerAccountingDiagnostics


def calculate_topology_sandia_inverter_power_accounting(
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
    pre_limit_ac: TopologySandiaPreLimitAcResult,
) -> TopologySandiaInverterPowerAccountingResult:
    """Account for admitted Sandia conversion, clipping, and tare power."""

    admitted = _admit_s93a(
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
        pre_limit_ac,
    )
    records: list[dict[str, object]] = []
    upstream_columns = _COLUMNS[20:46]
    for _, row in admitted.iterrows():
        pdc = (
            float(row["p_dc_inverter_input_w"])
            if pd.notna(row["p_dc_inverter_input_w"])
            else np.nan
        )
        pac = float(row["p_ac_available_w"]) if pd.notna(row["p_ac_available_w"]) else np.nan
        praw = float(row["p_ac_pre_limit_w"]) if pd.notna(row["p_ac_pre_limit_w"]) else np.nan
        values: dict[str, object] = {
            "conversion_delta_w": np.nan,
            "conversion_loss_w": np.nan,
            "conversion_gain_w": np.nan,
            "clipping_loss_w": np.nan,
            "sandia_tare_ac_consumption_w": np.nan,
            "net_dc_to_available_ac_delta_w": np.nan,
            "conversion_clipping_accounting_applicable": False,
            "tare_accounting_applicable": False,
            "clipping_active": pd.NA,
            "conversion_gain_present": pd.NA,
            "pre_limit_ac_negative": pd.NA,
            "accounting_resolved": False,
            "accounting_state": "unresolved_upstream_sandia_power_accounting",
            "accounting_path": "not_evaluated",
        }
        state = str(row["pre_limit_ac_state"])
        if bool(row["pre_limit_ac_resolved"]) and bool(row["pre_limit_ac_applicable"]):
            delta = pdc - praw
            loss = max(delta, 0.0)
            gain = max(-delta, 0.0)
            clipping = praw - pac
            values.update(
                conversion_delta_w=delta,
                conversion_loss_w=loss,
                conversion_gain_w=gain,
                clipping_loss_w=clipping,
                sandia_tare_ac_consumption_w=0.0,
                net_dc_to_available_ac_delta_w=pdc - pac,
                conversion_clipping_accounting_applicable=True,
                clipping_active=praw > float(row["paco_w"]),
                conversion_gain_present=gain > 0.0,
                pre_limit_ac_negative=praw < 0.0,
                accounting_resolved=True,
                accounting_state="resolved_sandia_conversion_power_accounting",
                accounting_path="sandia_conversion_clipping_accounting",
            )
        elif state == "resolved_pre_limit_not_applicable_below_startup":
            values.update(
                sandia_tare_ac_consumption_w=-pac,
                net_dc_to_available_ac_delta_w=pdc - pac,
                tare_accounting_applicable=True,
                accounting_resolved=True,
                accounting_state="resolved_sandia_below_startup_tare_accounting",
                accounting_path="sandia_below_startup_tare_accounting",
            )
        elif state == "unresolved_nonfinite_sandia_pre_limit_potential":
            values["accounting_state"] = "unresolved_nonfinite_pre_limit_power_accounting"
        record = {column: row[column] for column in _COLUMNS[:6]}
        record.update(values)
        record.update({column: row[column] for column in upstream_columns})
        record.update(
            topology_sandia_inverter_accounting_contract=(
                TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_CONTRACT_ID
            ),
            topology_sandia_inverter_accounting_model=(
                TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_MODEL_ID
            ),
            topology_sandia_inverter_accounting_scope=(TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_SCOPE),
            topology_sandia_inverter_accounting_coverage_scope=(
                TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_COVERAGE_SCOPE
            ),
            pvlib_version=row["pvlib_version"],
        )
        records.append(record)
    output = pd.DataFrame(records, index=admitted.index.copy(), columns=_COLUMNS)
    for column in ("clipping_active", "conversion_gain_present", "pre_limit_ac_negative"):
        output[column] = output[column].astype("boolean")
    diagnostics = _diagnostics(topology, output)
    _validate(admitted, output, diagnostics)
    return TopologySandiaInverterPowerAccountingResult(output.copy(deep=True), diagnostics)


def _admit_s93a(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    names: Mapping[str, str],
    authority: TopologyInverterAuthorityResult,
    limits: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    envelope: TopologyInverterDcEnvelopeResult,
    inverter_ac: TopologySandiaInverterAcResult,
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologySandiaPreLimitAcResult:
        raise ValueError("S9-3A result type is invalid")
    if type(supplied.diagnostics) is not TopologySandiaPreLimitAcDiagnostics:
        raise ValueError("S9-3A diagnostics type is invalid")
    replayed = calculate_topology_sandia_pre_limit_ac(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
        names,
        authority,
        limits,
        envelope,
        inverter_ac,
    )
    try:
        pd.testing.assert_frame_equal(
            supplied.operating_points, replayed.operating_points, check_exact=True
        )
    except AssertionError as error:
        raise ValueError("S9-3A operating points do not match canonical replay") from error
    if supplied.diagnostics != replayed.diagnostics:
        raise ValueError("S9-3A diagnostics do not match canonical replay")
    return replayed.operating_points.copy(deep=True)


def _diagnostics(
    topology: ElectricalTopologyConfig, output: pd.DataFrame
) -> TopologySandiaInverterPowerAccountingDiagnostics:
    states = output["accounting_state"].value_counts()
    resolved = int(output["accounting_resolved"].sum()) if len(output) else 0
    boundary = (
        (output["p_ac_pre_limit_w"] == output["paco_w"])
        & output["would_hit_paco"].fillna(False)
        & ~output["clipping_active"].fillna(False)
    )
    return TopologySandiaInverterPowerAccountingDiagnostics(
        inverter_count=topology.inverter_count,
        represented_inverter_count=(
            len(output.index.get_level_values("inverter_id").unique()) if len(output) else 0
        ),
        timestamp_count=(
            len(output.index.get_level_values("timestamp").unique()) if len(output) else 0
        ),
        row_count=len(output),
        resolved_count=resolved,
        unresolved_count=len(output) - resolved,
        conversion_clipping_accounting_count=int(
            output["conversion_clipping_accounting_applicable"].sum()
        )
        if len(output)
        else 0,
        tare_accounting_count=int(output["tare_accounting_applicable"].sum()) if len(output) else 0,
        clipping_active_count=int(output["clipping_active"].fillna(False).sum())
        if len(output)
        else 0,
        paco_boundary_without_clipping_count=int(boundary.sum()) if len(output) else 0,
        conversion_loss_positive_count=int((output["conversion_loss_w"] > 0.0).sum()),
        conversion_gain_count=int(output["conversion_gain_present"].fillna(False).sum())
        if len(output)
        else 0,
        pre_limit_negative_count=int(output["pre_limit_ac_negative"].fillna(False).sum())
        if len(output)
        else 0,
        unresolved_upstream_count=int(states.get("unresolved_upstream_sandia_power_accounting", 0)),
        unresolved_nonfinite_pre_limit_count=int(
            states.get("unresolved_nonfinite_pre_limit_power_accounting", 0)
        ),
        model=TOPOLOGY_SANDIA_INVERTER_ACCOUNTING_MODEL_ID,
    )


def _validate(
    admitted: pd.DataFrame,
    output: pd.DataFrame,
    diagnostics: TopologySandiaInverterPowerAccountingDiagnostics,
) -> None:
    if tuple(output.columns) != _COLUMNS or not output.index.equals(admitted.index):
        raise RuntimeError("S9-3B schema or S9-3A alignment is invalid")
    if output.index.has_duplicates or output.index.names != ["timestamp", "inverter_id"]:
        raise RuntimeError("S9-3B index is invalid")
    if diagnostics.row_count != diagnostics.resolved_count + diagnostics.unresolved_count:
        raise RuntimeError("S9-3B resolution counts do not close")
    for _, row in output.iterrows():
        if not bool(row["accounting_resolved"]):
            for column in _COLUMNS[6:12]:
                if pd.notna(row[column]):
                    raise RuntimeError("unresolved S9-3B accounting must be NaN")
            continue
        pdc = float(row["p_dc_inverter_input_w"])
        pac = float(row["p_ac_available_w"])
        if bool(row["conversion_clipping_accounting_applicable"]):
            loss = float(row["conversion_loss_w"])
            gain = float(row["conversion_gain_w"])
            clipping = float(row["clipping_loss_w"])
            raw = float(row["p_ac_pre_limit_w"])
            if min(loss, gain, clipping) < -_ACCOUNTING_ABS_TOL:
                raise RuntimeError("S9-3B accounting components must be non-negative")
            if loss > 0.0 and gain > 0.0:
                raise RuntimeError("conversion loss and gain are mutually exclusive")
            if not electrical._handoff_close(pdc + gain - loss - clipping, pac):
                raise RuntimeError("S9-3B applicable power balance failed")
            if not electrical._handoff_close(raw - pac, clipping):
                raise RuntimeError("S9-3B clipping closure failed")
        else:
            if not electrical._handoff_close(pac, -float(row["pnt_w"])):
                raise RuntimeError("S9-3B tare closure failed")
            if not electrical._handoff_close(
                float(row["sandia_tare_ac_consumption_w"]), float(row["pnt_w"])
            ):
                raise RuntimeError("S9-3B tare accounting failed")
