"""Tests for sample-level direct-beam irradiance coupling."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from heliotelligence.physics.direct_beam_shading import (
    calculate_direct_beam_shading,
)
from heliotelligence.physics.irradiance_components import (
    resolve_horizontal_irradiance_components,
)
from heliotelligence.physics.poa_transposition import (
    calculate_raw_poa_transposition,
)
from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility_map,
    solar_direction_enu,
)
from heliotelligence.physics.solar_geometry import calculate_solar_geometry
from heliotelligence.physics.spatial_direct_beam_irradiance import (
    calculate_spatial_direct_beam_irradiance,
)

_COLUMNS = [
    "receiver_id",
    "sample_index",
    "sample_u_index",
    "sample_v_index",
    "sample_east_m",
    "sample_north_m",
    "sample_up_m",
    "beam_visible",
    "beam_shaded",
    "poa_direct_raw_wm2",
    "poa_direct_visible_wm2",
    "poa_direct_shading_loss_wm2",
    "spatial_beam_irradiance_resolved",
    "spatial_beam_irradiance_state",
]


def _horizontal(
    surface_id: str,
    *,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    span_u: float = 2.0,
    span_v: float = 2.0,
) -> RectangularSurface3D:
    return RectangularSurface3D(
        id=surface_id,
        center_enu_m=center,
        u_axis_enu=(1.0, 0.0, 0.0),
        v_axis_enu=(0.0, 1.0, 0.0),
        span_u_m=span_u,
        span_v_m=span_v,
    )


def _calculate(
    raw: pd.Series,
    *,
    surfaces: list[RectangularSurface3D] | None = None,
    zenith: float = 0.0,
    azimuth: float = 0.0,
    samples_u: int = 2,
    samples_v: int = 2,
) -> pd.DataFrame:
    scene = surfaces if surfaces is not None else [_horizontal(str(raw.index[0]))]
    return calculate_spatial_direct_beam_irradiance(
        raw,
        surfaces=scene,
        apparent_solar_zenith_deg=zenith,
        solar_azimuth_deg=azimuth,
        samples_u=samples_u,
        samples_v=samples_v,
    )


def test_exact_schema_dtypes_and_clear_receiver() -> None:
    result = _calculate(pd.Series([800.0], index=["receiver"]))

    assert result.columns.tolist() == _COLUMNS
    assert result.dtypes.astype(str).tolist() == [
        "object",
        "int64",
        "int64",
        "int64",
        "float64",
        "float64",
        "float64",
        "bool",
        "bool",
        "float64",
        "float64",
        "float64",
        "bool",
        "string",
    ]
    assert result["beam_visible"].all()
    assert not result["beam_shaded"].any()
    assert (result["poa_direct_raw_wm2"] == 800.0).all()
    assert (result["poa_direct_visible_wm2"] == 800.0).all()
    assert (result["poa_direct_shading_loss_wm2"] == 0.0).all()
    assert result["spatial_beam_irradiance_resolved"].all()
    assert (result["spatial_beam_irradiance_state"] == "resolved").all()


def test_full_and_half_masks_have_binary_spatial_irradiance() -> None:
    receiver = _horizontal("receiver")
    full = _calculate(
        pd.Series([600.0], index=["receiver"]),
        surfaces=[receiver, _horizontal("full", center=(0.0, 0.0, 1.0))],
    )
    half = _calculate(
        pd.Series([600.0], index=["receiver"]),
        surfaces=[
            receiver,
            _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0),
        ],
    )

    assert full["beam_shaded"].all()
    assert (full["poa_direct_visible_wm2"] == 0.0).all()
    assert (full["poa_direct_shading_loss_wm2"] == 600.0).all()
    assert half["beam_shaded"].tolist() == [False, False, True, True]
    assert half["poa_direct_visible_wm2"].tolist() == [600.0, 600.0, 0.0, 0.0]
    assert half["poa_direct_shading_loss_wm2"].tolist() == [0.0, 0.0, 600.0, 600.0]
    assert half["poa_direct_visible_wm2"].mean() == 300.0


def test_zero_raw_preserves_nontrivial_geometry_but_zero_energy() -> None:
    result = _calculate(
        pd.Series([0.0], index=["receiver"]),
        surfaces=[
            _horizontal("receiver"),
            _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0),
        ],
    )

    assert result["beam_shaded"].tolist() == [False, False, True, True]
    assert (result["poa_direct_visible_wm2"] == 0.0).all()
    assert (result["poa_direct_shading_loss_wm2"] == 0.0).all()
    assert result["spatial_beam_irradiance_resolved"].all()


def test_missing_raw_preserves_geometry_and_unresolved_irradiance() -> None:
    result = _calculate(
        pd.Series([np.nan], index=["receiver"]),
        surfaces=[
            _horizontal("receiver"),
            _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0),
        ],
    )

    assert result["beam_shaded"].tolist() == [False, False, True, True]
    irradiance_columns = [
        "poa_direct_raw_wm2",
        "poa_direct_visible_wm2",
        "poa_direct_shading_loss_wm2",
    ]
    assert result[irradiance_columns].isna().all().all()
    assert not result["spatial_beam_irradiance_resolved"].any()
    assert (
        result["spatial_beam_irradiance_state"] == "geometry_resolved_irradiance_unresolved"
    ).all()


def test_two_receivers_preserve_order_and_distinct_raw_values() -> None:
    surfaces = [
        _horizontal("b", center=(-3.0, 0.0, 0.0)),
        _horizontal("a", center=(3.0, 0.0, 0.0)),
    ]
    result = _calculate(pd.Series([800.0, 500.0], index=["b", "a"]), surfaces=surfaces)

    assert result["receiver_id"].tolist() == ["b"] * 4 + ["a"] * 4
    assert result["poa_direct_visible_wm2"].tolist() == [800.0] * 4 + [500.0] * 4


def test_sample_energy_conservation_and_binary_bounds() -> None:
    result = _calculate(
        pd.Series([777.25], index=["receiver"]),
        surfaces=[
            _horizontal("receiver"),
            _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0),
        ],
        samples_u=10,
        samples_v=2,
    )

    np.testing.assert_allclose(
        result["poa_direct_raw_wm2"],
        result["poa_direct_visible_wm2"] + result["poa_direct_shading_loss_wm2"],
    )
    assert (result["poa_direct_visible_wm2"] >= 0.0).all()
    assert (result["poa_direct_shading_loss_wm2"] >= 0.0).all()
    assert (result["poa_direct_visible_wm2"] <= result["poa_direct_raw_wm2"]).all()
    assert (result["poa_direct_shading_loss_wm2"] <= result["poa_direct_raw_wm2"]).all()


def test_r4b_geometry_fields_preserved_exactly() -> None:
    surfaces = [
        _horizontal("receiver"),
        _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0),
    ]
    r4b = calculate_direct_beam_visibility_map(
        surfaces,
        ["receiver"],
        solar_zenith_deg=20.0,
        solar_azimuth_deg=180.0,
        samples_u=5,
        samples_v=3,
    )
    r4c = _calculate(
        pd.Series([700.0], index=["receiver"]),
        surfaces=surfaces,
        zenith=20.0,
        azimuth=180.0,
        samples_u=5,
        samples_v=3,
    )

    pdt.assert_frame_equal(r4c.iloc[:, :9], r4b)


@pytest.mark.parametrize("samples_u,samples_v", [(1, 1), (2, 2), (5, 5), (10, 2)])
@pytest.mark.parametrize("scene", ["clear", "full", "half"])
def test_sample_means_aggregate_exactly_to_r4a(samples_u: int, samples_v: int, scene: str) -> None:
    surfaces = [_horizontal("receiver")]
    if scene == "full":
        surfaces.append(_horizontal("full", center=(0.0, 0.0, 1.0)))
    elif scene == "half":
        surfaces.append(_horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0))
    raw_value = 800.0
    r4c = _calculate(
        pd.Series([raw_value], index=["receiver"]),
        surfaces=surfaces,
        samples_u=samples_u,
        samples_v=samples_v,
    )
    time = pd.DatetimeIndex(["2026-06-21 12:00"], tz="Europe/London", name="time")
    r4a = calculate_direct_beam_shading(
        pd.DataFrame({"receiver": [raw_value]}, index=time),
        pd.Series([0.0], index=time),
        pd.Series([0.0], index=time),
        surfaces=surfaces,
        samples_u=samples_u,
        samples_v=samples_v,
    ).iloc[0]

    assert r4c["beam_visible"].mean() == r4a["beam_visible_fraction"]
    assert r4c["beam_shaded"].mean() == r4a["beam_shaded_fraction"]
    assert r4c["poa_direct_visible_wm2"].mean() == pytest.approx(r4a["poa_direct_visible_wm2"])
    assert r4c["poa_direct_shading_loss_wm2"].mean() == pytest.approx(
        r4a["poa_direct_shading_loss_wm2"]
    )


def test_same_mean_different_masks_produce_different_local_irradiance() -> None:
    raw = pd.Series([800.0], index=["receiver"])
    receiver = _horizontal("receiver")
    east = _calculate(
        raw,
        surfaces=[receiver, _horizontal("east", center=(0.5, 0.0, 1.0), span_u=1.0)],
    )
    north = _calculate(
        raw,
        surfaces=[receiver, _horizontal("north", center=(0.0, 0.5, 1.0), span_v=1.0)],
    )

    assert east["poa_direct_visible_wm2"].mean() == north["poa_direct_visible_wm2"].mean() == 400.0
    assert east["beam_shaded"].tolist() != north["beam_shaded"].tolist()
    assert east["poa_direct_visible_wm2"].tolist() != north["poa_direct_visible_wm2"].tolist()


def test_empty_receiver_series_returns_stable_schema_and_delegates_validation() -> None:
    result = calculate_spatial_direct_beam_irradiance(
        pd.Series([], index=pd.Index([], dtype=object), dtype=float),
        surfaces=[],
        apparent_solar_zenith_deg=0.0,
        solar_azimuth_deg=0.0,
    )

    assert result.empty
    assert result.columns.tolist() == _COLUMNS
    assert result.dtypes.astype(str).tolist() == [
        "object",
        "int64",
        "int64",
        "int64",
        "float64",
        "float64",
        "float64",
        "bool",
        "bool",
        "float64",
        "float64",
        "float64",
        "bool",
        "string",
    ]
    with pytest.raises(ValueError, match="solar_zenith_deg"):
        calculate_spatial_direct_beam_irradiance(
            pd.Series([], dtype=float),
            surfaces=[],
            apparent_solar_zenith_deg=90.0,
            solar_azimuth_deg=0.0,
        )


@pytest.mark.parametrize("value", [-1.0, True, "1", np.inf, -np.inf])
def test_invalid_present_raw_values_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="present poa_direct_raw_wm2"):
        _calculate(pd.Series([value], index=["receiver"], dtype=object))


def test_invalid_raw_container_and_receiver_ids_rejected() -> None:
    with pytest.raises(ValueError, match="pandas Series"):
        calculate_spatial_direct_beam_irradiance(  # type: ignore[arg-type]
            [1.0],
            surfaces=[],
            apparent_solar_zenith_deg=0.0,
            solar_azimuth_deg=0.0,
        )
    for index in [[""], [1], ["x", "x"]]:
        with pytest.raises(ValueError, match="receiver IDs"):
            calculate_spatial_direct_beam_irradiance(
                pd.Series([1.0] * len(index), index=index),
                surfaces=[],
                apparent_solar_zenith_deg=0.0,
                solar_azimuth_deg=0.0,
            )


def test_inputs_immutable_and_repeated_calls_identical() -> None:
    raw = pd.Series([800.0, np.nan], index=["b", "a"])
    surfaces = [
        _horizontal("b", center=(-3.0, 0.0, 0.0)),
        _horizontal("a", center=(3.0, 0.0, 0.0)),
    ]
    raw_before = raw.copy(deep=True)
    surfaces_before = list(surfaces)
    objects_before = copy.deepcopy([surface.__dict__ for surface in surfaces])

    first = _calculate(raw, surfaces=surfaces)
    second = _calculate(raw, surfaces=surfaces)

    pdt.assert_frame_equal(first, second)
    pdt.assert_series_equal(raw, raw_before)
    assert raw.index.tolist() == ["b", "a"]
    assert surfaces == surfaces_before
    assert [surface.__dict__ for surface in surfaces] == objects_before


def test_r1a_r1b_r2_r4c_composition_distributes_raw_direct_without_recomputation() -> None:
    time = pd.DatetimeIndex(["2026-06-21 12:00"], tz="Europe/London", name="time")
    geometry = calculate_solar_geometry(
        time, latitude_deg=52.5, longitude_deg=-1.2, altitude_m=100.0
    )
    missing = pd.Series([np.nan], index=time)
    r1b = resolve_horizontal_irradiance_components(
        pd.Series([800.0], index=time),
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
        surface_tilt_deg=0.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model="perez-driesse",
    )
    raw_direct = float(r2["poa_direct_raw_wm2"].iloc[0])
    direction = solar_direction_enu(
        float(geometry["apparent_solar_zenith_deg"].iloc[0]),
        float(geometry["solar_azimuth_deg"].iloc[0]),
    )
    result = _calculate(
        pd.Series([raw_direct], index=["receiver"]),
        surfaces=[_horizontal("receiver"), _horizontal("cover", center=direction)],
        zenith=float(geometry["apparent_solar_zenith_deg"].iloc[0]),
        azimuth=float(geometry["solar_azimuth_deg"].iloc[0]),
    )

    assert (result["poa_direct_raw_wm2"] == raw_direct).all()
    assert result["beam_shaded"].all()
    assert (result["poa_direct_visible_wm2"] == 0.0).all()
    assert (result["poa_direct_shading_loss_wm2"] == raw_direct).all()
