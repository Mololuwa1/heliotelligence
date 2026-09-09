"""Physics-contract tests for front-surface direct-beam IAM."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pvlib.iam
import pytest

from heliotelligence.physics.iam import calculate_beam_iam
from heliotelligence.physics.irradiance_components import (
    resolve_horizontal_irradiance_components,
)
from heliotelligence.physics.poa_transposition import (
    calculate_raw_poa_transposition,
)
from heliotelligence.physics.solar_geometry import calculate_solar_geometry

OUTPUT_COLUMNS = [
    "aoi_deg",
    "beam_iam_factor",
    "beam_iam_resolved",
    "beam_iam_state",
    "beam_iam_model",
]
AOIS = [0.0, 5.0, 30.0, 60.0, 85.0, 89.0, 90.0, 100.0, 180.0]


def _index(length: int = len(AOIS)) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [pd.Timestamp("2026-06-21 12:00", tz="Europe/London") + pd.Timedelta(minutes=i)
         for i in range(length)],
        name="physical_time",
    )


def _aoi(values: list[object] | None = None) -> pd.Series:
    values = AOIS if values is None else values
    return pd.Series(values, index=_index(len(values)), name="source_aoi")


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        (
            {"n": 1.526, "K": 4.0, "L": 0.002, "n_ar": None},
            lambda aoi: pvlib.iam.physical(
                aoi, n=1.526, K=4.0, L=0.002, n_ar=None
            ),
        ),
        (
            {"n": 1.52, "K": 3.5, "L": 0.003, "n_ar": 1.29},
            lambda aoi: pvlib.iam.physical(
                aoi, n=1.52, K=3.5, L=0.003, n_ar=1.29
            ),
        ),
    ],
)
def test_physical_matches_public_pvlib_with_explicit_parameters(
    parameters: dict[str, object], expected: object
) -> None:
    aoi = _aoi()
    result = calculate_beam_iam(aoi, model="physical", model_parameters=parameters)
    reference = expected(aoi)  # type: ignore[operator]

    pdt.assert_series_equal(
        result["beam_iam_factor"], reference, check_names=False, check_exact=True
    )
    assert result["beam_iam_model"].tolist() == ["physical"] * len(aoi)


@pytest.mark.parametrize("a_r", [0.08, 0.22])
def test_martin_ruiz_matches_public_pvlib(a_r: float) -> None:
    aoi = _aoi()
    result = calculate_beam_iam(
        aoi, model="martin-ruiz", model_parameters={"a_r": a_r}
    )
    expected = pvlib.iam.martin_ruiz(aoi, a_r=a_r)
    pdt.assert_series_equal(
        result["beam_iam_factor"], expected, check_names=False, check_exact=True
    )


@pytest.mark.parametrize("b", [0.0, 0.07])
def test_ashrae_matches_public_pvlib(b: float) -> None:
    aoi = _aoi()
    result = calculate_beam_iam(aoi, model="ashrae", model_parameters={"b": b})
    expected = pvlib.iam.ashrae(aoi, b=b)
    pdt.assert_series_equal(
        result["beam_iam_factor"], expected, check_names=False, check_exact=True
    )


@pytest.mark.parametrize(
    ("model", "parameters"),
    [
        ("physical", {"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": None}),
        ("martin-ruiz", {"a_r": 0.16}),
        ("ashrae", {"b": 0.05}),
    ],
)
def test_resolution_state_reflects_reference_output(
    model: str, parameters: dict[str, object]
) -> None:
    result = calculate_beam_iam(
        _aoi(), model=model, model_parameters=parameters  # type: ignore[arg-type]
    )
    finite = np.isfinite(result["beam_iam_factor"])
    pdt.assert_series_equal(result["beam_iam_resolved"], finite, check_names=False)
    assert result.loc[finite, "beam_iam_state"].eq("resolved").all()
    assert result.loc[~finite, "beam_iam_state"].eq(
        "model_output_unresolved"
    ).all()


def test_nonfinite_physical_output_is_preserved_and_reported_unresolved() -> None:
    aoi = _aoi([0.0, 30.0])
    parameters = {"n": 0.1, "K": 4.0, "L": 0.002, "n_ar": None}
    with pytest.warns(RuntimeWarning, match="invalid value"):
        expected = pvlib.iam.physical(aoi, **parameters)
    with pytest.warns(RuntimeWarning, match="invalid value"):
        result = calculate_beam_iam(
            aoi, model="physical", model_parameters=parameters
        )

    pdt.assert_series_equal(
        result["beam_iam_factor"], expected, check_names=False, check_exact=True
    )
    assert result["beam_iam_resolved"].tolist() == [True, False]
    assert result["beam_iam_state"].tolist() == [
        "resolved",
        "model_output_unresolved",
    ]


def test_model_and_parameter_mapping_are_required() -> None:
    signature = inspect.signature(calculate_beam_iam)
    assert signature.parameters["model"].default is inspect.Parameter.empty
    assert signature.parameters["model_parameters"].default is inspect.Parameter.empty


@pytest.mark.parametrize("model", ["", "sapm", "Physical", None])
def test_invalid_model_is_rejected(model: object) -> None:
    with pytest.raises(ValueError, match="model must"):
        calculate_beam_iam(
            _aoi([30.0]), model=model, model_parameters={}  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("parameters", [None, 1, "n=1.5", [("n", 1.5)]])
def test_parameter_mapping_type_is_required(parameters: object) -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        calculate_beam_iam(
            _aoi([30.0]), model="ashrae", model_parameters=parameters  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("model", "parameters"),
    [
        ("physical", {"n": 1.5, "K": 4.0, "L": 0.002}),
        ("physical", {"n": 1.5, "K": 4.0, "L": 0.002, "n_ar": None, "b": 0.05}),
        ("martin-ruiz", {}),
        ("martin-ruiz", {"a_r": 0.16, "b": 0.05}),
        ("ashrae", {}),
        ("ashrae", {"a_r": 0.16}),
    ],
)
def test_parameter_keys_must_match_selected_model_exactly(
    model: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="must contain exactly"):
        calculate_beam_iam(
            _aoi([30.0]), model=model, model_parameters=parameters  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("bad", [True, "1.5", np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("key", ["n", "K", "L"])
def test_physical_rejects_non_numeric_or_nonfinite_parameters(
    key: str, bad: object
) -> None:
    parameters: dict[str, object] = {
        "n": 1.52,
        "K": 4.0,
        "L": 0.002,
        "n_ar": None,
    }
    parameters[key] = bad
    with pytest.raises(ValueError, match=key):
        calculate_beam_iam(_aoi([30.0]), model="physical", model_parameters=parameters)


@pytest.mark.parametrize(
    ("key", "value"), [("n", 0.0), ("n", -1.0), ("K", -1.0), ("L", -0.1)]
)
def test_physical_parameter_bounds(key: str, value: float) -> None:
    parameters: dict[str, object] = {
        "n": 1.52,
        "K": 4.0,
        "L": 0.002,
        "n_ar": None,
    }
    parameters[key] = value
    with pytest.raises(ValueError, match=key):
        calculate_beam_iam(_aoi([30.0]), model="physical", model_parameters=parameters)


@pytest.mark.parametrize("n_ar", [0.0, -1.0, True, "1.29", np.nan, np.inf])
def test_physical_n_ar_is_none_or_finite_positive(n_ar: object) -> None:
    with pytest.raises(ValueError, match="n_ar"):
        calculate_beam_iam(
            _aoi([30.0]),
            model="physical",
            model_parameters={"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": n_ar},
        )


@pytest.mark.parametrize(
    ("model", "key", "bad"),
    [
        ("martin-ruiz", "a_r", 0.0),
        ("martin-ruiz", "a_r", -0.1),
        ("martin-ruiz", "a_r", None),
        ("martin-ruiz", "a_r", True),
        ("martin-ruiz", "a_r", np.nan),
        ("ashrae", "b", -0.1),
        ("ashrae", "b", None),
        ("ashrae", "b", False),
        ("ashrae", "b", np.inf),
    ],
)
def test_empirical_parameter_validation(model: str, key: str, bad: object) -> None:
    with pytest.raises(ValueError, match=key):
        calculate_beam_iam(
            _aoi([30.0]),
            model=model,  # type: ignore[arg-type]
            model_parameters={key: bad},
        )


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, True, "30", None, -0.1, 180.1])
def test_invalid_aoi_is_rejected(bad: object) -> None:
    with pytest.raises(ValueError, match="aoi_deg"):
        calculate_beam_iam(_aoi([bad]), model="ashrae", model_parameters={"b": 0.05})


def test_non_series_aoi_is_rejected() -> None:
    with pytest.raises(ValueError, match="pandas Series"):
        calculate_beam_iam(  # type: ignore[arg-type]
            [30.0], model="ashrae", model_parameters={"b": 0.05}
        )


@pytest.mark.parametrize(
    ("index", "message"),
    [
        (pd.Index([1]), "DatetimeIndex"),
        (pd.DatetimeIndex(["2026-01-01"]), "timezone-aware"),
        (pd.DatetimeIndex([pd.NaT], tz="UTC"), "NaT"),
        (
            pd.DatetimeIndex(["2026-01-01", "2026-01-01"], tz="UTC"),
            "duplicate",
        ),
    ],
)
def test_index_contract_is_enforced(index: pd.Index, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_beam_iam(
            pd.Series([30.0] * len(index), index=index),
            model="ashrae",
            model_parameters={"b": 0.05},
        )


def test_irregular_unsorted_index_is_preserved_exactly() -> None:
    index = pd.DatetimeIndex(
        ["2026-06-21 12:17", "2026-06-21 08:03", "2026-06-21 16:41"],
        tz="UTC",
        name="physical_time",
    )
    result = calculate_beam_iam(
        pd.Series([30.0, 60.0, 89.0], index=index),
        model="martin-ruiz",
        model_parameters={"a_r": 0.16},
    )
    pdt.assert_index_equal(result.index, index, exact=True)
    assert result.index.tz == index.tz
    assert result.index.name == "physical_time"


def test_empty_result_has_stable_schema_and_dtypes() -> None:
    index = pd.DatetimeIndex([], tz="Europe/London", name="physical_time")
    result = calculate_beam_iam(
        pd.Series(index=index, dtype=float),
        model="physical",
        model_parameters={"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": None},
    )
    assert list(result.columns) == OUTPUT_COLUMNS
    pdt.assert_index_equal(result.index, index, exact=True)
    assert result["aoi_deg"].dtype == float
    assert result["beam_iam_factor"].dtype == float
    assert result["beam_iam_resolved"].dtype == bool
    assert pd.api.types.is_string_dtype(result["beam_iam_state"].dtype)
    assert pd.api.types.is_string_dtype(result["beam_iam_model"].dtype)


def test_inputs_are_not_mutated() -> None:
    aoi = _aoi([10.0, 70.0])
    parameters = {"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": 1.29}
    original_aoi = aoi.copy(deep=True)
    original_parameters = parameters.copy()
    calculate_beam_iam(aoi, model="physical", model_parameters=parameters)
    pdt.assert_series_equal(aoi, original_aoi)
    assert parameters == original_parameters


def test_r1a_r1b_r2_r3a_composition_uses_r2_aoi_only() -> None:
    index = pd.DatetimeIndex(
        ["2026-06-21 12:00"], tz="Europe/London", name="physical_time"
    )
    geometry = calculate_solar_geometry(
        index, latitude_deg=52.5, longitude_deg=-1.2, altitude_m=100.0
    )
    missing = pd.Series(np.nan, index=index)
    r1b = resolve_horizontal_irradiance_components(
        pd.Series([800.0], index=index),
        missing.copy(),
        missing.copy(),
        geometry["solar_zenith_deg"],
    )
    r2 = calculate_raw_poa_transposition(
        r1b["ghi_wm2"],
        r1b["dhi_wm2"],
        r1b["dni_wm2"],
        geometry["apparent_solar_zenith_deg"],
        geometry["solar_azimuth_deg"],
        surface_tilt_deg=30.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model="perez-driesse",
    )
    parameters = {"n": 1.52, "K": 4.0, "L": 0.002, "n_ar": 1.29}
    r3a = calculate_beam_iam(
        r2["aoi_deg"], model="physical", model_parameters=parameters
    )
    expected = pvlib.iam.physical(r2["aoi_deg"], **parameters)
    pdt.assert_series_equal(
        r3a["beam_iam_factor"], expected, check_names=False, check_exact=True
    )
    expected_transmitted_beam = (
        r2["poa_direct_raw_wm2"] * r3a["beam_iam_factor"]
    )
    pdt.assert_series_equal(
        expected_transmitted_beam,
        r2["poa_direct_raw_wm2"] * expected,
        check_names=False,
        check_exact=True,
    )
    assert list(r3a.columns) == OUTPUT_COLUMNS


def test_iam_resolution_is_independent_of_r2_poa_output_resolution() -> None:
    index = _index(1)
    zero = pd.Series([0.0], index=index)
    r2 = calculate_raw_poa_transposition(
        zero.copy(),
        zero.copy(),
        zero.copy(),
        pd.Series([30.0], index=index),
        pd.Series([180.0], index=index),
        surface_tilt_deg=30.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model="perez",
    )
    assert not bool(r2.iloc[0]["poa_transposition_resolved"])
    result = calculate_beam_iam(
        r2["aoi_deg"], model="ashrae", model_parameters={"b": 0.05}
    )
    assert bool(result.iloc[0]["beam_iam_resolved"])
    assert result.iloc[0]["beam_iam_state"] == "resolved"
