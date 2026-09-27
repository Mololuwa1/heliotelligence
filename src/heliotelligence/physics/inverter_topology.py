"""Topology-aware inverter DC-envelope classification.

S9-1 admits canonical S8-3C MPPT-input operating points and canonical S9-0
equipment authority, then classifies each independent tracker without changing
its operating point.  It performs no MPPT aggregation or inverter conversion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Literal, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter_authority import (
    TOPOLOGY_INVERTER_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_INVERTER_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_INVERTER_AUTHORITY_MODEL_ID,
    TOPOLOGY_INVERTER_AUTHORITY_SCOPE,
    TopologyInverterAuthorityDiagnostics,
    TopologyInverterAuthorityResult,
    resolve_topology_inverter_authority,
)

TOPOLOGY_INVERTER_DC_ENVELOPE_CONTRACT_ID = "mppt_input_operating_point_to_inverter_dc_envelope_v1"
TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID = "explicit_mppt_voltage_and_current_limit_classification_v1"
TOPOLOGY_INVERTER_DC_ENVELOPE_SCOPE = "mppt_resolved_inverter_dc_envelope_before_conversion"
TOPOLOGY_INVERTER_DC_ENVELOPE_COVERAGE_SCOPE = (
    "cec_sam_voltage_limits_with_explicit_tracker_current_or_single_input_idcmax"
)

_CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})
_COLUMNS = (
    "v_mppt_input_v",
    "i_mppt_input_a",
    "p_mppt_input_w",
    "mppt_input_resolved",
    "mppt_input_state",
    "inverter_model_reference",
    "inverter_authority_resolved",
    "inverter_authority_state",
    "mppt_voltage_min_v",
    "mppt_voltage_max_v",
    "absolute_dc_voltage_max_v",
    "dc_current_max_a",
    "dc_current_limit_resolved",
    "dc_current_limit_source_kind",
    "dc_current_limit_parameter_source",
    "dc_current_limit_confidence",
    "is_active_dc_input",
    "below_mppt_voltage_limit",
    "above_mppt_voltage_limit",
    "above_absolute_dc_voltage_limit",
    "above_dc_current_limit",
    "dc_limits_satisfied",
    "dc_envelope_resolved",
    "dc_envelope_state",
    "electrical_reference_plane",
    "mppt_input_common_voltage_contract",
    "mppt_input_common_voltage_model",
    "mppt_input_common_voltage_scope",
    "mppt_input_common_voltage_coverage_scope",
    "topology_inverter_authority_contract",
    "topology_inverter_authority_model",
    "topology_inverter_authority_scope",
    "topology_inverter_authority_coverage_scope",
    "topology_inverter_dc_envelope_contract",
    "topology_inverter_dc_envelope_model",
    "topology_inverter_dc_envelope_scope",
    "topology_inverter_dc_envelope_coverage_scope",
)


@dataclass(frozen=True)
class MpptDcCurrentLimitAuthority:
    """Explicit current limit for one physical MPPT tracker."""

    dc_current_max_a: float
    parameter_source: str
    confidence: Literal["high", "medium", "low", "unknown"]

    def __post_init__(self) -> None:
        value = self.dc_current_max_a
        if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value):
            raise ValueError("dc_current_max_a must be a finite real number")
        if value <= 0:
            raise ValueError("dc_current_max_a must be greater than 0")
        if type(self.parameter_source) is not str or not self.parameter_source.strip():
            raise ValueError("parameter_source must be a non-empty string")
        if self.confidence not in _CONFIDENCE:
            raise ValueError("confidence must be one of: high, medium, low, unknown")


@dataclass(frozen=True)
class TopologyInverterDcEnvelopeDiagnostics:
    inverter_count: int
    mppt_count: int
    populated_mppt_count: int
    timestamp_count: int
    row_count: int
    upstream_unresolved_count: int
    inverter_authority_unresolved_count: int
    current_authority_unresolved_count: int
    inactive_count: int
    within_envelope_count: int
    below_mppt_voltage_count: int
    above_mppt_voltage_count: int
    absolute_overvoltage_count: int
    current_limit_exceeded_count: int
    resolved_envelope_count: int
    unresolved_envelope_count: int
    explicit_mppt_current_limit_count: int
    single_input_idcmax_use_count: int
    envelope_model: str


@dataclass(frozen=True)
class TopologyInverterDcEnvelopeResult:
    states: pd.DataFrame
    diagnostics: TopologyInverterDcEnvelopeDiagnostics


def evaluate_topology_inverter_dc_envelope(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    cec_sam_name_by_inverter_id: Mapping[str, str],
    inverter_authority: TopologyInverterAuthorityResult,
    mppt_current_limit_by_key: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
) -> TopologyInverterDcEnvelopeResult:
    """Classify canonical MPPT-input states against explicit equipment limits."""

    if type(topology) is not ElectricalTopologyConfig:
        raise TypeError("topology must be exactly ElectricalTopologyConfig")
    current_authority = _admit_current_authority(topology, mppt_current_limit_by_key)
    operating_points = _admit_s83c(
        topology,
        topology_string_iv,
        branch_authority,
        mppt_input_string_iv,
        mppt_input_operating_points,
    )
    authority = _admit_s90(topology, cec_sam_name_by_inverter_id, inverter_authority)
    populated_counts = {
        inverter.id: sum(bool(mppt.strings) for mppt in inverter.mppts)
        for inverter in topology.inverters
    }

    records: list[dict[str, object]] = []
    for (_, inverter_id, mppt_id), upstream in operating_points.iterrows():
        authority_row = authority.states.loc[inverter_id]
        reference = authority_row["inverter_model_reference"]
        authority_resolved = bool(authority_row["inverter_authority_resolved"])
        common = {
            "v_mppt_input_v": upstream["v_mppt_input_v"],
            "i_mppt_input_a": upstream["i_mppt_input_a"],
            "p_mppt_input_w": upstream["p_mppt_input_w"],
            "mppt_input_resolved": upstream["mppt_input_resolved"],
            "mppt_input_state": upstream["mppt_input_state"],
            "inverter_model_reference": reference,
            "inverter_authority_resolved": authority_resolved,
            "inverter_authority_state": authority_row["inverter_authority_state"],
        }
        limits: dict[str, object] = {
            "mppt_voltage_min_v": np.nan,
            "mppt_voltage_max_v": np.nan,
            "absolute_dc_voltage_max_v": np.nan,
            "dc_current_max_a": np.nan,
            "dc_current_limit_resolved": False,
            "dc_current_limit_source_kind": "unresolved_no_tracker_current_limit",
            "dc_current_limit_parameter_source": "",
            "dc_current_limit_confidence": "unknown",
        }
        flags: dict[str, object] = {
            "is_active_dc_input": False,
            "below_mppt_voltage_limit": False,
            "above_mppt_voltage_limit": False,
            "above_absolute_dc_voltage_limit": False,
            "above_dc_current_limit": pd.NA,
            "dc_limits_satisfied": pd.NA,
            "dc_envelope_resolved": False,
            "dc_envelope_state": "unresolved_mppt_input_operating_point",
        }
        if not bool(upstream["mppt_input_resolved"]):
            pass
        elif not authority_resolved:
            flags["dc_envelope_state"] = "unresolved_no_explicit_inverter_model_reference"
        else:
            resolved_envelope = authority.dc_envelopes_by_inverter_id[inverter_id]
            envelope = resolved_envelope.envelope
            limits.update(
                mppt_voltage_min_v=envelope.mppt_voltage_min_v,
                mppt_voltage_max_v=envelope.mppt_voltage_max_v,
                absolute_dc_voltage_max_v=envelope.absolute_dc_voltage_max_v,
            )
            key = (inverter_id, mppt_id)
            explicit = current_authority.get(key)
            if explicit is not None:
                limits.update(
                    dc_current_max_a=float(explicit.dc_current_max_a),
                    dc_current_limit_resolved=True,
                    dc_current_limit_source_kind="explicit_mppt_current_limit",
                    dc_current_limit_parameter_source=explicit.parameter_source,
                    dc_current_limit_confidence=explicit.confidence,
                )
            elif populated_counts[inverter_id] == 1:
                limits.update(
                    dc_current_max_a=envelope.dc_current_max_a,
                    dc_current_limit_resolved=True,
                    dc_current_limit_source_kind=("inverter_idcmax_single_populated_mppt"),
                    dc_current_limit_parameter_source=resolved_envelope.parameter_source,
                    dc_current_limit_confidence=resolved_envelope.confidence,
                )
            _classify(upstream, limits, flags)
        records.append(
            {
                **common,
                **limits,
                **flags,
                "electrical_reference_plane": dc_collection.MPPT_INPUT_REFERENCE_PLANE,
                "mppt_input_common_voltage_contract": upstream[
                    "mppt_input_common_voltage_contract"
                ],
                "mppt_input_common_voltage_model": upstream["mppt_input_common_voltage_model"],
                "mppt_input_common_voltage_scope": upstream["mppt_input_common_voltage_scope"],
                "mppt_input_common_voltage_coverage_scope": upstream[
                    "mppt_input_common_voltage_coverage_scope"
                ],
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
            }
        )

    states = pd.DataFrame(records, index=operating_points.index.copy(), columns=_COLUMNS)
    for column in ("above_dc_current_limit", "dc_limits_satisfied"):
        states[column] = states[column].astype("boolean")
    diagnostics = _diagnostics(topology, states)
    _validate_result(topology, states, diagnostics)
    return TopologyInverterDcEnvelopeResult(states.copy(deep=True), diagnostics)


def _classify(upstream: pd.Series, limits: dict[str, object], flags: dict[str, object]) -> None:
    voltage = float(upstream["v_mppt_input_v"])
    current = float(upstream["i_mppt_input_a"])
    power = float(upstream["p_mppt_input_w"])
    active = power > 0.0
    flags["is_active_dc_input"] = active
    below = active and voltage < cast(float, limits["mppt_voltage_min_v"])
    above = active and voltage > cast(float, limits["mppt_voltage_max_v"])
    absolute = voltage > cast(float, limits["absolute_dc_voltage_max_v"])
    current_resolved = bool(limits["dc_current_limit_resolved"])
    above_current: bool | pd._libs.missing.NAType = pd.NA
    if current_resolved:
        above_current = current > cast(float, limits["dc_current_max_a"])
    flags.update(
        below_mppt_voltage_limit=below,
        above_mppt_voltage_limit=above,
        above_absolute_dc_voltage_limit=absolute,
        above_dc_current_limit=above_current,
    )
    if not active:
        flags.update(
            above_dc_current_limit=False,
            dc_limits_satisfied=True,
            dc_envelope_resolved=True,
            dc_envelope_state="resolved_inactive_dc_input",
        )
    elif absolute:
        flags.update(
            dc_limits_satisfied=False,
            dc_envelope_resolved=True,
            dc_envelope_state="resolved_absolute_dc_overvoltage",
        )
    elif above_current is True:
        flags.update(
            dc_limits_satisfied=False,
            dc_envelope_resolved=True,
            dc_envelope_state="resolved_dc_current_limit_exceeded",
        )
    elif above:
        flags.update(
            dc_limits_satisfied=False,
            dc_envelope_resolved=True,
            dc_envelope_state="resolved_above_mppt_voltage",
        )
    elif below:
        flags.update(
            dc_limits_satisfied=False,
            dc_envelope_resolved=True,
            dc_envelope_state="resolved_below_mppt_voltage",
        )
    elif not current_resolved:
        flags["dc_envelope_state"] = "unresolved_no_explicit_mppt_current_limit_for_multi_mppt"
    else:
        flags.update(
            dc_limits_satisfied=True,
            dc_envelope_resolved=True,
            dc_envelope_state="resolved_within_dc_envelope",
        )


def _admit_current_authority(
    topology: ElectricalTopologyConfig, supplied: object
) -> dict[tuple[str, str], MpptDcCurrentLimitAuthority]:
    if not isinstance(supplied, Mapping):
        raise TypeError("mppt_current_limit_by_key must be a mapping")
    valid_keys = {
        (inverter.id, mppt.id) for inverter in topology.inverters for mppt in inverter.mppts
    }
    output: dict[tuple[str, str], MpptDcCurrentLimitAuthority] = {}
    for key, value in supplied.items():
        if type(key) is not tuple or len(key) != 2 or key not in valid_keys:
            raise ValueError(f"unexpected MPPT current-limit key: {key!r}")
        if type(value) is not MpptDcCurrentLimitAuthority:
            raise ValueError("MPPT current-limit values must be exact authority objects")
        output[key] = value
    return output


def _admit_s83c(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not dc_collection.TopologyMpptInputOperatingPointResult:
        raise ValueError("S8-3C result type is invalid")
    if type(supplied.diagnostics) is not dc_collection.TopologyMpptInputOperatingPointDiagnostics:
        raise ValueError("S8-3C diagnostics type is invalid")
    replayed = dc_collection.calculate_topology_mppt_input_operating_points(
        topology, topology_string_iv, branch_authority, mppt_input_string_iv
    )
    try:
        pd.testing.assert_frame_equal(
            supplied.operating_points,
            replayed.operating_points,
            check_exact=True,
            check_like=False,
        )
    except AssertionError as error:
        raise ValueError("S8-3C operating points do not match canonical replay") from error
    if supplied.diagnostics != replayed.diagnostics:
        raise ValueError("S8-3C diagnostics do not match canonical replay")
    return replayed.operating_points.copy(deep=True)


def _admit_s90(
    topology: ElectricalTopologyConfig,
    names: Mapping[str, str],
    supplied: object,
) -> TopologyInverterAuthorityResult:
    if type(supplied) is not TopologyInverterAuthorityResult:
        raise ValueError("S9-0 result type is invalid")
    if type(supplied.diagnostics) is not TopologyInverterAuthorityDiagnostics:
        raise ValueError("S9-0 diagnostics type is invalid")
    replayed = resolve_topology_inverter_authority(topology, names)
    try:
        pd.testing.assert_frame_equal(supplied.states, replayed.states, check_exact=True)
    except AssertionError as error:
        raise ValueError("S9-0 states do not match canonical replay") from error
    if supplied.diagnostics != replayed.diagnostics:
        raise ValueError("S9-0 diagnostics do not match canonical replay")
    if (
        list(supplied.sandia_models_by_inverter_id) != list(replayed.sandia_models_by_inverter_id)
        or list(supplied.dc_envelopes_by_inverter_id) != list(replayed.dc_envelopes_by_inverter_id)
        or dict(supplied.sandia_models_by_inverter_id)
        != dict(replayed.sandia_models_by_inverter_id)
        or dict(supplied.dc_envelopes_by_inverter_id) != dict(replayed.dc_envelopes_by_inverter_id)
    ):
        raise ValueError("S9-0 equipment objects do not match canonical replay")
    return replayed


def _diagnostics(
    topology: ElectricalTopologyConfig, states: pd.DataFrame
) -> TopologyInverterDcEnvelopeDiagnostics:
    counts = states["dc_envelope_state"].value_counts()
    source = states["dc_current_limit_source_kind"]
    populated = sum(bool(mppt.strings) for inv in topology.inverters for mppt in inv.mppts)
    resolved = int(states["dc_envelope_resolved"].sum()) if len(states) else 0
    return TopologyInverterDcEnvelopeDiagnostics(
        inverter_count=topology.inverter_count,
        mppt_count=topology.mppt_count,
        populated_mppt_count=populated,
        timestamp_count=len(states.index.get_level_values("timestamp").unique())
        if len(states)
        else 0,
        row_count=len(states),
        upstream_unresolved_count=int(counts.get("unresolved_mppt_input_operating_point", 0)),
        inverter_authority_unresolved_count=int(
            counts.get("unresolved_no_explicit_inverter_model_reference", 0)
        ),
        current_authority_unresolved_count=int(
            counts.get("unresolved_no_explicit_mppt_current_limit_for_multi_mppt", 0)
        ),
        inactive_count=int(counts.get("resolved_inactive_dc_input", 0)),
        within_envelope_count=int(counts.get("resolved_within_dc_envelope", 0)),
        below_mppt_voltage_count=int(counts.get("resolved_below_mppt_voltage", 0)),
        above_mppt_voltage_count=int(counts.get("resolved_above_mppt_voltage", 0)),
        absolute_overvoltage_count=int(counts.get("resolved_absolute_dc_overvoltage", 0)),
        current_limit_exceeded_count=int(counts.get("resolved_dc_current_limit_exceeded", 0)),
        resolved_envelope_count=resolved,
        unresolved_envelope_count=len(states) - resolved,
        explicit_mppt_current_limit_count=int((source == "explicit_mppt_current_limit").sum()),
        single_input_idcmax_use_count=int(
            (source == "inverter_idcmax_single_populated_mppt").sum()
        ),
        envelope_model=TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    states: pd.DataFrame,
    diagnostics: TopologyInverterDcEnvelopeDiagnostics,
) -> None:
    if tuple(states.columns) != _COLUMNS:
        raise RuntimeError("S9-1 state schema is invalid")
    if (
        not isinstance(states.index, pd.MultiIndex)
        or states.index.names != ["timestamp", "inverter_id", "mppt_id"]
        or states.index.has_duplicates
    ):
        raise RuntimeError("S9-1 state index is invalid")
    if (
        str(states["above_dc_current_limit"].dtype) != "boolean"
        or str(states["dc_limits_satisfied"].dtype) != "boolean"
    ):
        raise RuntimeError("S9-1 nullable Boolean dtype is invalid")
    if (
        diagnostics.row_count
        != diagnostics.resolved_envelope_count + diagnostics.unresolved_envelope_count
    ):
        raise RuntimeError("S9-1 resolution counts do not close")
    if diagnostics.row_count != diagnostics.timestamp_count * diagnostics.populated_mppt_count:
        raise RuntimeError("S9-1 output grid does not close")
    if (
        diagnostics.inverter_count != topology.inverter_count
        or diagnostics.mppt_count != topology.mppt_count
    ):
        raise RuntimeError("S9-1 topology diagnostics are stale")
    if diagnostics.envelope_model != TOPOLOGY_INVERTER_DC_ENVELOPE_MODEL_ID:
        raise RuntimeError("S9-1 model provenance is invalid")
    if diagnostics.row_count:
        resolved = states["dc_envelope_resolved"]
        if states.loc[resolved, "dc_limits_satisfied"].isna().any():
            raise RuntimeError("resolved S9-1 rows require a definite limit result")
        definite_false = states["dc_limits_satisfied"].eq(False).fillna(False)  # noqa: E712
        if (definite_false & ~resolved).any():
            raise RuntimeError("definite violations must be resolved")
