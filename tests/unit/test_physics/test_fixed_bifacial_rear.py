"""Production tests for fixed-row raw rear bifacial irradiance."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest
from pvlib import irradiance  # type: ignore[import-untyped]
from pvlib.bifacial.infinite_sheds import get_irradiance_poa  # type: ignore[import-untyped]

from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.fixed_bifacial_rear import (
    COVERAGE_SCOPE,
    MODEL_ID,
    FixedBifacialRearParameters,
    FixedBifacialRearScene,
    calculate_fixed_bifacial_rear_irradiance,
)
from heliotelligence.physics.fixed_inter_row_shading import (
    FixedRowArrayDefinition,
    FixedRowBlockingPair,
    FixedRowDefinition,
)


def _normal(rotation: float = 30.0, axis_azimuth: float = 0.0) -> tuple[float, float, float]:
    tilt = np.radians(abs(rotation))
    azimuth = np.radians((axis_azimuth + (90.0 if rotation >= 0 else 270.0)) % 360.0)
    return (
        float(np.sin(tilt) * np.sin(azimuth)),
        float(np.sin(tilt) * np.cos(azimuth)),
        float(np.cos(tilt)),
    )


def _receiver(
    identifier: str,
    *,
    kind: ReceiverKind = ReceiverKind.FIXED_TABLE,
    normal: tuple[float, float, float] | None = None,
) -> PVReceiver:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))),
        np.asarray(((0, 1, 2),)),
    )
    return PVReceiver(identifier, mesh, (0.0, 0.0, 1.0), normal or _normal(), kind)


def _row(
    identifier: str, receiver_id: str, *, rotation: float = 30.0, width: float = 2.0
) -> FixedRowDefinition:
    return FixedRowDefinition(identifier, (receiver_id,), rotation, width)


def _array(
    *,
    count: int = 2,
    pitches: tuple[float, ...] | None = None,
    rotations: tuple[float, ...] | None = None,
    axis_tilt: float = 0.0,
    slopes: tuple[float, ...] | None = None,
    pairs: tuple[tuple[int, int], ...] | None = None,
    array_id: str = "array",
) -> FixedRowArrayDefinition:
    rotations = rotations or (30.0,) * count
    rows = tuple(_row(f"row-{i}", f"r{i}", rotation=rotations[i]) for i in range(count))
    edges = pairs or tuple((i, i + 1) for i in range(count - 1))
    pitches = pitches or (4.0,) * len(edges)
    slopes = slopes or (0.0,) * len(edges)
    blocking = tuple(
        FixedRowBlockingPair(f"row-{left}", f"row-{right}", pitches[i], slopes[i])
        for i, (left, right) in enumerate(edges)
    )
    return FixedRowArrayDefinition(array_id, 0.0, axis_tilt, rows, blocking)


def _scene(
    *,
    array: FixedRowArrayDefinition | None = None,
    receivers: list[PVReceiver] | None = None,
    parameters: list[FixedBifacialRearParameters] | None = None,
    points: int = 40,
) -> FixedBifacialRearScene:
    array = array or _array()
    if receivers is None:
        receivers = [_receiver("r0"), _receiver("r1")]
    if parameters is None:
        parameters = [FixedBifacialRearParameters(array.array_id, 1.5, 0.2)]
    return FixedBifacialRearScene(receivers, [array], parameters, view_factor_points=points)


def _inputs(scale: float = 1.0) -> tuple[pd.Series, ...]:
    index = pd.date_range("2026-06-01 12:00", periods=2, freq="h", tz="UTC", name="time")
    return (
        pd.Series(np.asarray((800.0, 600.0)) * scale, index=index),
        pd.Series(np.asarray((120.0, 100.0)) * scale, index=index),
        pd.Series(np.asarray((700.0, 500.0)) * scale, index=index),
        pd.Series((35.0, 50.0), index=index),
        pd.Series((180.0, 210.0), index=index),
    )


def _calculate(
    scene: FixedBifacialRearScene | None = None,
    *,
    model: str = "isotropic",
    inputs: tuple[pd.Series, ...] | None = None,
) -> pd.DataFrame:
    values = inputs or _inputs()
    return calculate_fixed_bifacial_rear_irradiance(
        *values,
        scene=scene or _scene(),
        model=model,  # type: ignore[arg-type]
    )


def test_parameter_contract_and_diagnostics() -> None:
    parameters = FixedBifacialRearParameters("array", 1.5, 0.2)
    with pytest.raises(FrozenInstanceError):
        parameters.albedo = 0.5  # type: ignore[misc]
    for height in (0.0, -1.0, np.nan, np.inf, True):
        with pytest.raises(ValueError):
            FixedBifacialRearParameters("array", height, 0.2)
    for albedo in (-0.1, 1.1, np.nan, np.inf, True):
        with pytest.raises(ValueError):
            FixedBifacialRearParameters("array", 1.0, albedo)
    scene = _scene()
    assert scene.diagnostics.receiver_count == 2
    assert scene.diagnostics.array_count == 1
    assert scene.diagnostics.row_count == 2
    assert scene.diagnostics.regular_blocking_pair_count == 1
    assert scene.diagnostics.coverage_scope == COVERAGE_SCOPE


def test_zero_irradiance_and_component_closure() -> None:
    values = list(_inputs())
    for position in range(3):
        values[position] = values[position] * 0.0
    zero = _calculate(inputs=tuple(values))
    component_columns = [column for column in zero if column.startswith("poa_rear_")]
    assert (zero[component_columns] == 0.0).all().all()

    result = _calculate()
    np.testing.assert_allclose(
        result["poa_rear_diffuse_raw_wm2"],
        result["poa_rear_sky_diffuse_raw_wm2"] + result["poa_rear_ground_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        result["poa_rear_global_raw_wm2"],
        result["poa_rear_direct_raw_wm2"] + result["poa_rear_diffuse_raw_wm2"],
        rtol=1e-12,
        atol=1e-9,
    )


def test_albedo_zero_and_linear_scaling() -> None:
    zero_albedo = _scene(parameters=[FixedBifacialRearParameters("array", 1.5, 0.0)])
    assert np.allclose(_calculate(zero_albedo)["poa_rear_ground_diffuse_raw_wm2"], 0.0)
    base = _calculate()
    doubled = _calculate(inputs=_inputs(scale=2.0))
    for column in (
        "poa_rear_direct_raw_wm2",
        "poa_rear_circumsolar_diffuse_raw_wm2",
        "poa_rear_sky_diffuse_raw_wm2",
        "poa_rear_ground_diffuse_raw_wm2",
        "poa_rear_diffuse_raw_wm2",
        "poa_rear_global_raw_wm2",
    ):
        np.testing.assert_allclose(doubled[column], 2.0 * base[column], rtol=1e-12, atol=1e-9)


@pytest.mark.parametrize("model", ["isotropic", "haydavies"])
def test_direct_pvlib_reference_parity(model: str) -> None:
    scene = _scene(points=31)
    ghi, dhi, dni, zenith, azimuth = _inputs()
    zenith = pd.Series((70.0, 75.0), index=zenith.index)
    azimuth = pd.Series((270.0, 270.0), index=azimuth.index)
    reference_inputs = (ghi, dhi, dni, zenith, azimuth)
    result = _calculate(scene, model=model, inputs=reference_inputs).xs("r0", level="receiver_id")
    dni_extra = irradiance.get_extra_radiation(ghi.index) if model == "haydavies" else None
    reference = get_irradiance_poa(
        150.0,
        270.0,
        zenith.to_numpy(),
        azimuth.to_numpy(),
        0.5,
        1.5,
        4.0,
        ghi.to_numpy(),
        dhi.to_numpy(),
        dni.to_numpy(),
        0.2,
        model=model,
        dni_extra=dni_extra,
        iam=1.0,
        npoints=31,
        vectorize=False,
    )
    np.testing.assert_allclose(
        result["poa_rear_ground_diffuse_raw_wm2"],
        reference["poa_ground_diffuse"],
        rtol=1e-12,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        result["rear_direct_shaded_fraction"],
        reference["shaded_fraction"],
        rtol=1e-12,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        result["poa_rear_global_raw_wm2"], reference["poa_global"], rtol=1e-12, atol=1e-9
    )
    if model == "isotropic":
        assert (result["poa_rear_circumsolar_diffuse_raw_wm2"] == 0.0).all()
        np.testing.assert_allclose(
            result["poa_rear_direct_raw_wm2"], reference["poa_direct"], rtol=1e-12, atol=1e-9
        )
        np.testing.assert_allclose(
            result["poa_rear_sky_diffuse_raw_wm2"],
            reference["poa_sky_diffuse"],
            rtol=1e-12,
            atol=1e-9,
        )
    else:
        unshaded_original_beam = irradiance.beam_component(
            150.0,
            270.0,
            zenith.to_numpy(),
            azimuth.to_numpy(),
            dni.to_numpy(),
        )
        true_beam = unshaded_original_beam * (1.0 - reference["shaded_fraction"])
        circumsolar = reference["poa_direct"] - true_beam
        assert np.any(circumsolar > 0.0)
        np.testing.assert_allclose(
            result["poa_rear_direct_raw_wm2"], true_beam, rtol=1e-12, atol=1e-9
        )
        np.testing.assert_allclose(
            result["poa_rear_circumsolar_diffuse_raw_wm2"],
            circumsolar,
            rtol=1e-12,
            atol=1e-9,
        )
        np.testing.assert_allclose(
            result["poa_rear_direct_raw_wm2"] + result["poa_rear_circumsolar_diffuse_raw_wm2"],
            reference["poa_direct"],
            rtol=1e-12,
            atol=1e-9,
        )
        np.testing.assert_allclose(
            result["poa_rear_sky_diffuse_raw_wm2"],
            reference["poa_sky_diffuse"] + circumsolar,
            rtol=1e-12,
            atol=1e-9,
        )
        assert np.isfinite(result["dni_extra_wm2"]).all()


def test_independent_rear_orientation_oracles() -> None:
    tilted = _calculate().iloc[0]
    assert tilted["surface_tilt_deg"] == pytest.approx(30.0)
    assert tilted["surface_azimuth_deg"] == pytest.approx(90.0)
    assert tilted["rear_surface_tilt_deg"] == pytest.approx(150.0)
    assert tilted["rear_surface_azimuth_deg"] == pytest.approx(270.0)

    horizontal_array = _array(rotations=(0.0, 0.0))
    horizontal_receivers = [
        _receiver("r0", normal=(0.0, 0.0, 1.0)),
        _receiver("r1", normal=(0.0, 0.0, 1.0)),
    ]
    horizontal = _calculate(_scene(array=horizontal_array, receivers=horizontal_receivers)).iloc[0]
    assert horizontal["surface_tilt_deg"] == 0.0
    assert horizontal["rear_surface_tilt_deg"] == 180.0


def test_receiver_normal_mismatch_is_rejected() -> None:
    receivers = [_receiver("r0", normal=(0.0, 0.0, 1.0)), _receiver("r1")]
    with pytest.raises(ValueError, match="normal conflicts"):
        _scene(receivers=receivers)


@pytest.mark.parametrize(
    "array",
    [
        _array(count=3, pairs=((0, 1), (0, 2))),
        _array(count=3, pairs=((0, 1), (0, 2), (1, 2))),
        _array(count=3, pairs=((0, 1),)),
        _array(count=4, pairs=((0, 1), (2, 3), (1, 3))),
    ],
)
def test_non_chain_topology_is_rejected(array: FixedRowArrayDefinition) -> None:
    receivers = [_receiver(f"r{i}") for i in range(len(array.rows))]
    with pytest.raises(ValueError, match="linear row chain|branch|connected"):
        _scene(array=array, receivers=receivers)


def test_nonuniform_geometry_axis_slope_and_gcr_are_rejected() -> None:
    receivers3 = [_receiver(f"r{i}") for i in range(3)]
    with pytest.raises(ValueError, match="uniform pitch"):
        _scene(array=_array(count=3, pitches=(4.0, 5.0)), receivers=receivers3)
    with pytest.raises(ValueError, match="uniform row rotation"):
        _scene(array=_array(rotations=(30.0, 20.0)))
    with pytest.raises(ValueError, match="horizontal row axes"):
        _scene(array=_array(axis_tilt=1.0))
    with pytest.raises(ValueError, match="zero cross-axis slope"):
        _scene(array=_array(slopes=(1.0,)))
    narrow_pitch = FixedRowArrayDefinition(
        "array",
        0.0,
        0.0,
        (_row("row-0", "r0", width=2.0), _row("row-1", "r1", width=2.0)),
        (FixedRowBlockingPair("row-0", "row-1", 1.5),),
    )
    with pytest.raises(ValueError, match="GCR"):
        _scene(array=narrow_pitch)
    with pytest.raises(ValueError, match="equal collector widths"):
        FixedRowArrayDefinition(
            "array",
            0.0,
            0.0,
            (_row("row-0", "r0", width=2.0), _row("row-1", "r1", width=2.1)),
            (FixedRowBlockingPair("row-0", "row-1", 4.0),),
        )


def test_height_ground_intersection_validation() -> None:
    _scene(parameters=[FixedBifacialRearParameters("array", 0.5, 0.2)])
    with pytest.raises(ValueError, match="penetrate level ground"):
        _scene(parameters=[FixedBifacialRearParameters("array", 0.1, 0.2)])


@pytest.mark.parametrize("kind", [ReceiverKind.MODULE, ReceiverKind.UNKNOWN])
def test_unsupported_receiver_kinds_are_rejected(kind: ReceiverKind) -> None:
    with pytest.raises(ValueError, match="FIXED_TABLE"):
        _scene(receivers=[_receiver("r0", kind=kind), _receiver("r1")])


def test_tracker_receiver_is_rejected_with_s6c_boundary() -> None:
    with pytest.raises(ValueError, match="S6C.*outside S6E v1"):
        _scene(receivers=[_receiver("r0", kind=ReceiverKind.TRACKER_TABLE), _receiver("r1")])


def test_assignment_parameter_and_control_validation() -> None:
    with pytest.raises(ValueError, match="assigned exactly once"):
        _scene(receivers=[_receiver("r0"), _receiver("missing")])
    duplicate_rows = (
        FixedRowDefinition("a", ("r0",), 30.0, 2.0),
        FixedRowDefinition("b", ("r0",), 30.0, 2.0),
    )
    duplicate_array = FixedRowArrayDefinition(
        "array", 0.0, 0.0, duplicate_rows, (FixedRowBlockingPair("a", "b", 4.0),)
    )
    with pytest.raises(ValueError, match="assignments"):
        _scene(array=duplicate_array, receivers=[_receiver("r0")])
    with pytest.raises(ValueError, match="exactly one rear-parameter"):
        _scene(parameters=[])
    with pytest.raises(ValueError, match="receiver IDs"):
        FixedBifacialRearScene(
            [_receiver("r0"), _receiver("r0")],
            [_array()],
            [FixedBifacialRearParameters("array", 1.5, 0.2)],
            view_factor_points=10,
        )
    with pytest.raises(ValueError, match="parameter array IDs"):
        FixedBifacialRearScene(
            [_receiver("r0"), _receiver("r1")],
            [_array()],
            [
                FixedBifacialRearParameters("array", 1.5, 0.2),
                FixedBifacialRearParameters("array", 1.5, 0.2),
            ],
            view_factor_points=10,
        )
    for points in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            _scene(points=points)


def test_missing_irradiance_and_model_selection() -> None:
    values = list(_inputs())
    values[0] = values[0].copy()
    values[0].iloc[1] = np.nan
    result = _calculate(inputs=tuple(values)).xs("r0", level="receiver_id")
    assert bool(result.iloc[0]["rear_irradiance_resolved"])
    assert not bool(result.iloc[1]["rear_irradiance_resolved"])
    assert np.isnan(result.iloc[1]["poa_rear_global_raw_wm2"])
    assert result.iloc[1]["rear_irradiance_state"] == "unresolved_missing_irradiance"
    with pytest.raises(ValueError, match="model"):
        _calculate(model="perez")


def test_index_and_numeric_validation() -> None:
    values = list(_inputs())
    values[0] = values[0].copy()
    values[0].index = values[0].index.rename("different")
    with pytest.raises(ValueError, match="identical"):
        _calculate(inputs=tuple(values))
    values = list(_inputs())
    values[0] = values[0].copy()
    values[0].index = values[0].index.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        _calculate(inputs=tuple(values))
    for bad in (-1.0, np.inf, True):
        values = list(_inputs())
        values[0] = pd.Series((bad, 600.0), index=values[0].index, dtype="object")
        with pytest.raises(ValueError):
            _calculate(inputs=tuple(values))
    values = list(_inputs())
    values[3] = values[3].copy()
    values[3].iloc[0] = 181.0
    with pytest.raises(ValueError):
        _calculate(inputs=tuple(values))


def test_timestamp_mismatch_duplicates_and_nat_are_rejected() -> None:
    values = list(_inputs())
    values[1] = values[1].copy()
    values[1].index = values[1].index + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="identical"):
        _calculate(inputs=tuple(values))

    values = list(_inputs())
    duplicate = pd.DatetimeIndex([values[0].index[0], values[0].index[0]], name="time")
    values = [pd.Series(item.to_numpy(), index=duplicate) for item in values]
    with pytest.raises(ValueError, match="unique"):
        _calculate(inputs=tuple(values))

    values = list(_inputs())
    nat_index = pd.DatetimeIndex([values[0].index[0], pd.NaT], name="time")
    values = [pd.Series(item.to_numpy(), index=nat_index) for item in values]
    with pytest.raises(ValueError, match="NaT"):
        _calculate(inputs=tuple(values))


def test_multiple_array_receiver_and_parameter_order_invariance() -> None:
    array_a = FixedRowArrayDefinition(
        "array-a",
        0.0,
        0.0,
        (_row("a0", "a0"), _row("a1", "a1")),
        (FixedRowBlockingPair("a0", "a1", 4.0),),
    )
    array_b = FixedRowArrayDefinition(
        "array-b",
        90.0,
        0.0,
        (_row("b0", "b0"), _row("b1", "b1")),
        (FixedRowBlockingPair("b0", "b1", 5.0),),
    )
    receivers = [
        _receiver("a0"),
        _receiver("a1"),
        _receiver("b0", normal=_normal(axis_azimuth=90.0)),
        _receiver("b1", normal=_normal(axis_azimuth=90.0)),
    ]
    parameters = [
        FixedBifacialRearParameters("array-a", 1.5, 0.2),
        FixedBifacialRearParameters("array-b", 1.8, 0.3),
    ]
    first_scene = FixedBifacialRearScene(
        receivers, [array_a, array_b], parameters, view_factor_points=20
    )
    second_scene = FixedBifacialRearScene(
        list(reversed(receivers)),
        [array_b, array_a],
        list(reversed(parameters)),
        view_factor_points=20,
    )
    first = _calculate(first_scene).sort_index()
    second = _calculate(second_scene).sort_index()
    pd.testing.assert_frame_equal(first, second)


def test_determinism_ordering_schema_and_provenance() -> None:
    scene = _scene()
    first = _calculate(scene)
    pd.testing.assert_frame_equal(first, _calculate(scene))
    assert first.index.names == ["time", "receiver_id"]
    assert first.iloc[0]["rear_irradiance_model"] == MODEL_ID
    assert first.iloc[0]["rear_coverage_scope"] == COVERAGE_SCOPE
    assert first.iloc[0]["rear_diffuse_model"] == "isotropic"
    assert str(first["rear_irradiance_resolved"].dtype) == "bool"
    assert str(first["poa_rear_global_raw_wm2"].dtype) == "float64"


def test_empty_scene_and_empty_timeseries_are_stable() -> None:
    empty_scene = FixedBifacialRearScene([], [], [], view_factor_points=10)
    empty = _calculate(empty_scene)
    assert empty.empty
    assert list(empty.columns)[0] == "ghi_wm2"
    index = pd.DatetimeIndex([], tz="UTC", name="time")
    inputs = tuple(pd.Series([], index=index, dtype="float64") for _ in range(5))
    result = _calculate(inputs=inputs)
    assert result.empty
    assert str(result["poa_rear_global_raw_wm2"].dtype) == "float64"
