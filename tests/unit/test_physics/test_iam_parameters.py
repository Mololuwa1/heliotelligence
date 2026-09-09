"""Physics-contract tests for beam-IAM parameter resolution and provenance."""

from __future__ import annotations

import json
from collections.abc import Callable

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pvlib.iam
import pytest

from heliotelligence.physics.iam import calculate_beam_iam
from heliotelligence.physics.iam_parameters import resolve_beam_iam_parameters

AOI = np.array([0.0, 20.0, 40.0, 60.0, 75.0, 85.0])
RESULT_KEYS = [
    "model",
    "model_parameters",
    "resolution_method",
    "source_label",
    "source_reference",
    "is_fallback",
    "derivation_note",
    "fit_sample_count",
    "fit_aoi_min_deg",
    "fit_aoi_max_deg",
    "fit_rmse",
    "fit_mae",
    "fit_max_abs_error",
]
FIT_KEYS = RESULT_KEYS[7:]


def _time_aoi() -> pd.Series:
    index = pd.DatetimeIndex(
        ["2026-06-21 12:00", "2026-06-21 12:07"],
        tz="Europe/London",
        name="physical_time",
    )
    return pd.Series([15.0, 70.0], index=index)


def _assert_r3a_compatible(result: dict[str, object]) -> None:
    r3a = calculate_beam_iam(
        _time_aoi(),
        model=result["model"],  # type: ignore[arg-type]
        model_parameters=result["model_parameters"],  # type: ignore[arg-type]
    )
    assert r3a["beam_iam_resolved"].all()
    assert r3a["beam_iam_model"].eq(result["model"]).all()


@pytest.mark.parametrize(
    ("model", "parameters"),
    [
        ("physical", {"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": None}),
        ("physical", {"n": 1.52, "K": 3.5, "L": 0.003, "n_ar": 1.29}),
        ("martin-ruiz", {"a_r": 0.16}),
        ("ashrae", {"b": 0.0}),
        ("ashrae", {"b": 0.05}),
    ],
)
def test_direct_preserves_native_parameters_and_provenance(
    model: str, parameters: dict[str, object]
) -> None:
    result = resolve_beam_iam_parameters(
        model=model,  # type: ignore[arg-type]
        method="direct",
        source_label="manufacturer data sheet",
        source_reference="document:rev-2",
        model_parameters=parameters,
    )

    assert list(result) == RESULT_KEYS
    assert result["model"] == model
    assert result["model_parameters"] == parameters
    assert result["resolution_method"] == "direct"
    assert result["source_label"] == "manufacturer data sheet"
    assert result["source_reference"] == "document:rev-2"
    assert result["is_fallback"] is False
    assert result["derivation_note"] is None
    assert all(result[key] is None for key in FIT_KEYS)
    json.dumps(result)
    _assert_r3a_compatible(result)


def test_direct_converts_numpy_scalars_to_json_friendly_equivalents() -> None:
    result = resolve_beam_iam_parameters(
        model="physical",
        method="direct",
        source_label="curated record",
        model_parameters={
            "n": np.float64(1.52),
            "K": np.int64(4),
            "L": np.float64(0.002),
            "n_ar": None,
        },
    )
    parameters = result["model_parameters"]
    assert isinstance(parameters, dict)
    assert parameters == {"n": 1.52, "K": 4, "L": 0.002, "n_ar": None}
    assert all(not isinstance(value, np.generic) for value in parameters.values())
    json.dumps(result)


def test_explicit_fallback_is_caller_supplied_and_r3a_compatible() -> None:
    parameters = {"b": 0.05}
    result = resolve_beam_iam_parameters(
        model="ashrae",
        method="explicit_fallback",
        source_label="documented engineering fallback",
        source_reference="policy:IAM-1",
        model_parameters=parameters,
    )
    assert result["model_parameters"] == parameters
    assert result["resolution_method"] == "explicit_fallback"
    assert result["is_fallback"] is True
    assert result["source_label"] == "documented engineering fallback"
    assert result["source_reference"] == "policy:IAM-1"
    assert result["derivation_note"] is None
    assert all(result[key] is None for key in FIT_KEYS)
    json.dumps(result)
    _assert_r3a_compatible(result)


def _profile(model: str) -> np.ndarray:
    if model == "physical":
        return np.asarray(pvlib.iam.physical(AOI, n=1.52, K=4.0, L=0.002))
    if model == "martin-ruiz":
        return np.asarray(pvlib.iam.martin_ruiz(AOI, a_r=0.16))
    return np.asarray(pvlib.iam.ashrae(AOI, b=0.05))


def _reference_parameters(model: str, measured: np.ndarray) -> dict[str, object]:
    fitted = dict(
        pvlib.iam.fit(
            AOI,
            measured,
            model_name="martin_ruiz" if model == "martin-ruiz" else model,
        )
    )
    if model == "physical":
        fitted["n_ar"] = None
    return {
        key: value.item() if isinstance(value, np.generic) else value
        for key, value in fitted.items()
    }


def _predict(
    model: str, aoi: np.ndarray, parameters: dict[str, object]
) -> np.ndarray:
    function: Callable[..., object] = {
        "physical": pvlib.iam.physical,
        "martin-ruiz": pvlib.iam.martin_ruiz,
        "ashrae": pvlib.iam.ashrae,
    }[model]
    return np.asarray(function(aoi, **parameters), dtype=float)


@pytest.mark.parametrize("model", ["physical", "martin-ruiz", "ashrae"])
def test_measured_fit_matches_public_pvlib_and_reports_residuals(model: str) -> None:
    measured = _profile(model)
    expected_parameters = _reference_parameters(model, measured)
    result = resolve_beam_iam_parameters(
        model=model,  # type: ignore[arg-type]
        method="measured_fit",
        source_label="laboratory IAM profile",
        source_reference="test-report:123",
        measured_aoi_deg=AOI,
        measured_iam=measured,
    )

    assert result["model_parameters"] == pytest.approx(expected_parameters)
    assert result["resolution_method"] == "measured_fit"
    assert result["is_fallback"] is False
    predicted = _predict(model, AOI, expected_parameters)
    residual = predicted - measured
    assert result["fit_sample_count"] == len(AOI)
    assert result["fit_aoi_min_deg"] == 0.0
    assert result["fit_aoi_max_deg"] == 85.0
    assert result["fit_rmse"] == pytest.approx(np.sqrt(np.mean(residual**2)))
    assert result["fit_mae"] == pytest.approx(np.mean(np.abs(residual)))
    assert result["fit_max_abs_error"] == pytest.approx(
        np.max(np.abs(residual))
    )
    json.dumps(result)
    _assert_r3a_compatible(result)


def test_physical_fit_adds_explicit_unfitted_n_ar_semantics() -> None:
    measured = _profile("physical")
    direct_fit = pvlib.iam.fit(AOI, measured, model_name="physical")
    assert set(direct_fit) == {"n", "K", "L"}
    result = resolve_beam_iam_parameters(
        model="physical",
        method="measured_fit",
        source_label="measured profile",
        measured_aoi_deg=AOI,
        measured_iam=measured,
    )
    parameters = result["model_parameters"]
    assert isinstance(parameters, dict)
    assert parameters["n"] == pytest.approx(direct_fit["n"])
    assert parameters["K"] == pytest.approx(direct_fit["K"])
    assert parameters["L"] == pytest.approx(direct_fit["L"])
    assert parameters["n_ar"] is None
    assert result["derivation_note"] == (
        "pvlib_physical_fit_does_not_fit_n_ar; n_ar set to None"
    )
    expected = pvlib.iam.physical(AOI, **parameters)
    residual = expected - measured
    assert result["fit_rmse"] == pytest.approx(np.sqrt(np.mean(residual**2)))
    _assert_r3a_compatible(result)


def test_non_normalized_profile_is_passed_to_pvlib_without_normalization() -> None:
    measured = np.array([0.99, 0.98, 0.94, 0.82, 0.60, 0.25])
    expected = pvlib.iam.fit(AOI, measured, model_name="ashrae")
    result = resolve_beam_iam_parameters(
        model="ashrae",
        method="measured_fit",
        source_label="raw profile",
        measured_aoi_deg=AOI,
        measured_iam=measured,
    )
    assert result["model_parameters"] == pytest.approx(expected)


def test_iam_above_one_and_duplicate_aoi_are_accepted_without_clipping() -> None:
    aoi = [0.0, 20.0, 20.0, 60.0]
    measured = [1.01, 1.005, 0.995, 0.8]
    expected = pvlib.iam.fit(
        np.asarray(aoi), np.asarray(measured), model_name="martin_ruiz"
    )
    result = resolve_beam_iam_parameters(
        model="martin-ruiz",
        method="measured_fit",
        source_label="raw repeated measurements",
        measured_aoi_deg=aoi,
        measured_iam=measured,
    )
    assert result["model_parameters"] == pytest.approx(expected)
    assert result["fit_sample_count"] == 4


@pytest.mark.parametrize("model", ["", "sapm", "Physical", None])
def test_invalid_model_is_rejected(model: object) -> None:
    with pytest.raises(ValueError, match="model must"):
        resolve_beam_iam_parameters(
            model=model,  # type: ignore[arg-type]
            method="direct",
            source_label="source",
            model_parameters={"b": 0.05},
        )


@pytest.mark.parametrize("method", ["", "automatic", "fallback", None])
def test_invalid_method_is_rejected(method: object) -> None:
    with pytest.raises(ValueError, match="method must"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method=method,  # type: ignore[arg-type]
            source_label="source",
            model_parameters={"b": 0.05},
        )


@pytest.mark.parametrize("label", [None, 1, "", "   "])
def test_source_label_must_be_nonempty_string(label: object) -> None:
    with pytest.raises(ValueError, match="source_label"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="direct",
            source_label=label,  # type: ignore[arg-type]
            model_parameters={"b": 0.05},
        )


@pytest.mark.parametrize("reference", [1, "", "  "])
def test_source_reference_must_be_none_or_nonempty_string(reference: object) -> None:
    with pytest.raises(ValueError, match="source_reference"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="direct",
            source_label="source",
            source_reference=reference,  # type: ignore[arg-type]
            model_parameters={"b": 0.05},
        )


def test_provenance_whitespace_is_validated_but_not_rewritten() -> None:
    result = resolve_beam_iam_parameters(
        model="ashrae",
        method="direct",
        source_label="  source label  ",
        source_reference="  opaque reference  ",
        model_parameters={"b": 0.05},
    )
    assert result["source_label"] == "  source label  "
    assert result["source_reference"] == "  opaque reference  "


@pytest.mark.parametrize(
    ("model", "parameters"),
    [
        ("physical", {"n": 1.52, "K": 4.0, "L": 0.002}),
        ("physical", {"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": None, "b": 0.05}),
        ("martin-ruiz", {}),
        ("martin-ruiz", {"a_r": 0.16, "b": 0.05}),
        ("ashrae", {}),
        ("ashrae", {"a_r": 0.16}),
    ],
)
def test_direct_parameter_keys_must_match_exactly(
    model: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="contain exactly"):
        resolve_beam_iam_parameters(
            model=model,  # type: ignore[arg-type]
            method="direct",
            source_label="source",
            model_parameters=parameters,
        )


@pytest.mark.parametrize("parameters", [None, 1, "b=0.05", [("b", 0.05)]])
def test_direct_parameter_mapping_type_is_required(parameters: object) -> None:
    with pytest.raises(ValueError, match="model_parameters must be a mapping"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="direct",
            source_label="source",
            model_parameters=parameters,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("bad", [True, "1.5", None, np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("key", ["n", "K", "L"])
def test_physical_rejects_invalid_parameters(key: str, bad: object) -> None:
    parameters: dict[str, object] = {
        "n": 1.52,
        "K": 4.0,
        "L": 0.002,
        "n_ar": None,
    }
    parameters[key] = bad
    with pytest.raises(ValueError, match=key):
        resolve_beam_iam_parameters(
            model="physical",
            method="direct",
            source_label="source",
            model_parameters=parameters,
        )


@pytest.mark.parametrize(
    ("key", "bad"), [("n", 0.0), ("n", -1.0), ("K", -1.0), ("L", -0.1)]
)
def test_physical_parameter_bounds(key: str, bad: float) -> None:
    parameters = {"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": None}
    parameters[key] = bad
    with pytest.raises(ValueError, match=key):
        resolve_beam_iam_parameters(
            model="physical",
            method="direct",
            source_label="source",
            model_parameters=parameters,
        )


@pytest.mark.parametrize("bad", [0.0, -1.0, True, "1.29", np.nan, np.inf, -np.inf])
def test_physical_n_ar_validation(bad: object) -> None:
    with pytest.raises(ValueError, match="n_ar"):
        resolve_beam_iam_parameters(
            model="physical",
            method="direct",
            source_label="source",
            model_parameters={"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": bad},
        )


@pytest.mark.parametrize(
    ("model", "key", "bad"),
    [
        ("martin-ruiz", "a_r", 0.0),
        ("martin-ruiz", "a_r", -0.1),
        ("martin-ruiz", "a_r", None),
        ("martin-ruiz", "a_r", True),
        ("martin-ruiz", "a_r", "0.16"),
        ("martin-ruiz", "a_r", np.nan),
        ("martin-ruiz", "a_r", np.inf),
        ("ashrae", "b", -0.1),
        ("ashrae", "b", None),
        ("ashrae", "b", False),
        ("ashrae", "b", "0.05"),
        ("ashrae", "b", np.inf),
        ("ashrae", "b", -np.inf),
    ],
)
def test_empirical_parameter_validation(model: str, key: str, bad: object) -> None:
    with pytest.raises(ValueError, match=key):
        resolve_beam_iam_parameters(
            model=model,  # type: ignore[arg-type]
            method="direct",
            source_label="source",
            model_parameters={key: bad},
        )


@pytest.mark.parametrize("method", ["direct", "explicit_fallback"])
def test_native_methods_require_parameters_and_reject_measurements(method: str) -> None:
    with pytest.raises(ValueError, match="model_parameters must be a mapping"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method=method,  # type: ignore[arg-type]
            source_label="source",
        )
    with pytest.raises(ValueError, match="does not accept measured"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method=method,  # type: ignore[arg-type]
            source_label="source",
            model_parameters={"b": 0.05},
            measured_aoi_deg=[0.0, 60.0],
        )


def test_measured_fit_rejects_parameters_and_incomplete_profiles() -> None:
    with pytest.raises(ValueError, match="does not accept model_parameters"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            model_parameters={"b": 0.05},
            measured_aoi_deg=AOI,
            measured_iam=_profile("ashrae"),
        )
    for kwargs in (
        {"measured_aoi_deg": AOI},
        {"measured_iam": _profile("ashrae")},
        {},
    ):
        with pytest.raises(ValueError, match="requires measured_aoi_deg"):
            resolve_beam_iam_parameters(
                model="ashrae",
                method="measured_fit",
                source_label="source",
                **kwargs,
            )


@pytest.mark.parametrize(
    "bad",
    [1, 1.0, "0,20", b"0,20", {"aoi": [0, 20]}, np.array([[0.0, 20.0]])],
)
def test_measured_aoi_requires_one_dimensional_array_like(bad: object) -> None:
    with pytest.raises(ValueError, match="measured_aoi_deg"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=bad,  # type: ignore[arg-type]
            measured_iam=[1.0, 0.9],
        )


@pytest.mark.parametrize(
    "bad",
    [1, 1.0, "1,0.9", b"1,0.9", {"iam": [1, 0.9]}, np.array([[1.0, 0.9]])],
)
def test_measured_iam_requires_one_dimensional_array_like(bad: object) -> None:
    with pytest.raises(ValueError, match="measured_iam"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, 60.0],
            measured_iam=bad,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("aoi", [[], [0.0], [20.0, 20.0]])
def test_measured_profile_sample_requirements(aoi: list[float]) -> None:
    with pytest.raises(ValueError, match="at least 2"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=aoi,
            measured_iam=[1.0] * len(aoi),
        )


def test_measured_profile_lengths_must_match() -> None:
    with pytest.raises(ValueError, match="equal length"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, 30.0, 60.0],
            measured_iam=[1.0, 0.8],
        )


@pytest.mark.parametrize("bad", [-0.1, 90.1, np.nan, np.inf, -np.inf, True, "20"])
def test_invalid_measured_aoi_values_are_rejected(bad: object) -> None:
    with pytest.raises(ValueError, match="measured_aoi_deg"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, bad],
            measured_iam=[1.0, 0.8],
        )


@pytest.mark.parametrize("bad", [-0.1, np.nan, np.inf, -np.inf, True, "0.8"])
def test_invalid_measured_iam_values_are_rejected(bad: object) -> None:
    with pytest.raises(ValueError, match="measured_iam"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, 60.0],
            measured_iam=[1.0, bad],
        )


@pytest.mark.parametrize("container", ["list", "tuple", "array", "series"])
def test_measured_inputs_are_not_mutated(container: str) -> None:
    aoi_values = [0.0, 30.0, 60.0, 80.0]
    iam_values = [1.0, 0.98, 0.85, 0.4]
    if container == "tuple":
        aoi: object = tuple(aoi_values)
        iam: object = tuple(iam_values)
    elif container == "array":
        aoi = np.array(aoi_values)
        iam = np.array(iam_values)
    elif container == "series":
        aoi = pd.Series(aoi_values, name="measured_aoi")
        iam = pd.Series(iam_values, name="measured_iam")
    else:
        aoi = aoi_values.copy()
        iam = iam_values.copy()

    if isinstance(aoi, np.ndarray):
        before_aoi, before_iam = aoi.copy(), iam.copy()  # type: ignore[union-attr]
    elif isinstance(aoi, pd.Series):
        before_aoi, before_iam = aoi.copy(deep=True), iam.copy(deep=True)  # type: ignore[union-attr]
    elif isinstance(aoi, list):
        before_aoi, before_iam = aoi.copy(), iam.copy()  # type: ignore[union-attr]
    else:
        before_aoi, before_iam = aoi, iam

    resolve_beam_iam_parameters(
        model="ashrae",
        method="measured_fit",
        source_label="source",
        measured_aoi_deg=aoi,  # type: ignore[arg-type]
        measured_iam=iam,  # type: ignore[arg-type]
    )
    if isinstance(aoi, np.ndarray):
        np.testing.assert_array_equal(aoi, before_aoi)
        np.testing.assert_array_equal(iam, before_iam)
    elif isinstance(aoi, pd.Series):
        pdt.assert_series_equal(aoi, before_aoi)
        pdt.assert_series_equal(iam, before_iam)
    else:
        assert aoi == before_aoi
        assert iam == before_iam


def test_direct_parameter_mapping_is_not_mutated() -> None:
    parameters = {"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": None}
    before = parameters.copy()
    result = resolve_beam_iam_parameters(
        model="physical",
        method="direct",
        source_label="source",
        model_parameters=parameters,
    )
    assert parameters == before
    assert result["model_parameters"] is not parameters


def test_invalid_fitted_parameters_fail_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pvlib.iam, "fit", lambda *args, **kwargs: {"b": np.nan})
    with pytest.raises(ValueError, match="b must be a finite real number"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, 60.0],
            measured_iam=[1.0, 0.8],
        )


def test_invalid_fitted_parameter_schema_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pvlib.iam, "fit", lambda *args, **kwargs: {"a_r": 0.16})
    with pytest.raises(ValueError, match="returned invalid parameters"):
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, 60.0],
            measured_iam=[1.0, 0.8],
        )


def test_pvlib_fit_error_is_chained_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("optimizer failed")

    monkeypatch.setattr(pvlib.iam, "fit", fail)
    with pytest.raises(ValueError, match="pvlib IAM fitting failed") as exc_info:
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, 60.0],
            measured_iam=[1.0, 0.8],
        )
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_nonfinite_fitted_curve_fails_without_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pvlib.iam, "fit", lambda *args, **kwargs: {"n": 0.1, "K": 4, "L": 0.002}
    )
    with (
        pytest.warns(RuntimeWarning, match="invalid value"),
        pytest.raises(ValueError, match="curve contains non-finite"),
    ):
        resolve_beam_iam_parameters(
            model="physical",
            method="measured_fit",
            source_label="source",
            measured_aoi_deg=[0.0, 30.0],
            measured_iam=[1.0, 0.8],
        )
