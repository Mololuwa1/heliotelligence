"""Tests for deterministic sample-level direct-beam visibility maps."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from heliotelligence.physics.direct_beam_shading import (
    calculate_direct_beam_shading,
)
from heliotelligence.physics.shading import (
    RectangularSurface3D,
    calculate_direct_beam_visibility,
    calculate_direct_beam_visibility_map,
)


def _horizontal(
    surface_id: str,
    *,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    span_u: float = 2.0,
    span_v: float = 2.0,
    reverse_normal: bool = False,
) -> RectangularSurface3D:
    return RectangularSurface3D(
        id=surface_id,
        center_enu_m=center,
        u_axis_enu=(1.0, 0.0, 0.0),
        v_axis_enu=(0.0, -1.0 if reverse_normal else 1.0, 0.0),
        span_u_m=span_u,
        span_v_m=span_v,
    )


def _map(
    surfaces: list[RectangularSurface3D],
    receiver_ids: list[str] | None = None,
    *,
    zenith: float = 0.0,
    azimuth: float = 0.0,
    samples_u: int = 2,
    samples_v: int = 2,
) -> pd.DataFrame:
    return calculate_direct_beam_visibility_map(
        surfaces,
        ["receiver"] if receiver_ids is None else receiver_ids,
        solar_zenith_deg=zenith,
        solar_azimuth_deg=azimuth,
        samples_u=samples_u,
        samples_v=samples_v,
    )


def _aggregate(spatial: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for receiver_id, receiver in spatial.groupby("receiver_id", sort=False):
        count = len(receiver)
        shaded = int(receiver["beam_shaded"].sum())
        rows.append(
            {
                "receiver_id": receiver_id,
                "visible_fraction": float(receiver["beam_visible"].mean()),
                "shaded_fraction": float(receiver["beam_shaded"].mean()),
                "sample_count": count,
                "shaded_sample_count": shaded,
            }
        )
    return pd.DataFrame(rows)


def test_exact_schema_dtypes_and_known_two_by_two_coordinates() -> None:
    result = _map([_horizontal("receiver")])

    assert result.columns.tolist() == [
        "receiver_id",
        "sample_index",
        "sample_u_index",
        "sample_v_index",
        "sample_east_m",
        "sample_north_m",
        "sample_up_m",
        "beam_visible",
        "beam_shaded",
    ]
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
    ]
    assert result[["sample_index", "sample_u_index", "sample_v_index"]].values.tolist() == [
        [0, 0, 0],
        [1, 0, 1],
        [2, 1, 0],
        [3, 1, 1],
    ]
    np.testing.assert_allclose(
        result[["sample_east_m", "sample_north_m", "sample_up_m"]].values,
        [[-0.5, -0.5, 0.0], [-0.5, 0.5, 0.0], [0.5, -0.5, 0.0], [0.5, 0.5, 0.0]],
    )
    assert result["beam_visible"].tolist() == [True] * 4
    assert result["beam_shaded"].tolist() == [False] * 4


def test_full_and_displaced_occluders_have_expected_masks() -> None:
    receiver = _horizontal("receiver")
    full = _horizontal("full", center=(0.0, 0.0, 1.0))
    displaced = _horizontal("far", center=(5.0, 0.0, 1.0))

    assert _map([receiver, full])["beam_shaded"].tolist() == [True] * 4
    assert _map([receiver, displaced])["beam_shaded"].tolist() == [False] * 4


def test_half_occluder_exposes_expected_spatial_side() -> None:
    result = _map(
        [
            _horizontal("receiver"),
            _horizontal("east-half", center=(0.5, 0.0, 1.0), span_u=1.0),
        ]
    )

    assert result["beam_shaded"].tolist() == [False, False, True, True]
    assert result.loc[result["beam_shaded"], "sample_u_index"].tolist() == [1, 1]
    assert result.loc[result["beam_visible"], "sample_u_index"].tolist() == [0, 0]
    assert (result["beam_visible"] ^ result["beam_shaded"]).all()


def test_same_fraction_different_spatial_patterns_remain_distinguishable() -> None:
    receiver = _horizontal("receiver")
    east_mask = _map(
        [receiver, _horizontal("east", center=(0.5, 0.0, 1.0), span_u=1.0)]
    )
    north_mask = _map(
        [receiver, _horizontal("north", center=(0.0, 0.5, 1.0), span_v=1.0)]
    )

    assert east_mask["beam_visible"].mean() == north_mask["beam_visible"].mean() == 0.5
    assert east_mask["beam_shaded"].tolist() != north_mask["beam_shaded"].tolist()


def test_oblique_behind_parallel_and_two_sided_cases() -> None:
    receiver = _horizontal("receiver")
    oblique = _map(
        [receiver, _horizontal("east-up", center=(1.0, 0.0, 1.0))],
        zenith=45.0,
        azimuth=90.0,
    )
    behind = _map([receiver, _horizontal("behind", center=(0.0, 0.0, -1.0))])
    vertical_parallel = RectangularSurface3D(
        id="parallel",
        center_enu_m=(0.0, 2.0, 0.0),
        u_axis_enu=(1.0, 0.0, 0.0),
        v_axis_enu=(0.0, 0.0, 1.0),
        span_u_m=2.0,
        span_v_m=2.0,
    )
    parallel = _map([receiver, vertical_parallel])
    forward = _map([receiver, _horizontal("cover", center=(0.0, 0.0, 1.0))])
    reversed_normal = _map(
        [
            receiver,
            _horizontal(
                "cover", center=(0.0, 0.0, 1.0), reverse_normal=True
            ),
        ]
    )

    assert oblique["beam_shaded"].all()
    assert not behind["beam_shaded"].any()
    assert not parallel["beam_shaded"].any()
    pd.testing.assert_series_equal(
        forward["beam_shaded"], reversed_normal["beam_shaded"]
    )


@pytest.mark.parametrize("samples_u,samples_v", [(1, 1), (2, 2), (5, 5), (10, 2)])
@pytest.mark.parametrize("scene", ["clear", "full", "partial", "multiple"])
def test_spatial_aggregation_exactly_reproduces_reference(
    samples_u: int, samples_v: int, scene: str
) -> None:
    receiver = _horizontal("receiver")
    surfaces = [receiver]
    zenith, azimuth = 0.0, 0.0
    if scene == "full":
        surfaces.append(_horizontal("full", center=(0.0, 0.0, 1.0)))
    elif scene == "partial":
        surfaces.append(
            _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0)
        )
    elif scene == "multiple":
        zenith, azimuth = 30.0, 90.0
        surfaces.extend(
            [
                _horizontal("near", center=(0.6, 0.0, 1.0), span_u=1.0),
                _horizontal("far", center=(5.0, 0.0, 2.0)),
            ]
        )

    spatial = _map(
        surfaces,
        zenith=zenith,
        azimuth=azimuth,
        samples_u=samples_u,
        samples_v=samples_v,
    )
    reference = calculate_direct_beam_visibility(
        surfaces,
        ["receiver"],
        solar_zenith_deg=zenith,
        solar_azimuth_deg=azimuth,
        samples_u=samples_u,
        samples_v=samples_v,
    )

    pd.testing.assert_frame_equal(_aggregate(spatial), reference)


def test_receiver_order_controls_blocks_and_scene_order_does_not_change_mask() -> None:
    z = _horizontal("z", center=(-3.0, 0.0, 0.0))
    a = _horizontal("a", center=(3.0, 0.0, 0.0))
    cover = _horizontal("cover", center=(-3.0, 0.0, 1.0))
    surfaces = [z, a, cover]

    za = _map(surfaces, ["z", "a"])
    az = _map(surfaces, ["a", "z"])
    reversed_scene = _map(list(reversed(surfaces)), ["z", "a"])

    assert za["receiver_id"].tolist() == ["z"] * 4 + ["a"] * 4
    assert az["receiver_id"].tolist() == ["a"] * 4 + ["z"] * 4
    pd.testing.assert_frame_equal(za, reversed_scene)


def test_empty_receivers_return_stable_typed_schema() -> None:
    result = _map([_horizontal("surface")], [])

    assert result.empty
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
    ]


@pytest.mark.parametrize(
    ("zenith", "azimuth", "message"),
    [
        (-1.0, 0.0, "solar_zenith_deg"),
        (90.0, 0.0, "solar_zenith_deg"),
        (45.0, -1.0, "solar_azimuth_deg"),
        (45.0, 360.0, "solar_azimuth_deg"),
    ],
)
def test_invalid_solar_values_rejected(
    zenith: float, azimuth: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _map([], [], zenith=zenith, azimuth=azimuth)


@pytest.mark.parametrize("samples_u,samples_v", [(0, 1), (1, 0), (True, 1), (1, 1.5)])
def test_invalid_sample_counts_rejected(samples_u: object, samples_v: object) -> None:
    with pytest.raises(ValueError, match="samples"):
        calculate_direct_beam_visibility_map(
            [_horizontal("receiver")],
            ["receiver"],
            solar_zenith_deg=0.0,
            solar_azimuth_deg=0.0,
            samples_u=samples_u,  # type: ignore[arg-type]
            samples_v=samples_v,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("surfaces", "receiver_ids", "message"),
    [
        ("bad", [], "surfaces must be a sequence"),
        ([object()], [], "RectangularSurface3D"),
        ([_horizontal("x"), _horizontal("x", center=(2.0, 0.0, 0.0))], [], "duplicate ids"),
        ([_horizontal("x")], "x", "receiver_ids must be a sequence"),
        ([_horizontal("x")], [1], "only strings"),
        ([_horizontal("x")], ["x", "x"], "duplicate ids"),
        ([_horizontal("x")], ["missing"], "absent from surfaces"),
    ],
)
def test_invalid_scene_and_receiver_contracts(
    surfaces: object, receiver_ids: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_direct_beam_visibility_map(
            surfaces,  # type: ignore[arg-type]
            receiver_ids,  # type: ignore[arg-type]
            solar_zenith_deg=0.0,
            solar_azimuth_deg=0.0,
        )


def test_inputs_immutable_and_repeated_calls_equal() -> None:
    surfaces = [
        _horizontal("receiver"),
        _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0),
    ]
    receiver_ids = ["receiver"]
    surfaces_before = list(surfaces)
    receivers_before = list(receiver_ids)
    objects_before = copy.deepcopy([surface.__dict__ for surface in surfaces])

    first = _map(surfaces, receiver_ids)
    second = _map(surfaces, receiver_ids)

    pd.testing.assert_frame_equal(first, second)
    assert surfaces == surfaces_before
    assert receiver_ids == receivers_before
    assert [surface.__dict__ for surface in surfaces] == objects_before


def test_r4a_visible_fraction_equals_spatial_mean() -> None:
    surfaces = [
        _horizontal("receiver"),
        _horizontal("half", center=(0.5, 0.0, 1.0), span_u=1.0),
    ]
    spatial = _map(surfaces, samples_u=10, samples_v=2)
    index = pd.DatetimeIndex(["2026-06-21 12:00"], tz="Europe/London", name="time")
    raw = pd.DataFrame({"receiver": [800.0]}, index=index)
    zenith = pd.Series([0.0], index=index)
    azimuth = pd.Series([180.0], index=index)
    r4a = calculate_direct_beam_shading(
        raw,
        zenith,
        azimuth,
        surfaces=surfaces,
        samples_u=10,
        samples_v=2,
    )

    assert r4a["beam_visible_fraction"].iloc[0] == spatial["beam_visible"].mean()
    assert r4a["beam_shaded_fraction"].iloc[0] == spatial["beam_shaded"].mean()
