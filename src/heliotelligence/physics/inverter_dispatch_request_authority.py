"""Admit explicit inverter active-power dispatch-request authority.

S10A records timestamped absolute active-power setpoints at the inverter AC
output.  It does not assess feasibility, select dispatch, persist commands, or
modify P/Q/S. Reactive-power request authority remains exclusively in S9-4B.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import dc_collection, electrical
from heliotelligence.physics.inverter_ac_authority import (
    InverterAcCapabilityAuthority,
    TopologyInverterAcCapabilityAuthorityResult,
)
from heliotelligence.physics.inverter_accounting import (
    TopologySandiaInverterPowerAccountingResult,
)
from heliotelligence.physics.inverter_authority import TopologyInverterAuthorityResult
from heliotelligence.physics.inverter_conversion import TopologySandiaInverterAcResult
from heliotelligence.physics.inverter_potential import TopologySandiaPreLimitAcResult
from heliotelligence.physics.inverter_pqs_capability import (
    InverterReactivePowerRequest,
    TopologyInverterPqsCapabilityResult,
)
from heliotelligence.physics.inverter_temperature_capability import (
    InverterTemperatureState,
    TopologyInverterTemperatureCapabilityResult,
    calculate_topology_inverter_temperature_capability,
)
from heliotelligence.physics.inverter_thermal_authority import (
    InverterThermalDeratingAuthority,
    TopologyInverterThermalDeratingAuthorityResult,
)
from heliotelligence.physics.inverter_topology import (
    MpptDcCurrentLimitAuthority,
    TopologyInverterDcEnvelopeResult,
)

TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_CONTRACT_ID = (
    "topology_inverter_active_power_dispatch_request_authority_v1"
)
TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_MODEL_ID = (
    "explicit_absolute_inverter_ac_active_power_setpoint_authority_v1"
)
TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_SCOPE = (
    "timestamped_inverter_active_power_dispatch_request_authority_before_feasibility_and_selection"
)
TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_direct_per_inverter_active_power_setpoints_at_inverter_ac_output"
)

Confidence = Literal["high", "medium", "low", "unknown"]
ReferencePlane = Literal["inverter_ac_output"]
RequestSemantics = Literal["absolute_active_power_setpoint"]
_CONFIDENCES = {"high", "medium", "low", "unknown"}

_COLUMNS = (
    "active_power_dispatch_request_present",
    "active_power_setpoint_w",
    "active_power_setpoint_is_zero",
    "dispatch_request_reference_plane",
    "dispatch_request_semantics",
    "controller_mode",
    "controller_mode_present",
    "parameter_source",
    "confidence",
    "dispatch_request_authority_resolved",
    "dispatch_request_authority_state",
    "topology_inverter_active_power_dispatch_request_authority_contract",
    "topology_inverter_active_power_dispatch_request_authority_model",
    "topology_inverter_active_power_dispatch_request_authority_scope",
    "topology_inverter_active_power_dispatch_request_authority_coverage_scope",
)
_BOOL = {
    "active_power_dispatch_request_present",
    "controller_mode_present",
    "dispatch_request_authority_resolved",
}


@dataclass(frozen=True)
class InverterActivePowerDispatchRequest:
    """An explicit absolute active-power target at ``inverter_ac_output``.

    Positive power is export/injection toward the downstream AC network; zero
    is an explicit zero request. Negative power is outside the v1 PV contract.
    """

    active_power_setpoint_w: float
    reference_plane: ReferencePlane
    request_semantics: RequestSemantics
    parameter_source: str
    confidence: Confidence
    controller_mode: str | None = None

    def __post_init__(self) -> None:
        value = self.active_power_setpoint_w
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("active_power_setpoint_w must be a real non-Boolean number")
        setpoint = float(value)
        if not math.isfinite(setpoint) or setpoint < 0.0:
            raise ValueError("active_power_setpoint_w must be finite and non-negative")
        if self.reference_plane != "inverter_ac_output":
            raise ValueError("reference_plane must be inverter_ac_output")
        if self.request_semantics != "absolute_active_power_setpoint":
            raise ValueError("request_semantics must be absolute_active_power_setpoint")
        if type(self.parameter_source) is not str or not self.parameter_source.strip():
            raise ValueError("parameter_source must be a non-empty string")
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")
        if self.controller_mode is not None and (
            type(self.controller_mode) is not str or not self.controller_mode.strip()
        ):
            raise ValueError("controller_mode must be None or a non-empty string")
        object.__setattr__(self, "active_power_setpoint_w", setpoint)


@dataclass(frozen=True)
class TopologyInverterActivePowerDispatchRequestAuthorityDiagnostics:
    inverter_count: int
    represented_inverter_count: int
    timestamp_count: int
    row_count: int
    resolved_request_count: int
    unresolved_request_count: int
    explicit_zero_setpoint_count: int
    positive_setpoint_count: int
    controller_mode_present_count: int
    controller_mode_absent_count: int
    model: str


@dataclass(frozen=True)
class TopologyInverterActivePowerDispatchRequestAuthorityResult:
    requests_by_key: Mapping[
        tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest
    ]
    states: pd.DataFrame
    diagnostics: TopologyInverterActivePowerDispatchRequestAuthorityDiagnostics


def resolve_topology_inverter_active_power_dispatch_request_authority(
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
    inverter_power_accounting: TopologySandiaInverterPowerAccountingResult,
    ac_capability_by_inverter_id: Mapping[str, InverterAcCapabilityAuthority],
    ac_capability_authority: TopologyInverterAcCapabilityAuthorityResult,
    reactive_power_request_by_key: Mapping[
        tuple[pd.Timestamp, str], InverterReactivePowerRequest
    ],
    pqs_capability: TopologyInverterPqsCapabilityResult,
    thermal_derating_by_inverter_id: Mapping[
        str, InverterThermalDeratingAuthority
    ],
    thermal_derating_authority: TopologyInverterThermalDeratingAuthorityResult,
    inverter_temperature_by_key: Mapping[
        tuple[pd.Timestamp, str], InverterTemperatureState
    ],
    temperature_capability: TopologyInverterTemperatureCapabilityResult,
    active_power_dispatch_request_by_key: Mapping[
        tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest
    ],
) -> TopologyInverterActivePowerDispatchRequestAuthorityResult:
    """Admit direct P-setpoint evidence without evaluating or applying it."""
    parent = _admit_temperature_capability(
        topology, topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, cec_sam_name_by_inverter_id, inverter_authority,
        mppt_current_limit_by_key, inverter_dc_envelope, inverter_ac, pre_limit_ac,
        inverter_power_accounting, ac_capability_by_inverter_id, ac_capability_authority,
        reactive_power_request_by_key, pqs_capability, thermal_derating_by_inverter_id,
        thermal_derating_authority, inverter_temperature_by_key, temperature_capability,
    )
    admitted = _admit_requests(parent.index, active_power_dispatch_request_by_key)
    states = _build_states(parent.index, admitted)
    diagnostics = _diagnostics(topology, states)
    _validate_result(parent.index, admitted, states, diagnostics, topology)
    return TopologyInverterActivePowerDispatchRequestAuthorityResult(
        MappingProxyType(dict(admitted)), states.copy(deep=True), diagnostics
    )


def _admit_temperature_capability(
    topology: ElectricalTopologyConfig,
    topology_string_iv: electrical.TopologyStringIVResult,
    branch_authority: dc_collection.DcBranchPathAuthorityResult,
    mppt_input_string_iv: dc_collection.TopologyMpptInputStringIVResult,
    mppt_input_operating_points: dc_collection.TopologyMpptInputOperatingPointResult,
    names: Mapping[str, str], inverter_authority: TopologyInverterAuthorityResult,
    limits: Mapping[tuple[str, str], MpptDcCurrentLimitAuthority],
    envelope: TopologyInverterDcEnvelopeResult, inverter_ac: TopologySandiaInverterAcResult,
    potential: TopologySandiaPreLimitAcResult,
    accounting: TopologySandiaInverterPowerAccountingResult,
    ac_mapping: Mapping[str, InverterAcCapabilityAuthority],
    ac_authority: TopologyInverterAcCapabilityAuthorityResult,
    q_requests: Mapping[tuple[pd.Timestamp, str], InverterReactivePowerRequest],
    pqs: TopologyInverterPqsCapabilityResult,
    thermal_mapping: Mapping[str, InverterThermalDeratingAuthority],
    thermal_authority: TopologyInverterThermalDeratingAuthorityResult,
    temperatures: Mapping[tuple[pd.Timestamp, str], InverterTemperatureState],
    supplied: object,
) -> pd.DataFrame:
    if type(supplied) is not TopologyInverterTemperatureCapabilityResult:
        raise ValueError("S9-4D result type is invalid")
    replayed = calculate_topology_inverter_temperature_capability(
        topology, topology_string_iv, branch_authority, mppt_input_string_iv,
        mppt_input_operating_points, names, inverter_authority, limits, envelope,
        inverter_ac, potential, accounting, ac_mapping, ac_authority, q_requests, pqs,
        thermal_mapping, thermal_authority, temperatures,
    )
    try:
        pd.testing.assert_frame_equal(supplied.capability, replayed.capability, check_exact=True)
    except AssertionError as exc:
        raise ValueError("S9-4D capability does not match canonical replay") from exc
    if type(supplied.diagnostics) is not type(replayed.diagnostics) or (
        supplied.diagnostics != replayed.diagnostics
    ):
        raise ValueError("S9-4D diagnostics do not match canonical replay")
    return replayed.capability.copy(deep=True)


def _admit_requests(
    index: pd.Index,
    supplied: Mapping[tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest],
) -> dict[tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest]:
    if not isinstance(supplied, Mapping):
        raise TypeError("active_power_dispatch_request_by_key must be a mapping")
    canonical = [(pd.Timestamp(key[0]), str(key[1])) for key in index]
    canonical_set = set(canonical)
    supplied_by_key: dict[tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest] = {}
    for key, request in supplied.items():
        if type(key) is not tuple or len(key) != 2 or type(key[0]) is not pd.Timestamp or (
            type(key[1]) is not str
        ):
            raise ValueError("dispatch request keys must be (pd.Timestamp, inverter_id)")
        if key not in canonical_set:
            raise ValueError(f"unexpected active-power dispatch request key: {key!r}")
        if type(request) is not InverterActivePowerDispatchRequest:
            raise TypeError("every dispatch request must use the exact request type")
        supplied_by_key[key] = request
    return {key: supplied_by_key[key] for key in canonical if key in supplied_by_key}


def _build_states(
    index: pd.Index,
    requests: Mapping[tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for raw_key in index:
        key = (pd.Timestamp(raw_key[0]), str(raw_key[1]))
        request = requests.get(key)
        if request is None:
            record: dict[str, object] = {
                "active_power_dispatch_request_present": False,
                "active_power_setpoint_w": np.nan,
                "active_power_setpoint_is_zero": pd.NA,
                "dispatch_request_reference_plane": "",
                "dispatch_request_semantics": "",
                "controller_mode": "",
                "controller_mode_present": False,
                "parameter_source": "",
                "confidence": "unknown",
                "dispatch_request_authority_resolved": False,
                "dispatch_request_authority_state": (
                    "unresolved_no_explicit_inverter_active_power_dispatch_request"
                ),
            }
        else:
            record = {
                "active_power_dispatch_request_present": True,
                "active_power_setpoint_w": request.active_power_setpoint_w,
                "active_power_setpoint_is_zero": request.active_power_setpoint_w == 0.0,
                "dispatch_request_reference_plane": request.reference_plane,
                "dispatch_request_semantics": request.request_semantics,
                "controller_mode": request.controller_mode or "",
                "controller_mode_present": request.controller_mode is not None,
                "parameter_source": request.parameter_source,
                "confidence": request.confidence,
                "dispatch_request_authority_resolved": True,
                "dispatch_request_authority_state": (
                    "resolved_explicit_inverter_active_power_dispatch_request"
                ),
            }
        record.update(
            topology_inverter_active_power_dispatch_request_authority_contract=(
                TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_CONTRACT_ID
            ),
            topology_inverter_active_power_dispatch_request_authority_model=(
                TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_MODEL_ID
            ),
            topology_inverter_active_power_dispatch_request_authority_scope=(
                TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_SCOPE
            ),
            topology_inverter_active_power_dispatch_request_authority_coverage_scope=(
                TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_COVERAGE_SCOPE
            ),
        )
        records.append(record)
    frame = pd.DataFrame(records, index=index.copy(), columns=_COLUMNS)
    frame["active_power_setpoint_w"] = frame["active_power_setpoint_w"].astype("float64")
    for column in _BOOL:
        frame[column] = frame[column].astype("bool")
    frame["active_power_setpoint_is_zero"] = frame[
        "active_power_setpoint_is_zero"
    ].astype("boolean")
    for column in set(_COLUMNS) - _BOOL - {
        "active_power_setpoint_w", "active_power_setpoint_is_zero"
    }:
        frame[column] = frame[column].astype("object")
    return frame


def _diagnostics(
    topology: ElectricalTopologyConfig, frame: pd.DataFrame
) -> TopologyInverterActivePowerDispatchRequestAuthorityDiagnostics:
    resolved = frame["dispatch_request_authority_resolved"]
    setpoints = frame.loc[resolved, "active_power_setpoint_w"]
    modes = frame.loc[resolved, "controller_mode_present"]
    return TopologyInverterActivePowerDispatchRequestAuthorityDiagnostics(
        inverter_count=len(topology.inverters),
        represented_inverter_count=len(set(frame.index.get_level_values("inverter_id"))),
        timestamp_count=len(set(frame.index.get_level_values("timestamp"))),
        row_count=len(frame),
        resolved_request_count=int(resolved.sum()),
        unresolved_request_count=int((~resolved).sum()),
        explicit_zero_setpoint_count=int((setpoints == 0.0).sum()),
        positive_setpoint_count=int((setpoints > 0.0).sum()),
        controller_mode_present_count=int(modes.sum()),
        controller_mode_absent_count=int((~modes).sum()),
        model=TOPOLOGY_INVERTER_ACTIVE_POWER_DISPATCH_REQUEST_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    index: pd.Index,
    requests: Mapping[tuple[pd.Timestamp, str], InverterActivePowerDispatchRequest],
    states: pd.DataFrame,
    diagnostics: TopologyInverterActivePowerDispatchRequestAuthorityDiagnostics,
    topology: ElectricalTopologyConfig,
) -> None:
    expected = _build_states(index, requests)
    try:
        pd.testing.assert_frame_equal(states, expected, check_exact=True)
    except AssertionError as exc:
        raise RuntimeError("S10A request-authority result failed exact closure") from exc
    if diagnostics != _diagnostics(topology, expected):
        raise RuntimeError("S10A diagnostics failed exact closure")
    if diagnostics.resolved_request_count + diagnostics.unresolved_request_count != len(states):
        raise RuntimeError("S10A resolution counts do not close")
    if diagnostics.explicit_zero_setpoint_count + diagnostics.positive_setpoint_count != (
        diagnostics.resolved_request_count
    ):
        raise RuntimeError("S10A setpoint counts do not close")
    if diagnostics.controller_mode_present_count + diagnostics.controller_mode_absent_count != (
        diagnostics.resolved_request_count
    ):
        raise RuntimeError("S10A controller-mode counts do not close")
