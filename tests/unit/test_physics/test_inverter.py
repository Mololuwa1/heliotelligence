"""Tests for the model-aware Sandia inverter physics foundation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pvlib.inverter
import pytest

from heliotelligence.physics.inverter import (
    ResolvedSandiaInverterModel,
    SandiaInverterParameters,
    calculate_sandia_inverter_ac_power,
    sandia_parameters_from_mapping,
)


def _parameters(**overrides: object) -> SandiaInverterParameters:
    values: dict[str, object] = {
        "paco_w": 1000.0,
        "pdco_w": 1050.0,
        "vdco_v": 400.0,
        "pso_w": 10.0,
        "c0_per_w": 0.0,
        "c1_per_v": 0.0,
        "c2_per_v": 0.0,
        "c3_per_v": 0.0,
        "pnt_w": 1.0,
    }
    values.update(overrides)
    return SandiaInverterParameters(**values)  # type: ignore[arg-type]


def _model(
    parameters: SandiaInverterParameters | None = None,
) -> ResolvedSandiaInverterModel:
    return ResolvedSandiaInverterModel(
        parameters=parameters or _parameters(),
        parameter_source="synthetic:test",
        confidence="high",
    )


def _series(values: list[float]) -> pd.Series:
    index = pd.date_range("2025-06-21 10:00", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=index, dtype=float)


def _calculate(
    p_dc: list[float],
    *,
    v_dc: list[float] | None = None,
    i_dc: list[float] | None = None,
    model: ResolvedSandiaInverterModel | None = None,
) -> pd.DataFrame:
    voltages = v_dc or [400.0] * len(p_dc)
    currents = i_dc or [
        max(power / voltage, 1.0)
        for power, voltage in zip(p_dc, voltages, strict=True)
    ]
    return calculate_sandia_inverter_ac_power(
        _series(voltages),
        _series(currents),
        _series(p_dc),
        model or _model(),
    )


def test_sandia_parameters_are_frozen() -> None:
    parameters = _parameters()

    with pytest.raises(FrozenInstanceError):
        parameters.paco_w = 2000.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paco_w", True),
        ("pdco_w", "1050"),
        ("vdco_v", np.nan),
        ("pso_w", np.inf),
        ("pnt_w", -np.inf),
        ("c0_per_w", True),
        ("c1_per_v", np.nan),
        ("c2_per_v", np.inf),
        ("c3_per_v", "0"),
    ],
)
def test_parameter_fields_require_finite_real_non_bool_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError, match=field):
        _parameters(**{field: value})


@pytest.mark.parametrize("field", ["paco_w", "pdco_w", "vdco_v"])
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_positive_parameter_fields_are_strictly_positive(
    field: str, value: float
) -> None:
    with pytest.raises(ValueError, match=field):
        _parameters(**{field: value})


@pytest.mark.parametrize("field", ["pso_w", "pnt_w"])
def test_non_negative_parameter_fields_reject_negative_values(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _parameters(**{field: -1.0})


@pytest.mark.parametrize("pso_w", [1050.0, 1100.0])
def test_startup_power_must_be_below_reference_dc_power(pso_w: float) -> None:
    with pytest.raises(ValueError, match="pso_w must be less than pdco_w"):
        _parameters(pso_w=pso_w)


def test_coefficients_accept_unconstrained_finite_values() -> None:
    parameters = _parameters(
        c0_per_w=-2.5,
        c1_per_v=3.5,
        c2_per_v=-4.5,
        c3_per_v=5.5,
    )

    assert parameters.c0_per_w == -2.5
    assert parameters.c1_per_v == 3.5
    assert parameters.c2_per_v == -4.5
    assert parameters.c3_per_v == 5.5


def test_to_pvlib_dict_has_exact_keys_and_is_independent() -> None:
    parameters = _parameters()
    first = parameters.to_pvlib_dict()
    second = parameters.to_pvlib_dict()

    assert list(first) == ["Paco", "Pdco", "Vdco", "Pso", "C0", "C1", "C2", "C3", "Pnt"]
    assert first is not second
    first["Paco"] = -1.0
    assert parameters.paco_w == 1000.0
    assert second["Paco"] == 1000.0


def test_source_agnostic_mapping_ignores_extra_fields() -> None:
    values = _parameters().to_pvlib_dict() | {"Manufacturer": "Synthetic"}

    assert sandia_parameters_from_mapping(values) == _parameters()


def test_mapping_adapter_reports_all_missing_keys_sorted() -> None:
    values = _parameters().to_pvlib_dict()
    del values["Vdco"]
    del values["C0"]
    del values["Paco"]

    with pytest.raises(ValueError) as error:
        sandia_parameters_from_mapping(values)

    assert str(error.value) == "missing Sandia parameter keys: C0, Paco, Vdco"


def test_mapping_adapter_rejects_non_mapping_input() -> None:
    with pytest.raises(ValueError, match="values must be a mapping"):
        sandia_parameters_from_mapping([])  # type: ignore[arg-type]


def test_resolved_model_is_frozen_and_retains_provenance() -> None:
    model = _model()

    assert model.parameter_source == "synthetic:test"
    assert model.confidence == "high"
    with pytest.raises(FrozenInstanceError):
        model.confidence = "low"  # type: ignore[misc]


@pytest.mark.parametrize("parameters", [None, {}, "parameters"])
def test_resolved_model_rejects_invalid_parameter_type(parameters: object) -> None:
    with pytest.raises(ValueError, match="parameters must be"):
        ResolvedSandiaInverterModel(  # type: ignore[arg-type]
            parameters=parameters,
            parameter_source="source",
            confidence="high",
        )


@pytest.mark.parametrize("source", [None, "", "   ", 1])
def test_resolved_model_rejects_invalid_source(source: object) -> None:
    with pytest.raises(ValueError, match="parameter_source"):
        ResolvedSandiaInverterModel(  # type: ignore[arg-type]
            parameters=_parameters(),
            parameter_source=source,
            confidence="high",
        )


@pytest.mark.parametrize("confidence", ["HIGH", "", "certain", None, []])
def test_resolved_model_rejects_invalid_confidence(confidence: object) -> None:
    with pytest.raises(ValueError, match="confidence"):
        ResolvedSandiaInverterModel(  # type: ignore[arg-type]
            parameters=_parameters(),
            parameter_source="source",
            confidence=confidence,
        )


@pytest.mark.parametrize("input_name", ["v_dc_v", "i_dc_a", "p_dc_available_w"])
@pytest.mark.parametrize("value", [[400.0], (400.0,), np.array([400.0]), 400.0])
def test_calculation_requires_series_inputs(input_name: str, value: object) -> None:
    inputs: dict[str, object] = {
        "v_dc_v": _series([400.0]),
        "i_dc_a": _series([1.0]),
        "p_dc_available_w": _series([400.0]),
    }
    inputs[input_name] = value

    with pytest.raises(ValueError, match=f"{input_name} must be a pandas Series"):
        calculate_sandia_inverter_ac_power(**inputs, model=_model())  # type: ignore[arg-type]


def test_rated_reference_point_is_ac_limited() -> None:
    result = _calculate([1050.0], i_dc=[1050.0 / 400.0])

    assert result.loc[result.index[0], "p_ac_available_w"] == pytest.approx(1000.0)
    assert bool(result.loc[result.index[0], "at_ac_power_limit"])
    assert result.loc[result.index[0], "operating_state"] == "ac_limited"
    assert result.loc[result.index[0], "model_used"] == "sandia"
    assert pd.isna(result.loc[result.index[0], "ac_to_dc_ratio"])


def test_night_tare_signed_power_is_preserved() -> None:
    result = _calculate([5.0], i_dc=[1.0])

    assert result.loc[result.index[0], "p_ac_available_w"] == pytest.approx(-1.0)
    assert result.loc[result.index[0], "operating_state"] == "night_tare"
    assert pd.isna(result.loc[result.index[0], "ac_to_dc_ratio"])


def test_zero_power_preserves_night_tare() -> None:
    result = _calculate([0.0], v_dc=[0.0], i_dc=[0.0])

    assert result.loc[result.index[0], "p_ac_available_w"] == pytest.approx(-1.0)
    assert result.loc[result.index[0], "operating_state"] == "night_tare"


def test_startup_boundary_with_zero_ac_is_non_producing() -> None:
    result = _calculate([10.0], i_dc=[1.0])

    assert result.loc[result.index[0], "p_ac_available_w"] == pytest.approx(0.0)
    assert result.loc[result.index[0], "operating_state"] == "non_producing"


def test_part_load_behavior_is_not_one_fixed_efficiency() -> None:
    result = _calculate([200.0, 500.0, 800.0])
    ratios = result["p_ac_available_w"] / result["p_dc_available_w"]

    assert result["p_ac_available_w"].is_monotonic_increasing
    assert ratios.nunique() > 1


def test_nonzero_coefficients_make_output_voltage_dependent() -> None:
    parameters = _parameters(c1_per_v=0.001, c2_per_v=0.002, c3_per_v=0.001)
    result = _calculate(
        [500.0, 500.0],
        v_dc=[350.0, 450.0],
        i_dc=[500.0 / 350.0, 500.0 / 450.0],
        model=_model(parameters),
    )

    assert result["p_ac_available_w"].nunique() == 2


def test_public_result_matches_pvlib_sandia_exactly() -> None:
    parameters = _parameters(c0_per_w=-0.00001, c1_per_v=0.0002)
    model = _model(parameters)
    v_dc = _series([350.0, 400.0, 450.0, 400.0])
    p_dc = _series([0.0, 250.0, 700.0, 1100.0])
    i_dc = _series([0.0, 0.7, 1.6, 2.8])

    result = calculate_sandia_inverter_ac_power(v_dc, i_dc, p_dc, model)
    expected = pvlib.inverter.sandia(v_dc, p_dc, parameters.to_pvlib_dict())

    pd.testing.assert_series_equal(
        result["p_ac_available_w"], expected.rename("p_ac_available_w")
    )


def test_idc_and_timezone_aware_index_are_preserved() -> None:
    v_dc = _series([400.0, 410.0])
    i_dc = _series([1.234, 2.345])
    p_dc = _series([490.0, 950.0])

    result = calculate_sandia_inverter_ac_power(v_dc, i_dc, p_dc, _model())

    pd.testing.assert_index_equal(result.index, v_dc.index, exact=True)
    pd.testing.assert_series_equal(result["i_dc_a"], i_dc.rename("i_dc_a"))


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
        calculate_sandia_inverter_ac_power(v_dc, i_dc, p_dc, _model())


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
    input_name: str, value: object
) -> None:
    inputs: dict[str, pd.Series] = {
        "v_dc_v": _series([400.0]),
        "i_dc_a": _series([1.0]),
        "p_dc_available_w": _series([400.0]),
    }
    inputs[input_name] = pd.Series([value], index=inputs[input_name].index)

    with pytest.raises(ValueError, match=input_name):
        calculate_sandia_inverter_ac_power(**inputs, model=_model())


@pytest.mark.parametrize(("v_dc", "i_dc"), [(0.0, 1.0), (400.0, 0.0)])
def test_positive_power_requires_positive_voltage_and_current(
    v_dc: float, i_dc: float
) -> None:
    with pytest.raises(ValueError, match="positive p_dc_available_w"):
        _calculate([100.0], v_dc=[v_dc], i_dc=[i_dc])


def test_vi_product_is_not_enforced_or_recalculated() -> None:
    v_dc = _series([400.0])
    i_dc = _series([1.01])
    p_dc = _series([405.0])

    result = calculate_sandia_inverter_ac_power(v_dc, i_dc, p_dc, _model())

    pd.testing.assert_series_equal(result["v_dc_v"], v_dc.rename("v_dc_v"))
    pd.testing.assert_series_equal(result["i_dc_a"], i_dc.rename("i_dc_a"))
    pd.testing.assert_series_equal(
        result["p_dc_available_w"], p_dc.rename("p_dc_available_w")
    )


def test_empty_inputs_return_exact_empty_schema_without_calling_pvlib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = pd.DatetimeIndex([], tz="UTC")
    empty = pd.Series([], index=index, dtype=float)

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("pvlib.inverter.sandia must not be called")

    monkeypatch.setattr(pvlib.inverter, "sandia", fail_if_called)
    result = calculate_sandia_inverter_ac_power(empty, empty, empty, _model())

    assert result.empty
    assert result.columns.tolist() == [
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
    pd.testing.assert_index_equal(result.index, index)
    for column in (
        "v_dc_v",
        "i_dc_a",
        "p_dc_available_w",
        "p_ac_available_w",
        "ac_to_dc_ratio",
    ):
        assert pd.api.types.is_float_dtype(result[column])
        assert not pd.api.types.is_object_dtype(result[column])
    assert pd.api.types.is_bool_dtype(result["at_ac_power_limit"])
    assert not pd.api.types.is_object_dtype(result["at_ac_power_limit"])


@pytest.mark.parametrize("empty_first", [True, False])
def test_empty_and_populated_results_concatenate_without_dtype_degradation(
    empty_first: bool,
) -> None:
    index = pd.DatetimeIndex([], tz="UTC")
    empty_series = pd.Series([], index=index, dtype=float)
    empty_result = calculate_sandia_inverter_ac_power(
        empty_series,
        empty_series,
        empty_series,
        _model(),
    )
    populated_result = _calculate([500.0])
    frames = (
        [empty_result, populated_result]
        if empty_first
        else [populated_result, empty_result]
    )

    combined = pd.concat(frames)

    for column in (
        "v_dc_v",
        "i_dc_a",
        "p_dc_available_w",
        "p_ac_available_w",
        "ac_to_dc_ratio",
    ):
        assert pd.api.types.is_float_dtype(combined[column])
        assert not pd.api.types.is_object_dtype(combined[column])
        pd.testing.assert_series_equal(
            combined[column],
            populated_result[column],
            check_names=True,
            check_freq=False,
        )
    assert pd.api.types.is_bool_dtype(combined["at_ac_power_limit"])
    assert not pd.api.types.is_object_dtype(combined["at_ac_power_limit"])
    pd.testing.assert_series_equal(
        combined["at_ac_power_limit"],
        populated_result["at_ac_power_limit"],
        check_names=True,
        check_freq=False,
    )


def test_ac_to_dc_ratio_is_only_reported_away_from_tare_and_limit() -> None:
    result = _calculate([5.0, 500.0, 1050.0])

    assert pd.isna(result["ac_to_dc_ratio"].iloc[0])
    assert result["ac_to_dc_ratio"].iloc[1] == pytest.approx(
        result["p_ac_available_w"].iloc[1] / 500.0
    )
    assert pd.isna(result["ac_to_dc_ratio"].iloc[2])


def test_inputs_and_model_are_not_mutated() -> None:
    v_dc = _series([400.0, 410.0])
    i_dc = _series([1.0, 2.0])
    p_dc = _series([400.0, 820.0])
    model = _model()
    before = (v_dc.copy(deep=True), i_dc.copy(deep=True), p_dc.copy(deep=True), model)

    calculate_sandia_inverter_ac_power(v_dc, i_dc, p_dc, model)

    pd.testing.assert_series_equal(v_dc, before[0])
    pd.testing.assert_series_equal(i_dc, before[1])
    pd.testing.assert_series_equal(p_dc, before[2])
    assert model == before[3]


def test_calculation_rejects_unresolved_model_object() -> None:
    valid = _series([400.0])

    with pytest.raises(ValueError, match="model must be ResolvedSandiaInverterModel"):
        calculate_sandia_inverter_ac_power(valid, valid, valid, _parameters())  # type: ignore[arg-type]


def test_output_does_not_claim_deferred_loss_decomposition() -> None:
    result = _calculate([500.0])

    assert not {
        "p_conversion_loss",
        "p_clipping_loss",
        "p_ac_potential",
        "p_ac_dispatched",
    } & set(result.columns)


def test_model_metadata_is_repeated_on_every_row() -> None:
    result = _calculate([200.0, 500.0, 1050.0])

    assert result["model_used"].tolist() == ["sandia"] * 3
    assert result["parameter_source"].tolist() == ["synthetic:test"] * 3
    assert result["confidence"].tolist() == ["high"] * 3
