"""Single equivalent-section Bishop88 I-V; no clamp, composition or optical binding."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from numbers import Real

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from pvlib import singlediode  # type: ignore[import-untyped]

from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    SectionReverseBreakdownAuthority,
    validate_section_reverse_breakdown_parameters,
)

SECTION_REVERSE_IV_CONTRACT_ID = "bypass_section_single_diode_reverse_iv_v1"
SECTION_REVERSE_IV_MODEL_ID = "pvlib_bishop88_explicit_reverse_breakdown_section_iv_v1"
SECTION_REVERSE_IV_SCOPE = "advanced_s8_bypass_section_iv_before_bypass_diode_clamp"
REVERSE_BREAKDOWN_GRID_GUARD_FRACTION = 0.99
DEFAULT_CURVE_POINTS = 401
# Numerical acceptance only, not physical tolerance/uncertainty evidence.
_OPEN_CIRCUIT_CURRENT_ATOL_A = 1e-8
_OPEN_CIRCUIT_CURRENT_RTOL = 1e-9


@dataclass(frozen=True)
class SectionSingleDiodeOperatingState:
    """Already-resolved section SDM; irradiance/temperature are context only."""

    state_reference: str
    effective_irradiance_wm2: float
    cell_temperature_c: float
    photocurrent_a: float
    saturation_current_a: float
    resistance_series_ohm: float
    resistance_shunt_ohm: float
    n_ns_vth_v: float

    def __post_init__(self) -> None:
        validate_section_single_diode_operating_state(self)


def validate_section_single_diode_operating_state(state: SectionSingleDiodeOperatingState) -> None:
    """Check original fields, including forged frozen instances, before pvlib."""
    if type(state) is not SectionSingleDiodeOperatingState:
        raise ValueError("expected exact section single-diode operating state")
    ref = state.state_reference
    if type(ref) is not str or not ref or ref != ref.strip():
        raise ValueError("state_reference must be exact non-empty unpadded text")
    for field in fields(state):
        if field.name == "state_reference":
            continue
        value = getattr(state, field.name)
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise ValueError(f"{field.name} must be a finite non-Boolean real")
        if field.name == "cell_temperature_c":
            continue
        if value < 0 or (
            field.name in {"saturation_current_a", "resistance_shunt_ohm", "n_ns_vth_v"}
            and value == 0
        ):
            raise ValueError(f"{field.name} is outside its section SDM domain")


@dataclass(frozen=True)
class SectionReverseIVResult:
    """Owned mutable curve with detached immutable input/provenance snapshots."""

    curve: pd.DataFrame
    operating_state: SectionSingleDiodeOperatingState
    authority: SectionReverseBreakdownAuthority
    contract: str = SECTION_REVERSE_IV_CONTRACT_ID
    model: str = SECTION_REVERSE_IV_MODEL_ID
    scope: str = SECTION_REVERSE_IV_SCOPE


def evaluate_section_reverse_iv(
    state: SectionSingleDiodeOperatingState,
    authority: SectionReverseBreakdownAuthority,
    curve_points: int = DEFAULT_CURVE_POINTS,
) -> SectionReverseIVResult:
    """Evaluate one explicit section-equivalent element with pvlib 0.15.2.

    Diode-voltage sampling includes an exact zero and ends at Bishop open circuit.
    reverse_bias means diode_voltage_v < 0, not bypass-diode conduction. Negative
    terminal voltage/power is preserved. No recombination term is modeled.
    """
    validate_section_single_diode_operating_state(state)
    validate_section_reverse_breakdown_parameters(authority)
    if type(curve_points) is not int or curve_points < 3:
        raise ValueError("curve_points must be an exact non-Boolean integer >= 3")
    args = {
        "photocurrent": state.photocurrent_a,
        "saturation_current": state.saturation_current_a,
        "resistance_series": state.resistance_series_ohm,
        "resistance_shunt": state.resistance_shunt_ohm,
        "nNsVth": state.n_ns_vth_v,
        "d2mutau": 0.0,
        "NsVbi": np.inf,
        "breakdown_factor": authority.breakdown_factor,
        "breakdown_voltage": authority.breakdown_voltage_v,
        "breakdown_exp": authority.breakdown_exponent,
    }
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            # Nonzero breakdown requires Newton in the pinned pvlib API.
            voc = float(
                singlediode.bishop88_v_from_i(
                    0.0,
                    **args,
                    method="newton",
                    method_kwargs={"tol": 1e-10, "maxiter": 100},
                )
            )
            minimum = REVERSE_BREAKDOWN_GRID_GUARD_FRACTION * authority.breakdown_voltage_v
            if not math.isfinite(voc) or voc < 0 or not authority.breakdown_voltage_v < minimum < 0:
                raise ValueError("unrepresentable reverse grid or open-circuit endpoint")
            reverse_points = (curve_points - 1) // 2
            diode_voltage = np.concatenate(
                (
                    np.linspace(minimum, 0.0, reverse_points + 1),
                    np.linspace(0.0, voc, curve_points - reverse_points)[1:],
                )
            )
            current, voltage, _ = singlediode.bishop88(diode_voltage, **args)
            current = np.asarray(current, dtype=float)
            voltage = np.asarray(voltage, dtype=float)
            power = voltage * current
            if any(
                v.shape != (curve_points,) or not np.isfinite(v).all()
                for v in (diode_voltage, current, voltage, power)
            ):
                raise ValueError("Bishop returned a nonfinite or malformed section curve")
            limit = _OPEN_CIRCUIT_CURRENT_ATOL_A + _OPEN_CIRCUIT_CURRENT_RTOL * state.photocurrent_a
            if abs(current[-1]) > limit:
                raise ValueError(
                    "Bishop open-circuit current did not converge within numerical tolerance"
                )
    except Exception as exc:
        raise ValueError(
            f"section Bishop88 evaluation failed for {authority.identity!r} "
            f"at state {state.state_reference!r}: {exc}"
        ) from exc
    curve = pd.DataFrame(
        {
            "curve_point": np.arange(curve_points),
            "diode_voltage_v": diode_voltage,
            "voltage_v": voltage,
            "current_a": current,
            "power_w": power,
            "reverse_bias": diode_voltage < 0,
        },
        copy=True,
    )
    return SectionReverseIVResult(
        curve,
        replace(state),
        replace(authority, identity=replace(authority.identity)),
    )
