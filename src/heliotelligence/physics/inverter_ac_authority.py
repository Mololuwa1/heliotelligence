"""Explicit static AC capability authority for physical inverter units.

S9-4A records nameplate facts only.  It performs no P/Q/S, current, thermal,
network, controller, or timestamped operating-state calculation.
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

TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_CONTRACT_ID = (
    "topology_inverter_ac_capability_authority_v1"
)
TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_MODEL_ID = (
    "explicit_ac_nameplate_and_fixed_q_limit_authority_v1"
)
TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_SCOPE = (
    "static_inverter_ac_capability_authority_before_pqs_state_evaluation"
)
TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_per_inverter_voltage_phase_smax_with_optional_fixed_q_limits"
)

AcVoltageBasis = Literal["line_to_line", "line_to_neutral", "single_phase_terminal"]
PhaseConfiguration = Literal["single_phase", "three_phase"]
Confidence = Literal["high", "medium", "low", "unknown"]

_VOLTAGE_BASES = {"line_to_line", "line_to_neutral", "single_phase_terminal"}
_PHASES = {"single_phase", "three_phase"}
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_COLUMNS = (
    "nominal_ac_voltage_v",
    "ac_voltage_basis",
    "phase_configuration",
    "rated_apparent_power_va",
    "reactive_power_min_var",
    "reactive_power_max_var",
    "fixed_reactive_power_limits_resolved",
    "ac_capability_authority_resolved",
    "ac_capability_authority_state",
    "parameter_source",
    "confidence",
    "topology_inverter_ac_capability_authority_contract",
    "topology_inverter_ac_capability_authority_model",
    "topology_inverter_ac_capability_authority_scope",
    "topology_inverter_ac_capability_authority_coverage_scope",
)


def _positive_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return result


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real non-Boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class InverterAcCapabilityAuthority:
    nominal_ac_voltage_v: float
    ac_voltage_basis: AcVoltageBasis
    phase_configuration: PhaseConfiguration
    rated_apparent_power_va: float
    reactive_power_min_var: float | None = None
    reactive_power_max_var: float | None = None
    parameter_source: str = ""
    confidence: Confidence = "unknown"

    def __post_init__(self) -> None:
        voltage = _positive_finite(self.nominal_ac_voltage_v, "nominal_ac_voltage_v")
        apparent = _positive_finite(self.rated_apparent_power_va, "rated_apparent_power_va")
        if type(self.ac_voltage_basis) is not str or self.ac_voltage_basis not in _VOLTAGE_BASES:
            raise ValueError("ac_voltage_basis is unsupported")
        if type(self.phase_configuration) is not str or self.phase_configuration not in _PHASES:
            raise ValueError("phase_configuration is unsupported")
        if (
            self.phase_configuration == "three_phase"
            and self.ac_voltage_basis == "single_phase_terminal"
        ):
            raise ValueError("three_phase authority cannot use single_phase_terminal voltage basis")
        if type(self.parameter_source) is not str or not self.parameter_source.strip():
            raise ValueError("parameter_source must be a non-empty string")
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")
        if (self.reactive_power_min_var is None) != (self.reactive_power_max_var is None):
            raise ValueError("reactive-power limits must both be present or both absent")
        object.__setattr__(self, "nominal_ac_voltage_v", voltage)
        object.__setattr__(self, "rated_apparent_power_va", apparent)
        if self.reactive_power_min_var is not None:
            q_min = _finite(self.reactive_power_min_var, "reactive_power_min_var")
            q_max = _finite(self.reactive_power_max_var, "reactive_power_max_var")
            if q_min > q_max:
                raise ValueError("reactive_power_min_var must not exceed reactive_power_max_var")
            if abs(q_min) > apparent or abs(q_max) > apparent:
                raise ValueError("reactive-power magnitude must not exceed apparent power")
            object.__setattr__(self, "reactive_power_min_var", q_min)
            object.__setattr__(self, "reactive_power_max_var", q_max)


@dataclass(frozen=True)
class TopologyInverterAcCapabilityAuthorityDiagnostics:
    inverter_count: int
    resolved_inverter_count: int
    unresolved_inverter_count: int
    explicit_authority_count: int
    missing_authority_count: int
    fixed_q_limit_authority_count: int
    no_fixed_q_limit_authority_count: int
    single_phase_count: int
    three_phase_count: int
    line_to_line_voltage_count: int
    line_to_neutral_voltage_count: int
    single_phase_terminal_voltage_count: int
    authority_model: str


@dataclass(frozen=True)
class TopologyInverterAcCapabilityAuthorityResult:
    authorities_by_inverter_id: Mapping[str, InverterAcCapabilityAuthority]
    states: pd.DataFrame
    diagnostics: TopologyInverterAcCapabilityAuthorityDiagnostics


def resolve_topology_inverter_ac_capability_authority(
    topology: ElectricalTopologyConfig,
    ac_capability_by_inverter_id: Mapping[str, InverterAcCapabilityAuthority],
) -> TopologyInverterAcCapabilityAuthorityResult:
    """Resolve explicit AC capability facts in topology traversal order."""

    if type(topology) is not ElectricalTopologyConfig:
        raise TypeError("topology must be exactly ElectricalTopologyConfig")
    if not isinstance(ac_capability_by_inverter_id, Mapping):
        raise TypeError("ac_capability_by_inverter_id must be a mapping")
    inverter_ids = [inverter.id for inverter in topology.inverters]
    unexpected = [key for key in ac_capability_by_inverter_id if key not in set(inverter_ids)]
    if unexpected:
        raise ValueError(f"unexpected inverter AC capability IDs: {unexpected!r}")
    explicit: dict[str, InverterAcCapabilityAuthority] = {}
    for inverter_id in inverter_ids:
        if inverter_id not in ac_capability_by_inverter_id:
            continue
        authority = ac_capability_by_inverter_id[inverter_id]
        if type(authority) is not InverterAcCapabilityAuthority:
            raise TypeError("every explicit AC capability must use the exact authority type")
        explicit[inverter_id] = authority

    records: list[dict[str, object]] = []
    for inverter_id in inverter_ids:
        row_authority = explicit.get(inverter_id)
        if row_authority is None:
            record: dict[str, object] = {
                "nominal_ac_voltage_v": np.nan,
                "ac_voltage_basis": "",
                "phase_configuration": "",
                "rated_apparent_power_va": np.nan,
                "reactive_power_min_var": np.nan,
                "reactive_power_max_var": np.nan,
                "fixed_reactive_power_limits_resolved": False,
                "ac_capability_authority_resolved": False,
                "ac_capability_authority_state": ("unresolved_no_explicit_ac_capability_authority"),
                "parameter_source": "",
                "confidence": "unknown",
            }
        else:
            q_resolved = row_authority.reactive_power_min_var is not None
            record = {
                "nominal_ac_voltage_v": row_authority.nominal_ac_voltage_v,
                "ac_voltage_basis": row_authority.ac_voltage_basis,
                "phase_configuration": row_authority.phase_configuration,
                "rated_apparent_power_va": row_authority.rated_apparent_power_va,
                "reactive_power_min_var": (
                    row_authority.reactive_power_min_var if q_resolved else np.nan
                ),
                "reactive_power_max_var": (
                    row_authority.reactive_power_max_var if q_resolved else np.nan
                ),
                "fixed_reactive_power_limits_resolved": q_resolved,
                "ac_capability_authority_resolved": True,
                "ac_capability_authority_state": ("resolved_explicit_ac_capability_authority"),
                "parameter_source": row_authority.parameter_source,
                "confidence": row_authority.confidence,
            }
        record.update(
            topology_inverter_ac_capability_authority_contract=(
                TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_CONTRACT_ID
            ),
            topology_inverter_ac_capability_authority_model=(
                TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_MODEL_ID
            ),
            topology_inverter_ac_capability_authority_scope=(
                TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_SCOPE
            ),
            topology_inverter_ac_capability_authority_coverage_scope=(
                TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_COVERAGE_SCOPE
            ),
        )
        records.append(record)
    if records:
        states = pd.DataFrame.from_records(
            records, columns=_COLUMNS, index=pd.Index(inverter_ids, name="inverter_id")
        )
    else:
        states = pd.DataFrame(
            columns=_COLUMNS, index=pd.Index([], name="inverter_id", dtype=object)
        )
    numeric_columns = {
        "nominal_ac_voltage_v",
        "rated_apparent_power_va",
        "reactive_power_min_var",
        "reactive_power_max_var",
    }
    boolean_columns = {
        "fixed_reactive_power_limits_resolved",
        "ac_capability_authority_resolved",
    }
    for column in numeric_columns:
        states[column] = states[column].astype(float)
    for column in boolean_columns:
        states[column] = states[column].astype(bool)
    for column in set(_COLUMNS) - numeric_columns - boolean_columns:
        states[column] = states[column].astype(object)
    diagnostics = _diagnostics(topology, states)
    _validate_result(topology, explicit, states, diagnostics)
    return TopologyInverterAcCapabilityAuthorityResult(
        MappingProxyType(explicit.copy()), states.copy(deep=True), diagnostics
    )


def _diagnostics(
    topology: ElectricalTopologyConfig, states: pd.DataFrame
) -> TopologyInverterAcCapabilityAuthorityDiagnostics:
    resolved = states.loc[states["ac_capability_authority_resolved"].astype(bool)]
    return TopologyInverterAcCapabilityAuthorityDiagnostics(
        inverter_count=topology.inverter_count,
        resolved_inverter_count=len(resolved),
        unresolved_inverter_count=len(states) - len(resolved),
        explicit_authority_count=len(resolved),
        missing_authority_count=len(states) - len(resolved),
        fixed_q_limit_authority_count=int(resolved["fixed_reactive_power_limits_resolved"].sum()),
        no_fixed_q_limit_authority_count=int(
            (~resolved["fixed_reactive_power_limits_resolved"]).sum()
        ),
        single_phase_count=int((resolved["phase_configuration"] == "single_phase").sum()),
        three_phase_count=int((resolved["phase_configuration"] == "three_phase").sum()),
        line_to_line_voltage_count=int((resolved["ac_voltage_basis"] == "line_to_line").sum()),
        line_to_neutral_voltage_count=int(
            (resolved["ac_voltage_basis"] == "line_to_neutral").sum()
        ),
        single_phase_terminal_voltage_count=int(
            (resolved["ac_voltage_basis"] == "single_phase_terminal").sum()
        ),
        authority_model=TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    explicit: Mapping[str, InverterAcCapabilityAuthority],
    states: pd.DataFrame,
    diagnostics: TopologyInverterAcCapabilityAuthorityDiagnostics,
) -> None:
    inverter_ids = [inverter.id for inverter in topology.inverters]
    if tuple(states.columns) != _COLUMNS:
        raise RuntimeError("AC capability authority schema is invalid")
    if states.index.name != "inverter_id" or states.index.has_duplicates:
        raise RuntimeError("AC capability authority index is invalid")
    if states.index.tolist() != inverter_ids or len(states) != topology.inverter_count:
        raise RuntimeError("AC capability authority ordering is invalid")
    if list(explicit) != [key for key in inverter_ids if key in explicit]:
        raise RuntimeError("AC capability authority mapping ordering is invalid")
    expected = _diagnostics(topology, states)
    if diagnostics != expected:
        raise RuntimeError("AC capability authority diagnostics are inconsistent")
    if diagnostics.inverter_count != topology.inverter_count:
        raise RuntimeError("AC capability topology count is inconsistent")
    if diagnostics.explicit_authority_count != len(
        explicit
    ) or diagnostics.resolved_inverter_count != len(explicit):
        raise RuntimeError("AC capability explicit-authority counts are inconsistent")
    missing_count = topology.inverter_count - len(explicit)
    if (
        diagnostics.missing_authority_count != missing_count
        or diagnostics.unresolved_inverter_count != missing_count
    ):
        raise RuntimeError("AC capability missing-authority counts are inconsistent")
    if (
        diagnostics.resolved_inverter_count + diagnostics.unresolved_inverter_count
        != diagnostics.inverter_count
    ):
        raise RuntimeError("AC capability resolution counts do not close")
    if (
        diagnostics.fixed_q_limit_authority_count + diagnostics.no_fixed_q_limit_authority_count
        != diagnostics.resolved_inverter_count
    ):
        raise RuntimeError("AC capability Q-authority counts do not close")
    if (
        diagnostics.single_phase_count + diagnostics.three_phase_count
        != diagnostics.resolved_inverter_count
    ):
        raise RuntimeError("AC capability phase counts do not close")
    if (
        diagnostics.line_to_line_voltage_count
        + diagnostics.line_to_neutral_voltage_count
        + diagnostics.single_phase_terminal_voltage_count
        != diagnostics.resolved_inverter_count
    ):
        raise RuntimeError("AC capability voltage-basis counts do not close")
    provenance = {
        "topology_inverter_ac_capability_authority_contract": (
            TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_CONTRACT_ID
        ),
        "topology_inverter_ac_capability_authority_model": (
            TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_MODEL_ID
        ),
        "topology_inverter_ac_capability_authority_scope": (
            TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_SCOPE
        ),
        "topology_inverter_ac_capability_authority_coverage_scope": (
            TOPOLOGY_INVERTER_AC_CAPABILITY_AUTHORITY_COVERAGE_SCOPE
        ),
    }
    for inverter_id, row in states.iterrows():
        for column, value in provenance.items():
            if row[column] != value:
                raise RuntimeError(f"AC capability {column} is invalid")
        authority = explicit.get(inverter_id)
        if authority is None:
            numeric = (
                "nominal_ac_voltage_v",
                "rated_apparent_power_va",
                "reactive_power_min_var",
                "reactive_power_max_var",
            )
            if not all(pd.isna(row[column]) for column in numeric):
                raise RuntimeError("unresolved AC capability numeric values are invalid")
            actual = (
                row["ac_voltage_basis"],
                row["phase_configuration"],
                row["fixed_reactive_power_limits_resolved"],
                row["ac_capability_authority_resolved"],
                row["ac_capability_authority_state"],
                row["parameter_source"],
                row["confidence"],
            )
            expected_unresolved = (
                "",
                "",
                False,
                False,
                "unresolved_no_explicit_ac_capability_authority",
                "",
                "unknown",
            )
            if actual != expected_unresolved:
                raise RuntimeError("unresolved AC capability state is contradictory")
            continue
        expected_core = (
            authority.nominal_ac_voltage_v,
            authority.ac_voltage_basis,
            authority.phase_configuration,
            authority.rated_apparent_power_va,
            authority.parameter_source,
            authority.confidence,
            True,
            "resolved_explicit_ac_capability_authority",
        )
        actual_core = (
            row["nominal_ac_voltage_v"],
            row["ac_voltage_basis"],
            row["phase_configuration"],
            row["rated_apparent_power_va"],
            row["parameter_source"],
            row["confidence"],
            row["ac_capability_authority_resolved"],
            row["ac_capability_authority_state"],
        )
        if actual_core != expected_core:
            raise RuntimeError("resolved AC capability state does not match authority")
        if authority.reactive_power_min_var is None:
            if bool(row["fixed_reactive_power_limits_resolved"]) or not (
                pd.isna(row["reactive_power_min_var"]) and pd.isna(row["reactive_power_max_var"])
            ):
                raise RuntimeError("absent fixed-Q authority is contradictory")
        elif (
            not bool(row["fixed_reactive_power_limits_resolved"])
            or row["reactive_power_min_var"] != authority.reactive_power_min_var
            or row["reactive_power_max_var"] != authority.reactive_power_max_var
        ):
            raise RuntimeError("resolved fixed-Q authority does not match source")
