"""One section at caller currents: Bishop PV branch plus explicit ideal diode."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from numbers import Real

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from pvlib import singlediode  # type: ignore[import-untyped]

from heliotelligence.physics.string_section_bypass_diode_authority import (
    SectionBypassDiodeAuthority,
    validate_section_bypass_diode_parameters,
)
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    SectionReverseBreakdownAuthority,
    validate_section_reverse_breakdown_parameters,
)
from heliotelligence.physics.string_section_reverse_iv import (
    SectionSingleDiodeOperatingState,
    validate_section_single_diode_operating_state,
)

BYPASS_CLAMP_CONTRACT_ID = "explicit_bypass_section_common_current_clamp_v1"
BYPASS_CLAMP_MODEL_ID = "bishop88_transition_and_constant_forward_voltage_ideal_bypass_clamp_v1"
BYPASS_CLAMP_SCOPE = "advanced_s8_section_terminal_response_before_series_composition"
BYPASS_CLAMP_COVERAGE_SCOPE = "explicit_section_sdm_reverse_breakdown_and_bypass_diode_authority"


def validate_common_current_grid(currents: tuple[float, ...]) -> None:
    """An explicit non-empty strictly increasing nonnegative grid, never sorted."""
    if type(currents) is not tuple or not currents:
        raise ValueError("common currents require an exact non-empty ordered tuple")
    previous = -1.0
    for current in currents:
        if (
            isinstance(current, bool)
            or not isinstance(current, Real)
            or not math.isfinite(current)
            or current < 0
            or current <= previous
        ):
            raise ValueError(
                "common currents must be finite non-Boolean, nonnegative, strictly increasing"
            )
        previous = current


@dataclass(frozen=True)
class SectionBypassClampResult:
    samples: pd.DataFrame
    transition_current_a: float
    operating_state: SectionSingleDiodeOperatingState
    reverse_authority: SectionReverseBreakdownAuthority
    diode_authority: SectionBypassDiodeAuthority
    contract: str = BYPASS_CLAMP_CONTRACT_ID
    model: str = BYPASS_CLAMP_MODEL_ID
    scope: str = BYPASS_CLAMP_SCOPE
    coverage_scope: str = BYPASS_CLAMP_COVERAGE_SCOPE


def evaluate_section_bypass_clamp(
    state: SectionSingleDiodeOperatingState,
    reverse_authority: SectionReverseBreakdownAuthority,
    diode_authority: SectionBypassDiodeAuthority,
    common_currents_a: tuple[float, ...],
) -> SectionBypassClampResult:
    """Evaluate only the needed PV branch; excess imposed current uses the diode.

    Raw *unconstrained* PV voltage is NaN/not evaluated at bypass-active samples.
    The actual PV branch then operates at -Vf and transition current. This avoids
    unnecessary inverse solves beyond the physical operating domain. No fallback.
    """
    validate_section_single_diode_operating_state(state)
    validate_section_reverse_breakdown_parameters(reverse_authority)
    validate_section_bypass_diode_parameters(diode_authority)
    validate_common_current_grid(common_currents_a)
    if reverse_authority.identity != diode_authority.identity:
        raise ValueError("reverse and diode section identities differ")
    vf = diode_authority.forward_voltage_v
    args = dict(
        photocurrent=state.photocurrent_a,
        saturation_current=state.saturation_current_a,
        resistance_series=state.resistance_series_ohm,
        resistance_shunt=state.resistance_shunt_ohm,
        nNsVth=state.n_ns_vth_v,
        d2mutau=0.0,
        NsVbi=np.inf,
        breakdown_factor=reverse_authority.breakdown_factor,
        breakdown_voltage=reverse_authority.breakdown_voltage_v,
        breakdown_exp=reverse_authority.breakdown_exponent,
    )
    method = dict(tol=1e-10, maxiter=100)
    records = []
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            transition = float(
                singlediode.bishop88_i_from_v(-vf, **args, method="newton", method_kwargs=method)
            )
            if not math.isfinite(transition) or transition < 0:
                raise ValueError("invalid clamp-transition current")
            # Vdiode = Vterminal + Ipv*Rs. Verify the public inverse solution using
            # public Bishop, not a copied diode/breakdown equation.
            vd = -vf + transition * state.resistance_series_ohm
            if not math.isfinite(vd) or vd <= reverse_authority.breakdown_voltage_v:
                raise ValueError("clamp transition is outside the Bishop domain")
            check_i, check_v, _ = singlediode.bishop88(vd, **args)
            current_tolerance = 1e-8 + 1e-9 * max(1.0, transition)
            voltage_tolerance = 1e-8 + 1e-9 * vf
            if (
                not np.isfinite([check_i, check_v]).all()
                or abs(check_i - transition) > current_tolerance
                or abs(check_v + vf) > voltage_tolerance
            ):
                raise ValueError("Bishop transition failed round-trip validation")
            for point, current in enumerate(common_currents_a):
                active = current > transition
                if active:
                    raw = np.nan
                    terminal = -vf
                    pv_current = transition
                elif current == transition:
                    raw = float(check_v)
                    terminal = -vf
                    pv_current = current
                else:
                    raw = float(
                        singlediode.bishop88_v_from_i(
                            current, **args, method="newton", method_kwargs=method
                        )
                    )
                    vd = raw + current * state.resistance_series_ohm
                    if not math.isfinite(raw) or vd <= reverse_authority.breakdown_voltage_v:
                        raise ValueError("invalid unclamped Bishop solution")
                    verify_i, _, _ = singlediode.bishop88(vd, **args)
                    if (
                        not math.isfinite(verify_i)
                        or abs(verify_i - current) > current_tolerance
                        or raw < -vf - voltage_tolerance
                    ):
                        raise ValueError(
                            "unclamped Bishop solution failed current/domain validation"
                        )
                    # Only remove inverse-solver boundary roundoff on this
                    # non-bypassed branch; engagement is determined by current.
                    terminal = max(raw, -vf)
                    pv_current = current
                bypass_current = current - pv_current
                if not math.isfinite(bypass_current):
                    raise ValueError("nonfinite bypass current")
                records.append(
                    dict(
                        curve_point=point,
                        common_current_a=current,
                        raw_pv_voltage_v=raw,
                        raw_voltage_evaluated=not active,
                        raw_voltage_state="not_evaluated_bypass_active" if active else "evaluated",
                        pv_branch_current_a=pv_current,
                        bypass_current_a=bypass_current,
                        pv_branch_voltage_v=terminal,
                        terminal_voltage_v=terminal,
                        bypass_active=active,
                        clamp_transition_current_a=transition,
                        forward_voltage_v=vf,
                    )
                )
    except Exception as exc:
        raise ValueError(
            f"section bypass clamp failed for {reverse_authority.identity!r} "
            f"at state {state.state_reference!r}: {exc}"
        ) from exc
    return SectionBypassClampResult(
        pd.DataFrame.from_records(records),
        transition,
        replace(state),
        replace(reverse_authority, identity=replace(reverse_authority.identity)),
        replace(diode_authority, identity=replace(diode_authority.identity)),
    )
