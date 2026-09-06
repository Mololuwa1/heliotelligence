"""Tests for the NumPy direct-beam shading reference kernel."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility,
    make_fixed_tilt_rectangular_surface,
    solar_direction_enu,
)


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


def _visibility(
    surfaces: list[RectangularSurface3D],
    receiver_ids: list[str] | None = None,
    *,
    zenith: float = 0.0,
    azimuth: float = 0.0,
    samples_u: int = 10,
    samples_v: int = 2,
) -> pd.DataFrame:
    return calculate_direct_beam_visibility(
        surfaces,
        receiver_ids or ["receiver"],
        solar_zenith_deg=zenith,
        solar_azimuth_deg=azimuth,
        samples_u=samples_u,
        samples_v=samples_v,
    )


def test_solar_zenith_zero_points_up_for_any_legal_azimuth() -> None:
    for azimuth in (0.0, 90.0, 180.0, 359.999):
        assert solar_direction_enu(0.0, azimuth) == pytest.approx((0.0, 0.0, 1.0), abs=1e-15)


def test_east_sun_uses_pvlib_azimuth_convention() -> None:
    direction = solar_direction_enu(60.0, 90.0)

    assert direction == pytest.approx((np.sin(np.radians(60.0)), 0.0, 0.5), abs=1e-15)


def test_north_sun_uses_pvlib_azimuth_convention() -> None:
    east, north, up = solar_direction_enu(60.0, 0.0)

    assert east == pytest.approx(0.0, abs=1e-15)
    assert north > 0.0
    assert up > 0.0


@pytest.mark.parametrize(
    ("zenith", "azimuth"),
    [(0.0, 0.0), (15.0, 45.0), (60.0, 90.0), (89.999, 359.999)],
)
def test_solar_direction_is_unit_length(zenith: float, azimuth: float) -> None:
    assert np.linalg.norm(solar_direction_enu(zenith, azimuth)) == pytest.approx(
        1.0, abs=1e-15
    )


def test_south_facing_fixed_tilt_basis_and_normal() -> None:
    surface = make_fixed_tilt_rectangular_surface(
        surface_id="south",
        center_enu_m=(0.0, 0.0, 0.0),
        span_u_m=2.0,
        span_v_m=1.0,
        tilt_deg=30.0,
        surface_azimuth_deg=180.0,
    )
    u_axis = np.asarray(surface.u_axis_enu)
    v_axis = np.asarray(surface.v_axis_enu)
    normal = np.asarray(surface.normal_enu)

    assert normal[0] == pytest.approx(0.0, abs=1e-15)
    assert normal[1] < 0.0
    assert normal[2] > 0.0
    assert np.linalg.norm(u_axis) == pytest.approx(1.0)
    assert np.linalg.norm(v_axis) == pytest.approx(1.0)
    assert np.dot(u_axis, v_axis) == pytest.approx(0.0, abs=1e-15)
    assert np.cross(u_axis, v_axis) == pytest.approx(normal, abs=1e-15)


@pytest.mark.parametrize("azimuth", [0.0, 90.0, 180.0, 270.0])
def test_horizontal_factory_has_deterministic_basis(azimuth: float) -> None:
    surface = make_fixed_tilt_rectangular_surface(
        surface_id="horizontal",
        center_enu_m=(0.0, 0.0, 0.0),
        span_u_m=1.0,
        span_v_m=1.0,
        tilt_deg=0.0,
        surface_azimuth_deg=azimuth,
    )

    assert surface.u_axis_enu == (1.0, 0.0, 0.0)
    assert surface.v_axis_enu == (0.0, 1.0, 0.0)
    assert surface.normal_enu == pytest.approx((0.0, 0.0, 1.0))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": ""}, "surface id must be non-empty"),
        ({"center_enu_m": (np.nan, 0.0, 0.0)}, "center_enu_m must contain only finite"),
        ({"center_enu_m": (np.inf, 0.0, 0.0)}, "center_enu_m must contain only finite"),
        ({"center_enu_m": (0.0, 0.0)}, "center_enu_m must be a three-component tuple"),
        ({"u_axis_enu": (np.nan, 0.0, 0.0)}, "u_axis_enu must contain only finite"),
        ({"v_axis_enu": (0.0, np.inf, 0.0)}, "v_axis_enu must contain only finite"),
        ({"u_axis_enu": (0.0, 0.0, 0.0)}, "u_axis_enu must be a unit vector"),
        ({"u_axis_enu": (2.0, 0.0, 0.0)}, "u_axis_enu must be a unit vector"),
        ({"v_axis_enu": (0.0, 2.0, 0.0)}, "v_axis_enu must be a unit vector"),
        ({"v_axis_enu": (1.0, 0.0, 0.0)}, "must be orthogonal"),
        ({"span_u_m": 0.0}, "span_u_m must be finite and greater than 0"),
        ({"span_u_m": -1.0}, "span_u_m must be finite and greater than 0"),
        ({"span_v_m": 0.0}, "span_v_m must be finite and greater than 0"),
        ({"span_v_m": np.nan}, "span_v_m must be finite and greater than 0"),
    ],
)
def test_invalid_surfaces_are_rejected(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "id": "surface",
        "center_enu_m": (0.0, 0.0, 0.0),
        "u_axis_enu": (1.0, 0.0, 0.0),
        "v_axis_enu": (0.0, 1.0, 0.0),
        "span_u_m": 1.0,
        "span_v_m": 1.0,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        RectangularSurface3D(**values)  # type: ignore[arg-type]


def test_surface_is_frozen() -> None:
    surface = _horizontal("surface")

    with pytest.raises(FrozenInstanceError):
        surface.span_u_m = 5.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("zenith", "azimuth", "message"),
    [
        (-1.0, 0.0, "solar_zenith_deg"),
        (90.0, 0.0, "solar_zenith_deg"),
        (np.nan, 0.0, "solar_zenith_deg"),
        (45.0, -1.0, "solar_azimuth_deg"),
        (45.0, 360.0, "solar_azimuth_deg"),
        (45.0, np.nan, "solar_azimuth_deg"),
    ],
)
def test_invalid_solar_inputs_fail_before_scene_work(
    zenith: float, azimuth: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_direct_beam_visibility(
            [], [], solar_zenith_deg=zenith, solar_azimuth_deg=azimuth
        )


@pytest.mark.parametrize(
    ("samples_u", "samples_v", "message"),
    [(0, 1, "samples_u"), (-1, 1, "samples_u"), (1, 0, "samples_v"), (1, -1, "samples_v")],
)
def test_invalid_sample_counts_are_rejected(
    samples_u: int, samples_v: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _visibility(
            [_horizontal("receiver")], samples_u=samples_u, samples_v=samples_v
        )


def test_single_receiver_does_not_self_shade() -> None:
    result = _visibility([_horizontal("receiver")])

    assert result.columns.tolist() == [
        "receiver_id",
        "visible_fraction",
        "shaded_fraction",
        "sample_count",
        "shaded_sample_count",
    ]
    assert result.iloc[0].to_dict() == {
        "receiver_id": "receiver",
        "visible_fraction": 1.0,
        "shaded_fraction": 0.0,
        "sample_count": 20,
        "shaded_sample_count": 0,
    }


def test_vertical_sun_complete_occlusion() -> None:
    result = _visibility(
        [_horizontal("receiver"), _horizontal("occluder", center=(0.0, 0.0, 1.0))]
    )

    assert result.loc[0, "visible_fraction"] == 0.0
    assert result.loc[0, "shaded_fraction"] == 1.0
    assert result.loc[0, "shaded_sample_count"] == 20


def test_occluder_opacity_is_two_sided() -> None:
    receiver = _horizontal("receiver")
    forward = _horizontal("occluder", center=(0.0, 0.0, 1.0))
    reversed_normal = RectangularSurface3D(
        id="occluder",
        center_enu_m=(0.0, 0.0, 1.0),
        u_axis_enu=(1.0, 0.0, 0.0),
        v_axis_enu=(0.0, -1.0, 0.0),
        span_u_m=2.0,
        span_v_m=2.0,
    )

    assert np.cross(forward.u_axis_enu, forward.v_axis_enu) == pytest.approx(
        (0.0, 0.0, 1.0)
    )
    assert np.cross(
        reversed_normal.u_axis_enu, reversed_normal.v_axis_enu
    ) == pytest.approx((0.0, 0.0, -1.0))

    forward_result = _visibility([receiver, forward])
    reversed_result = _visibility([receiver, reversed_normal])

    assert forward_result.loc[0, "visible_fraction"] == 0.0
    assert reversed_result.loc[0, "visible_fraction"] == 0.0
    assert forward_result.loc[0, "shaded_fraction"] == 1.0
    assert reversed_result.loc[0, "shaded_fraction"] == 1.0
    assert (
        forward_result.loc[0, "shaded_sample_count"]
        == forward_result.loc[0, "sample_count"]
    )
    assert (
        reversed_result.loc[0, "shaded_sample_count"]
        == reversed_result.loc[0, "sample_count"]
    )
    pd.testing.assert_frame_equal(forward_result, reversed_result)


def test_displaced_occluder_does_not_shade() -> None:
    result = _visibility(
        [_horizontal("receiver"), _horizontal("occluder", center=(5.0, 0.0, 1.0))]
    )

    assert result.loc[0, "visible_fraction"] == 1.0
    assert result.loc[0, "shaded_sample_count"] == 0


def test_aligned_half_occlusion_uses_cell_centre_geometry() -> None:
    result = _visibility(
        [
            _horizontal("receiver"),
            _horizontal(
                "occluder", center=(0.5, 0.0, 1.0), span_u=1.0, span_v=2.0
            ),
        ]
    )

    assert result.loc[0, "sample_count"] == 20
    assert result.loc[0, "shaded_sample_count"] == 10
    assert result.loc[0, "visible_fraction"] == pytest.approx(0.5)
    assert result.loc[0, "shaded_fraction"] == pytest.approx(0.5)


def test_oblique_east_sun_intersects_east_shifted_occluder() -> None:
    result = _visibility(
        [_horizontal("receiver"), _horizontal("occluder", center=(1.0, 0.0, 1.0))],
        zenith=45.0,
        azimuth=90.0,
    )

    assert result.loc[0, "shaded_fraction"] == 1.0


def test_occluder_behind_ray_does_not_shade() -> None:
    result = _visibility(
        [_horizontal("receiver"), _horizontal("behind", center=(0.0, 0.0, -1.0))]
    )

    assert result.loc[0, "visible_fraction"] == 1.0


def test_parallel_ray_and_plane_is_stable_and_unshaded() -> None:
    vertical = RectangularSurface3D(
        id="vertical",
        center_enu_m=(0.0, 2.0, 0.0),
        u_axis_enu=(1.0, 0.0, 0.0),
        v_axis_enu=(0.0, 0.0, 1.0),
        span_u_m=2.0,
        span_v_m=2.0,
    )
    result = _visibility([_horizontal("receiver"), vertical])

    assert result.loc[0, "visible_fraction"] == 1.0
    assert np.isfinite(result[["visible_fraction", "shaded_fraction"]]).all().all()


def test_scene_order_does_not_change_visibility() -> None:
    receiver = _horizontal("receiver")
    half = _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0)
    far = _horizontal("far", center=(10.0, 0.0, 2.0))

    forward = _visibility([receiver, half, far])
    reverse = _visibility([far, half, receiver])

    pd.testing.assert_frame_equal(forward, reverse)


def test_receiver_order_controls_only_output_order() -> None:
    receiver_a = _horizontal("receiver-a", center=(-3.0, 0.0, 0.0))
    receiver_b = _horizontal("receiver-b", center=(3.0, 0.0, 0.0))
    occluder = _horizontal("occluder", center=(-3.0, 0.0, 1.0))
    surfaces = [receiver_a, receiver_b, occluder]

    result_ab = _visibility(surfaces, ["receiver-a", "receiver-b"])
    result_ba = _visibility(surfaces, ["receiver-b", "receiver-a"])

    assert result_ab["receiver_id"].tolist() == ["receiver-a", "receiver-b"]
    assert result_ba["receiver_id"].tolist() == ["receiver-b", "receiver-a"]
    for receiver_id in ("receiver-a", "receiver-b"):
        pd.testing.assert_series_equal(
            result_ab.set_index("receiver_id").loc[receiver_id],
            result_ba.set_index("receiver_id").loc[receiver_id],
        )


def test_duplicate_surface_ids_are_sorted_and_rejected() -> None:
    surfaces = [
        _horizontal("z"),
        _horizontal("a", center=(1.0, 0.0, 0.0)),
        _horizontal("z", center=(2.0, 0.0, 0.0)),
        _horizontal("a", center=(3.0, 0.0, 0.0)),
    ]

    with pytest.raises(ValueError) as error:
        _visibility(surfaces, ["a"])

    assert str(error.value) == "surfaces contains duplicate ids: a, z"


def test_missing_receiver_ids_are_sorted_and_rejected() -> None:
    with pytest.raises(ValueError) as error:
        _visibility([_horizontal("receiver")], ["z", "a"])

    assert str(error.value) == "receiver_ids are absent from surfaces: a, z"


def test_duplicate_receiver_ids_are_sorted_and_rejected() -> None:
    with pytest.raises(ValueError) as error:
        _visibility(
            [_horizontal("a"), _horizontal("z", center=(3.0, 0.0, 0.0))],
            ["z", "a", "z", "a"],
        )

    assert str(error.value) == "receiver_ids contains duplicate ids: a, z"


def test_fraction_conservation_for_mixed_scene() -> None:
    result = _visibility(
        [
            _horizontal("receiver"),
            _horizontal("occluder", center=(0.5, 0.0, 1.0), span_u=1.0),
        ]
    )

    assert result["visible_fraction"].between(0.0, 1.0).all()
    assert result["shaded_fraction"].between(0.0, 1.0).all()
    assert (result["visible_fraction"] + result["shaded_fraction"]).to_numpy() == pytest.approx(1.0)
    assert (result["sample_count"] == 20).all()
    assert (result["shaded_sample_count"] <= result["sample_count"]).all()


def test_inputs_are_not_mutated_and_repeated_calls_are_identical() -> None:
    surfaces = [
        _horizontal("receiver"),
        _horizontal("occluder", center=(0.5, 0.0, 1.0), span_u=1.0),
    ]
    receiver_ids = ["receiver"]
    surfaces_before = list(surfaces)
    receiver_ids_before = list(receiver_ids)
    surface_values_before = [surface.__dict__.copy() for surface in surfaces]

    first = _visibility(surfaces, receiver_ids)
    second = _visibility(surfaces, receiver_ids)

    pd.testing.assert_frame_equal(first, second)
    assert surfaces == surfaces_before
    assert receiver_ids == receiver_ids_before
    assert [surface.__dict__ for surface in surfaces] == surface_values_before
