"""Bishop transition gating keeps bypass and raw reverse bias distinct."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest
from pvlib import singlediode  # type: ignore[import-untyped]

from heliotelligence.physics import string_section_bypass_clamp as c
from heliotelligence.physics import string_section_reverse_iv as iv
from heliotelligence.physics.string_section_reverse_breakdown_authority import (
    BypassSectionIdentity,
    SectionReverseBreakdownAuthority,
)
from tests.unit.test_physics.test_string_section_bypass_diode_authority import diode


def state(photocurrent: float = 10.0) -> iv.SectionSingleDiodeOperatingState:
    return iv.SectionSingleDiodeOperatingState(
        "test-state", 1000.0, 25.0, photocurrent, 1e-9, 0.05, 200.0, 0.8
    )


def reverse() -> SectionReverseBreakdownAuthority:
    return SectionReverseBreakdownAuthority(
        BypassSectionIdentity("module", "section"),
        0.002,
        -15.0,
        3.0,
        "synthetic",
        "unknown",
        "test",
        "test only",
    )


def test_transition_pvlib_parity_and_branch_current_closure() -> None:
    s = state(2.0)
    r = reverse()
    d = diode(r.identity)
    expected = float(
        singlediode.bishop88_i_from_v(
            -d.forward_voltage_v,
            s.photocurrent_a,
            s.saturation_current_a,
            s.resistance_series_ohm,
            s.resistance_shunt_ohm,
            s.n_ns_vth_v,
            d2mutau=0.0,
            NsVbi=np.inf,
            breakdown_factor=r.breakdown_factor,
            breakdown_voltage=r.breakdown_voltage_v,
            breakdown_exp=r.breakdown_exponent,
            method="newton",
            method_kwargs={"tol": 1e-10, "maxiter": 100},
        )
    )
    result = c.evaluate_section_bypass_clamp(s, r, d, (0.0, 1.0, expected, 8.0))
    f = result.samples
    assert result.transition_current_a == expected
    assert f.bypass_active.tolist() == [False, False, False, True]
    assert f.terminal_voltage_v.iloc[2] == f.terminal_voltage_v.iloc[3] == -0.5
    assert (f.terminal_voltage_v >= -0.5).all()
    assert f.raw_voltage_evaluated.tolist() == [True, True, True, False]
    assert np.isnan(f.raw_pv_voltage_v.iloc[-1])
    assert f.raw_voltage_state.iloc[-1] == "not_evaluated_bypass_active"
    assert f.pv_branch_current_a.iloc[-1] == expected
    assert f.bypass_current_a.iloc[-1] == 8.0 - expected
    np.testing.assert_allclose(
        f.common_current_a, f.pv_branch_current_a + f.bypass_current_a, rtol=0, atol=2e-15
    )
    assert f.raw_pv_voltage_v.iloc[0] > -0.5
    assert f.terminal_voltage_v.iloc[0] == f.raw_pv_voltage_v.iloc[0]
    assert f.pv_branch_voltage_v.iloc[-1] == -0.5


def test_weak_and_strong_at_same_current_and_raw_stage2_unchanged() -> None:
    r = reverse()
    d = diode(r.identity)
    s = state(2.0)
    before = iv.evaluate_section_reverse_iv(s, r)
    snapshot = before.curve.copy(deep=True)
    weak = c.evaluate_section_bypass_clamp(s, r, d, (0.0, 4.0, 8.0))
    strong = c.evaluate_section_bypass_clamp(state(), r, d, (0.0, 4.0, 8.0))
    assert weak.samples.bypass_active.tolist() == [False, True, True]
    assert strong.samples.bypass_active.tolist() == [False, False, False]
    assert before.curve.voltage_v.min() < -10
    pd.testing.assert_frame_equal(before.curve, snapshot)
    assert s == state(2.0) and r == reverse()
    again = c.evaluate_section_bypass_clamp(s, r, d, (0.0, 4.0, 8.0))
    weak.samples.loc[0, "terminal_voltage_v"] = -999
    assert again.samples.terminal_voltage_v.iloc[0] != -999
    assert again.operating_state is not s and again.reverse_authority is not r
    assert again.diode_authority is not d


def test_forward_voltage_and_confidence() -> None:
    r = reverse()
    d = diode(r.identity)
    s = state(2.0)
    a = c.evaluate_section_bypass_clamp(s, r, d, (0.0, 3.0))
    b = c.evaluate_section_bypass_clamp(s, r, replace(d, forward_voltage_v=0.8), (0.0, 3.0))
    assert a.transition_current_a != b.transition_current_a
    assert a.samples.terminal_voltage_v.iloc[-1] == -0.5
    assert b.samples.terminal_voltage_v.iloc[-1] == -0.8
    other = c.evaluate_section_bypass_clamp(
        s, replace(r, confidence="high"), replace(d, confidence="low"), (0.0, 3.0)
    )
    pd.testing.assert_frame_equal(a.samples, other.samples, check_exact=True)


@pytest.mark.parametrize(
    "grid",
    [
        (),
        [0.0, 1.0],
        (True,),
        (float("nan"),),
        (float("inf"),),
        (-1.0,),
        (1.0, 0.0),
        (0.0, 0.0),
        ("1",),
    ],
)
def test_invalid_grid(grid: Any) -> None:
    with pytest.raises(ValueError):
        c.evaluate_section_bypass_clamp(state(), reverse(), diode(reverse().identity), grid)


def test_identity_and_frozen_tampering() -> None:
    r = reverse()
    d = diode(r.identity)
    with pytest.raises(ValueError):
        c.evaluate_section_bypass_clamp(
            state(), r, replace(d, identity=BypassSectionIdentity("other", "section")), (0.0,)
        )
    object.__setattr__(d, "forward_voltage_v", True)
    with pytest.raises(ValueError):
        c.evaluate_section_bypass_clamp(state(), r, d, (0.0,))


@pytest.mark.parametrize("failure", ["transition", "nonfinite", "branch"])
def test_contextual_numerical_failure(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if failure == "nonfinite":
        monkeypatch.setattr(singlediode, "bishop88_i_from_v", lambda *a, **k: np.nan)
    else:

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic solver failure")

        monkeypatch.setattr(
            singlediode,
            "bishop88_i_from_v" if failure == "transition" else "bishop88_v_from_i",
            broken,
        )
    with pytest.raises(ValueError, match="bypass clamp.*module.*test-state"):
        c.evaluate_section_bypass_clamp(state(), reverse(), diode(reverse().identity), (0.0, 3.0))


def test_bypassed_samples_never_solve_raw_at_excess_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = singlediode.bishop88_v_from_i
    requested: list[float] = []

    def record(current: float, *args: Any, **kwargs: Any) -> Any:
        requested.append(current)
        return original(current, *args, **kwargs)

    monkeypatch.setattr(singlediode, "bishop88_v_from_i", record)
    result = c.evaluate_section_bypass_clamp(
        state(2.0), reverse(), diode(reverse().identity), (0.0, 1000.0)
    )
    assert result.samples.bypass_active.iloc[-1]
    assert requested == [0.0]


def test_invalid_input_never_calls_bishop(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("must not reach Bishop")

    monkeypatch.setattr(singlediode, "bishop88_i_from_v", forbidden)
    s = state()
    object.__setattr__(s, "photocurrent_a", True)
    with pytest.raises(ValueError):
        c.evaluate_section_bypass_clamp(s, reverse(), diode(reverse().identity), (0.0,))
    assert not called


def test_zero_avalanche_and_dark_state_are_explicit() -> None:
    r = replace(reverse(), breakdown_factor=0.0)
    result = c.evaluate_section_bypass_clamp(state(0.0), r, diode(r.identity), (0.0, 1.0))
    assert result.samples.bypass_active.tolist() == [False, True]
    assert result.samples.terminal_voltage_v.iloc[-1] == -0.5


def test_clamp_contracts_are_explicit() -> None:
    result = c.evaluate_section_bypass_clamp(state(), reverse(), diode(reverse().identity), (0.0,))
    assert result.contract == c.BYPASS_CLAMP_CONTRACT_ID
    assert result.model == c.BYPASS_CLAMP_MODEL_ID
    assert result.scope == c.BYPASS_CLAMP_SCOPE
    assert result.coverage_scope == c.BYPASS_CLAMP_COVERAGE_SCOPE
