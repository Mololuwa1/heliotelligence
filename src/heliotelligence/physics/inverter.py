"""Model-aware inverter conversion physics.

This module establishes the Tier 1 Sandia conversion model as an isolated,
component-level physics primitive.  The intended future model hierarchy is:

1. Sandia
2. ADR / Driesse
3. PVWatts inverter
4. constant-efficiency compatibility fallback

Only Sandia is implemented here.  The returned Sandia AC power already
contains the model's Paco limit, so this foundation deliberately does not
invent separate potential-power, conversion-loss, or clipping-loss values.
Later increments must keep conversion, inverter capability, plant-controller
curtailment, cables, transformers, and revenue-meter boundaries distinct.

The eventual output contract is expected to include DC voltage/current/power;
AC potential, conversion loss, clipping loss, available and dispatched power;
P/Q/S, AC voltage/current and power factor; and model provenance.  Future
capability modelling must respect P**2 + Q**2 <= S_rated**2 without describing
reactive-power headroom as ordinary clipping.  MPPT voltage windows, absolute
voltage and current limits, manufacturer or measured-temperature thermal
derating, and multi-MPPT routing are intentionally deferred.  Independent
MPPT voltages must never be averaged: each tracker can have distinct Vdc, Idc,
and Pdc state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Literal

import numpy as np
import pandas as pd
import pvlib.inverter

_SANDIA_KEYS = ("Paco", "Pdco", "Vdco", "Pso", "C0", "C1", "C2", "C3", "Pnt")
_OUTPUT_COLUMNS = [
    "v_dc_v",
    "i_dc_a",
    "p_dc_available_w",
    "p_ac_available_w",
    "ac_to_dc_ratio",
    "operating_state",
    "at_ac_power_limit",
    "model_used",
    "parameter_source",
    "confidence",
]
_CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unknown"})


@dataclass(frozen=True)
class SandiaInverterParameters:
    """Validated coefficients for the public pvlib Sandia inverter model."""

    paco_w: float
    pdco_w: float
    vdco_v: float
    pso_w: float
    c0_per_w: float
    c1_per_v: float
    c2_per_v: float
    c3_per_v: float
    pnt_w: float

    def __post_init__(self) -> None:
        """Validate physical quantities without imposing empirical ranges."""
        values = {
            "paco_w": self.paco_w,
            "pdco_w": self.pdco_w,
            "vdco_v": self.vdco_v,
            "pso_w": self.pso_w,
            "c0_per_w": self.c0_per_w,
            "c1_per_v": self.c1_per_v,
            "c2_per_v": self.c2_per_v,
            "c3_per_v": self.c3_per_v,
            "pnt_w": self.pnt_w,
        }
        for name, value in values.items():
            _validate_finite_real(value, name)

        for name in ("paco_w", "pdco_w", "vdco_v"):
            if values[name] <= 0:
                raise ValueError(f"{name} must be greater than 0")
        for name in ("pso_w", "pnt_w"):
            if values[name] < 0:
                raise ValueError(f"{name} must be greater than or equal to 0")
        if self.pso_w >= self.pdco_w:
            raise ValueError("pso_w must be less than pdco_w")

    def to_pvlib_dict(self) -> dict[str, float]:
        """Return a fresh mapping with pvlib's exact public Sandia keys."""
        return {
            "Paco": float(self.paco_w),
            "Pdco": float(self.pdco_w),
            "Vdco": float(self.vdco_v),
            "Pso": float(self.pso_w),
            "C0": float(self.c0_per_w),
            "C1": float(self.c1_per_v),
            "C2": float(self.c2_per_v),
            "C3": float(self.c3_per_v),
            "Pnt": float(self.pnt_w),
        }


@dataclass(frozen=True)
class ResolvedSandiaInverterModel:
    """Sandia parameters together with auditable source and confidence."""

    parameters: SandiaInverterParameters
    parameter_source: str
    confidence: Literal["high", "medium", "low", "unknown"]

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, SandiaInverterParameters):
            raise ValueError("parameters must be SandiaInverterParameters")
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


def sandia_parameters_from_mapping(
    values: Mapping[str, object],
) -> SandiaInverterParameters:
    """Build Sandia parameters from any trusted mapping-based source."""
    if not isinstance(values, Mapping):
        raise ValueError("values must be a mapping")
    missing = sorted(set(_SANDIA_KEYS) - set(values))
    if missing:
        raise ValueError("missing Sandia parameter keys: " + ", ".join(missing))
    return SandiaInverterParameters(
        paco_w=values["Paco"],  # type: ignore[arg-type]
        pdco_w=values["Pdco"],  # type: ignore[arg-type]
        vdco_v=values["Vdco"],  # type: ignore[arg-type]
        pso_w=values["Pso"],  # type: ignore[arg-type]
        c0_per_w=values["C0"],  # type: ignore[arg-type]
        c1_per_v=values["C1"],  # type: ignore[arg-type]
        c2_per_v=values["C2"],  # type: ignore[arg-type]
        c3_per_v=values["C3"],  # type: ignore[arg-type]
        pnt_w=values["Pnt"],  # type: ignore[arg-type]
    )


def calculate_sandia_inverter_ac_power(
    v_dc_v: pd.Series,
    i_dc_a: pd.Series,
    p_dc_available_w: pd.Series,
    model: ResolvedSandiaInverterModel,
) -> pd.DataFrame:
    """Evaluate one healthy Sandia inverter using explicit Vdc, Idc and Pdc."""
    inputs = {
        "v_dc_v": v_dc_v,
        "i_dc_a": i_dc_a,
        "p_dc_available_w": p_dc_available_w,
    }
    for name, series in inputs.items():
        if not isinstance(series, pd.Series):
            raise ValueError(f"{name} must be a pandas Series")
    if not isinstance(model, ResolvedSandiaInverterModel):
        raise ValueError("model must be ResolvedSandiaInverterModel")

    if not v_dc_v.index.equals(i_dc_a.index) or not v_dc_v.index.equals(
        p_dc_available_w.index
    ):
        raise ValueError("v_dc_v, i_dc_a, and p_dc_available_w indexes must match exactly")

    for name, series in inputs.items():
        _validate_electrical_series(series, name)
    positive_power = p_dc_available_w > 0
    if (positive_power & (v_dc_v <= 0)).any():
        raise ValueError("positive p_dc_available_w requires positive v_dc_v")
    if (positive_power & (i_dc_a <= 0)).any():
        raise ValueError("positive p_dc_available_w requires positive i_dc_a")

    if v_dc_v.empty:
        return _empty_sandia_inverter_result(v_dc_v.index)

    parameters = model.parameters
    p_ac_available_w = pvlib.inverter.sandia(
        v_dc_v,
        p_dc_available_w,
        parameters.to_pvlib_dict(),
    )
    p_ac_available_w = pd.Series(p_ac_available_w, index=v_dc_v.index, dtype=float)
    at_ac_power_limit = p_ac_available_w == parameters.paco_w

    ac_to_dc_ratio = pd.Series(np.nan, index=v_dc_v.index, dtype=float)
    ratio_mask = positive_power & (p_ac_available_w >= 0) & ~at_ac_power_limit
    ac_to_dc_ratio.loc[ratio_mask] = (
        p_ac_available_w.loc[ratio_mask] / p_dc_available_w.loc[ratio_mask]
    )

    operating_state = pd.Series("non_producing", index=v_dc_v.index, dtype=object)
    operating_state.loc[p_ac_available_w > 0] = "producing"
    operating_state.loc[at_ac_power_limit] = "ac_limited"
    operating_state.loc[p_dc_available_w < parameters.pso_w] = "night_tare"

    return pd.DataFrame(
        {
            "v_dc_v": v_dc_v.copy(),
            "i_dc_a": i_dc_a.copy(),
            "p_dc_available_w": p_dc_available_w.copy(),
            "p_ac_available_w": p_ac_available_w,
            "ac_to_dc_ratio": ac_to_dc_ratio,
            "operating_state": operating_state,
            "at_ac_power_limit": at_ac_power_limit,
            "model_used": "sandia",
            "parameter_source": model.parameter_source,
            "confidence": model.confidence,
        },
        index=v_dc_v.index,
        columns=_OUTPUT_COLUMNS,
    )


def _validate_finite_real(value: object, name: str) -> None:
    """Reject booleans, non-real values, and non-finite real values."""
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")


def _empty_sandia_inverter_result(index: pd.Index) -> pd.DataFrame:
    """Return the empty public schema with populated-result-compatible dtypes."""
    return pd.DataFrame(
        {
            "v_dc_v": pd.Series(index=index, dtype=float),
            "i_dc_a": pd.Series(index=index, dtype=float),
            "p_dc_available_w": pd.Series(index=index, dtype=float),
            "p_ac_available_w": pd.Series(index=index, dtype=float),
            "ac_to_dc_ratio": pd.Series(index=index, dtype=float),
            "operating_state": pd.Series(index=index, dtype=object),
            "at_ac_power_limit": pd.Series(index=index, dtype=bool),
            "model_used": pd.Series(index=index, dtype=str),
            "parameter_source": pd.Series(index=index, dtype=str),
            "confidence": pd.Series(index=index, dtype=str),
        },
        index=index,
        columns=_OUTPUT_COLUMNS,
    )


def _validate_electrical_series(series: pd.Series, name: str) -> None:
    """Validate finite non-negative numeric values without coercion."""
    for value in series.array:
        _validate_finite_real(value, f"{name} values")
        if value < 0:
            raise ValueError(f"{name} values must be greater than or equal to 0")
