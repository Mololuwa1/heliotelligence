"""Pinned pvlib parity for a single explicit section; no clamp/composition."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pvlib  # type: ignore[import-untyped]
import pytest
from pvlib import singlediode

from heliotelligence.physics import string_section_reverse_breakdown_authority as a
from heliotelligence.physics import string_section_reverse_iv as iv


def state() -> iv.SectionSingleDiodeOperatingState:
    return iv.SectionSingleDiodeOperatingState(
        "synthetic-section-state",
        1000.0,
        25.0,
        10.0,
        1e-9,
        0.05,
        200.0,
        0.8,
    )


def authority() -> a.SectionReverseBreakdownAuthority:
    # Explicit test-only values follow pvlib's partial-module-shading example pattern.
    return a.SectionReverseBreakdownAuthority(
        a.BypassSectionIdentity("synthetic-module", "section"),
        0.002,
        -15.0,
        3.0,
        "synthetic-test",
        "unknown",
        "pvlib-example-pattern-test",
        "test fixture only",
    )


def bishop_args(
    s: iv.SectionSingleDiodeOperatingState, evidence: a.SectionReverseBreakdownAuthority
) -> dict[str, float]:
    return {
        "photocurrent": s.photocurrent_a,
        "saturation_current": s.saturation_current_a,
        "resistance_series": s.resistance_series_ohm,
        "resistance_shunt": s.resistance_shunt_ohm,
        "nNsVth": s.n_ns_vth_v,
        "d2mutau": 0.0,
        "NsVbi": np.inf,
        "breakdown_factor": evidence.breakdown_factor,
        "breakdown_voltage": evidence.breakdown_voltage_v,
        "breakdown_exp": evidence.breakdown_exponent,
    }


@pytest.mark.parametrize("points", [3, 4, 19, 400, 401])
@pytest.mark.parametrize("factor", [0, 0.002])
def test_pinned_bishop_parity_domain_endpoint_and_no_clamp(points: int, factor: float) -> None:
    assert pvlib.__version__ == "0.15.2"
    evidence = replace(authority(), breakdown_factor=factor)
    result = iv.evaluate_section_reverse_iv(state(), evidence, points)
    curve = result.curve
    assert tuple(curve.columns) == (
        "curve_point",
        "diode_voltage_v",
        "voltage_v",
        "current_a",
        "power_w",
        "reverse_bias",
    )
    assert len(curve) == points
    assert curve.curve_point.tolist() == list(range(points))
    assert curve.diode_voltage_v.iloc[0] == 0.99 * evidence.breakdown_voltage_v
    assert (curve.diode_voltage_v > evidence.breakdown_voltage_v).all()
    assert (curve.diode_voltage_v == 0).any()
    assert (curve.diode_voltage_v.diff().dropna() > 0).all()
    assert curve.voltage_v.iloc[0] < -10  # No diode-forward clamp has leaked in.
    assert (curve.voltage_v < 0).any() and (curve.power_w < 0).any()
    assert curve.voltage_v.iloc[-1] > 0
    assert abs(curve.current_a.iloc[-1]) < 1e-8  # Tighter than the kernel acceptance bound.
    np.testing.assert_array_equal(curve.reverse_bias, curve.diode_voltage_v < 0)
    np.testing.assert_array_equal(curve.power_w, curve.voltage_v * curve.current_a)
    current, voltage, power = singlediode.bishop88(
        curve.diode_voltage_v.to_numpy(), **bishop_args(state(), evidence)
    )
    np.testing.assert_array_equal(curve.current_a, current)
    np.testing.assert_array_equal(curve.voltage_v, voltage)
    np.testing.assert_array_equal(curve.power_w, power)
    endpoint = singlediode.bishop88_v_from_i(
        0.0,
        **bishop_args(state(), evidence),
        method="newton",
        method_kwargs={"tol": 1e-10, "maxiter": 100},
    )
    assert curve.diode_voltage_v.iloc[-1] == endpoint


def test_default_and_metadata() -> None:
    result = iv.evaluate_section_reverse_iv(state(), authority())
    assert len(result.curve) == iv.DEFAULT_CURVE_POINTS == 401
    assert iv.REVERSE_BREAKDOWN_GRID_GUARD_FRACTION == 0.99
    assert (
        result.contract
        == iv.SECTION_REVERSE_IV_CONTRACT_ID
        == "bypass_section_single_diode_reverse_iv_v1"
    )
    assert (
        result.model
        == iv.SECTION_REVERSE_IV_MODEL_ID
        == "pvlib_bishop88_explicit_reverse_breakdown_section_iv_v1"
    )
    assert (
        result.scope
        == iv.SECTION_REVERSE_IV_SCOPE
        == "advanced_s8_bypass_section_iv_before_bypass_diode_clamp"
    )
    assert result.operating_state == state()
    assert result.authority == authority()
    assert result.authority.identity == a.BypassSectionIdentity("synthetic-module", "section")
    assert result.operating_state.state_reference == "synthetic-section-state"
    with pytest.raises(FrozenInstanceError):
        result.scope = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field,value",
    [
        ("breakdown_factor", 0.01),
        ("breakdown_exponent", 2.5),
        ("breakdown_voltage_v", -10.0),
    ],
)
def test_reverse_parameters_change_response(field: str, value: Any) -> None:
    base = iv.evaluate_section_reverse_iv(state(), authority()).curve
    changed = iv.evaluate_section_reverse_iv(state(), replace(authority(), **{field: value})).curve
    assert not np.array_equal(base.current_a.iloc[:100], changed.current_a.iloc[:100])
    if field == "breakdown_voltage_v":
        assert changed.diode_voltage_v.iloc[0] == 0.99 * value
        assert changed.diode_voltage_v.iloc[0] != base.diode_voltage_v.iloc[0]


@pytest.mark.parametrize("confidence", ["high", "medium", "low", "unknown"])
def test_confidence_never_alters_numerics(confidence: str) -> None:
    baseline = iv.evaluate_section_reverse_iv(state(), authority()).curve
    result = iv.evaluate_section_reverse_iv(state(), replace(authority(), confidence=confidence))
    pd.testing.assert_frame_equal(baseline, result.curve, check_exact=True)


def test_no_recalculation_from_irradiance_or_temperature_context() -> None:
    baseline = iv.evaluate_section_reverse_iv(state(), authority()).curve
    changed_context = replace(state(), effective_irradiance_wm2=0, cell_temperature_c=-40)
    changed = iv.evaluate_section_reverse_iv(changed_context, authority()).curve
    pd.testing.assert_frame_equal(baseline, changed, check_exact=True)


def test_zero_photocurrent_and_ideal_series_resistance() -> None:
    result = iv.evaluate_section_reverse_iv(
        replace(state(), photocurrent_a=0, resistance_series_ohm=0), authority()
    )
    assert np.isfinite(result.curve.select_dtypes(include="number")).all().all()
    assert result.curve.diode_voltage_v.iloc[-1] == 0
    assert result.curve.current_a.iloc[-1] == 0


def test_inputs_unmutated_and_output_detached() -> None:
    s, evidence = state(), authority()
    result = iv.evaluate_section_reverse_iv(s, evidence)
    assert s == state() and evidence == authority()
    assert result.operating_state is not s and result.authority is not evidence
    assert result.authority.identity is not evidence.identity
    repeated = iv.evaluate_section_reverse_iv(s, evidence)
    original = repeated.curve.copy(deep=True)
    result.curve.loc[0, "current_a"] = -999
    pd.testing.assert_frame_equal(repeated.curve, original)
    object.__setattr__(s, "photocurrent_a", -1)
    object.__setattr__(evidence, "breakdown_voltage_v", 0)
    assert result.operating_state.photocurrent_a == 10
    assert result.authority.breakdown_voltage_v == -15


NUMERIC_FIELDS = tuple(
    f.name for f in fields(iv.SectionSingleDiodeOperatingState) if f.name != "state_reference"
)


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize(
    "value", [True, False, float("nan"), float("inf"), -float("inf"), "1", None]
)
def test_invalid_state_values(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(state(), **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("effective_irradiance_wm2", -1),
        ("photocurrent_a", -1),
        ("saturation_current_a", 0),
        ("saturation_current_a", -1),
        ("resistance_series_ohm", -1),
        ("resistance_shunt_ohm", 0),
        ("resistance_shunt_ohm", -1),
        ("n_ns_vth_v", 0),
        ("n_ns_vth_v", -1),
    ],
)
def test_state_domains(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(state(), **{field: value})


@pytest.mark.parametrize("value", ["", " padded", "padded ", None, 1])
def test_state_reference(value: Any) -> None:
    with pytest.raises(ValueError):
        replace(state(), state_reference=value)


@pytest.mark.parametrize("points", [True, False, 2, 0, -1, 3.0, "401", None])
def test_invalid_curve_points(points: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("pvlib reached for invalid input")

    monkeypatch.setattr(singlediode, "bishop88_v_from_i", forbidden)
    with pytest.raises(ValueError, match="curve_points"):
        iv.evaluate_section_reverse_iv(state(), authority(), points)


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_forged_state_rejected_before_pvlib(field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("pvlib must not be reached")

    monkeypatch.setattr(singlediode, "bishop88_v_from_i", forbidden)
    s = state()
    object.__setattr__(s, field, True)
    with pytest.raises(ValueError, match=field):
        iv.evaluate_section_reverse_iv(s, authority())


@pytest.mark.parametrize(
    "field,value",
    [
        ("breakdown_factor", True),
        ("breakdown_voltage_v", 0),
        ("breakdown_exponent", float("nan")),
        ("contract", "wrong"),
        ("confidence", "certain"),
    ],
)
def test_invalid_authority_fails_before_pvlib(
    field: str, value: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("pvlib must not be reached")

    monkeypatch.setattr(singlediode, "bishop88_v_from_i", forbidden)
    evidence = authority()
    object.__setattr__(evidence, field, value)
    with pytest.raises(ValueError):
        iv.evaluate_section_reverse_iv(state(), evidence)
    assert not called


@pytest.mark.parametrize(
    "failure", ["solver", "nonfinite_endpoint", "nonfinite_curve", "endpoint_current"]
)
def test_solver_failures_contextual_no_fallback(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if failure == "solver":

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic Newton failure")

        monkeypatch.setattr(singlediode, "bishop88_v_from_i", broken)
    elif failure == "nonfinite_endpoint":
        monkeypatch.setattr(singlediode, "bishop88_v_from_i", lambda *a, **k: np.nan)
    else:
        monkeypatch.setattr(singlediode, "bishop88_v_from_i", lambda *a, **k: 10.0)

        def invalid_curve(vd: Any, **kwargs: Any) -> Any:
            return (np.full_like(vd, np.nan if failure == "nonfinite_curve" else 1.0), vd, vd)

        monkeypatch.setattr(singlediode, "bishop88", invalid_curve)
    with pytest.raises(
        ValueError,
        match="section Bishop88 evaluation failed.*synthetic-module.*synthetic-section-state",
    ):
        iv.evaluate_section_reverse_iv(state(), authority())


def test_newton_and_explicit_recombination_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    original = singlediode.bishop88_v_from_i
    calls: list[dict[str, Any]] = []

    def record(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(singlediode, "bishop88_v_from_i", record)
    iv.evaluate_section_reverse_iv(state(), authority())
    assert calls[0]["method"] == "newton"
    assert calls[0]["d2mutau"] == 0 and calls[0]["NsVbi"] == np.inf
    assert calls[0]["breakdown_factor"] == 0.002
    assert calls[0]["breakdown_voltage"] == -15
    assert calls[0]["breakdown_exp"] == 3


def test_no_composition_or_module_parameter_inference_imports() -> None:
    tree = ast.parse(Path(iv.__file__).read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert set(imports) <= {
        "__future__",
        "dataclasses",
        "numbers",
        "pvlib",
        "heliotelligence.physics.string_section_reverse_breakdown_authority",
    }
    assert {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)} <= {
        "math",
        "numpy",
        "pandas",
    }
    excluded = {
        "bypass_forward_voltage_v",
        "module_id",
        "string_id",
        "module_parameters",
        "series_cells_per_branch",
        "parallel_cell_branches",
        "d2mutau",
        "NsVbi",
    }
    assert excluded.isdisjoint(f.name for f in fields(iv.SectionSingleDiodeOperatingState))
    assert set(f.name for f in fields(iv.SectionReverseIVResult)) == {
        "curve",
        "operating_state",
        "authority",
        "contract",
        "model",
        "scope",
    }
