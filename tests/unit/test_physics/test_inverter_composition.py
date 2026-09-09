"""Tests for single-input inverter envelope and Sandia composition."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heliotelligence.physics.inverter import (
    ResolvedSandiaInverterModel,
    SandiaInverterParameters,
    calculate_sandia_inverter_ac_power,
)
from heliotelligence.physics.inverter_composition import (
    evaluate_sandia_inverter_input,
)
from heliotelligence.physics.inverter_envelope import (
    InverterDcOperatingEnvelope,
    ResolvedInverterDcOperatingEnvelope,
    evaluate_inverter_dc_operating_envelope,
)

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
    "conversion_evaluated",
    "p_ac_available_w",
    "ac_to_dc_ratio",
    "at_ac_power_limit",
    "inverter_operating_state",
    "model_used",
    "sandia_parameter_source",
    "sandia_confidence",
    "envelope_parameter_source",
    "envelope_confidence",
]
_ENVELOPE_COLUMNS = [
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


def _model() -> ResolvedSandiaInverterModel:
    return ResolvedSandiaInverterModel(
        parameters=SandiaInverterParameters(
            paco_w=1000.0,
            pdco_w=1050.0,
            vdco_v=400.0,
            pso_w=10.0,
            c0_per_w=0.0,
            c1_per_v=0.0,
            c2_per_v=0.0,
            c3_per_v=0.0,
            pnt_w=1.0,
        ),
        parameter_source="sandia-source",
        confidence="high",
    )


def _envelope() -> ResolvedInverterDcOperatingEnvelope:
    return ResolvedInverterDcOperatingEnvelope(
        envelope=InverterDcOperatingEnvelope(
            mppt_voltage_min_v=200.0,
            mppt_voltage_max_v=500.0,
            absolute_dc_voltage_max_v=600.0,
            dc_current_max_a=32.0,
        ),
        parameter_source="envelope-source",
        confidence="medium",
    )


def _series(values: list[object]) -> pd.Series:
    index = pd.date_range("2025-06-21 10:00", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=index)


def _evaluate(
    v_dc: list[object],
    i_dc: list[object],
    p_dc: list[object],
) -> pd.DataFrame:
    return evaluate_sandia_inverter_input(
        _series(v_dc),
        _series(i_dc),
        _series(p_dc),
        _model(),
        _envelope(),
    )


def test_valid_active_point_equals_direct_sandia_result() -> None:
    v_dc = _series([400.0])
    i_dc = _series([1.0])
    p_dc = _series([500.0])
    result = evaluate_sandia_inverter_input(v_dc, i_dc, p_dc, _model(), _envelope())
    direct = calculate_sandia_inverter_ac_power(v_dc, i_dc, p_dc, _model())
    assert bool(result.iloc[0]["conversion_evaluated"])
    assert result.iloc[0]["p_ac_available_w"] == direct.iloc[0]["p_ac_available_w"]
    assert result.iloc[0]["inverter_operating_state"] == direct.iloc[0][
        "operating_state"
    ]


def test_safe_inactive_point_preserves_signed_night_tare() -> None:
    result = _evaluate([100.0], [0.0], [0.0])
    row = result.iloc[0]
    assert row["dc_operating_state"] == "inactive"
    assert bool(row["dc_limits_satisfied"])
    assert bool(row["conversion_evaluated"])
    assert row["p_ac_available_w"] == pytest.approx(-1.0)
    assert row["inverter_operating_state"] == "night_tare"


def test_valid_ac_limited_point_preserves_i1_limit_state() -> None:
    result = _evaluate([400.0], [3.0], [1050.0])
    row = result.iloc[0]
    assert bool(row["conversion_evaluated"])
    assert row["p_ac_available_w"] == pytest.approx(1000.0)
    assert bool(row["at_ac_power_limit"])
    assert row["inverter_operating_state"] == "ac_limited"


@pytest.mark.parametrize(
    ("v_dc", "i_dc", "p_dc", "state", "flag"),
    [
        (199.0, 2.0, 300.0, "below_mppt_voltage", "below_mppt_voltage_limit"),
        (550.0, 2.0, 500.0, "above_mppt_voltage", "above_mppt_voltage_limit"),
        (
            601.0,
            0.0,
            0.0,
            "absolute_dc_overvoltage",
            "above_absolute_dc_voltage_limit",
        ),
        (400.0, 33.0, 0.0, "dc_current_limit_exceeded", "above_dc_current_limit"),
    ],
)
def test_envelope_violations_leave_ac_unresolved(
    v_dc: float,
    i_dc: float,
    p_dc: float,
    state: str,
    flag: str,
) -> None:
    result = _evaluate([v_dc], [i_dc], [p_dc])
    row = result.iloc[0]
    assert bool(row[flag])
    assert not bool(row["dc_limits_satisfied"])
    assert not bool(row["conversion_evaluated"])
    assert np.isnan(row["p_ac_available_w"])
    assert np.isnan(row["ac_to_dc_ratio"])
    assert not bool(row["at_ac_power_limit"])
    assert row["inverter_operating_state"] == state


def test_simultaneous_violations_retain_flags_and_i2_precedence() -> None:
    result = _evaluate([650.0], [40.0], [1000.0])
    row = result.iloc[0]
    assert bool(row["above_mppt_voltage_limit"])
    assert bool(row["above_absolute_dc_voltage_limit"])
    assert bool(row["above_dc_current_limit"])
    assert row["dc_operating_state"] == "absolute_dc_overvoltage"
    assert row["inverter_operating_state"] == "absolute_dc_overvoltage"
    assert not bool(row["conversion_evaluated"])
    assert np.isnan(row["p_ac_available_w"])


def test_violation_classification_does_not_fabricate_constrained_point() -> None:
    supplied_v_dc = 550.0
    supplied_i_dc = 40.0
    supplied_p_dc = 1000.0
    result = _evaluate([supplied_v_dc], [supplied_i_dc], [supplied_p_dc])
    row = result.iloc[0]
    assert row["v_dc_v"] == supplied_v_dc
    assert row["i_dc_a"] == supplied_i_dc
    assert row["p_dc_available_w"] == supplied_p_dc
    assert row["v_dc_v"] != _envelope().envelope.mppt_voltage_max_v
    assert row["i_dc_a"] != _envelope().envelope.dc_current_max_a
    assert row["p_dc_available_w"] != (
        row["v_dc_v"] * _envelope().envelope.dc_current_max_a
    )


def test_mixed_series_evaluates_only_admissible_rows_without_reordering() -> None:
    v_dc = _series([400.0, 199.0, 100.0, 650.0, 400.0])
    i_dc = _series([1.0, 2.0, 0.0, 40.0, 3.0])
    p_dc = _series([500.0, 300.0, 0.0, 1000.0, 1050.0])
    result = evaluate_sandia_inverter_input(v_dc, i_dc, p_dc, _model(), _envelope())
    assert result.index.equals(v_dc.index)
    assert result["conversion_evaluated"].tolist() == [True, False, True, False, True]
    assert result["p_ac_available_w"].notna().tolist() == [True, False, True, False, True]
    assert result["inverter_operating_state"].tolist() == [
        "producing",
        "below_mppt_voltage",
        "night_tare",
        "absolute_dc_overvoltage",
        "ac_limited",
    ]


def test_all_admissible_rows_are_exactly_equivalent_to_i1() -> None:
    v_dc = _series([100.0, 400.0, 400.0])
    i_dc = _series([0.0, 1.0, 3.0])
    p_dc = _series([0.0, 500.0, 1050.0])
    result = evaluate_sandia_inverter_input(v_dc, i_dc, p_dc, _model(), _envelope())
    direct = calculate_sandia_inverter_ac_power(v_dc, i_dc, p_dc, _model())
    pd.testing.assert_series_equal(
        result["p_ac_available_w"],
        direct["p_ac_available_w"],
    )
    pd.testing.assert_series_equal(result["ac_to_dc_ratio"], direct["ac_to_dc_ratio"])
    pd.testing.assert_series_equal(
        result["at_ac_power_limit"],
        direct["at_ac_power_limit"],
    )
    assert result["inverter_operating_state"].tolist() == direct[
        "operating_state"
    ].tolist()


def test_envelope_fields_are_exactly_equivalent_to_i2() -> None:
    v_dc = _series([100.0, 199.0, 400.0, 550.0, 650.0])
    i_dc = _series([0.0, 2.0, 1.0, 40.0, 40.0])
    p_dc = _series([0.0, 300.0, 500.0, 1000.0, 1000.0])
    result = evaluate_sandia_inverter_input(v_dc, i_dc, p_dc, _model(), _envelope())
    direct = evaluate_inverter_dc_operating_envelope(v_dc, i_dc, p_dc, _envelope())
    pd.testing.assert_frame_equal(result[_ENVELOPE_COLUMNS], direct[_ENVELOPE_COLUMNS])


def test_sandia_and_envelope_provenance_remain_independent() -> None:
    result = _evaluate([400.0], [1.0], [500.0])
    row = result.iloc[0]
    assert row["model_used"] == "sandia"
    assert row["sandia_parameter_source"] == "sandia-source"
    assert row["sandia_confidence"] == "high"
    assert row["envelope_parameter_source"] == "envelope-source"
    assert row["envelope_confidence"] == "medium"


def test_empty_inputs_return_exact_typed_schema_and_index() -> None:
    index = pd.DatetimeIndex([], tz="Europe/London", name="timestamp")
    empty = pd.Series([], index=index, dtype=float)
    result = evaluate_sandia_inverter_input(
        empty,
        empty,
        empty,
        _model(),
        _envelope(),
    )
    assert result.empty
    assert list(result.columns) == _OUTPUT_COLUMNS
    assert result.index.equals(index)
    for column in [
        "v_dc_v",
        "i_dc_a",
        "p_dc_available_w",
        "p_ac_available_w",
        "ac_to_dc_ratio",
    ]:
        assert pd.api.types.is_float_dtype(result[column])
    for column in [
        "is_active_dc_input",
        "below_mppt_voltage_limit",
        "above_mppt_voltage_limit",
        "above_absolute_dc_voltage_limit",
        "above_dc_current_limit",
        "dc_limits_satisfied",
        "conversion_evaluated",
        "at_ac_power_limit",
    ]:
        assert pd.api.types.is_bool_dtype(result[column])
    assert result["dc_operating_state"].dtype == object
    assert result["inverter_operating_state"].dtype == object


def test_empty_and_populated_results_concatenate_without_bool_dtype_drift() -> None:
    index = pd.DatetimeIndex([], tz="UTC")
    empty = pd.Series([], index=index, dtype=float)
    empty_result = evaluate_sandia_inverter_input(
        empty,
        empty,
        empty,
        _model(),
        _envelope(),
    )
    populated = _evaluate([400.0], [1.0], [500.0])
    combined = pd.concat([empty_result, populated])
    for column in [
        "is_active_dc_input",
        "below_mppt_voltage_limit",
        "above_mppt_voltage_limit",
        "above_absolute_dc_voltage_limit",
        "above_dc_current_limit",
        "dc_limits_satisfied",
        "conversion_evaluated",
        "at_ac_power_limit",
    ]:
        assert pd.api.types.is_bool_dtype(combined[column])


@pytest.mark.parametrize("input_name", ["v_dc_v", "i_dc_a", "p_dc_available_w"])
@pytest.mark.parametrize("value", [[400.0], (400.0,), np.array([400.0]), 400.0])
def test_inputs_must_be_series(input_name: str, value: object) -> None:
    inputs: dict[str, object] = {
        "v_dc_v": _series([400.0]),
        "i_dc_a": _series([1.0]),
        "p_dc_available_w": _series([400.0]),
    }
    inputs[input_name] = value
    with pytest.raises(ValueError, match=f"{input_name} must be a pandas Series"):
        evaluate_sandia_inverter_input(
            **inputs,  # type: ignore[arg-type]
            model=_model(),
            resolved_envelope=_envelope(),
        )


@pytest.mark.parametrize("mismatched", ["v_i", "v_p", "i_p"])
def test_indexes_must_match_without_alignment(mismatched: str) -> None:
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
        evaluate_sandia_inverter_input(v_dc, i_dc, p_dc, _model(), _envelope())


@pytest.mark.parametrize(
    ("input_name", "value"),
    [
        ("v_dc_v", -1.0),
        ("i_dc_a", -1.0),
        ("p_dc_available_w", -1.0),
        ("v_dc_v", np.nan),
        ("i_dc_a", np.inf),
        ("p_dc_available_w", -np.inf),
        ("p_dc_available_w", True),
    ],
)
def test_invalid_electrical_values_use_existing_validation(
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
        evaluate_sandia_inverter_input(
            **inputs,
            model=_model(),
            resolved_envelope=_envelope(),
        )


@pytest.mark.parametrize(("v_dc", "i_dc"), [(0.0, 1.0), (400.0, 0.0)])
def test_positive_power_requires_positive_voltage_and_current(
    v_dc: float,
    i_dc: float,
) -> None:
    with pytest.raises(ValueError, match="positive p_dc_available_w"):
        _evaluate([v_dc], [i_dc], [100.0])


def test_inputs_and_models_are_not_mutated() -> None:
    v_dc = _series([400.0, 550.0])
    i_dc = _series([1.0, 40.0])
    p_dc = _series([500.0, 1000.0])
    model = _model()
    envelope = _envelope()
    v_before = v_dc.copy(deep=True)
    i_before = i_dc.copy(deep=True)
    p_before = p_dc.copy(deep=True)
    evaluate_sandia_inverter_input(v_dc, i_dc, p_dc, model, envelope)
    pd.testing.assert_series_equal(v_dc, v_before)
    pd.testing.assert_series_equal(i_dc, i_before)
    pd.testing.assert_series_equal(p_dc, p_before)
    assert model == _model()
    assert envelope == _envelope()
