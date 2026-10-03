"""Explicit static thermal-derating authority for physical inverter units.

S9-4C records static thermal derating authority only. It does not calculate
inverter temperature, evaluate timestamped derated capability, dispatch, or
modify power. Module/cell thermal state is a different physical quantity.
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

TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_CONTRACT_ID = (
    "topology_inverter_thermal_derating_authority_v1"
)
TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_MODEL_ID = (
    "explicit_temperature_domain_piecewise_capability_derating_authority_v1"
)
TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_SCOPE = (
    "static_inverter_thermal_derating_authority_before_temperature_state_evaluation"
)
TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_COVERAGE_SCOPE = (
    "explicit_per_inverter_temperature_domain_with_no_derating_or_piecewise_limits"
)

DeratingMode = Literal["explicit_no_derating", "piecewise_linear_limits"]
Confidence = Literal["high", "medium", "low", "unknown"]

_MODES = {"explicit_no_derating", "piecewise_linear_limits"}
_CONFIDENCES = {"high", "medium", "low", "unknown"}
_COLUMNS = (
    "temperature_quantity",
    "derating_mode",
    "temperature_min_c",
    "temperature_max_c",
    "temperature_point_count",
    "temperature_points_c",
    "active_power_limit_w_curve",
    "apparent_power_limit_va_curve",
    "reactive_power_min_var_curve",
    "reactive_power_max_var_curve",
    "active_power_thermal_limit_resolved",
    "apparent_power_thermal_limit_resolved",
    "reactive_power_thermal_limits_resolved",
    "thermal_derating_authority_resolved",
    "thermal_derating_authority_state",
    "interpolation_model",
    "outside_domain_policy",
    "parameter_source",
    "confidence",
    "topology_inverter_thermal_derating_authority_contract",
    "topology_inverter_thermal_derating_authority_model",
    "topology_inverter_thermal_derating_authority_scope",
    "topology_inverter_thermal_derating_authority_coverage_scope",
)
_FLOAT_COLUMNS = {"temperature_min_c", "temperature_max_c"}
_BOOL_COLUMNS = {
    "active_power_thermal_limit_resolved",
    "apparent_power_thermal_limit_resolved",
    "reactive_power_thermal_limits_resolved",
    "thermal_derating_authority_resolved",
}


def _finite_tuple(value: object, name: str) -> tuple[float, ...]:
    if type(value) is not tuple:
        raise ValueError(f"{name} must be an exact tuple")
    normalized: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, Real):
            raise ValueError(f"{name} values must be real non-Boolean numbers")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{name} values must be finite")
        normalized.append(number)
    return tuple(normalized)


def _optional_curve(
    value: object, name: str, point_count: int
) -> tuple[float, ...] | None:
    if value is None:
        return None
    result = _finite_tuple(value, name)
    if len(result) != point_count:
        raise ValueError(f"{name} must align exactly with temperature_points_c")
    return result


@dataclass(frozen=True)
class InverterThermalDeratingAuthority:
    temperature_quantity: str
    derating_mode: DeratingMode
    temperature_points_c: tuple[float, ...]
    active_power_limit_w: tuple[float, ...] | None = None
    apparent_power_limit_va: tuple[float, ...] | None = None
    reactive_power_min_var: tuple[float, ...] | None = None
    reactive_power_max_var: tuple[float, ...] | None = None
    parameter_source: str = ""
    confidence: Confidence = "unknown"

    def __post_init__(self) -> None:
        if type(self.temperature_quantity) is not str or not self.temperature_quantity.strip():
            raise ValueError("temperature_quantity must be a non-empty string")
        if type(self.derating_mode) is not str or self.derating_mode not in _MODES:
            raise ValueError("derating_mode is unsupported")
        if type(self.parameter_source) is not str or not self.parameter_source.strip():
            raise ValueError("parameter_source must be a non-empty string")
        if type(self.confidence) is not str or self.confidence not in _CONFIDENCES:
            raise ValueError("confidence is unsupported")

        points = _finite_tuple(self.temperature_points_c, "temperature_points_c")
        if len(points) < 2:
            raise ValueError("temperature_points_c must contain at least two points")
        if any(right <= left for left, right in zip(points, points[1:], strict=False)):
            raise ValueError("temperature_points_c must be strictly increasing")

        active = _optional_curve(self.active_power_limit_w, "active_power_limit_w", len(points))
        apparent = _optional_curve(
            self.apparent_power_limit_va, "apparent_power_limit_va", len(points)
        )
        q_min = _optional_curve(
            self.reactive_power_min_var, "reactive_power_min_var", len(points)
        )
        q_max = _optional_curve(
            self.reactive_power_max_var, "reactive_power_max_var", len(points)
        )
        if (q_min is None) != (q_max is None):
            raise ValueError("reactive-power curves must both be present or both absent")

        if self.derating_mode == "explicit_no_derating":
            if len(points) != 2:
                raise ValueError("explicit_no_derating requires exactly two temperature points")
            if any(curve is not None for curve in (active, apparent, q_min, q_max)):
                raise ValueError("explicit_no_derating must not contain capability curves")
        elif all(curve is None for curve in (active, apparent, q_min, q_max)):
            raise ValueError("piecewise_linear_limits requires at least one capability channel")

        if active is not None and any(value < 0.0 for value in active):
            raise ValueError("active_power_limit_w values must be non-negative")
        if apparent is not None and any(value < 0.0 for value in apparent):
            raise ValueError("apparent_power_limit_va values must be non-negative")
        if q_min is not None and q_max is not None and any(
            low > high for low, high in zip(q_min, q_max, strict=True)
        ):
            raise ValueError("reactive-power minimum must not exceed maximum")
        if apparent is not None:
            if active is not None and any(
                power > capacity for power, capacity in zip(active, apparent, strict=True)
            ):
                raise ValueError("active-power limit must not exceed apparent-power limit")
            if q_min is not None and q_max is not None and any(
                abs(low) > capacity or abs(high) > capacity
                for low, high, capacity in zip(q_min, q_max, apparent, strict=True)
            ):
                raise ValueError("reactive-power magnitude must not exceed apparent-power limit")

        object.__setattr__(self, "temperature_points_c", points)
        object.__setattr__(self, "active_power_limit_w", active)
        object.__setattr__(self, "apparent_power_limit_va", apparent)
        object.__setattr__(self, "reactive_power_min_var", q_min)
        object.__setattr__(self, "reactive_power_max_var", q_max)


@dataclass(frozen=True)
class TopologyInverterThermalDeratingAuthorityDiagnostics:
    inverter_count: int
    resolved_inverter_count: int
    unresolved_inverter_count: int
    explicit_authority_count: int
    missing_authority_count: int
    explicit_no_derating_authority_count: int
    piecewise_derating_authority_count: int
    active_power_limit_authority_count: int
    apparent_power_limit_authority_count: int
    reactive_power_limit_authority_count: int
    active_only_authority_count: int
    apparent_only_authority_count: int
    q_only_authority_count: int
    authority_model: str


@dataclass(frozen=True)
class TopologyInverterThermalDeratingAuthorityResult:
    authorities_by_inverter_id: Mapping[str, InverterThermalDeratingAuthority]
    states: pd.DataFrame
    diagnostics: TopologyInverterThermalDeratingAuthorityDiagnostics


def resolve_topology_inverter_thermal_derating_authority(
    topology: ElectricalTopologyConfig,
    thermal_derating_by_inverter_id: Mapping[str, InverterThermalDeratingAuthority],
) -> TopologyInverterThermalDeratingAuthorityResult:
    """Resolve static thermal authority; no temperature or capability is evaluated."""

    if type(topology) is not ElectricalTopologyConfig:
        raise TypeError("topology must be exactly ElectricalTopologyConfig")
    if not isinstance(thermal_derating_by_inverter_id, Mapping):
        raise TypeError("thermal_derating_by_inverter_id must be a mapping")
    inverter_ids = [inverter.id for inverter in topology.inverters]
    known = set(inverter_ids)
    unexpected = [key for key in thermal_derating_by_inverter_id if key not in known]
    if unexpected:
        raise ValueError(f"unexpected inverter thermal authority IDs: {unexpected!r}")
    explicit: dict[str, InverterThermalDeratingAuthority] = {}
    for inverter_id in inverter_ids:
        if inverter_id not in thermal_derating_by_inverter_id:
            continue
        authority = thermal_derating_by_inverter_id[inverter_id]
        if type(authority) is not InverterThermalDeratingAuthority:
            raise TypeError("every explicit thermal authority must use the exact authority type")
        explicit[inverter_id] = authority

    records = [_record(explicit.get(inverter_id)) for inverter_id in inverter_ids]
    states = pd.DataFrame.from_records(
        records, columns=_COLUMNS, index=pd.Index(inverter_ids, name="inverter_id")
    )
    states.index = pd.Index(inverter_ids, name="inverter_id", dtype=object)
    for column in _FLOAT_COLUMNS:
        states[column] = states[column].astype(float)
    states["temperature_point_count"] = states["temperature_point_count"].astype("int64")
    for column in _BOOL_COLUMNS:
        states[column] = states[column].astype(bool)
    for column in set(_COLUMNS) - _FLOAT_COLUMNS - _BOOL_COLUMNS - {"temperature_point_count"}:
        states[column] = states[column].astype(object)

    diagnostics = _diagnostics(topology, states)
    _validate_result(topology, explicit, states, diagnostics)
    return TopologyInverterThermalDeratingAuthorityResult(
        authorities_by_inverter_id=MappingProxyType(explicit.copy()),
        states=states.copy(deep=True),
        diagnostics=diagnostics,
    )


def _record(authority: InverterThermalDeratingAuthority | None) -> dict[str, object]:
    if authority is None:
        record: dict[str, object] = {
            "temperature_quantity": "",
            "derating_mode": "",
            "temperature_min_c": np.nan,
            "temperature_max_c": np.nan,
            "temperature_point_count": 0,
            "temperature_points_c": (),
            "active_power_limit_w_curve": (),
            "apparent_power_limit_va_curve": (),
            "reactive_power_min_var_curve": (),
            "reactive_power_max_var_curve": (),
            "active_power_thermal_limit_resolved": False,
            "apparent_power_thermal_limit_resolved": False,
            "reactive_power_thermal_limits_resolved": False,
            "thermal_derating_authority_resolved": False,
            "thermal_derating_authority_state": (
                "unresolved_no_explicit_inverter_thermal_derating_authority"
            ),
            "interpolation_model": "",
            "outside_domain_policy": "",
            "parameter_source": "",
            "confidence": "unknown",
        }
    else:
        active = authority.active_power_limit_w
        apparent = authority.apparent_power_limit_va
        q_min = authority.reactive_power_min_var
        q_max = authority.reactive_power_max_var
        no_derating = authority.derating_mode == "explicit_no_derating"
        record = {
            "temperature_quantity": authority.temperature_quantity,
            "derating_mode": authority.derating_mode,
            "temperature_min_c": authority.temperature_points_c[0],
            "temperature_max_c": authority.temperature_points_c[-1],
            "temperature_point_count": len(authority.temperature_points_c),
            "temperature_points_c": authority.temperature_points_c,
            "active_power_limit_w_curve": active or (),
            "apparent_power_limit_va_curve": apparent or (),
            "reactive_power_min_var_curve": q_min or (),
            "reactive_power_max_var_curve": q_max or (),
            "active_power_thermal_limit_resolved": active is not None,
            "apparent_power_thermal_limit_resolved": apparent is not None,
            "reactive_power_thermal_limits_resolved": q_min is not None,
            "thermal_derating_authority_resolved": True,
            "thermal_derating_authority_state": (
                "resolved_explicit_no_thermal_derating_authority"
                if no_derating
                else "resolved_explicit_piecewise_thermal_derating_authority"
            ),
            "interpolation_model": "not_applicable" if no_derating else "linear",
            "outside_domain_policy": "unresolved",
            "parameter_source": authority.parameter_source,
            "confidence": authority.confidence,
        }
    record.update(
        topology_inverter_thermal_derating_authority_contract=(
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_CONTRACT_ID
        ),
        topology_inverter_thermal_derating_authority_model=(
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_MODEL_ID
        ),
        topology_inverter_thermal_derating_authority_scope=(
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_SCOPE
        ),
        topology_inverter_thermal_derating_authority_coverage_scope=(
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_COVERAGE_SCOPE
        ),
    )
    return record


def _diagnostics(
    topology: ElectricalTopologyConfig, states: pd.DataFrame
) -> TopologyInverterThermalDeratingAuthorityDiagnostics:
    resolved = states.loc[states["thermal_derating_authority_resolved"]]
    active = resolved["active_power_thermal_limit_resolved"]
    apparent = resolved["apparent_power_thermal_limit_resolved"]
    reactive = resolved["reactive_power_thermal_limits_resolved"]
    return TopologyInverterThermalDeratingAuthorityDiagnostics(
        inverter_count=topology.inverter_count,
        resolved_inverter_count=len(resolved),
        unresolved_inverter_count=len(states) - len(resolved),
        explicit_authority_count=len(resolved),
        missing_authority_count=len(states) - len(resolved),
        explicit_no_derating_authority_count=int(
            (resolved["derating_mode"] == "explicit_no_derating").sum()
        ),
        piecewise_derating_authority_count=int(
            (resolved["derating_mode"] == "piecewise_linear_limits").sum()
        ),
        active_power_limit_authority_count=int(active.sum()),
        apparent_power_limit_authority_count=int(apparent.sum()),
        reactive_power_limit_authority_count=int(reactive.sum()),
        active_only_authority_count=int((active & ~apparent & ~reactive).sum()),
        apparent_only_authority_count=int((~active & apparent & ~reactive).sum()),
        q_only_authority_count=int((~active & ~apparent & reactive).sum()),
        authority_model=TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_MODEL_ID,
    )


def _validate_result(
    topology: ElectricalTopologyConfig,
    explicit: Mapping[str, InverterThermalDeratingAuthority],
    states: pd.DataFrame,
    diagnostics: TopologyInverterThermalDeratingAuthorityDiagnostics,
) -> None:
    inverter_ids = [inverter.id for inverter in topology.inverters]
    if tuple(states.columns) != _COLUMNS:
        raise RuntimeError("thermal authority schema is invalid")
    if states.index.name != "inverter_id" or states.index.has_duplicates:
        raise RuntimeError("thermal authority index is invalid")
    if states.index.tolist() != inverter_ids or len(states) != topology.inverter_count:
        raise RuntimeError("thermal authority topology ordering is invalid")
    expected_dtypes = {
        **{column: "float64" for column in _FLOAT_COLUMNS},
        "temperature_point_count": "int64",
        **{column: "bool" for column in _BOOL_COLUMNS},
    }
    for column in _COLUMNS:
        expected_dtype = expected_dtypes.get(column, "object")
        if str(states[column].dtype) != expected_dtype:
            raise RuntimeError(f"thermal authority dtype is invalid for {column}")
    if list(explicit) != [key for key in inverter_ids if key in explicit]:
        raise RuntimeError("thermal authority mapping ordering is invalid")
    if diagnostics != _diagnostics(topology, states):
        raise RuntimeError("thermal authority diagnostics are inconsistent")
    if diagnostics.inverter_count != topology.inverter_count:
        raise RuntimeError("thermal authority inverter count is inconsistent")
    if diagnostics.explicit_authority_count != len(explicit):
        raise RuntimeError("thermal authority explicit count is inconsistent")
    missing = topology.inverter_count - len(explicit)
    if diagnostics.resolved_inverter_count != len(explicit) or (
        diagnostics.unresolved_inverter_count != missing
        or diagnostics.missing_authority_count != missing
    ):
        raise RuntimeError("thermal authority resolution counts are inconsistent")
    if diagnostics.resolved_inverter_count + diagnostics.unresolved_inverter_count != (
        diagnostics.inverter_count
    ):
        raise RuntimeError("thermal authority resolution counts do not close")
    if (
        diagnostics.explicit_no_derating_authority_count
        + diagnostics.piecewise_derating_authority_count
        != diagnostics.resolved_inverter_count
    ):
        raise RuntimeError("thermal authority mode counts do not close")
    if diagnostics.authority_model != TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_MODEL_ID:
        raise RuntimeError("thermal authority diagnostics model is invalid")

    provenance = {
        "topology_inverter_thermal_derating_authority_contract": (
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_CONTRACT_ID
        ),
        "topology_inverter_thermal_derating_authority_model": (
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_MODEL_ID
        ),
        "topology_inverter_thermal_derating_authority_scope": (
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_SCOPE
        ),
        "topology_inverter_thermal_derating_authority_coverage_scope": (
            TOPOLOGY_INVERTER_THERMAL_DERATING_AUTHORITY_COVERAGE_SCOPE
        ),
    }
    for inverter_id, row in states.iterrows():
        if any(row[column] != value for column, value in provenance.items()):
            raise RuntimeError("thermal authority provenance is invalid")
        authority = explicit.get(inverter_id)
        expected = _record(None) if authority is None else _record(authority)
        for column in _COLUMNS:
            actual_value = row[column]
            expected_value = expected[column]
            if isinstance(expected_value, float) and math.isnan(expected_value):
                if not pd.isna(actual_value):
                    raise RuntimeError("thermal authority unresolved numeric value is invalid")
            elif actual_value != expected_value:
                raise RuntimeError(f"thermal authority row does not replay {column}")
