"""Tests for inverter DC operating-envelope physics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from heliotelligence.physics.inverter_envelope import (
    InverterDcOperatingEnvelope,
    ResolvedInverterDcOperatingEnvelope,
    evaluate_inverter_dc_operating_envelope,
    inverter_dc_operating_envelope_from_mapping,
)


def _envelope(**overrides: object) -> InverterDcOperatingEnvelope:
    values: dict[str, object] = {
        "mppt_voltage_min_v": 200.0,
        "mppt_voltage_max_v": 500.0,
        "absolute_dc_voltage_max_v": 600.0,
        "dc_current_max_a": 32.0,
    }
    values.update(overrides)
    return InverterDcOperatingEnvelope(**values)  # type: ignore[arg-type]


def _resolved(
    envelope: InverterDcOperatingEnvelope | None = None,
) -> ResolvedInverterDcOperatingEnvelope:
    return ResolvedInverterDcOperatingEnvelope(
        envelope=envelope or _envelope(),
        parameter_source="synthetic:test",
        confidence="high",
    )


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range("2025-06-21 10:00", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=index, dtype=float)


def _evaluate(
    *,
    v_dc: list[float],
    i_dc: list[float],
    p_dc: list[float],
    envelope: ResolvedInverterDcOperatingEnvelope | None = None,
) -> pd.DataFrame:
    return evaluate_inverter_dc_operating_envelope(
        _series(v_dc),
        _series(i_dc),
        _series(p_dc),
        envelope or _resolved(),
    )


def test_envelope_is_frozen() -> None:
    envelope = _envelope()
    with pytest.raises(FrozenInstanceError):
        envelope.dc_current_max_a = 64.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mppt_voltage_min_v", True),
        ("mppt_voltage_max_v", "500"),
        ("absolute_dc_voltage_max_v", np.nan),
        ("dc_current_max_a", np.inf),
        ("dc_current_max_a", -np.inf),
    ],
)
def test_envelope_fields_require_finite_real_non_bool_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match=field):
        _envelope(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "mppt_voltage_min_v",
        "mppt_voltage_max_v",
        "absolute_dc_voltage_max_v",
        "dc_current_max_a",
    ],
)
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_envelope_fields_are_strictly_positive(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        _envelope(**{field: value})


@pytest.mark.parametrize("mppt_min", [500.0, 550.0])
def test_mppt_minimum_must_be_below_mppt_maximum(mppt_min: float) -> None:
    with pytest.raises(
        ValueError,
        match="mppt_voltage_min_v must be less than mppt_voltage_max_v",
    ):
        _envelope(mppt_voltage_min_v=mppt_min)


def test_mppt_maximum_may_equal_absolute_voltage_maximum() -> None:
    envelope = _envelope(
        mppt_voltage_max_v=600.0,
        absolute_dc_voltage_max_v=600.0,
    )
    assert envelope.mppt_voltage_max_v == envelope.absolute_dc_voltage_max_v


def test_mppt_maximum_cannot_exceed_absolute_voltage_maximum() -> None:
    with pytest.raises(ValueError, match="absolute_dc_voltage_max_v"):
        _envelope(mppt_voltage_max_v=601.0)


def test_mapping_adapter_uses_exact_cec_envelope_keys_and_ignores_extras() -> None:
    values = {
        "Mppt_low": 200.0,
        "Mppt_high": 500.0,
        "Vdcmax": 600.0,
        "Idcmax": 32.0,
        "Paco": 6000.0,
    }
    assert inverter_dc_operating_envelope_from_mapping(values) == _envelope()


def test_mapping_adapter_reports_all_missing_keys_sorted() -> None:
    with pytest.raises(ValueError) as error:
        inverter_dc_operating_envelope_from_mapping({"Mppt_low": 200.0})
    assert str(error.value) == (
        "missing inverter envelope keys: Idcmax, Mppt_high, Vdcmax"
    )


def test_mapping_adapter_rejects_non_mapping_input() -> None:
    with pytest.raises(ValueError, match="values must be a mapping"):
        inverter_dc_operating_envelope_from_mapping([])  # type: ignore[arg-type]


def test_resolved_envelope_is_frozen_and_retains_provenance() -> None:
    resolved = _resolved()
    assert resolved.parameter_source == "synthetic:test"
    assert resolved.confidence == "high"
    with pytest.raises(FrozenInstanceError):
        resolved.confidence = "low"  # type: ignore[misc]


@pytest.mark.parametrize("envelope", [None, {}, "envelope"])
def test_resolved_envelope_rejects_invalid_envelope_type(envelope: object) -> None:
    with pytest.raises(ValueError, match="envelope must be"):
        ResolvedInverterDcOperatingEnvelope(  # type: ignore[arg-type]
            envelope=envelope,
            parameter_source="source",
            confidence="high",
        )


@pytest.mark.parametrize("source", [None, "", "   ", 1])
def test_resolved_envelope_rejects_invalid_source(source: object) -> None:
    with pytest.raises(ValueError, match="parameter_source"):
        ResolvedInverterDcOperatingEnvelope(  # type: ignore[arg-type]
            envelope=_envelope(),
            parameter_source=source,
            confidence="high",
        )


@pytest.mark.parametrize("confidence", ["HIGH", "", "certain", None, []])
def test_resolved_envelope_rejects_invalid_confidence(confidence: object) -> None:
    with pytest.raises(ValueError, match="confidence"):
        ResolvedInverterDcOperatingEnvelope(  # type: ignore[arg-type]
            envelope=_envelope(),
            parameter_source="source",
            confidence=confidence,
        )


@pytest.mark.parametrize("input_name", ["v_dc_v", "i_dc_a", "p_dc_available_w"])
@pytest.mark.parametrize("value", [[400.0], (400.0,), np.array([400.0]), 400.0])
def test_evaluation_requires_series_inputs(input_name: str, value: object) -> None:
    inputs: dict[str, object] = {
        "v_dc_v": _series([400.0]),
        "i_dc_a": _series([1.0]),
        "p_dc_available_w": _series([400.0]),
    }
    inputs[input_name] = value
    with pytest.raises(ValueError, match=f"{input_name} must be a pandas Series"):
        evaluate_inverter_dc_operating_envelope(
            **inputs,  # type: ignore[arg-type]
            resolved_envelope=_resolved(),
        )


def test_evaluation_requires_resolved_envelope_type() -> None:
    with pytest.raises(ValueError, match="resolved_envelope"):
        evaluate_inverter_dc_operating_envelope(
            _series([400.0]),
            _series([1.0]),
            _series([400.0]),
            _envelope(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("mismatched", ["v_i", "v_p", "i_p"])
def test_index_mismatch_is_rejected_without_alignment(mismatched: str) -> None:
    v_dc = _series([400.0, 400.0])
    i_dc = _series([1.0, 1.0])
    p_dc = _series([400.0, 400.0])
    shifted = pd.Series([1.0, 1.0], index=i_dc.index.shift(1, freq="min"))
    if mismatched == "v_i":
        i_dc = shifted
    elif mismatched == "v_p":
        p_dc = shifted
    else:
        v_dc = shifted
    with pytest.raises(ValueError, match="indexes must match exactly"):
        evaluate_inverter_dc_operating_envelope(v_dc, i_dc, p_dc, _resolved())


@pytest.mark.parametrize(
    ("input_name", "value"),
    [
        ("v_dc_v", -1.0),
        ("i_dc_a", -1.0),
        ("p_dc_available_w", -1.0),
        ("v_dc_v", np.nan),
        ("i_dc_a", np.inf),
        ("p_dc_available_w", -np.inf),
        ("v_dc_v", True),
    ],
)
def test_invalid_electrical_values_are_rejected(
    input_name: str,
    value: object,
) -> None:
    inputs: dict[str, pd.Series] = {
        "v_dc_v": _series([400.0]),
        "i_dc_a": _series([1.0]),
        "p_dc_available_w": _series([400.0]),
    }
    inputs[input_name] = pd.Series([value], index=inputs[input_name].index)
    with pytest.raises(ValueError, match=input_name):
        evaluate_inverter_dc_operating_envelope(
            **inputs,
            resolved_envelope=_resolved(),
        )


@pytest.mark.parametrize(("v_dc", "i_dc"), [(0.0, 1.0), (400.0, 0.0)])
def test_positive_power_requires_positive_voltage_and_current(
    v_dc: float,
    i_dc: float,
) -> None:
    with pytest.raises(ValueError, match="positive p_dc_available_w"):
        _evaluate(v_dc=[v_dc], i_dc=[i_dc], p_dc=[100.0])


def test_mppt_boundaries_are_inclusive() -> None:
    result = _evaluate(
        v_dc=[200.0, 500.0],
        i_dc=[1.0, 32.0],
        p_dc=[200.0, 500.0],
    )
    assert result["dc_limits_satisfied"].tolist() == [True, True]
    assert result["dc_operating_state"].tolist() == [
        "within_envelope",
        "within_envelope",
    ]


def test_absolute_voltage_limit_is_inclusive_when_input_is_inactive() -> None:
    result = _evaluate(v_dc=[600.0], i_dc=[0.0], p_dc=[0.0])
    assert bool(result.iloc[0]["dc_limits_satisfied"])
    assert result.iloc[0]["dc_operating_state"] == "inactive"


def test_current_limit_is_inclusive() -> None:
    result = _evaluate(v_dc=[400.0], i_dc=[32.0], p_dc=[500.0])
    assert bool(result.iloc[0]["dc_limits_satisfied"])
    assert result.iloc[0]["dc_operating_state"] == "within_envelope"


def test_active_input_below_mppt_window_is_classified() -> None:
    result = _evaluate(v_dc=[199.9], i_dc=[2.0], p_dc=[300.0])
    assert bool(result.iloc[0]["below_mppt_voltage_limit"])
    assert not bool(result.iloc[0]["dc_limits_satisfied"])
    assert result.iloc[0]["dc_operating_state"] == "below_mppt_voltage"


def test_active_input_above_mppt_window_is_not_called_absolute_overvoltage() -> None:
    result = _evaluate(v_dc=[550.0], i_dc=[2.0], p_dc=[500.0])
    assert bool(result.iloc[0]["above_mppt_voltage_limit"])
    assert not bool(result.iloc[0]["above_absolute_dc_voltage_limit"])
    assert result.iloc[0]["dc_operating_state"] == "above_mppt_voltage"


def test_absolute_overvoltage_is_detected_at_zero_power() -> None:
    result = _evaluate(v_dc=[600.1], i_dc=[0.0], p_dc=[0.0])
    assert not bool(result.iloc[0]["is_active_dc_input"])
    assert not bool(result.iloc[0]["above_mppt_voltage_limit"])
    assert bool(result.iloc[0]["above_absolute_dc_voltage_limit"])
    assert not bool(result.iloc[0]["dc_limits_satisfied"])
    assert result.iloc[0]["dc_operating_state"] == "absolute_dc_overvoltage"


def test_current_limit_is_detected_even_when_reported_power_is_zero() -> None:
    result = _evaluate(v_dc=[400.0], i_dc=[32.1], p_dc=[0.0])
    assert not bool(result.iloc[0]["is_active_dc_input"])
    assert bool(result.iloc[0]["above_dc_current_limit"])
    assert result.iloc[0]["dc_operating_state"] == "dc_current_limit_exceeded"


def test_inactive_input_outside_mppt_window_is_not_an_mppt_violation() -> None:
    result = _evaluate(
        v_dc=[100.0, 550.0],
        i_dc=[0.0, 0.0],
        p_dc=[0.0, 0.0],
    )
    assert result["below_mppt_voltage_limit"].tolist() == [False, False]
    assert result["above_mppt_voltage_limit"].tolist() == [False, False]
    assert result["dc_limits_satisfied"].tolist() == [True, True]
    assert result["dc_operating_state"].tolist() == ["inactive", "inactive"]


def test_violation_flags_preserve_multiple_simultaneous_constraints() -> None:
    result = _evaluate(v_dc=[650.0], i_dc=[40.0], p_dc=[1000.0])
    assert bool(result.iloc[0]["above_mppt_voltage_limit"])
    assert bool(result.iloc[0]["above_absolute_dc_voltage_limit"])
    assert bool(result.iloc[0]["above_dc_current_limit"])
    assert result.iloc[0]["dc_operating_state"] == "absolute_dc_overvoltage"


def test_absolute_voltage_has_state_precedence_over_current_limit() -> None:
    result = _evaluate(v_dc=[650.0], i_dc=[40.0], p_dc=[0.0])
    assert result.iloc[0]["dc_operating_state"] == "absolute_dc_overvoltage"


def test_current_limit_has_state_precedence_over_mppt_window_violation() -> None:
    result = _evaluate(v_dc=[550.0], i_dc=[40.0], p_dc=[1000.0])
    assert result.iloc[0]["dc_operating_state"] == "dc_current_limit_exceeded"


def test_vi_product_is_not_enforced_or_recalculated() -> None:
    v_dc = _series([400.0])
    i_dc = _series([1.01])
    p_dc = _series([405.0])
    result = evaluate_inverter_dc_operating_envelope(v_dc, i_dc, p_dc, _resolved())
    pd.testing.assert_series_equal(result["v_dc_v"], v_dc.rename("v_dc_v"))
    pd.testing.assert_series_equal(result["i_dc_a"], i_dc.rename("i_dc_a"))
    pd.testing.assert_series_equal(
        result["p_dc_available_w"],
        p_dc.rename("p_dc_available_w"),
    )


def test_input_series_are_not_mutated() -> None:
    v_dc = _series([400.0, 550.0])
    i_dc = _series([1.0, 40.0])
    p_dc = _series([400.0, 500.0])
    v_before = v_dc.copy(deep=True)
    i_before = i_dc.copy(deep=True)
    p_before = p_dc.copy(deep=True)
    evaluate_inverter_dc_operating_envelope(v_dc, i_dc, p_dc, _resolved())
    pd.testing.assert_series_equal(v_dc, v_before)
    pd.testing.assert_series_equal(i_dc, i_before)
    pd.testing.assert_series_equal(p_dc, p_before)


def test_timezone_aware_index_and_provenance_are_preserved() -> None:
    result = _evaluate(v_dc=[400.0], i_dc=[1.0], p_dc=[400.0])
    assert str(result.index.tz) == "UTC"
    assert result.iloc[0]["envelope_parameter_source"] == "synthetic:test"
    assert result.iloc[0]["envelope_confidence"] == "high"


def test_output_contract_does_not_invent_constrained_power_or_current() -> None:
    supplied_v_dc = 550.0
    supplied_i_dc = 40.0
    supplied_p_dc = 1000.0
    result = _evaluate(
        v_dc=[supplied_v_dc],
        i_dc=[supplied_i_dc],
        p_dc=[supplied_p_dc],
    )
    assert list(result.columns) == [
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
    assert not any("clipped" in column or "constrained" in column for column in result)
    row = result.iloc[0]
    assert bool(row["above_mppt_voltage_limit"])
    assert bool(row["above_dc_current_limit"])
    assert not bool(row["dc_limits_satisfied"])
    assert row["v_dc_v"] == supplied_v_dc
    assert row["i_dc_a"] == supplied_i_dc
    assert row["p_dc_available_w"] == supplied_p_dc
    assert row["p_dc_available_w"] != row["v_dc_v"] * _envelope().dc_current_max_a


def test_empty_inputs_return_stable_typed_schema() -> None:
    index = pd.DatetimeIndex([], tz="UTC")
    empty = pd.Series([], index=index, dtype=float)
    result = evaluate_inverter_dc_operating_envelope(
        empty,
        empty,
        empty,
        _resolved(),
    )
    assert list(result.columns) == [
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
    assert result.empty
    assert result["v_dc_v"].dtype == float
    assert result["i_dc_a"].dtype == float
    assert result["p_dc_available_w"].dtype == float
    for column in [
        "is_active_dc_input",
        "below_mppt_voltage_limit",
        "above_mppt_voltage_limit",
        "above_absolute_dc_voltage_limit",
        "above_dc_current_limit",
        "dc_limits_satisfied",
    ]:
        assert result[column].dtype == bool
    assert result["dc_operating_state"].dtype == object


def test_empty_and_populated_results_can_be_concatenated_without_bool_dtype_drift() -> None:
    index = pd.DatetimeIndex([], tz="UTC")
    empty = pd.Series([], index=index, dtype=float)
    empty_result = evaluate_inverter_dc_operating_envelope(
        empty,
        empty,
        empty,
        _resolved(),
    )
    populated = _evaluate(v_dc=[400.0], i_dc=[1.0], p_dc=[400.0])
    combined = pd.concat([empty_result, populated])
    for column in [
        "is_active_dc_input",
        "below_mppt_voltage_limit",
        "above_mppt_voltage_limit",
        "above_absolute_dc_voltage_limit",
        "above_dc_current_limit",
        "dc_limits_satisfied",
    ]:
        assert combined[column].dtype == bool
