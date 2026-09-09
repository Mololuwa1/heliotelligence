"""Physics-contract tests for raw front-side POA transposition."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pvlib.irradiance
import pytest

from heliotelligence.physics.irradiance_components import (
    resolve_horizontal_irradiance_components,
)
from heliotelligence.physics.poa_transposition import (
    calculate_raw_poa_transposition,
)
from heliotelligence.physics.solar_geometry import calculate_solar_geometry

OUTPUT_COLUMNS = [
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "apparent_solar_zenith_deg",
    "solar_azimuth_deg",
    "dni_extra_wm2",
    "aoi_deg",
    "poa_direct_raw_wm2",
    "poa_sky_diffuse_raw_wm2",
    "poa_ground_diffuse_raw_wm2",
    "poa_diffuse_raw_wm2",
    "poa_global_raw_wm2",
    "poa_transposition_resolved",
    "transposition_applied",
    "transposition_state",
    "transposition_model",
]


def _index(*hours: int) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [f"2026-06-21 {hour:02d}:00" for hour in hours],
        tz="Europe/London",
        name="physical_time",
    )


def _inputs(
    index: pd.DatetimeIndex | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    index = _index(6, 12, 23) if index is None else index
    return (
        pd.Series([120.0, 800.0, 20.0][: len(index)], index=index),
        pd.Series([70.0, 140.0, 15.0][: len(index)], index=index),
        pd.Series([300.0, 750.0, 25.0][: len(index)], index=index),
        pd.Series([78.0, 30.0, 105.0][: len(index)], index=index),
        pd.Series([80.0, 180.0, 320.0][: len(index)], index=index),
    )


def _calculate(
    inputs: tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series] | None = None,
    *,
    model: str = "perez",
) -> pd.DataFrame:
    values = _inputs() if inputs is None else inputs
    return calculate_raw_poa_transposition(
        *values,
        surface_tilt_deg=30.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model=model,  # type: ignore[arg-type]
    )


def _reference(
    inputs: tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series],
    model: str,
) -> pd.DataFrame:
    ghi, dhi, dni, zenith, azimuth = inputs
    dni_extra = pvlib.irradiance.get_extra_radiation(ghi.index)
    return pvlib.irradiance.get_total_irradiance(
        surface_tilt=30.0,
        surface_azimuth=180.0,
        solar_zenith=zenith,
        solar_azimuth=azimuth,
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        dni_extra=dni_extra,
        albedo=0.2,
        model=model,
        model_perez="allsitescomposite1990",
    )


@pytest.mark.parametrize("model", ["perez", "perez-driesse"])
def test_raw_components_match_public_pvlib_exactly(model: str) -> None:
    inputs = _inputs()
    result = _calculate(inputs, model=model)
    expected = _reference(inputs, model)

    mappings = {
        "poa_direct_raw_wm2": "poa_direct",
        "poa_sky_diffuse_raw_wm2": "poa_sky_diffuse",
        "poa_ground_diffuse_raw_wm2": "poa_ground_diffuse",
        "poa_diffuse_raw_wm2": "poa_diffuse",
        "poa_global_raw_wm2": "poa_global",
    }
    for output, reference in mappings.items():
        pdt.assert_series_equal(
            result[output], expected[reference], check_names=False, rtol=1e-12, atol=1e-12
        )
    assert result["transposition_model"].tolist() == [model] * len(result)


def test_aoi_and_dni_extra_match_public_pvlib() -> None:
    inputs = _inputs()
    result = _calculate(inputs)
    expected_aoi = pvlib.irradiance.aoi(30.0, 180.0, inputs[3], inputs[4])
    expected_extra = pvlib.irradiance.get_extra_radiation(inputs[0].index)
    np.testing.assert_allclose(result["aoi_deg"], expected_aoi, rtol=0, atol=1e-12)
    pdt.assert_series_equal(
        result["dni_extra_wm2"], expected_extra, check_names=False, rtol=0, atol=0
    )


def test_poa_component_identities_hold_without_repair() -> None:
    result = _calculate(model="perez-driesse")
    np.testing.assert_allclose(
        result["poa_diffuse_raw_wm2"],
        result["poa_sky_diffuse_raw_wm2"]
        + result["poa_ground_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        result["poa_global_raw_wm2"],
        result["poa_direct_raw_wm2"] + result["poa_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )


def _zero_triplet_inputs(
    index: pd.DatetimeIndex | None = None,
    *,
    zenith: pd.Series | None = None,
    azimuth: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    index = _index(12) if index is None else index
    zeros = pd.Series(0.0, index=index)
    return (
        zeros.copy(),
        zeros.copy(),
        zeros.copy(),
        pd.Series(30.0, index=index) if zenith is None else zenith,
        pd.Series(180.0, index=index) if azimuth is None else azimuth,
    )


@pytest.mark.parametrize(
    ("model", "expected_resolved", "expected_state"),
    [
        ("perez", False, "model_output_unresolved"),
        ("perez-driesse", True, "transposed"),
    ],
)
def test_zero_triplet_preserves_model_outputs_and_reports_resolution_truthfully(
    model: str,
    expected_resolved: bool,
    expected_state: str,
) -> None:
    inputs = _zero_triplet_inputs()
    result = _calculate(inputs, model=model)
    expected = _reference(inputs, model)

    mappings = {
        "poa_direct_raw_wm2": "poa_direct",
        "poa_sky_diffuse_raw_wm2": "poa_sky_diffuse",
        "poa_ground_diffuse_raw_wm2": "poa_ground_diffuse",
        "poa_diffuse_raw_wm2": "poa_diffuse",
        "poa_global_raw_wm2": "poa_global",
    }
    for output, reference in mappings.items():
        pdt.assert_series_equal(
            result[output], expected[reference], check_names=False, check_exact=True
        )

    row = result.iloc[0]
    assert bool(row["transposition_applied"])
    assert bool(row["poa_transposition_resolved"]) is expected_resolved
    assert row["transposition_state"] == expected_state
    assert row["transposition_model"] == model
    if model == "perez":
        assert row["poa_direct_raw_wm2"] == 0.0
        assert row["poa_ground_diffuse_raw_wm2"] == 0.0
        assert pd.isna(row["poa_sky_diffuse_raw_wm2"])
        assert pd.isna(row["poa_diffuse_raw_wm2"])
        assert pd.isna(row["poa_global_raw_wm2"])
    else:
        raw_poa = row[list(mappings)].to_numpy(dtype=float)
        assert np.isfinite(raw_poa).all()
        assert (raw_poa == 0.0).all()


def test_staged_zero_ghi_preserves_perez_model_output_resolution_distinction() -> None:
    index = pd.DatetimeIndex(
        ["2026-06-21 04:45"], tz="Europe/London", name="physical_time"
    )
    geometry = calculate_solar_geometry(
        index, latitude_deg=52.5, longitude_deg=-1.2, altitude_m=100.0
    )
    assert geometry.iloc[0]["solar_zenith_deg"] >= 90.0
    assert geometry.iloc[0]["apparent_solar_zenith_deg"] < 90.0

    missing = pd.Series(np.nan, index=index)
    r1b = resolve_horizontal_irradiance_components(
        pd.Series(0.0, index=index),
        missing.copy(),
        missing.copy(),
        geometry["solar_zenith_deg"],
    )
    assert r1b.iloc[0]["component_resolution_state"] == "erbs_decomposed"
    assert bool(r1b.iloc[0]["irradiance_components_resolved"])
    assert r1b.iloc[0][["ghi_wm2", "dhi_wm2", "dni_wm2"]].tolist() == [
        0.0,
        0.0,
        0.0,
    ]

    inputs = (
        r1b["ghi_wm2"],
        r1b["dhi_wm2"],
        r1b["dni_wm2"],
        geometry["apparent_solar_zenith_deg"],
        geometry["solar_azimuth_deg"],
    )
    for model, expected_resolved, expected_state in (
        ("perez", False, "model_output_unresolved"),
        ("perez-driesse", True, "transposed"),
    ):
        result = _calculate(inputs, model=model)
        expected = _reference(inputs, model)
        pdt.assert_series_equal(
            result["poa_global_raw_wm2"],
            expected["poa_global"],
            check_names=False,
            check_exact=True,
        )
        assert bool(result.iloc[0]["transposition_applied"])
        assert bool(result.iloc[0]["poa_transposition_resolved"]) is expected_resolved
        assert result.iloc[0]["transposition_state"] == expected_state
        assert result.iloc[0]["transposition_model"] == model


def test_mixed_input_and_model_resolution_states_are_row_independent() -> None:
    index = _index(12, 13, 14)
    inputs = (
        pd.Series([800.0, np.nan, 0.0], index=index),
        pd.Series([140.0, 100.0, 0.0], index=index),
        pd.Series([750.0, 400.0, 0.0], index=index),
        pd.Series([30.0, 40.0, 30.0], index=index),
        pd.Series([180.0, 190.0, 180.0], index=index),
    )
    result = _calculate(inputs, model="perez")

    assert result.index.equals(index)
    assert result["transposition_state"].tolist() == [
        "transposed",
        "unresolved_irradiance",
        "model_output_unresolved",
    ]
    assert result["transposition_applied"].tolist() == [True, False, True]
    assert result["poa_transposition_resolved"].tolist() == [True, False, False]
    assert result["transposition_model"].tolist() == [
        "perez",
        "not_applied",
        "perez",
    ]
    assert result.iloc[1, 7:12].isna().all()
    assert pd.isna(result.iloc[2]["poa_global_raw_wm2"])


@pytest.mark.parametrize("model", ["perez", "perez-driesse"])
def test_night_horizon_and_sun_behind_plane_preserve_pvlib(model: str) -> None:
    index = _index(5, 6, 23)
    inputs = (
        pd.Series([10.0, 100.0, 20.0], index=index),
        pd.Series([8.0, 60.0, 15.0], index=index),
        pd.Series([40.0, 250.0, 30.0], index=index),
        pd.Series([100.0, 89.0, 105.0], index=index),
        pd.Series([180.0, 70.0, 180.0], index=index),
    )
    result = _calculate(inputs, model=model)
    expected = _reference(inputs, model)
    for output, reference in {
        "poa_direct_raw_wm2": "poa_direct",
        "poa_sky_diffuse_raw_wm2": "poa_sky_diffuse",
        "poa_global_raw_wm2": "poa_global",
    }.items():
        np.testing.assert_allclose(
            result[output], expected[reference], rtol=1e-12, atol=1e-12, equal_nan=True
        )
    pdt.assert_series_equal(
        result["dni_wm2"], inputs[2], check_dtype=False, check_names=False
    )


@pytest.mark.parametrize("model", ["perez", "perez-driesse"])
def test_r1a_r1b_r2_composition_uses_apparent_zenith(model: str) -> None:
    index = pd.DatetimeIndex(
        ["2026-06-21 04:00", "2026-06-21 12:00"],
        tz="Europe/London",
        name="physical_time",
    )
    geometry = calculate_solar_geometry(
        index, latitude_deg=52.5, longitude_deg=-1.2, altitude_m=100.0
    )
    r1b = resolve_horizontal_irradiance_components(
        pd.Series([30.0, 800.0], index=index),
        pd.Series([np.nan, np.nan], index=index),
        pd.Series([np.nan, np.nan], index=index),
        geometry["solar_zenith_deg"],
    )
    inputs = (
        r1b["ghi_wm2"],
        r1b["dhi_wm2"],
        r1b["dni_wm2"],
        geometry["apparent_solar_zenith_deg"],
        geometry["solar_azimuth_deg"],
    )
    result = _calculate(inputs, model=model)
    expected = _reference(inputs, model)
    assert not geometry["solar_zenith_deg"].equals(
        geometry["apparent_solar_zenith_deg"]
    )
    np.testing.assert_allclose(
        result["poa_global_raw_wm2"],
        expected["poa_global"],
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )


@pytest.mark.parametrize("missing_position", [0, 1, 2])
def test_incomplete_irradiance_remains_unresolved_without_zero_fill(
    missing_position: int,
) -> None:
    inputs = list(_inputs(_index(12)))
    inputs[missing_position] = pd.Series([np.nan], index=inputs[0].index)
    result = _calculate(tuple(inputs))  # type: ignore[arg-type]
    assert not result.loc[result.index[0], "poa_transposition_resolved"]
    assert not result.loc[result.index[0], "transposition_applied"]
    assert result.loc[result.index[0], "transposition_state"] == "unresolved_irradiance"
    assert result.loc[result.index[0], "transposition_model"] == "not_applied"
    assert pd.isna(result.iloc[0, missing_position])
    assert result.iloc[0, 7:12].isna().all()
    assert np.isfinite(result.loc[result.index[0], "dni_extra_wm2"])
    assert np.isfinite(result.loc[result.index[0], "aoi_deg"])


def test_mixed_rows_preserve_index_and_resolve_independently() -> None:
    index = pd.DatetimeIndex(
        ["2026-06-21 12:17", "2026-06-21 08:03", "2026-06-21 16:41", "2026-06-21 10:22"],
        tz="UTC",
        name="physical_time",
    )
    inputs = (
        pd.Series([800.0, np.nan, 500.0, 600.0], index=index),
        pd.Series([140.0, 90.0, np.nan, 120.0], index=index),
        pd.Series([750.0, 400.0, 500.0, np.nan], index=index),
        pd.Series([30.0, 60.0, 45.0, 50.0], index=index),
        pd.Series([180.0, 100.0, 220.0, 150.0], index=index),
    )
    result = _calculate(inputs, model="perez-driesse")
    assert result.index.equals(index)
    assert result.index.name == index.name
    assert result["poa_transposition_resolved"].tolist() == [True, False, False, False]
    assert result.loc[index[1:], "poa_global_raw_wm2"].isna().all()
    expected = _reference(tuple(value.iloc[[0]] for value in inputs), "perez-driesse")
    assert result.loc[index[0], "poa_global_raw_wm2"] == pytest.approx(
        expected.iloc[0]["poa_global"], rel=1e-12, abs=1e-12
    )


def test_model_and_albedo_are_required_keyword_arguments() -> None:
    signature = inspect.signature(calculate_raw_poa_transposition)
    assert signature.parameters["model"].default is inspect.Parameter.empty
    assert signature.parameters["albedo"].default is inspect.Parameter.empty


@pytest.mark.parametrize("model", ["isotropic", "Perez", "", None, True])
def test_invalid_model_is_rejected(model: object) -> None:
    with pytest.raises(ValueError, match="model"):
        _calculate(model=model)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("surface_tilt_deg", -0.1),
        ("surface_tilt_deg", 180.1),
        ("surface_tilt_deg", np.inf),
        ("surface_tilt_deg", True),
        ("surface_tilt_deg", "30"),
        ("surface_azimuth_deg", -0.1),
        ("surface_azimuth_deg", 360.1),
        ("surface_azimuth_deg", np.nan),
        ("surface_azimuth_deg", False),
        ("albedo", -0.01),
        ("albedo", 1.01),
        ("albedo", np.inf),
        ("albedo", True),
    ],
)
def test_invalid_scalar_inputs_are_rejected(name: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "surface_tilt_deg": 30.0,
        "surface_azimuth_deg": 180.0,
        "albedo": 0.2,
        "model": "perez",
    }
    kwargs[name] = value
    with pytest.raises(ValueError, match=name):
        calculate_raw_poa_transposition(*_inputs(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tilt", "azimuth", "albedo"),
    [(0.0, 0.0, 0.0), (180.0, 360.0, 1.0)],
)
def test_scalar_boundaries_are_accepted(
    tilt: float, azimuth: float, albedo: float
) -> None:
    calculate_raw_poa_transposition(
        *_inputs(),
        surface_tilt_deg=tilt,
        surface_azimuth_deg=azimuth,
        albedo=albedo,
        model="perez-driesse",
    )


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("value", [-1.0, np.inf, -np.inf, True, 1 + 2j])
def test_invalid_present_irradiance_is_rejected(position: int, value: object) -> None:
    inputs = list(_inputs(_index(12)))
    inputs[position] = pd.Series([value], index=inputs[0].index, dtype=object)
    with pytest.raises(ValueError):
        _calculate(tuple(inputs))  # type: ignore[arg-type]


@pytest.mark.parametrize("position", [3, 4])
@pytest.mark.parametrize("value", [np.nan, pd.NA, np.inf, -np.inf, True, 1 + 2j])
def test_invalid_geometry_values_are_rejected(position: int, value: object) -> None:
    inputs = list(_inputs(_index(12)))
    inputs[position] = pd.Series([value], index=inputs[0].index, dtype=object)
    with pytest.raises(ValueError):
        _calculate(tuple(inputs))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("position", "value"), [(3, -0.1), (3, 180.1), (4, -0.1), (4, 360.1)]
)
def test_geometry_ranges_are_enforced(position: int, value: float) -> None:
    inputs = list(_inputs(_index(12)))
    inputs[position] = pd.Series([value], index=inputs[0].index)
    with pytest.raises(ValueError, match="between"):
        _calculate(tuple(inputs))  # type: ignore[arg-type]


def test_geometry_boundaries_are_accepted() -> None:
    index = _index(12, 13)
    inputs = (
        pd.Series([0.0, 0.0], index=index),
        pd.Series([0.0, 0.0], index=index),
        pd.Series([0.0, 0.0], index=index),
        pd.Series([0.0, 180.0], index=index),
        pd.Series([0.0, 360.0], index=index),
    )
    _calculate(inputs, model="perez-driesse")


@pytest.mark.parametrize("position", range(5))
def test_all_inputs_must_be_series(position: int) -> None:
    inputs = list(_inputs(_index(12)))
    inputs[position] = [1.0]  # type: ignore[assignment]
    with pytest.raises(ValueError, match="pandas Series"):
        _calculate(tuple(inputs))  # type: ignore[arg-type]


@pytest.mark.parametrize("position", range(1, 5))
def test_each_secondary_index_must_be_datetime_index(position: int) -> None:
    canonical = _index(12)
    generic = pd.Index([canonical[0]], dtype=object, name=canonical.name)
    inputs = list(_inputs(canonical))
    inputs[position] = pd.Series([inputs[position].iloc[0]], index=generic)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        _calculate(tuple(inputs))  # type: ignore[arg-type]


@pytest.mark.parametrize("position", range(1, 5))
def test_each_secondary_index_name_must_match(position: int) -> None:
    inputs = list(_inputs(_index(12)))
    inputs[position] = inputs[position].rename_axis("different_name")
    with pytest.raises(ValueError, match="names must match"):
        _calculate(tuple(inputs))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("index", "message"),
    [
        (pd.RangeIndex(1), "DatetimeIndex"),
        (pd.DatetimeIndex(["2026-01-01"]), "timezone-aware"),
        (pd.DatetimeIndex([pd.NaT], tz="UTC"), "NaT"),
        (
            pd.DatetimeIndex(["2026-01-01", "2026-01-01"], tz="UTC"),
            "duplicate",
        ),
    ],
)
def test_every_input_index_is_validated(index: pd.Index, message: str) -> None:
    for position in range(5):
        canonical = pd.date_range("2026-01-01", periods=len(index), freq="h", tz="UTC")
        inputs = list(_inputs(canonical))
        inputs[position] = pd.Series([1.0] * len(index), index=index)
        with pytest.raises(ValueError, match=message):
            _calculate(tuple(inputs))  # type: ignore[arg-type]


def test_indexes_must_match_exact_timestamps_order_and_timezone() -> None:
    canonical = _index(12, 13)
    variants = [
        canonical[::-1],
        canonical + pd.Timedelta(minutes=1),
        canonical.tz_convert("UTC"),
    ]
    for variant in variants:
        inputs = list(_inputs(canonical))
        inputs[1] = pd.Series(inputs[1].to_numpy(), index=variant)
        with pytest.raises(ValueError, match="indexes must match"):
            _calculate(tuple(inputs))  # type: ignore[arg-type]


def test_matching_indexes_do_not_require_matching_frequency_metadata() -> None:
    with_frequency = pd.date_range(
        "2026-06-21 10:00", periods=3, freq="h", tz="UTC", name="physical_time"
    )
    without_frequency = pd.DatetimeIndex(
        list(with_frequency), tz="UTC", name="physical_time"
    )
    inputs = _inputs(with_frequency)
    mixed = (
        inputs[0],
        *(
            pd.Series(value.to_numpy(), index=without_frequency)
            for value in inputs[1:]
        ),
    )
    result = _calculate(mixed)  # type: ignore[arg-type]
    assert result.index.equals(with_frequency)
    assert result.index.freq == with_frequency.freq


def test_empty_result_has_exact_schema_index_and_dtypes() -> None:
    index = pd.DatetimeIndex([], tz="Europe/London", name="physical_time")
    empty = tuple(pd.Series(index=index, dtype=float) for _ in range(5))
    result = _calculate(empty)  # type: ignore[arg-type]
    assert list(result.columns) == OUTPUT_COLUMNS
    assert result.index.equals(index)
    assert result.index.name == "physical_time"
    assert result.index.tz == index.tz
    for column in OUTPUT_COLUMNS[:12]:
        assert result[column].dtype == float
    for column in OUTPUT_COLUMNS[12:14]:
        assert result[column].dtype == bool
    for column in OUTPUT_COLUMNS[14:]:
        assert pd.api.types.is_string_dtype(result[column].dtype)


def test_all_inputs_are_immutable() -> None:
    inputs = _inputs()
    originals = tuple(value.copy(deep=True) for value in inputs)
    indexes = tuple(value.index.copy(deep=True) for value in inputs)
    _calculate(inputs, model="perez-driesse")
    for value, original, index in zip(inputs, originals, indexes, strict=True):
        pdt.assert_series_equal(value, original)
        assert value.index.equals(index)
        assert value.index.name == index.name
