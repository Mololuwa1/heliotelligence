"""DC operating-envelope physics for inverter inputs.

This module evaluates whether an explicit inverter-boundary DC state is within
its declared operating envelope.  It is deliberately separate from AC
conversion: no input is clipped, clamped, or re-solved here.

The MPPT voltage window is an operational constraint and is therefore checked
only while positive DC power is being presented to the inverter.  Absolute DC
voltage and DC current are equipment/safety limits and remain observable even
when DC power is zero.  Boundary values are inclusive.

A violated current or MPPT constraint does not imply that the physically valid
constrained operating point is ``V * I_limit``.  Resolving that point can
require the upstream voltage-dependent string/MPPT model to be solved again,
so this layer reports constraint state only.

The envelope is for one evaluated inverter DC input boundary.  CEC/SAM
``Idcmax`` is a row-level inverter DC input limit and must not be copied onto
independent MPPTs as though it were a per-tracker rating.  Multi-MPPT routing
and tracker-specific current limits remain a later integration concern.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd

_ENVELOPE_KEYS = ("Mppt_low", "Mppt_high", "Vdcmax", "Idcmax")
_CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unknown"})
_OUTPUT_COLUMNS = [
    "v_dc_v",
    "i_dc_a",
    "p_dc_available_w",
    "is_active_dc_input",
    "below_mppt_voltage_limit",
    "above_mppt_voltage_limit",
    "above_absolute_dc_voltage_limit",
    "above_dc_current_limit",
    "dc_limits_satisfied",
    "dc_operating_state",
    "envelope_parameter_source",
    "envelope_confidence",
]


@dataclass(frozen=True)
class InverterDcOperatingEnvelope:
    """Validated inverter DC voltage and current operating limits."""

    mppt_voltage_min_v: float
    mppt_voltage_max_v: float
    absolute_dc_voltage_max_v: float
    dc_current_max_a: float

    def __post_init__(self) -> None:
        values = {
            "mppt_voltage_min_v": self.mppt_voltage_min_v,
            "mppt_voltage_max_v": self.mppt_voltage_max_v,
            "absolute_dc_voltage_max_v": self.absolute_dc_voltage_max_v,
            "dc_current_max_a": self.dc_current_max_a,
        }
        for name, value in values.items():
            _validate_finite_real(value, name)
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")

        if self.mppt_voltage_min_v >= self.mppt_voltage_max_v:
            raise ValueError("mppt_voltage_min_v must be less than mppt_voltage_max_v")
        if self.mppt_voltage_max_v > self.absolute_dc_voltage_max_v:
            raise ValueError(
                "mppt_voltage_max_v must be less than or equal to "
                "absolute_dc_voltage_max_v"
            )


@dataclass(frozen=True)
class ResolvedInverterDcOperatingEnvelope:
    """An inverter DC envelope with auditable source and confidence."""

    envelope: InverterDcOperatingEnvelope
    parameter_source: str
    confidence: Literal["high", "medium", "low", "unknown"]

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, InverterDcOperatingEnvelope):
            raise ValueError("envelope must be InverterDcOperatingEnvelope")
        if (
            not isinstance(self.parameter_source, str)
            or not self.parameter_source
            or self.parameter_source.isspace()
        ):
            raise ValueError("parameter_source must be a non-empty, non-whitespace string")
        if (
            not isinstance(self.confidence, str)
            or self.confidence not in _CONFIDENCE_VALUES
        ):
            raise ValueError("confidence must be one of: high, low, medium, unknown")


def inverter_dc_operating_envelope_from_mapping(
    values: Mapping[str, object],
) -> InverterDcOperatingEnvelope:
    """Build an operating envelope from a trusted CEC/SAM-like mapping."""
    if not isinstance(values, Mapping):
        raise ValueError("values must be a mapping")
    missing = sorted(set(_ENVELOPE_KEYS) - set(values))
    if missing:
        raise ValueError("missing inverter envelope keys: " + ", ".join(missing))

    return InverterDcOperatingEnvelope(
        mppt_voltage_min_v=values["Mppt_low"],  # type: ignore[arg-type]
        mppt_voltage_max_v=values["Mppt_high"],  # type: ignore[arg-type]
        absolute_dc_voltage_max_v=values["Vdcmax"],  # type: ignore[arg-type]
        dc_current_max_a=values["Idcmax"],  # type: ignore[arg-type]
    )


def evaluate_inverter_dc_operating_envelope(
    v_dc_v: pd.Series,
    i_dc_a: pd.Series,
    p_dc_available_w: pd.Series,
    resolved_envelope: ResolvedInverterDcOperatingEnvelope,
) -> pd.DataFrame:
    """Classify explicit inverter-boundary DC states without changing them."""
    inputs = {
        "v_dc_v": v_dc_v,
        "i_dc_a": i_dc_a,
        "p_dc_available_w": p_dc_available_w,
    }
    for name, series in inputs.items():
        if not isinstance(series, pd.Series):
            raise ValueError(f"{name} must be a pandas Series")
    if not isinstance(resolved_envelope, ResolvedInverterDcOperatingEnvelope):
        raise ValueError(
            "resolved_envelope must be ResolvedInverterDcOperatingEnvelope"
        )

    if not v_dc_v.index.equals(i_dc_a.index) or not v_dc_v.index.equals(
        p_dc_available_w.index
    ):
        raise ValueError("v_dc_v, i_dc_a, and p_dc_available_w indexes must match exactly")

    for name, series in inputs.items():
        _validate_electrical_series(series, name)

    is_active_dc_input = p_dc_available_w > 0
    if (is_active_dc_input & (v_dc_v <= 0)).any():
        raise ValueError("positive p_dc_available_w requires positive v_dc_v")
    if (is_active_dc_input & (i_dc_a <= 0)).any():
        raise ValueError("positive p_dc_available_w requires positive i_dc_a")

    if v_dc_v.empty:
        return _empty_operating_envelope_result(v_dc_v.index)

    envelope = resolved_envelope.envelope
    below_mppt_voltage_limit = is_active_dc_input & (
        v_dc_v < envelope.mppt_voltage_min_v
    )
    above_mppt_voltage_limit = is_active_dc_input & (
        v_dc_v > envelope.mppt_voltage_max_v
    )
    above_absolute_dc_voltage_limit = v_dc_v > envelope.absolute_dc_voltage_max_v
    above_dc_current_limit = i_dc_a > envelope.dc_current_max_a

    dc_limits_satisfied = ~(
        below_mppt_voltage_limit
        | above_mppt_voltage_limit
        | above_absolute_dc_voltage_limit
        | above_dc_current_limit
    )

    dc_operating_state = pd.Series("inactive", index=v_dc_v.index, dtype=object)
    dc_operating_state.loc[is_active_dc_input & dc_limits_satisfied] = "within_envelope"
    dc_operating_state.loc[below_mppt_voltage_limit] = "below_mppt_voltage"
    dc_operating_state.loc[above_mppt_voltage_limit] = "above_mppt_voltage"
    dc_operating_state.loc[above_dc_current_limit] = "dc_current_limit_exceeded"
    dc_operating_state.loc[above_absolute_dc_voltage_limit] = "absolute_dc_overvoltage"

    return pd.DataFrame(
        {
            "v_dc_v": v_dc_v.copy(),
            "i_dc_a": i_dc_a.copy(),
            "p_dc_available_w": p_dc_available_w.copy(),
            "is_active_dc_input": is_active_dc_input,
            "below_mppt_voltage_limit": below_mppt_voltage_limit,
            "above_mppt_voltage_limit": above_mppt_voltage_limit,
            "above_absolute_dc_voltage_limit": above_absolute_dc_voltage_limit,
            "above_dc_current_limit": above_dc_current_limit,
            "dc_limits_satisfied": dc_limits_satisfied,
            "dc_operating_state": dc_operating_state,
            "envelope_parameter_source": resolved_envelope.parameter_source,
            "envelope_confidence": resolved_envelope.confidence,
        },
        index=v_dc_v.index,
        columns=_OUTPUT_COLUMNS,
    )


def _validate_finite_real(value: object, name: str) -> None:
    """Reject booleans, non-real values, and non-finite real values."""
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")


def _validate_electrical_series(series: pd.Series, name: str) -> None:
    """Validate finite non-negative numeric values without coercion."""
    for value in series.array:
        _validate_finite_real(value, f"{name} values")
        if value < 0:
            raise ValueError(f"{name} values must be greater than or equal to 0")


def _empty_operating_envelope_result(index: pd.Index) -> pd.DataFrame:
    """Return the stable empty envelope schema with populated-compatible dtypes."""
    return pd.DataFrame(
        {
            "v_dc_v": pd.Series(index=index, dtype=float),
            "i_dc_a": pd.Series(index=index, dtype=float),
            "p_dc_available_w": pd.Series(index=index, dtype=float),
            "is_active_dc_input": pd.Series(index=index, dtype=bool),
            "below_mppt_voltage_limit": pd.Series(index=index, dtype=bool),
            "above_mppt_voltage_limit": pd.Series(index=index, dtype=bool),
            "above_absolute_dc_voltage_limit": pd.Series(index=index, dtype=bool),
            "above_dc_current_limit": pd.Series(index=index, dtype=bool),
            "dc_limits_satisfied": pd.Series(index=index, dtype=bool),
            "dc_operating_state": pd.Series(index=index, dtype=object),
            "envelope_parameter_source": pd.Series(index=index, dtype=str),
            "envelope_confidence": pd.Series(index=index, dtype=str),
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )
