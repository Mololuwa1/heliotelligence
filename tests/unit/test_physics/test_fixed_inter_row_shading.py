"""Production tests for analytical fixed inter-row direct-beam shading."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest
from pvlib.shading import (  # type: ignore[import-untyped]
    projected_solar_zenith_angle,
    shaded_fraction1d,
)

import heliotelligence.physics.fixed_inter_row_shading as fixed_module
from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.fixed_inter_row_shading import (
    MODEL_ID,
    FixedInterRowScene,
    FixedRowArrayDefinition,
    FixedRowBlockingPair,
    FixedRowDefinition,
    calculate_fixed_inter_row_direct_beam_shading,
)


def _receiver(
    receiver_id: str,
    kind: ReceiverKind = ReceiverKind.FIXED_TABLE,
) -> PVReceiver:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))),
        np.asarray(((0, 1, 2),)),
    )
    return PVReceiver(receiver_id, mesh, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), kind)


def _row(
    row_id: str,
    *receiver_ids: str,
    rotation: float = 30.0,
    width: float = 2.0,
) -> FixedRowDefinition:
    return FixedRowDefinition(row_id, tuple(receiver_ids), rotation, width)


def _array(
    rows: tuple[FixedRowDefinition, ...],
    pairs: tuple[FixedRowBlockingPair, ...] = (),
    *,
    array_id: str = "array",
    axis_azimuth: float = 0.0,
    axis_tilt: float = 0.0,
    offset: float = 0.0,
) -> FixedRowArrayDefinition:
    return FixedRowArrayDefinition(array_id, axis_azimuth, axis_tilt, rows, pairs, offset)


def _three_row_scene(
    *,
    pitch_01: float = 3.0,
    pitch_12: float = 3.0,
    axis_azimuth: float = 0.0,
) -> FixedInterRowScene:
    receivers = [_receiver("r0"), _receiver("r1"), _receiver("r2")]
    rows = (_row("row-0", "r0"), _row("row-1", "r1"), _row("row-2", "r2"))
    pairs = (
        FixedRowBlockingPair("row-0", "row-1", pitch_01),
        FixedRowBlockingPair("row-1", "row-2", pitch_12),
    )
    return FixedInterRowScene(receivers, [_array(rows, pairs, axis_azimuth=axis_azimuth)])


def _geometric_fraction(
    *,
    zenith: float,
    pitch: float,
    rotation: float,
    width: float,
    blocker_width: float | None = None,
    count: int = 100_000,
) -> float:
    """Independent 2-D ray/segment oracle for a north-axis, east-sun pair."""
    angle = np.radians(rotation)
    row_vector = np.asarray((np.cos(angle), -np.sin(angle)))
    sun = np.asarray((np.sin(np.radians(zenith)), np.cos(np.radians(zenith))))
    locations = ((np.arange(count) + 0.5) / count - 0.5) * width
    origins = locations[:, None] * row_vector
    system = np.column_stack((sun, -row_vector))
    solutions = np.linalg.solve(system, (np.asarray((pitch, 0.0)) - origins).T).T
    blocking_width = width if blocker_width is None else blocker_width
    hits = (solutions[:, 0] > 0.0) & (np.abs(solutions[:, 1]) <= blocking_width / 2.0)
    return float(np.mean(hits))


def test_immutable_contract_validation() -> None:
    row = _row("row", "receiver")
    with pytest.raises(FrozenInstanceError):
        row.row_id = "changed"  # type: ignore[misc]
    for bad_width in (0.0, -1.0, np.nan, True):
        with pytest.raises(ValueError):
            _row("row", "receiver", width=bad_width)
    with pytest.raises(ValueError, match="non-empty tuple"):
        FixedRowDefinition("row", (), 0.0, 2.0)
    with pytest.raises(ValueError, match="unique"):
        _row("row", "receiver", "receiver")
    with pytest.raises(ValueError, match="different"):
        FixedRowBlockingPair("row", "row", 3.0)
    for pitch in (0.0, -1.0, np.inf, True):
        with pytest.raises(ValueError):
            FixedRowBlockingPair("left", "right", pitch)


def test_array_topology_validation() -> None:
    rows = (_row("left", "a"), _row("right", "b"))
    pair = FixedRowBlockingPair("left", "right", 3.0)
    with pytest.raises(ValueError, match="row IDs"):
        _array((rows[0], rows[0]))
    with pytest.raises(ValueError, match="refer"):
        _array(rows, (FixedRowBlockingPair("left", "missing", 3.0),))
    with pytest.raises(ValueError, match="blocking pairs"):
        _array(rows, (pair, pair))
    for azimuth in (-1.0, 360.0, np.nan, True):
        with pytest.raises(ValueError):
            _array(rows, axis_azimuth=azimuth)
    for tilt in (-91.0, 91.0, np.inf, True):
        with pytest.raises(ValueError):
            _array(rows, axis_tilt=tilt)


def test_two_row_reverse_cycle_is_rejected() -> None:
    rows = (_row("A", "a"), _row("B", "b"))
    pairs = (
        FixedRowBlockingPair("A", "B", 3.0),
        FixedRowBlockingPair("B", "A", 3.0),
    )
    with pytest.raises(ValueError, match="must be acyclic"):
        _array(rows, pairs)


def test_longer_cross_axis_cycle_is_rejected() -> None:
    rows = (_row("A", "a"), _row("B", "b"), _row("C", "c"))
    pairs = (
        FixedRowBlockingPair("A", "B", 3.0),
        FixedRowBlockingPair("B", "C", 3.0),
        FixedRowBlockingPair("C", "A", 3.0),
    )
    with pytest.raises(ValueError, match="must be acyclic"):
        _array(rows, pairs)


def test_transitive_and_disconnected_dags_are_accepted() -> None:
    transitive_rows = (_row("A", "a"), _row("B", "b"), _row("C", "c"))
    transitive_pairs = (
        FixedRowBlockingPair("A", "B", 3.0),
        FixedRowBlockingPair("B", "C", 3.0),
        FixedRowBlockingPair("A", "C", 6.0),
    )
    assert _array(transitive_rows, transitive_pairs).blocking_pairs == transitive_pairs

    disconnected_rows = (
        _row("A", "a"),
        _row("B", "b"),
        _row("C", "c"),
        _row("D", "d"),
    )
    disconnected_pairs = (
        FixedRowBlockingPair("A", "B", 3.0),
        FixedRowBlockingPair("C", "D", 4.0),
    )
    assert _array(disconnected_rows, disconnected_pairs).blocking_pairs == disconnected_pairs


def test_valid_dag_pair_order_does_not_change_physics() -> None:
    receivers = [_receiver("a"), _receiver("b"), _receiver("c")]
    rows = (_row("A", "a"), _row("B", "b"), _row("C", "c"))
    pairs = (
        FixedRowBlockingPair("A", "B", 3.0),
        FixedRowBlockingPair("B", "C", 3.0),
        FixedRowBlockingPair("A", "C", 6.0),
    )
    forward = (
        FixedInterRowScene(receivers, [_array(rows, pairs)])
        .calculate_visibility(apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0)
        .receivers
    )
    reversed_order = (
        FixedInterRowScene(receivers, [_array(rows, tuple(reversed(pairs)))])
        .calculate_visibility(apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0)
        .receivers
    )
    pd.testing.assert_frame_equal(forward, reversed_order)


def test_blocking_pair_rejects_unequal_collector_widths() -> None:
    rows = (
        _row("target", "target", width=2.0),
        _row("blocker", "blocker", width=0.5),
    )
    pair = FixedRowBlockingPair("target", "blocker", 3.0)
    with pytest.raises(ValueError, match="require equal collector widths"):
        _array(rows, (pair,))


def test_pair_width_constraint_is_local_to_each_array() -> None:
    array_a = _array(
        (_row("a-negative", "a0", width=2.0), _row("a-positive", "a1", width=2.0)),
        (FixedRowBlockingPair("a-negative", "a-positive", 3.0),),
        array_id="array-a",
    )
    array_b = _array(
        (_row("b-negative", "b0", width=2.5), _row("b-positive", "b1", width=2.5)),
        (FixedRowBlockingPair("b-negative", "b-positive", 4.0),),
        array_id="array-b",
    )
    scene = FixedInterRowScene(
        [_receiver("a0"), _receiver("a1"), _receiver("b0"), _receiver("b1")],
        [array_a, array_b],
    )
    assert scene.receiver_ids == ("a0", "a1", "b0", "b1")


def test_independent_geometry_proves_blocker_width_materially_changes_shade() -> None:
    equal_width = _geometric_fraction(
        zenith=75.0, pitch=3.0, rotation=30.0, width=2.0, blocker_width=2.0
    )
    narrow_blocker = _geometric_fraction(
        zenith=75.0, pitch=3.0, rotation=30.0, width=2.0, blocker_width=0.5
    )
    assert equal_width == pytest.approx(0.45096, abs=2e-5)
    assert narrow_blocker == pytest.approx(0.07596, abs=2e-5)
    assert equal_width - narrow_blocker > 0.20


@pytest.mark.parametrize(
    "kind", [ReceiverKind.TRACKER_TABLE, ReceiverKind.MODULE, ReceiverKind.UNKNOWN]
)
def test_only_fixed_table_receivers_are_accepted(kind: ReceiverKind) -> None:
    with pytest.raises(ValueError, match="FIXED_TABLE"):
        FixedInterRowScene([_receiver("r", kind)], [_array((_row("row", "r"),))])


def test_scene_assignment_and_global_uniqueness_validation() -> None:
    receiver = _receiver("r")
    assert FixedInterRowScene([receiver], [_array((_row("row", "r"),))]).receiver_ids == ("r",)
    with pytest.raises(ValueError, match="receiver IDs"):
        FixedInterRowScene([receiver, receiver], [])
    with pytest.raises(ValueError, match="assigned"):
        FixedInterRowScene([receiver], [])
    with pytest.raises(ValueError, match="assigned"):
        FixedInterRowScene([], [_array((_row("row", "unknown"),))])
    two = [_receiver("a"), _receiver("b")]
    with pytest.raises(ValueError, match="assignments"):
        FixedInterRowScene(two, [_array((_row("x", "a"), _row("y", "a", "b")))])
    duplicate_arrays = (
        _array((_row("x", "a"),), array_id="same"),
        _array((_row("y", "b"),), array_id="same"),
    )
    with pytest.raises(ValueError, match="array IDs"):
        FixedInterRowScene(two, duplicate_arrays)
    duplicate_rows = (
        _array((_row("same-row", "a"),), array_id="first"),
        _array((_row("same-row", "b"),), array_id="second"),
    )
    with pytest.raises(ValueError, match="row IDs"):
        FixedInterRowScene(two, duplicate_rows)


def test_empty_scene_and_single_row_are_clear() -> None:
    empty = (
        FixedInterRowScene([], [])
        .calculate_visibility(apparent_solar_zenith_deg=20.0, solar_azimuth_deg=90.0)
        .receivers
    )
    assert empty.empty
    scene = FixedInterRowScene([_receiver("r")], [_array((_row("row", "r"),))])
    row = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0
    ).receivers.iloc[0]
    assert row["fixed_inter_row_beam_shaded_fraction"] == 0.0
    assert row["fixed_inter_row_beam_visible_fraction"] == 1.0
    assert row["shading_row_id"] is None


def test_official_pvlib_reference_case() -> None:
    receivers = [_receiver("negative"), _receiver("positive")]
    rows = (_row("negative-row", "negative"), _row("positive-row", "positive"))
    pair = FixedRowBlockingPair("negative-row", "positive-row", 3.0)
    scene = FixedInterRowScene(
        receivers,
        [_array(rows, (pair,), axis_azimuth=90.0, offset=0.05)],
    )
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=135.0
    ).receivers
    observed = result.loc[0, "fixed_inter_row_beam_shaded_fraction"]
    assert observed == pytest.approx(0.47755694708090535, abs=1e-15)
    assert result.loc[0, "shading_row_id"] == "positive-row"


@pytest.mark.parametrize(
    ("zenith", "pitch", "classification"),
    ((20.0, 3.0, "clear"), (75.0, 3.0, "partial"), (89.0, 2.1, "near-full")),
)
def test_independent_geometric_oracle(zenith: float, pitch: float, classification: str) -> None:
    receivers = [_receiver("negative"), _receiver("positive")]
    rows = (_row("negative", "negative"), _row("positive", "positive"))
    scene = FixedInterRowScene(
        receivers,
        [_array(rows, (FixedRowBlockingPair("negative", "positive", pitch),))],
    )
    analytical = scene.calculate_visibility(
        apparent_solar_zenith_deg=zenith, solar_azimuth_deg=90.0
    ).receivers.loc[0, "fixed_inter_row_beam_shaded_fraction"]
    geometric = _geometric_fraction(zenith=zenith, pitch=pitch, rotation=30.0, width=2.0)
    assert analytical == pytest.approx(geometric, abs=2e-5)
    if classification == "clear":
        assert analytical == 0.0
    elif classification == "partial":
        assert 0.0 < analytical < 1.0
    else:
        assert analytical > 0.9


def test_role_reversal_edges_and_north_south_axis_convention() -> None:
    scene = _three_row_scene()
    east = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0
    ).receivers
    west = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=270.0
    ).receivers
    assert east["sunward_side"].unique().tolist() == ["positive"]
    assert east["shading_row_id"].tolist() == ["row-1", "row-2", None]
    assert west["sunward_side"].unique().tolist() == ["negative"]
    assert west["shading_row_id"].tolist() == [None, "row-0", "row-1"]
    assert east.loc[2, "fixed_inter_row_beam_shaded_fraction"] == 0.0
    assert west.loc[0, "fixed_inter_row_beam_shaded_fraction"] == 0.0


def test_east_west_axis_and_axis_plane_conventions() -> None:
    scene = _three_row_scene(axis_azimuth=90.0)
    south = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=180.0
    ).receivers
    north = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=0.0
    ).receivers
    parallel = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0
    ).receivers
    assert south["sunward_side"].unique().tolist() == ["positive"]
    assert north["sunward_side"].unique().tolist() == ["negative"]
    assert parallel["sunward_side"].unique().tolist() == ["axis_plane"]
    assert (parallel["fixed_inter_row_beam_shaded_fraction"] == 0.0).all()


def test_pitch_solar_elevation_and_nonuniform_pitch_effects() -> None:
    small = _three_row_scene(pitch_01=2.1, pitch_12=5.0)
    low = small.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0
    ).receivers
    high = small.calculate_visibility(
        apparent_solar_zenith_deg=20.0, solar_azimuth_deg=90.0
    ).receivers
    assert (
        low.loc[0, "fixed_inter_row_beam_shaded_fraction"]
        > low.loc[1, "fixed_inter_row_beam_shaded_fraction"]
    )
    assert (
        low.loc[0, "fixed_inter_row_beam_shaded_fraction"]
        >= high.loc[0, "fixed_inter_row_beam_shaded_fraction"]
    )


def test_parameter_mapping_different_rotations_slope_and_axis_tilt() -> None:
    rows = (
        _row("target", "target", rotation=50.0, width=2.5),
        _row("blocker", "blocker", rotation=30.0, width=2.5),
    )
    pair = FixedRowBlockingPair("target", "blocker", 4.0, 7.0)
    scene = FixedInterRowScene(
        [_receiver("target"), _receiver("blocker")],
        [_array(rows, (pair,), axis_azimuth=270.0, axis_tilt=10.0, offset=0.05)],
    )
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=75.5
    ).receivers
    expected = shaded_fraction1d(
        80.0,
        75.5,
        270.0,
        50.0,
        collector_width=2.5,
        pitch=4.0,
        axis_tilt=10.0,
        surface_to_axis_offset=0.05,
        cross_axis_slope=7.0,
        shading_row_rotation=30.0,
    )
    assert result.loc[0, "fixed_inter_row_beam_shaded_fraction"] == pytest.approx(expected)


def test_multiple_candidates_choose_max_and_deterministic_tie() -> None:
    receivers = [_receiver("target"), _receiver("near"), _receiver("far")]
    rows = (
        _row("target", "target", rotation=30.0),
        _row("near", "near", rotation=0.0),
        _row("far", "far", rotation=60.0),
    )
    pairs = (
        FixedRowBlockingPair("target", "near", 3.0),
        FixedRowBlockingPair("target", "far", 5.0),
    )
    scene = FixedInterRowScene(receivers, [_array(rows, pairs)])
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0
    ).receivers.iloc[0]
    assert result["shading_row_id"] == "far"
    expected = shaded_fraction1d(
        80.0,
        90.0,
        0.0,
        30.0,
        collector_width=2.0,
        pitch=5.0,
        shading_row_rotation=60.0,
    )
    assert result["fixed_inter_row_beam_shaded_fraction"] == pytest.approx(expected)

    tie_rows = (_row("target", "target"), _row("z-row", "near"), _row("a-row", "far"))
    tie_pairs = (
        FixedRowBlockingPair("target", "z-row", 3.0),
        FixedRowBlockingPair("target", "a-row", 3.0),
    )
    tie_scene = FixedInterRowScene(receivers, [_array(tie_rows, tie_pairs)])
    tied = tie_scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0
    ).receivers.iloc[0]
    assert tied["shading_row_id"] == "a-row"


def test_multiple_arrays_order_invariance_and_receiver_order() -> None:
    receivers = [_receiver("b"), _receiver("a")]
    first_array = _array((_row("row-a", "a"),), array_id="array-a")
    second_array = _array((_row("row-b", "b"),), array_id="array-b", axis_azimuth=90.0)
    first = (
        FixedInterRowScene(receivers, [first_array, second_array])
        .calculate_visibility(apparent_solar_zenith_deg=60.0, solar_azimuth_deg=180.0)
        .receivers
    )
    second = (
        FixedInterRowScene(receivers, [second_array, first_array])
        .calculate_visibility(apparent_solar_zenith_deg=60.0, solar_azimuth_deg=180.0)
        .receivers
    )
    assert first["receiver_id"].tolist() == ["b", "a"]
    pd.testing.assert_frame_equal(first, second)


def test_multiple_receivers_in_one_row_share_row_fraction_and_schema() -> None:
    receivers = [_receiver("a"), _receiver("b"), _receiver("blocker")]
    rows = (_row("target", "a", "b"), _row("blocker-row", "blocker"))
    scene = FixedInterRowScene(
        receivers,
        [_array(rows, (FixedRowBlockingPair("target", "blocker-row", 3.0),))],
    )
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0
    ).receivers
    assert result.columns.tolist() == [
        "receiver_id",
        "fixed_row_array_id",
        "fixed_row_id",
        "row_rotation_deg",
        "collector_width_m",
        "projected_solar_zenith_deg",
        "fixed_inter_row_beam_visible_fraction",
        "fixed_inter_row_beam_shaded_fraction",
        "shading_row_id",
        "shading_pitch_m",
        "cross_axis_slope_deg",
        "sunward_side",
        "fixed_inter_row_model",
    ]
    assert (
        result.loc[0, "fixed_inter_row_beam_shaded_fraction"]
        == result.loc[1, "fixed_inter_row_beam_shaded_fraction"]
    )
    assert result.loc[0, "shading_row_id"] == result.loc[1, "shading_row_id"]
    assert str(result["receiver_id"].dtype) == "string"
    assert str(result["fixed_inter_row_beam_shaded_fraction"].dtype) == "float64"


def test_projected_angle_matches_pvlib_and_invalid_angles_rejected() -> None:
    scene = _three_row_scene()
    result = scene.calculate_visibility(
        apparent_solar_zenith_deg=70.0, solar_azimuth_deg=90.0
    ).receivers
    expected = projected_solar_zenith_angle(70.0, 90.0, 0.0, 0.0)
    np.testing.assert_allclose(result["projected_solar_zenith_deg"], expected)
    for zenith in (-1.0, 90.0, np.nan, np.inf):
        with pytest.raises(ValueError):
            scene.calculate_visibility(apparent_solar_zenith_deg=zenith, solar_azimuth_deg=0.0)


def test_direct_poa_coupling_and_irradiance_states() -> None:
    receivers = [_receiver("r0")]
    # An explicit candidate outside the supplied receiver set is forbidden, so use two
    # receivers and select r0 from the receiver-resolved output.
    receivers.append(_receiver("r1"))
    rows = (_row("row-0", "r0"), _row("row-1", "r1"))
    scene = FixedInterRowScene(
        receivers, [_array(rows, (FixedRowBlockingPair("row-0", "row-1", 3.0),))]
    )
    index = pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC", name="time")
    raw = pd.DataFrame(
        {"r0": [800.0, 0.0, np.nan, 0.0, np.nan, 800.0], "r1": [800.0] * 6},
        index=index,
    )
    zenith = pd.Series([80.0, 80.0, 80.0, 90.0, 100.0, 90.0], index=index)
    azimuth = pd.Series([90.0] * 6, index=index)
    result = calculate_fixed_inter_row_direct_beam_shading(raw, zenith, azimuth, scene=scene).xs(
        "r0", level="receiver_id"
    )
    fraction = float(result.iloc[0]["fixed_inter_row_beam_visible_fraction"])
    assert result.iloc[0]["poa_direct_after_fixed_inter_row_wm2"] == pytest.approx(800 * fraction)
    assert result.iloc[0]["fixed_inter_row_shading_loss_wm2"] == pytest.approx(800 * (1 - fraction))
    assert result.iloc[1]["poa_direct_after_fixed_inter_row_wm2"] == 0.0
    assert np.isnan(result.iloc[2]["poa_direct_after_fixed_inter_row_wm2"])
    assert result.iloc[3]["fixed_inter_row_state"] == "no_above_horizon_direct_beam"
    assert "unresolved" in result.iloc[4]["fixed_inter_row_state"]
    assert result.iloc[5]["fixed_inter_row_state"] == "below_horizon_positive_direct_inconsistent"
    assert result.iloc[0]["fixed_inter_row_model"] == MODEL_ID


@pytest.mark.parametrize(
    ("shaded", "expected_after", "expected_loss"),
    ((0.0, 800.0, 0.0), (0.25, 600.0, 200.0), (1.0, 0.0, 800.0)),
)
def test_exact_clear_partial_full_energy_conservation(
    monkeypatch: pytest.MonkeyPatch,
    shaded: float,
    expected_after: float,
    expected_loss: float,
) -> None:
    receivers = [_receiver("r0"), _receiver("r1")]
    rows = (_row("row-0", "r0"), _row("row-1", "r1"))
    scene = FixedInterRowScene(
        receivers, [_array(rows, (FixedRowBlockingPair("row-0", "row-1", 3.0),))]
    )
    monkeypatch.setattr(
        fixed_module,
        "_call_shaded_fraction1d",
        lambda *args, **kwargs: np.full(len(np.asarray(kwargs["solar_zenith"])), shaded),
    )
    index = pd.date_range("2026-01-01", periods=1, tz="UTC", name="time")
    raw = pd.DataFrame({"r0": [800.0], "r1": [800.0]}, index=index)
    zenith = pd.Series([80.0], index=index)
    azimuth = pd.Series([90.0], index=index)
    result = calculate_fixed_inter_row_direct_beam_shading(raw, zenith, azimuth, scene=scene).loc[
        (index[0], "r0")
    ]
    assert result["poa_direct_after_fixed_inter_row_wm2"] == expected_after
    assert result["fixed_inter_row_shading_loss_wm2"] == expected_loss
    assert result["poa_direct_raw_wm2"] == expected_after + expected_loss


def test_below_horizon_does_not_call_pvlib(monkeypatch: pytest.MonkeyPatch) -> None:
    receivers = [_receiver("r0"), _receiver("r1")]
    rows = (_row("row-0", "r0"), _row("row-1", "r1"))
    scene = FixedInterRowScene(
        receivers, [_array(rows, (FixedRowBlockingPair("row-0", "row-1", 3.0),))]
    )
    index = pd.date_range("2026-01-01", periods=1, tz="UTC", name="time")
    raw = pd.DataFrame({"r0": [0.0], "r1": [0.0]}, index=index)
    zenith = pd.Series([90.0], index=index)
    azimuth = pd.Series([90.0], index=index)

    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("below-horizon state must not call the row model")

    monkeypatch.setattr(fixed_module, "_call_shaded_fraction1d", unexpected)
    result = calculate_fixed_inter_row_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    assert result.iloc[0]["fixed_inter_row_state"] == "no_above_horizon_direct_beam"


def test_vectorized_model_calls_and_input_immutability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = _three_row_scene()
    index = pd.date_range("2026-01-01", periods=12, freq="h", tz="UTC", name="time")
    raw = pd.DataFrame({"r0": 800.0, "r1": 800.0, "r2": 800.0}, index=index)
    zenith = pd.Series(np.linspace(20.0, 80.0, len(index)), index=index)
    azimuth = pd.Series([90.0] * len(index), index=index)
    raw_before, zenith_before, azimuth_before = raw.copy(), zenith.copy(), azimuth.copy()
    original = fixed_module._call_shaded_fraction1d
    call_sizes: list[int] = []

    def recording(*args: object, **kwargs: object) -> object:
        call_sizes.append(len(np.asarray(kwargs["solar_zenith"])))
        return original(*args, **kwargs)

    monkeypatch.setattr(fixed_module, "_call_shaded_fraction1d", recording)
    first = calculate_fixed_inter_row_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    second = calculate_fixed_inter_row_direct_beam_shading(raw, zenith, azimuth, scene=scene)
    assert call_sizes == [12, 12, 12, 12]
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(raw, raw_before)
    pd.testing.assert_series_equal(zenith, zenith_before)
    pd.testing.assert_series_equal(azimuth, azimuth_before)


def test_fraction_bounds_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _three_row_scene()
    monkeypatch.setattr(
        fixed_module,
        "_call_shaded_fraction1d",
        lambda *args, **kwargs: np.asarray([1.01]),
    )
    with pytest.raises(RuntimeError, match="invalid"):
        scene.calculate_visibility(apparent_solar_zenith_deg=80.0, solar_azimuth_deg=90.0)
