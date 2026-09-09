"""Tests for horizontal irradiance component resolution."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib.irradiance
import pytest

from heliotelligence.physics.irradiance_components import (
    resolve_horizontal_irradiance_components,
)
from heliotelligence.physics.solar_geometry import calculate_solar_geometry

_COLUMNS = [
    "ghi_wm2",
    "dhi_wm2",
    "dni_wm2",
    "solar_zenith_deg",
    "direct_horizontal_wm2",
    "closure_residual_wm2",
    "irradiance_components_resolved",
    "decomposition_applied",
    "component_resolution_state",
    "decomposition_model",
    "ghi_provenance",
    "dhi_provenance",
    "dni_provenance",
]


def _index(*hours: int) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [f"2026-06-21 {hour:02d}:00" for hour in hours],
        tz="Europe/London",
        name="physical_time",
    )


def _series(values: list[object], index: pd.Index) -> pd.Series:
    return pd.Series(values, index=index)


def _resolve(
    ghi: list[object],
    dhi: list[object],
    dni: list[object],
    zenith: list[object],
    *,
    index: pd.Index | None = None,
) -> pd.DataFrame:
    actual_index = _index(*range(10, 10 + len(ghi))) if index is None else index
    return resolve_horizontal_irradiance_components(
        _series(ghi, actual_index),
        _series(dhi, actual_index),
        _series(dni, actual_index),
        _series(zenith, actual_index),
    )


def test_complete_supplied_triplet_is_preserved_without_decomposition() -> None:
    result = _resolve([800.0], [150.0], [700.0], [30.0])
    row = result.iloc[0]
    assert row["ghi_wm2"] == 800.0
    assert row["dhi_wm2"] == 150.0
    assert row["dni_wm2"] == 700.0
    assert row["irradiance_components_resolved"]
    assert not row["decomposition_applied"]
    assert row["component_resolution_state"] == "supplied_complete"
    assert row["decomposition_model"] == "not_applied"
    assert [row[name] for name in _COLUMNS[10:]] == ["supplied"] * 3


@pytest.mark.parametrize(
    ("ghi", "zenith"),
    [(0.0, 100.0), (200.0, 88.0), (500.0, 65.0), (900.0, 25.0)],
)
def test_ghi_only_matches_public_pvlib_erbs_exactly(ghi: float, zenith: float) -> None:
    index = _index(12)
    result = _resolve([ghi], [np.nan], [np.nan], [zenith], index=index)
    expected = pvlib.irradiance.erbs(
        pd.Series([ghi], index=index),
        pd.Series([zenith], index=index),
        index,
    )
    np.testing.assert_allclose(result["dhi_wm2"], expected["dhi"], rtol=0, atol=0)
    np.testing.assert_allclose(result["dni_wm2"], expected["dni"], rtol=0, atol=0)
    assert result.iloc[0]["ghi_wm2"] == ghi
    assert result.iloc[0]["component_resolution_state"] == "erbs_decomposed"
    assert result.iloc[0]["decomposition_model"] == "erbs"
    assert result.iloc[0]["ghi_provenance"] == "supplied"
    assert result.iloc[0]["dhi_provenance"] == "erbs_from_ghi"
    assert result.iloc[0]["dni_provenance"] == "erbs_from_ghi"


def test_r1a_true_zenith_composes_with_r1b_erbs() -> None:
    index = pd.DatetimeIndex(
        ["2026-06-21 04:30", "2026-06-21 12:00"],
        tz="Europe/London",
    )
    geometry = calculate_solar_geometry(
        index, latitude_deg=52.56, longitude_deg=1.21, altitude_m=47.0
    )
    ghi = pd.Series([25.0, 800.0], index=index)
    missing = pd.Series([np.nan, np.nan], index=index)
    result = resolve_horizontal_irradiance_components(
        ghi, missing, missing.copy(), geometry["solar_zenith_deg"]
    )
    expected = pvlib.irradiance.erbs(
        ghi, geometry["solar_zenith_deg"], index
    )
    np.testing.assert_allclose(result["dhi_wm2"], expected["dhi"], rtol=0, atol=0)
    np.testing.assert_allclose(result["dni_wm2"], expected["dni"], rtol=0, atol=0)
    assert not geometry["solar_zenith_deg"].equals(
        geometry["apparent_solar_zenith_deg"]
    )


@pytest.mark.parametrize(
    ("ghi", "dhi", "dni", "provenance"),
    [
        (500.0, 100.0, np.nan, ["supplied", "supplied", "missing"]),
        (500.0, np.nan, 600.0, ["supplied", "missing", "supplied"]),
        (np.nan, 100.0, 600.0, ["missing", "supplied", "supplied"]),
        (np.nan, 100.0, np.nan, ["missing", "supplied", "missing"]),
        (np.nan, np.nan, 600.0, ["missing", "missing", "supplied"]),
    ],
)
def test_partial_inputs_remain_unresolved_and_missing(
    ghi: float, dhi: float, dni: float, provenance: list[str]
) -> None:
    result = _resolve([ghi], [dhi], [dni], [40.0])
    row = result.iloc[0]
    assert not row["irradiance_components_resolved"]
    assert not row["decomposition_applied"]
    assert row["component_resolution_state"] == "unresolved_partial_input"
    assert row["decomposition_model"] == "not_applied"
    assert [row[name] for name in _COLUMNS[10:]] == provenance
    for supplied, name in zip((ghi, dhi, dni), _COLUMNS[:3], strict=True):
        assert pd.isna(row[name]) if pd.isna(supplied) else row[name] == supplied


def test_all_missing_is_distinct_and_not_zero_filled() -> None:
    result = _resolve([np.nan], [np.nan], [np.nan], [40.0])
    row = result.iloc[0]
    assert row["component_resolution_state"] == "unresolved_all_missing"
    assert not row["irradiance_components_resolved"]
    assert not row["decomposition_applied"]
    assert result[["ghi_wm2", "dhi_wm2", "dni_wm2"]].isna().all().all()
    assert pd.isna(row["direct_horizontal_wm2"])
    assert pd.isna(row["closure_residual_wm2"])
    assert [row[name] for name in _COLUMNS[10:]] == ["missing"] * 3


def test_direct_horizontal_uses_true_zenith_and_nonnegative_projection() -> None:
    result = _resolve(
        [800.0, 100.0], [150.0, 25.0], [700.0, 300.0], [30.0, 110.0]
    )
    assert result.iloc[0]["direct_horizontal_wm2"] == pytest.approx(
        700.0 * np.cos(np.deg2rad(30.0))
    )
    assert result.iloc[1]["dni_wm2"] == 300.0
    assert result.iloc[1]["direct_horizontal_wm2"] == 0.0


def test_closure_is_diagnostic_and_does_not_repair_supplied_values() -> None:
    result = _resolve([1000.0], [100.0], [100.0], [60.0])
    row = result.iloc[0]
    assert row["closure_residual_wm2"] == pytest.approx(850.0)
    assert [row[name] for name in _COLUMNS[:3]] == [1000.0, 100.0, 100.0]


def test_erbs_closure_uses_actual_reference_outputs() -> None:
    result = _resolve([650.0], [np.nan], [np.nan], [45.0])
    row = result.iloc[0]
    expected = row["ghi_wm2"] - (
        row["dhi_wm2"]
        + row["dni_wm2"] * max(np.cos(np.deg2rad(45.0)), 0.0)
    )
    assert row["closure_residual_wm2"] == pytest.approx(expected, abs=1e-12)


def test_mixed_series_resolves_each_row_independently_and_preserves_order() -> None:
    index = pd.DatetimeIndex(
        [
            "2026-06-21 12:07",
            "2026-06-21 01:00",
            "2026-06-21 10:03",
            "2026-06-21 09:11",
            "2026-06-21 08:29",
            "2026-06-21 03:00",
            "2026-06-21 04:00",
        ],
        tz="UTC",
        name="irregular_time",
    )
    result = _resolve(
        [800.0, 0.0, 500.0, np.nan, np.nan, 0.0, 100.0],
        [150.0, np.nan, 100.0, 100.0, np.nan, np.nan, np.nan],
        [700.0, np.nan, np.nan, 600.0, np.nan, np.nan, np.nan],
        [30.0, 100.0, 45.0, 50.0, 60.0, 105.0, 88.0],
        index=index,
    )
    assert result.index.equals(index)
    assert result["component_resolution_state"].tolist() == [
        "supplied_complete",
        "erbs_decomposed",
        "unresolved_partial_input",
        "unresolved_partial_input",
        "unresolved_all_missing",
        "erbs_decomposed",
        "erbs_decomposed",
    ]
    assert result["irradiance_components_resolved"].tolist() == [
        True,
        True,
        False,
        False,
        False,
        True,
        True,
    ]
    assert result.loc[index[2:4], "direct_horizontal_wm2"].isna().all()


@pytest.mark.parametrize("name", ["ghi", "dhi", "dni"])
@pytest.mark.parametrize("value", [-1.0, np.inf, -np.inf, True, "100"])
def test_invalid_present_irradiance_is_rejected(name: str, value: object) -> None:
    values: dict[str, list[object]] = {
        "ghi": [500.0],
        "dhi": [100.0],
        "dni": [600.0],
    }
    values[name] = [value]
    with pytest.raises(ValueError, match=f"{name}_wm2"):
        _resolve(values["ghi"], values["dhi"], values["dni"], [40.0])


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, True, "40", -0.1, 180.1])
def test_invalid_solar_zenith_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="solar_zenith_deg"):
        _resolve([500.0], [np.nan], [np.nan], [value])


@pytest.mark.parametrize("value", [0.0, 180.0])
def test_solar_zenith_boundaries_are_accepted(value: float) -> None:
    assert _resolve([500.0], [100.0], [600.0], [value]).iloc[0][
        "solar_zenith_deg"
    ] == value


@pytest.mark.parametrize("position", range(4))
def test_all_inputs_must_be_series(position: int) -> None:
    index = _index(12)
    inputs: list[object] = [pd.Series([1.0], index=index) for _ in range(4)]
    inputs[position] = [1.0]
    with pytest.raises(ValueError, match="pandas Series"):
        resolve_horizontal_irradiance_components(*inputs)  # type: ignore[arg-type]


def test_indexes_must_match_exactly() -> None:
    first = _index(10, 11)
    reversed_index = first[::-1]
    with pytest.raises(ValueError, match="indexes must match exactly"):
        resolve_horizontal_irradiance_components(
            pd.Series([1.0, 2.0], index=first),
            pd.Series([1.0, 2.0], index=reversed_index),
            pd.Series([1.0, 2.0], index=first),
            pd.Series([30.0, 40.0], index=first),
        )


@pytest.mark.parametrize(
    ("index", "message"),
    [
        (pd.RangeIndex(1), "DatetimeIndex"),
        (pd.DatetimeIndex(["2026-01-01"]), "timezone-aware"),
        (
            pd.DatetimeIndex(["2026-01-01", "2026-01-01"], tz="UTC"),
            "duplicate",
        ),
        (pd.DatetimeIndex([pd.NaT], tz="UTC"), "NaT"),
    ],
)
def test_invalid_index_contract_is_rejected(index: pd.Index, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _resolve(
            [1.0] * len(index),
            [1.0] * len(index),
            [1.0] * len(index),
            [1.0] * len(index),
            index=index,
        )


def test_empty_result_has_exact_schema_index_and_dtypes() -> None:
    index = pd.DatetimeIndex([], tz="Europe/London", name="physical_time")
    result = _resolve([], [], [], [], index=index)
    assert result.empty
    assert list(result.columns) == _COLUMNS
    assert result.index.equals(index)
    assert result.index.name == "physical_time"
    assert str(result.index.tz) == "Europe/London"
    for name in _COLUMNS[:6]:
        assert pd.api.types.is_float_dtype(result[name])
    for name in _COLUMNS[6:8]:
        assert pd.api.types.is_bool_dtype(result[name])
    for name in _COLUMNS[8:]:
        assert pd.api.types.is_string_dtype(result[name])


def test_inputs_are_not_mutated() -> None:
    index = _index(10, 11)
    inputs = [
        pd.Series([500.0, np.nan], index=index),
        pd.Series([np.nan, 100.0], index=index),
        pd.Series([np.nan, 600.0], index=index),
        pd.Series([40.0, 50.0], index=index),
    ]
    before = [value.copy(deep=True) for value in inputs]
    resolve_horizontal_irradiance_components(*inputs)
    for actual, expected in zip(inputs, before, strict=True):
        pd.testing.assert_series_equal(actual, expected)
