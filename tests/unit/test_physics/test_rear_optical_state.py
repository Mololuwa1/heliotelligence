"""Tests for S7C-0 fixed-table rear optical state admission."""

from __future__ import annotations

from copy import deepcopy
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
from heliotelligence.physics.iam import BeamIAMModel, calculate_beam_iam
from heliotelligence.physics.iam_parameters import resolve_beam_iam_parameters
from heliotelligence.physics.rear_optical_state import (
    REAR_OPTICAL_STATE_CONTRACT_ID,
    REAR_OPTICAL_STATE_COVERAGE_SCOPE,
    REAR_OPTICAL_STATE_MODEL_ID,
    RearOpticalStateResult,
    calculate_rear_optical_state,
)
from heliotelligence.physics.shading import solar_direction_enu


def _normal() -> tuple[float, float, float]:
    tilt = np.radians(30.0)
    return float(np.sin(tilt)), 0.0, float(np.cos(tilt))


def _receiver(identifier: str, kind: ReceiverKind = ReceiverKind.FIXED_TABLE) -> PVReceiver:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0))),
        np.asarray(((0, 1, 2),)),
    )
    return PVReceiver(identifier, mesh, (0.3, 0.3, 1.0), _normal(), kind)


def _scene(receivers: list[PVReceiver]) -> FixedBifacialRearScene:
    rows = (
        FixedRowDefinition("row-0", (receivers[0].id,), 30.0, 2.0),
        FixedRowDefinition("row-1", (receivers[1].id,), 30.0, 2.0),
    )
    array = FixedRowArrayDefinition(
        "array",
        0.0,
        0.0,
        rows,
        (FixedRowBlockingPair("row-0", "row-1", 4.0, 0.0),),
    )
    return FixedBifacialRearScene(
        receivers,
        [array],
        [FixedBifacialRearParameters("array", 1.5, 0.2)],
        view_factor_points=40,
    )


def _inputs(*, missing: bool = False, zero: bool = False) -> tuple[pd.Series, ...]:
    index = pd.date_range("2026-06-01 09:00", periods=2, freq="h", tz="UTC", name="time")
    ghi: tuple[float, ...] = (800.0, 700.0)
    dhi: tuple[float, ...] = (120.0, 110.0)
    dni: tuple[float, ...] = (700.0, 600.0)
    if missing:
        ghi, dhi, dni = (np.nan, 700.0), (np.nan, 110.0), (np.nan, 600.0)
    if zero:
        ghi = dhi = dni = (0.0, 0.0)
    return (
        pd.Series(ghi, index=index),
        pd.Series(dhi, index=index),
        pd.Series(dni, index=index),
        pd.Series((60.0, 85.0), index=index),
        pd.Series((90.0, 270.0), index=index),
    )


def _parameters(
    model: BeamIAMModel = "ashrae",
    *,
    method: Literal["direct", "measured_fit", "explicit_fallback"] = "direct",
) -> dict[str, object]:
    values: dict[BeamIAMModel, dict[str, object]] = {
        "physical": {"n": 1.526, "K": 4.0, "L": 0.002, "n_ar": None},
        "ashrae": {"b": 0.08},
        "martin-ruiz": {"a_r": 0.18},
    }
    return resolve_beam_iam_parameters(
        model=model,
        method=method,
        source_label="rear coating",
        source_reference="rear-datasheet",
        model_parameters=values[model],
    )


def _bundle(
    *, model: str = "isotropic", missing: bool = False, zero: bool = False
) -> tuple[list[PVReceiver], pd.DataFrame, dict[str, object]]:
    receivers = [_receiver("r0"), _receiver("r1")]
    rear = calculate_fixed_bifacial_rear_irradiance(
        *_inputs(missing=missing, zero=zero),
        scene=_scene(receivers),
        model=model,  # type: ignore[arg-type]
    )
    return receivers, rear, _parameters()


def _calculate(
    bundle: tuple[list[PVReceiver], pd.DataFrame, dict[str, object]],
) -> RearOpticalStateResult:
    receivers, rear, parameters = bundle
    return calculate_rear_optical_state(
        receivers,
        rear,
        rear_beam_iam_parameters_by_receiver={receiver.id: parameters for receiver in receivers},
    )


@pytest.mark.parametrize("model", ["isotropic", "haydavies"])
def test_real_s6e_integration_components_and_contract(model: str) -> None:
    receivers, rear, parameters = _bundle(model=model)
    result = _calculate((receivers, rear, parameters))
    state = result.state
    assert (state["rear_optical_state_contract"] == REAR_OPTICAL_STATE_CONTRACT_ID).all()
    assert (state["rear_optical_state_model"] == REAR_OPTICAL_STATE_MODEL_ID).all()
    assert (
        state["rear_optical_state_coverage_scope"] == REAR_OPTICAL_STATE_COVERAGE_SCOPE
    ).all()
    np.testing.assert_allclose(
        state["poa_rear_isotropic_sky_raw_wm2"]
        + state["poa_rear_circumsolar_diffuse_raw_wm2"],
        state["poa_rear_sky_diffuse_raw_wm2"],
    )
    if model == "isotropic":
        assert (state["poa_rear_circumsolar_diffuse_raw_wm2"] == 0.0).all()
        np.testing.assert_allclose(
            state["poa_rear_isotropic_sky_raw_wm2"], state["poa_rear_sky_diffuse_raw_wm2"]
        )
    else:
        assert (state["poa_rear_circumsolar_diffuse_raw_wm2"] > 0.0).any()
    assert result.diagnostics.rear_diffuse_model == model


def test_row_physics_flags_and_direct_is_not_reattenuated() -> None:
    receivers, rear, parameters = _bundle()
    partial = (rear["rear_direct_shaded_fraction"] > 0) & (
        rear["rear_direct_shaded_fraction"] < 1
    )
    assert partial.any()
    state = _calculate((receivers, rear, parameters)).state
    np.testing.assert_array_equal(state["poa_rear_direct_raw_wm2"], rear["poa_rear_direct_raw_wm2"])
    np.testing.assert_allclose(
        state["rear_direct_row_visible_fraction"], 1.0 - rear["rear_direct_shaded_fraction"]
    )
    for column in (
        "rear_row_direct_shading_embedded",
        "rear_row_sky_view_factor_embedded",
        "rear_ground_row_shadowing_embedded",
        "rear_row_ground_view_factor_embedded",
    ):
        assert state[column].all()


def test_rear_normal_orientation_aoi_and_input_immutability() -> None:
    receivers, rear, parameters = _bundle()
    original = deepcopy(receivers)
    state = _calculate((receivers, rear, parameters)).state.xs("r0", level="receiver_id")
    np.testing.assert_allclose(
        state.iloc[0][["rear_normal_east", "rear_normal_north", "rear_normal_up"]].to_numpy(
            dtype=float
        ),
        -np.asarray(receivers[0].normal_enu),
    )
    for _timestamp, row in state.iterrows():
        direction = np.asarray(
            solar_direction_enu(
                float(row["apparent_solar_zenith_deg"]), float(row["solar_azimuth_deg"])
            )
        )
        expected = np.degrees(
            np.arccos(np.clip(np.dot(-np.asarray(_normal()), direction), -1, 1))
        )
        assert row["rear_aoi_deg"] == pytest.approx(expected)
    assert receivers == original


@pytest.mark.parametrize(
    ("column", "delta"),
    [
        ("rear_surface_tilt_deg", 1.0),
        ("rear_surface_azimuth_deg", 1.0),
        ("surface_tilt_deg", 1.0),
        ("surface_azimuth_deg", 1.0),
    ],
)
def test_orientation_tampering_is_rejected(column: str, delta: float) -> None:
    receivers, rear, parameters = _bundle()
    rear.loc[rear.index[0], column] += delta
    with pytest.raises(ValueError, match="conflicts"):
        _calculate((receivers, rear, parameters))


@pytest.mark.parametrize("model", ["physical", "ashrae", "martin-ruiz"])
def test_rear_iam_uses_explicit_rear_parameters(model: BeamIAMModel) -> None:
    receivers, rear, _ = _bundle()
    parameters = _parameters(model)
    state = _calculate((receivers, rear, parameters)).state.xs("r0", level="receiver_id")
    reference = calculate_beam_iam(
        state["rear_aoi_deg"],
        model=model,
        model_parameters=parameters["model_parameters"],  # type: ignore[arg-type]
    )
    np.testing.assert_allclose(state["rear_beam_iam_factor"], reference["beam_iam_factor"])
    assert (state["rear_beam_iam_model"] == model).all()
    assert (state["rear_iam_parameter_source_label"] == "rear coating").all()
    assert "poa_rear_direct_effective_wm2" not in state


def test_parameter_mapping_and_provenance_validation() -> None:
    receivers, rear, parameters = _bundle()
    with pytest.raises(ValueError, match="keys must exactly match"):
        calculate_rear_optical_state(
            receivers, rear, rear_beam_iam_parameters_by_receiver={"r0": parameters}
        )
    malformed = deepcopy(parameters)
    malformed["model_parameters"] = {"b": True}
    with pytest.raises(ValueError, match="finite real"):
        calculate_rear_optical_state(
            receivers,
            rear,
            rear_beam_iam_parameters_by_receiver={receiver.id: malformed for receiver in receivers},
        )


def test_all_parameter_resolution_provenance_methods_are_preserved() -> None:
    receivers, rear, _ = _bundle()
    parameter_sets = (
        _parameters(),
        resolve_beam_iam_parameters(
            model="ashrae",
            method="explicit_fallback",
            source_label="rear fallback",
            model_parameters={"b": 0.09},
        ),
        resolve_beam_iam_parameters(
            model="ashrae",
            method="measured_fit",
            source_label="rear measurement",
            measured_aoi_deg=(0.0, 30.0, 60.0),
            measured_iam=(1.0, 0.98, 0.90),
        ),
    )
    for parameters in parameter_sets:
        result = _calculate((receivers, rear, parameters)).state
        assert (
            result["rear_iam_parameter_resolution_method"] == parameters["resolution_method"]
        ).all()
        assert (result["rear_iam_parameter_is_fallback"] == parameters["is_fallback"]).all()


def test_receiver_identity_and_supported_kind_validation() -> None:
    receivers, rear, parameters = _bundle()
    with pytest.raises(ValueError, match="exactly match"):
        _calculate((receivers[:1], rear, parameters))
    with pytest.raises(ValueError, match="unique"):
        _calculate(([receivers[0], receivers[0]], rear, parameters))
    modules = [_receiver("r0", ReceiverKind.MODULE), _receiver("r1")]
    with pytest.raises(ValueError, match="FIXED_TABLE"):
        _calculate((modules, rear, parameters))
    malformed = deepcopy(parameters)
    malformed["source_label"] = ""
    with pytest.raises(ValueError, match="source_label"):
        calculate_rear_optical_state(
            receivers,
            rear,
            rear_beam_iam_parameters_by_receiver={receiver.id: malformed for receiver in receivers},
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("rear_irradiance_model", "wrong"),
        ("rear_coverage_scope", "wrong"),
    ],
)
def test_s6e_provenance_tampering_is_rejected(column: str, value: str) -> None:
    receivers, rear, parameters = _bundle()
    rear.loc[rear.index[0], column] = value
    with pytest.raises(ValueError):
        _calculate((receivers, rear, parameters))


def test_mixed_diffuse_models_are_rejected() -> None:
    receivers, rear, parameters = _bundle()
    rear.loc[rear.index[0], "rear_diffuse_model"] = "haydavies"
    with pytest.raises(ValueError, match="common"):
        _calculate((receivers, rear, parameters))


@pytest.mark.parametrize(
    "column",
    ["poa_rear_sky_diffuse_raw_wm2", "poa_rear_diffuse_raw_wm2", "poa_rear_global_raw_wm2"],
)
def test_raw_component_closure_tampering_is_rejected(column: str) -> None:
    receivers, rear, parameters = _bundle()
    rear.loc[rear.index[0], column] += 10.0
    with pytest.raises(ValueError, match="close|exceeds"):
        _calculate((receivers, rear, parameters))


@pytest.mark.parametrize("value", [-0.1, 1.1, np.nan, True])
def test_invalid_resolved_shaded_fraction_is_rejected(value: object) -> None:
    receivers, rear, parameters = _bundle()
    rear["rear_direct_shaded_fraction"] = rear["rear_direct_shaded_fraction"].astype(object)
    rear.loc[rear.index[0], "rear_direct_shaded_fraction"] = value
    with pytest.raises(ValueError):
        _calculate((receivers, rear, parameters))


def test_unresolved_upstream_and_zero_irradiance_semantics() -> None:
    missing = _calculate(_bundle(missing=True)).state.iloc[0]
    assert not bool(missing["rear_irradiance_resolved"])
    assert np.isnan(missing["poa_rear_global_raw_wm2"])
    assert missing["rear_optical_admission_state"] == "unresolved_upstream_rear_irradiance"
    zero = _calculate(_bundle(zero=True)).state
    assert zero["rear_irradiance_resolved"].all()
    assert (zero[[column for column in zero if column.startswith("poa_rear_")]] == 0.0).all().all()


def test_receiver_kind_determinism_and_empty_timestamps() -> None:
    receivers, rear, parameters = _bundle()
    first = _calculate((receivers, rear, parameters)).state
    second = _calculate((list(reversed(receivers)), rear.iloc[::-1], parameters)).state
    pd.testing.assert_frame_equal(first, second)
    tracker = [_receiver("r0", ReceiverKind.TRACKER_TABLE), _receiver("r1")]
    with pytest.raises(ValueError, match="S6C runtime tracker pose"):
        _calculate((tracker, rear, parameters))
    empty = _calculate((receivers, rear.iloc[:0], parameters))
    assert empty.state.empty
    assert list(empty.state.columns)
