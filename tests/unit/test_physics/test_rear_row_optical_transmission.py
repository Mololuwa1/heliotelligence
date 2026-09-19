"""Tests for S7C-1 row-conditioned rear optical transmission."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Literal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.fixed_bifacial_rear import (
    FixedBifacialRearParameters,
    FixedBifacialRearScene,
    calculate_fixed_bifacial_rear_irradiance,
)
from heliotelligence.physics.fixed_inter_row_shading import (
    FixedRowArrayDefinition,
    FixedRowBlockingPair,
    FixedRowDefinition,
)
from heliotelligence.physics.iam_parameters import resolve_beam_iam_parameters
from heliotelligence.physics.rear_optical_state import (
    RearOpticalStateResult,
    calculate_rear_optical_state,
)
from heliotelligence.physics.rear_row_optical_transmission import (
    REAR_ROW_OPTICAL_CONTRACT_ID,
    REAR_ROW_OPTICAL_COVERAGE_SCOPE,
    REAR_ROW_OPTICAL_MODEL_ID,
    RearRowOpticalTransmissionResult,
    calculate_rear_row_optical_transmission,
)


def _parameters(
    model: Literal["physical", "ashrae", "martin-ruiz"] = "ashrae",
    *,
    loss: float | None = None,
) -> dict[str, object]:
    values: dict[str, dict[str, object]] = {
        "physical": {"n": 1.526, "K": 4.0, "L": 0.002, "n_ar": None},
        "ashrae": {"b": 0.05 if loss is None else loss},
        "martin-ruiz": {"a_r": 0.18 if loss is None else loss},
    }
    return resolve_beam_iam_parameters(
        model=model,
        method="direct",
        source_label="rear coating",
        source_reference="rear datasheet",
        model_parameters=values[model],
    )


def _normal(rotation: float, axis_azimuth: float = 0.0) -> tuple[float, float, float]:
    theta = np.radians(rotation)
    axis = np.radians(axis_azimuth)
    return (
        float(np.sin(theta) * np.cos(axis)),
        float(-np.sin(theta) * np.sin(axis)),
        float(np.cos(theta)),
    )


def _bundle(
    *,
    rotation: float = 30.0,
    pitch: float = 4.0,
    width: float = 2.0,
    axis_azimuth: float = 0.0,
    model: Literal["isotropic", "haydavies"] = "isotropic",
    parameters: dict[str, object] | None = None,
    second_parameters: dict[str, object] | None = None,
    periods: int = 2,
) -> tuple[FixedBifacialRearScene, RearOpticalStateResult, dict[str, dict[str, object]]]:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0))),
        np.asarray(((0, 1, 2),)),
    )
    receivers = [
        PVReceiver(
            f"r{i}",
            mesh,
            (0.3, 0.3, 1.0),
            _normal(rotation, axis_azimuth),
            ReceiverKind.FIXED_TABLE,
        )
        for i in range(2)
    ]
    rows = tuple(
        FixedRowDefinition(f"row-{i}", (receiver.id,), rotation, width)
        for i, receiver in enumerate(receivers)
    )
    array = FixedRowArrayDefinition(
        "array",
        axis_azimuth,
        0.0,
        rows,
        (FixedRowBlockingPair("row-0", "row-1", pitch, 0.0),),
    )
    scene = FixedBifacialRearScene(
        receivers,
        [array],
        [FixedBifacialRearParameters("array", 1.5, 0.2)],
        view_factor_points=40,
    )
    index = pd.date_range("2026-06-01 09:00", periods=periods, freq="h", tz="UTC", name="time")
    base = ([800.0, 700.0], [120.0, 110.0], [700.0, 600.0], [60.0, 85.0], [90.0, 270.0])
    series = [pd.Series(values[:periods], index=index) for values in base]
    rear = calculate_fixed_bifacial_rear_irradiance(*series, scene=scene, model=model)
    selected = parameters or _parameters()
    mapping = {"r0": selected, "r1": second_parameters or selected}
    state = calculate_rear_optical_state(
        receivers, rear, rear_beam_iam_parameters_by_receiver=mapping
    )
    return scene, state, mapping


def _calculate(
    bundle: tuple[FixedBifacialRearScene, RearOpticalStateResult, dict[str, dict[str, object]]],
    *,
    rows: int = 64,
    directions: int = 8192,
) -> RearRowOpticalTransmissionResult:
    scene, state, mapping = bundle
    return calculate_rear_row_optical_transmission(
        state,
        scene=scene,
        rear_beam_iam_parameters_by_receiver=mapping,
        row_position_count=rows,
        sky_direction_count=directions,
        ground_direction_count=directions,
    )


def test_s6e_public_optical_geometry_is_deterministic_and_immutable() -> None:
    scene, _, _ = _bundle()
    first = scene.optical_geometry
    assert first == scene.optical_geometry
    geometry = first[0]
    assert geometry.receiver_ids == ("r0", "r1")
    assert geometry.collector_width_m == 2.0
    assert geometry.pitch_m == 4.0
    assert geometry.gcr == 0.5
    with pytest.raises(FrozenInstanceError):
        geometry.gcr = 0.4  # type: ignore[misc]


@pytest.mark.parametrize("model", ["isotropic", "haydavies"])
def test_real_s6e_s7c0_s7c1_contract_and_no_irradiance(model: str) -> None:
    result = _calculate(_bundle(model=model))  # type: ignore[arg-type]
    frame = result.transmission
    assert (frame["rear_row_optical_contract"] == REAR_ROW_OPTICAL_CONTRACT_ID).all()
    assert (frame["rear_row_optical_model"] == REAR_ROW_OPTICAL_MODEL_ID).all()
    assert (frame["rear_row_optical_coverage_scope"] == REAR_ROW_OPTICAL_COVERAGE_SCOPE).all()
    assert not any("effective_wm2" in column or "horizon" in column for column in frame)
    assert frame.index.names == ["time", "receiver_id"]


@pytest.mark.parametrize(
    ("rotation", "gcr"),
    [(15.0, 0.2), (30.0, 0.4), (-30.0, 0.7), (60.0, 0.95)],
)
def test_sky_and_ground_view_factor_parity(rotation: float, gcr: float) -> None:
    result = _calculate(_bundle(rotation=rotation, pitch=2.0 / gcr))
    row = result.transmission.iloc[0]
    assert row["rear_sky_view_factor_abs_error"] <= 1e-3
    assert row["rear_ground_view_factor_abs_error"] <= 1e-3
    assert result.diagnostics.maximum_sky_view_factor_abs_error <= 1e-3
    assert result.diagnostics.maximum_ground_view_factor_abs_error <= 1e-3


def test_horizontal_rear_has_no_sky_field_and_ground_resolves() -> None:
    row = _calculate(_bundle(rotation=0.0, axis_azimuth=37.0)).transmission.iloc[0]
    assert row["rear_sky_analytic_row_view_factor"] == pytest.approx(0.0, abs=1e-12)
    assert not row["rear_sky_row_conditioned_iam_resolved"]
    assert np.isnan(row["rear_sky_row_conditioned_iam_factor"])
    assert row["rear_sky_row_conditioned_iam_state"] == "not_applicable_no_row_visible_field"
    assert row["rear_ground_analytic_row_view_factor"] == pytest.approx(1.0)
    assert row["rear_ground_row_conditioned_iam_resolved"]


def test_unity_iam_does_not_reapply_row_view_factor() -> None:
    row = _calculate(_bundle(parameters=_parameters("ashrae", loss=0.0))).transmission.iloc[0]
    assert row["rear_sky_row_conditioned_iam_factor"] == pytest.approx(1.0)
    assert row["rear_ground_row_conditioned_iam_factor"] == pytest.approx(1.0)
    assert row["rear_sky_analytic_row_view_factor"] < 0.1
    assert row["rear_isotropic_sky_s6e_relative_optical_factor"] == pytest.approx(1.0)


def test_row_conditioning_is_nonseparable_and_row_factor_not_reapplied() -> None:
    row = _calculate(_bundle(parameters=_parameters("ashrae", loss=0.12))).transmission.iloc[0]
    conditioned = row["rear_sky_row_conditioned_iam_factor"]
    unobstructed = row["rear_sky_unobstructed_iam_reference"]
    view = row["rear_sky_analytic_row_view_factor"]
    assert abs(conditioned - unobstructed) > 0.02
    assert conditioned != pytest.approx(view * conditioned)
    assert row["rear_isotropic_sky_s6e_relative_optical_factor"] == conditioned
    assert (
        row["rear_ground_s6e_relative_optical_factor"]
        == row["rear_ground_row_conditioned_iam_factor"]
    )


def test_direct_and_haydavies_circumsolar_use_beam_iam_only() -> None:
    _, state, _ = bundle = _bundle(model="haydavies")
    assert (state.state["poa_rear_circumsolar_diffuse_raw_wm2"] > 0).any()
    frame = _calculate(bundle).transmission
    np.testing.assert_allclose(
        frame["rear_direct_s6e_relative_optical_factor"], state.state["rear_beam_iam_factor"]
    )
    np.testing.assert_allclose(
        frame["rear_circumsolar_s6e_relative_optical_factor"], state.state["rear_beam_iam_factor"]
    )


def test_diffuse_factors_are_static_across_weather() -> None:
    frame = _calculate(_bundle()).transmission
    for receiver_id in ("r0", "r1"):
        receiver = frame.xs(receiver_id, level="receiver_id")
        assert receiver["rear_sky_row_conditioned_iam_factor"].nunique() == 1
        assert receiver["rear_ground_row_conditioned_iam_factor"].nunique() == 1


def test_receiver_specific_rear_iam_parameters_remain_separate() -> None:
    result = _calculate(
        _bundle(
            parameters=_parameters("ashrae", loss=0.02),
            second_parameters=_parameters("ashrae", loss=0.15),
        )
    ).transmission
    first = result.xs("r0", level="receiver_id").iloc[0]
    second = result.xs("r1", level="receiver_id").iloc[0]
    assert first["rear_sky_row_conditioned_iam_factor"] != pytest.approx(
        second["rear_sky_row_conditioned_iam_factor"]
    )


def test_empty_timestamp_state_has_stable_schema() -> None:
    result = _calculate(_bundle(periods=0))
    assert result.transmission.empty
    assert result.transmission.index.names == ["time", "receiver_id"]
    assert "rear_ground_s6e_relative_optical_factor" in result.transmission
    assert result.diagnostics.source_state_row_count == 0


@pytest.mark.parametrize(
    "column",
    [
        "rear_optical_state_contract",
        "rear_optical_state_model",
        "rear_optical_state_coverage_scope",
        "rear_irradiance_model",
        "rear_coverage_scope",
        "rear_row_geometry_model",
    ],
)
def test_contract_tampering_is_rejected(column: str) -> None:
    scene, state, mapping = _bundle()
    state.state[column] = "tampered"
    with pytest.raises(ValueError, match="incompatible"):
        _calculate((scene, state, mapping))


@pytest.mark.parametrize(
    "column",
    [
        "rear_row_direct_shading_embedded",
        "rear_row_sky_view_factor_embedded",
        "rear_ground_row_shadowing_embedded",
        "rear_row_ground_view_factor_embedded",
    ],
)
def test_embedded_row_flag_tampering_is_rejected(column: str) -> None:
    scene, state, mapping = _bundle()
    state.state.loc[state.state.index[0], column] = False
    with pytest.raises(ValueError, match="embedded row physics"):
        _calculate((scene, state, mapping))


def test_array_id_and_parameter_mismatch_are_rejected() -> None:
    scene, state, mapping = _bundle()
    state.state["fixed_row_array_id"] = "other"
    with pytest.raises(ValueError, match="array ID"):
        _calculate((scene, state, mapping))
    scene, state, mapping = _bundle()
    changed = _parameters("ashrae", loss=0.2)
    with pytest.raises(ValueError, match="reproduce"):
        _calculate((scene, state, {identifier: changed for identifier in mapping}))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("model", "physical"),
        ("resolution_method", "measured_fit"),
        ("source_label", "other"),
        ("source_reference", "other"),
        ("is_fallback", True),
    ],
)
def test_parameter_provenance_mismatch_is_rejected(key: str, value: object) -> None:
    scene, state, mapping = _bundle()
    changed = {identifier: dict(parameters) for identifier, parameters in mapping.items()}
    changed["r0"][key] = value
    if key == "is_fallback":
        changed["r0"]["resolution_method"] = "explicit_fallback"
    with pytest.raises(ValueError, match="provenance|parameter"):
        _calculate((scene, state, changed))


@pytest.mark.parametrize(("rows", "directions"), [(31, 8192), (64, 2047), (True, 8192)])
def test_inadequate_or_boolean_quadrature_is_rejected(rows: object, directions: object) -> None:
    scene, state, mapping = _bundle()
    with pytest.raises(ValueError, match="must be"):
        calculate_rear_row_optical_transmission(
            state,
            scene=scene,
            rear_beam_iam_parameters_by_receiver=mapping,
            row_position_count=rows,  # type: ignore[arg-type]
            sky_direction_count=directions,  # type: ignore[arg-type]
            ground_direction_count=8192,
        )


def test_determinism() -> None:
    bundle = _bundle()
    pd.testing.assert_frame_equal(_calculate(bundle).transmission, _calculate(bundle).transmission)
