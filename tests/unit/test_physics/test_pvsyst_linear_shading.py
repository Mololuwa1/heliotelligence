"""Tests for canonical PVsyst linear beam-shading interpolation."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics.pvsyst_linear_shading import (
    PVSYST_LINEAR_SHADING_CONTRACT_ID,
    PVSYST_LINEAR_SHADING_COVERAGE_SCOPE,
    PVSYST_LINEAR_SHADING_MODEL_ID,
    PVSYST_LINEAR_SHADING_SCOPE,
    PVsystLinearShadingResult,
    PVsystLinearShadingTable,
    convert_pvlib_azimuth_to_pvsyst,
    evaluate_pvsyst_linear_beam_shading,
)


def _table(
    *,
    semantics: str = "transmission_fraction",
    values: tuple[tuple[float, ...], ...] = (
        (0.2, 0.4, 0.6, 0.4, 0.2),
        (0.4, 0.6, 0.8, 0.6, 0.4),
        (0.6, 0.8, 1.0, 0.8, 0.6),
    ),
    heights: tuple[float, ...] = (10.0, 30.0, 50.0),
    azimuths: tuple[float, ...] = (-180.0, -90.0, 0.0, 90.0, 180.0),
) -> PVsystLinearShadingTable:
    return PVsystLinearShadingTable(
        table_id="near-shading-1",
        orientation_id="orientation-1",
        zone_id="zone-a",
        sun_height_deg=heights,
        pvsyst_solar_azimuth_deg=azimuths,
        values=values,
        value_semantics=semantics,  # type: ignore[arg-type]
        source_label="PVsyst normalized export",
        source_reference="project/file",
        pvsyst_version="8.0",
    )


def _series(
    elevations: tuple[float, ...], azimuths: tuple[float, ...]
) -> tuple[pd.Series, pd.Series]:
    index = pd.date_range("2026-06-01", periods=len(elevations), freq="h", tz="UTC", name="time")
    return pd.Series(elevations, index=index), pd.Series(azimuths, index=index)


def _evaluate(
    elevations: tuple[float, ...],
    azimuths: tuple[float, ...],
    *,
    table: PVsystLinearShadingTable | None = None,
    hemisphere: str = "north",
) -> PVsystLinearShadingResult:
    elevation, azimuth = _series(elevations, azimuths)
    return evaluate_pvsyst_linear_beam_shading(
        _table() if table is None else table,
        elevation,
        azimuth,
        hemisphere=hemisphere,  # type: ignore[arg-type]
    )


def test_value_semantics_normalize_to_identical_transmission() -> None:
    transmission = _table()
    shaded_values = tuple(tuple(1.0 - value for value in row) for row in transmission.values)
    shaded = _table(semantics="shaded_fraction", values=shaded_values)
    first = _evaluate((20.0,), (135.0,), table=transmission).shading.iloc[0]
    second = _evaluate((20.0,), (135.0,), table=shaded).shading.iloc[0]
    assert first["pvsyst_beam_transmission_fraction"] == pytest.approx(
        second["pvsyst_beam_transmission_fraction"]
    )
    assert first["pvsyst_beam_shaded_fraction"] == pytest.approx(
        second["pvsyst_beam_shaded_fraction"]
    )
    assert shaded.values == shaded_values


@pytest.mark.parametrize("semantics", [None, "", "loss", 1])
def test_value_semantics_are_never_guessed(semantics: object) -> None:
    with pytest.raises(ValueError, match="value_semantics"):
        _table(semantics=semantics)  # type: ignore[arg-type]


def test_pvlib_to_pvsyst_azimuth_conventions_and_seam() -> None:
    _, azimuth = _series((10.0,) * 7, (180.0, 90.0, 270.0, 0.0, 0.001, 359.999, 180.0))
    north = convert_pvlib_azimuth_to_pvsyst(azimuth, hemisphere="north")
    south = convert_pvlib_azimuth_to_pvsyst(azimuth, hemisphere="south")
    assert tuple(north.iloc[:4]) == (0.0, -90.0, 90.0, -180.0)
    assert north.iloc[4] == pytest.approx(-179.999)
    assert north.iloc[5] == pytest.approx(179.999)
    assert tuple(south.iloc[[3, 1, 2, 0]]) == (0.0, -90.0, 90.0, -180.0)


def test_exact_grid_points_return_exact_values() -> None:
    table = _table()
    for row_index, height in enumerate(table.sun_height_deg):
        for column_index, pvsyst_azimuth in enumerate(table.pvsyst_solar_azimuth_deg):
            pvlib_azimuth = (pvsyst_azimuth + 180.0) % 360.0
            value = _evaluate((height,), (pvlib_azimuth,), table=table).shading.iloc[0]
            assert value["pvsyst_beam_transmission_fraction"] == pytest.approx(
                table.beam_transmission_values[row_index][column_index], abs=1e-15
            )


def test_height_azimuth_and_bilinear_interpolation() -> None:
    table = _table()
    height = _evaluate((20.0,), (180.0,), table=table).shading.iloc[0]
    azimuth = _evaluate((10.0,), (225.0,), table=table).shading.iloc[0]
    bilinear = _evaluate((20.0,), (225.0,), table=table).shading.iloc[0]
    assert height["pvsyst_beam_transmission_fraction"] == pytest.approx(0.7)
    assert azimuth["pvsyst_beam_transmission_fraction"] == pytest.approx(0.5)
    assert bilinear["pvsyst_beam_transmission_fraction"] == pytest.approx(0.6)


def test_circular_seam_is_continuous() -> None:
    result = _evaluate((30.0,) * 4, (359.0, 1.0, 359.999, 0.001)).shading
    transmission = result["pvsyst_beam_transmission_fraction"].to_numpy()
    assert transmission[0] == pytest.approx(transmission[1])
    assert transmission[2] == pytest.approx(transmission[3])
    assert abs(transmission[2] - transmission[3]) < abs(transmission[0] - 0.4)


def test_inconsistent_seam_is_rejected() -> None:
    values = list(list(row) for row in _table().values)
    values[1][-1] = 0.5
    with pytest.raises(ValueError, match="seam"):
        _table(values=tuple(tuple(row) for row in values))


def test_night_and_outside_height_domain_states() -> None:
    result = _evaluate((0.0, -1.0, -20.0, 5.0, 60.0), (180.0,) * 5)
    frame = result.shading
    assert tuple(frame.iloc[:3]["pvsyst_linear_shading_state"]) == (
        "not_applicable_no_above_horizon_beam",
    ) * 3
    assert frame.iloc[:3]["pvsyst_beam_transmission_fraction"].isna().all()
    assert tuple(frame.iloc[3:]["pvsyst_linear_shading_state"]) == (
        "unresolved_outside_table_height_domain",
    ) * 2
    assert result.diagnostics.not_applicable_count == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("table_id", " "),
        ("orientation_id", 1),
        ("zone_id", ""),
        ("source_label", None),
        ("source_reference", np.nan),
        ("pvsyst_version", " "),
    ],
)
def test_invalid_text_provenance_is_rejected(field: str, value: object) -> None:
    kwargs = {
        "table_id": "table",
        "orientation_id": "orientation",
        "zone_id": None,
        "sun_height_deg": (10.0, 20.0),
        "pvsyst_solar_azimuth_deg": (-180.0, 180.0),
        "values": ((0.5, 0.5), (0.6, 0.6)),
        "value_semantics": "transmission_fraction",
        "source_label": "source",
        "source_reference": None,
        "pvsyst_version": None,
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        PVsystLinearShadingTable(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("heights", "azimuths", "values"),
    [
        ((10.0, 10.0), (-180.0, 180.0), ((0.5, 0.5), (0.5, 0.5))),
        ((20.0, 10.0), (-180.0, 180.0), ((0.5, 0.5), (0.5, 0.5))),
        ((10.0, 20.0), (0.0, 0.0), ((0.5, 0.5), (0.5, 0.5))),
        ((10.0, 20.0), (10.0, -10.0), ((0.5, 0.5), (0.5, 0.5))),
        ((10.0, 20.0), (-180.0, 180.0), ((0.5,), (0.5, 0.5))),
        ((10.0, 20.0), (-180.0, 180.0), ((True, True), (0.5, 0.5))),
        ((10.0, 20.0), (-180.0, 180.0), ((np.nan, np.nan), (0.5, 0.5))),
        ((10.0, 20.0), (-180.0, 180.0), ((-0.1, -0.1), (0.5, 0.5))),
        ((10.0, 20.0), (-180.0, 180.0), ((1.1, 1.1), (0.5, 0.5))),
    ],
)
def test_invalid_grids_and_values_are_rejected(
    heights: object, azimuths: object, values: object
) -> None:
    with pytest.raises(ValueError):
        _table(heights=heights, azimuths=azimuths, values=values)  # type: ignore[arg-type]


def test_input_series_integrity() -> None:
    elevation, azimuth = _series((20.0, 30.0), (180.0, 190.0))
    invalid_pairs = []
    invalid_pairs.append((elevation.set_axis(elevation.index.tz_localize(None)), azimuth))
    duplicate = elevation.copy()
    duplicate.index = pd.DatetimeIndex([elevation.index[0], elevation.index[0]], name="time")
    invalid_pairs.append((duplicate, azimuth))
    shifted = azimuth.copy()
    shifted.index = shifted.index + pd.Timedelta(minutes=1)
    invalid_pairs.append((elevation, shifted))
    renamed = azimuth.copy()
    renamed.index = renamed.index.rename("other")
    invalid_pairs.append((elevation, renamed))
    for left, right in invalid_pairs:
        with pytest.raises(ValueError):
            evaluate_pvsyst_linear_beam_shading(_table(), left, right, hemisphere="north")
    for bad_elevation in (True, np.nan, np.inf, 91.0):
        broken = elevation.astype(object)
        broken.iloc[0] = bad_elevation
        with pytest.raises(ValueError):
            evaluate_pvsyst_linear_beam_shading(_table(), broken, azimuth, hemisphere="north")
    for bad_azimuth in (True, np.nan, np.inf, -1.0, 360.0):
        broken = azimuth.astype(object)
        broken.iloc[0] = bad_azimuth
        with pytest.raises(ValueError):
            evaluate_pvsyst_linear_beam_shading(_table(), elevation, broken, hemisphere="north")


def test_empty_input_schema_and_diagnostics() -> None:
    index = pd.DatetimeIndex([], tz="UTC", name="time")
    result = evaluate_pvsyst_linear_beam_shading(
        _table(), pd.Series([], index=index, dtype=float), pd.Series([], index=index, dtype=float),
        hemisphere="north",
    )
    assert result.shading.empty
    assert tuple(result.shading.columns) == (
        "solar_elevation_deg",
        "solar_azimuth_deg",
        "pvsyst_solar_azimuth_deg",
        "pvsyst_beam_transmission_fraction",
        "pvsyst_beam_shaded_fraction",
        "pvsyst_linear_shading_resolved",
        "pvsyst_linear_shading_state",
        "pvsyst_table_id",
        "pvsyst_orientation_id",
        "pvsyst_zone_id",
        "pvsyst_input_value_semantics",
        "pvsyst_version",
        "pvsyst_source_label",
        "pvsyst_source_reference",
        "pvsyst_linear_shading_contract",
        "pvsyst_linear_shading_model",
        "pvsyst_linear_shading_coverage_scope",
        "pvsyst_linear_shading_scope",
    )
    assert result.diagnostics.timestamp_count == result.diagnostics.resolved_count == 0


def test_provenance_determinism_non_goals_and_no_mutation() -> None:
    table = _table()
    elevation, azimuth = _series((20.0,), (180.0,))
    original_table = deepcopy(table)
    original_elevation, original_azimuth = elevation.copy(), azimuth.copy()
    first = evaluate_pvsyst_linear_beam_shading(table, elevation, azimuth, hemisphere="north")
    second = evaluate_pvsyst_linear_beam_shading(table, elevation, azimuth, hemisphere="north")
    pd.testing.assert_frame_equal(first.shading, second.shading)
    assert first.diagnostics == second.diagnostics
    row = first.shading.iloc[0]
    assert row["pvsyst_table_id"] == table.table_id
    assert row["pvsyst_orientation_id"] == table.orientation_id
    assert row["pvsyst_zone_id"] == table.zone_id
    assert row["pvsyst_source_label"] == table.source_label
    assert row["pvsyst_source_reference"] == table.source_reference
    assert row["pvsyst_version"] == table.pvsyst_version
    assert row["pvsyst_input_value_semantics"] == table.value_semantics
    assert row["pvsyst_linear_shading_contract"] == PVSYST_LINEAR_SHADING_CONTRACT_ID
    assert row["pvsyst_linear_shading_model"] == PVSYST_LINEAR_SHADING_MODEL_ID
    assert row["pvsyst_linear_shading_coverage_scope"] == PVSYST_LINEAR_SHADING_COVERAGE_SCOPE
    assert row["pvsyst_linear_shading_scope"] == PVSYST_LINEAR_SHADING_SCOPE
    forbidden = ("wm2", "power", "current", "voltage", "temperature", "iam", "electrical")
    assert not any(any(term in column.lower() for term in forbidden) for column in first.shading)
    assert table == original_table
    pd.testing.assert_series_equal(elevation, original_elevation)
    pd.testing.assert_series_equal(azimuth, original_azimuth)
