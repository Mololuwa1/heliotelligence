"""Tests for S7C-2 rear optical-effective irradiance composition."""

from __future__ import annotations

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
from heliotelligence.physics.rear_effective_irradiance import (
    REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID,
    REAR_EFFECTIVE_IRRADIANCE_SCOPE,
    RearEffectiveIrradianceResult,
    calculate_rear_effective_irradiance,
)
from heliotelligence.physics.rear_optical_state import (
    RearOpticalStateResult,
    calculate_rear_optical_state,
)
from heliotelligence.physics.rear_row_optical_transmission import (
    RearRowOpticalTransmissionResult,
    calculate_rear_row_optical_transmission,
)


def _normal(rotation: float) -> tuple[float, float, float]:
    angle = np.radians(rotation)
    return float(np.sin(angle)), 0.0, float(np.cos(angle))


def _parameters(loss: float = 0.05) -> dict[str, object]:
    return resolve_beam_iam_parameters(
        model="ashrae",
        method="direct",
        source_label="rear coating",
        source_reference="rear datasheet",
        model_parameters={"b": loss},
    )


def _chain(
    *,
    model: Literal["isotropic", "haydavies"] = "isotropic",
    rotation: float = 30.0,
    loss: float = 0.05,
    missing: bool = False,
    zero: bool = False,
    periods: int = 2,
) -> tuple[list[PVReceiver], RearOpticalStateResult, RearRowOpticalTransmissionResult]:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0))),
        np.asarray(((0, 1, 2),)),
    )
    receivers = [
        PVReceiver(
            f"r{i}",
            mesh,
            (0.3, 0.3, 1.0),
            _normal(rotation),
            ReceiverKind.FIXED_TABLE,
        )
        for i in range(2)
    ]
    rows = tuple(
        FixedRowDefinition(f"row-{i}", (receiver.id,), rotation, 2.0)
        for i, receiver in enumerate(receivers)
    )
    array = FixedRowArrayDefinition(
        "array",
        0.0,
        0.0,
        rows,
        (FixedRowBlockingPair("row-0", "row-1", 4.0, 0.0),),
    )
    scene = FixedBifacialRearScene(
        receivers,
        [array],
        [FixedBifacialRearParameters("array", 1.5, 0.2)],
        view_factor_points=40,
    )
    index = pd.date_range("2026-06-01 09:00", periods=periods, freq="h", tz="UTC", name="time")
    ghi, dhi, dni = [800.0, 700.0], [120.0, 110.0], [700.0, 600.0]
    if missing:
        ghi[0] = np.nan
    if zero:
        ghi = dhi = dni = [0.0, 0.0]
    values = (ghi, dhi, dni, [60.0, 85.0], [90.0, 270.0])
    series = [pd.Series(item[:periods], index=index) for item in values]
    rear = calculate_fixed_bifacial_rear_irradiance(*series, scene=scene, model=model)
    parameters = _parameters(loss)
    mapping = {receiver.id: parameters for receiver in receivers}
    state = calculate_rear_optical_state(
        receivers, rear, rear_beam_iam_parameters_by_receiver=mapping
    )
    transmission = calculate_rear_row_optical_transmission(
        state,
        scene=scene,
        rear_beam_iam_parameters_by_receiver=mapping,
        row_position_count=64,
        sky_direction_count=8192,
        ground_direction_count=8192,
    )
    return receivers, state, transmission


def _calculate(
    chain: tuple[list[PVReceiver], RearOpticalStateResult, RearRowOpticalTransmissionResult],
) -> RearEffectiveIrradianceResult:
    return calculate_rear_effective_irradiance(*chain)


def _state_copy(result: RearOpticalStateResult) -> RearOpticalStateResult:
    return RearOpticalStateResult(result.state.copy(), result.diagnostics)


def _transmission_copy(
    result: RearRowOpticalTransmissionResult,
) -> RearRowOpticalTransmissionResult:
    return RearRowOpticalTransmissionResult(result.transmission.copy(), result.diagnostics)


@pytest.mark.parametrize("model", ["isotropic", "haydavies"])
def test_real_end_to_end_component_equations_and_closure(
    model: Literal["isotropic", "haydavies"],
) -> None:
    result = _calculate(_chain(model=model))
    frame = result.irradiance
    for _, row in frame.iterrows():
        assert row["poa_rear_direct_effective_wm2"] == pytest.approx(
            row["poa_rear_direct_raw_wm2"] * row["rear_direct_s6e_relative_optical_factor"]
        )
        assert row["poa_rear_circumsolar_diffuse_effective_wm2"] == pytest.approx(
            row["poa_rear_circumsolar_diffuse_raw_wm2"]
            * row["rear_circumsolar_s6e_relative_optical_factor"]
        )
        assert row["poa_rear_isotropic_sky_effective_wm2"] == pytest.approx(
            row["poa_rear_isotropic_sky_raw_wm2"]
            * row["rear_isotropic_sky_s6e_relative_optical_factor"]
        )
        assert row["poa_rear_ground_diffuse_effective_wm2"] == pytest.approx(
            row["poa_rear_ground_diffuse_raw_wm2"] * row["rear_ground_s6e_relative_optical_factor"]
        )
        assert row["poa_rear_sky_diffuse_effective_wm2"] == pytest.approx(
            row["poa_rear_circumsolar_diffuse_effective_wm2"]
            + row["poa_rear_isotropic_sky_effective_wm2"]
        )
        assert row["poa_rear_effective_optical_wm2"] <= row["poa_rear_global_raw_wm2"] + 1e-9
    assert (
        frame["rear_effective_irradiance_contract"] == REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID
    ).all()
    assert (frame["rear_effective_irradiance_scope"] == REAR_EFFECTIVE_IRRADIANCE_SCOPE).all()
    if model == "isotropic":
        assert (frame["poa_rear_circumsolar_diffuse_effective_wm2"] == 0.0).all()
    else:
        assert (frame["poa_rear_circumsolar_diffuse_raw_wm2"] > 0).any()


def test_unity_iam_does_not_reapply_row_geometry() -> None:
    _, _, transmission = chain = _chain(loss=0.0)
    assert (transmission.transmission["rear_sky_analytic_row_view_factor"] < 0.1).all()
    result = _calculate(chain).irradiance
    np.testing.assert_allclose(
        result["poa_rear_effective_optical_wm2"], result["poa_rear_global_raw_wm2"]
    )
    np.testing.assert_allclose(
        result["poa_rear_isotropic_sky_effective_wm2"],
        result["poa_rear_isotropic_sky_raw_wm2"],
    )
    np.testing.assert_allclose(
        result["poa_rear_ground_diffuse_effective_wm2"],
        result["poa_rear_ground_diffuse_raw_wm2"],
    )


def test_horizontal_rear_zero_sky_dependency_resolves() -> None:
    result = _calculate(_chain(rotation=0.0)).irradiance
    assert (result["poa_rear_isotropic_sky_raw_wm2"] == 0).all()
    assert (result["poa_rear_isotropic_sky_effective_wm2"] == 0).all()
    assert result["rear_isotropic_sky_effective_resolved"].all()
    assert result["rear_effective_irradiance_resolved"].all()


def test_upstream_unresolved_and_zero_irradiance_semantics() -> None:
    unresolved = _calculate(_chain(missing=True)).irradiance.iloc[0]
    assert unresolved.filter(like="effective_wm2").isna().all()
    assert unresolved["rear_effective_irradiance_state"] == "unresolved_upstream_rear_irradiance"
    zero = _calculate(_chain(zero=True)).irradiance
    assert (zero.filter(like="effective_wm2") == 0).all().all()
    assert zero["rear_effective_irradiance_resolved"].all()


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
def test_s7c0_contract_tampering_is_rejected(column: str) -> None:
    receivers, state, transmission = _chain()
    state = _state_copy(state)
    state.state.loc[state.state.index[0], column] = pd.NA
    with pytest.raises(ValueError, match="incompatible"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


@pytest.mark.parametrize(
    "column",
    ["rear_row_optical_contract", "rear_row_optical_model", "rear_row_optical_coverage_scope"],
)
def test_s7c1_contract_tampering_is_rejected(column: str) -> None:
    receivers, state, transmission = _chain()
    transmission = _transmission_copy(transmission)
    transmission.transmission.loc[transmission.transmission.index[0], column] = "tampered"
    with pytest.raises(ValueError, match="incompatible"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


@pytest.mark.parametrize("bad", [False, 0, 1, "True", pd.NA])
def test_row_embedding_flag_is_strict(bad: object) -> None:
    receivers, state, transmission = _chain()
    transmission = _transmission_copy(transmission)
    transmission.transmission["rear_row_geometry_already_embedded"] = transmission.transmission[
        "rear_row_geometry_already_embedded"
    ].astype(object)
    transmission.transmission.loc[
        transmission.transmission.index[0], "rear_row_geometry_already_embedded"
    ] = bad
    with pytest.raises(ValueError, match="Boolean|embedded"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


@pytest.mark.parametrize("bad", [-0.01, 1.01, np.nan, np.inf, True])
def test_resolved_factor_range_and_type_are_strict(bad: object) -> None:
    receivers, state, transmission = _chain()
    transmission = _transmission_copy(transmission)
    column = "rear_direct_s6e_relative_optical_factor"
    transmission.transmission[column] = transmission.transmission[column].astype(object)
    transmission.transmission.loc[transmission.transmission.index[0], column] = bad
    with pytest.raises(ValueError, match="finite|within"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


@pytest.mark.parametrize("bad", [0, 1, "True", "False", pd.NA])
def test_factor_resolution_boolean_is_strict(bad: object) -> None:
    receivers, state, transmission = _chain()
    transmission = _transmission_copy(transmission)
    column = "rear_direct_s6e_relative_optical_resolved"
    transmission.transmission[column] = transmission.transmission[column].astype(object)
    transmission.transmission.loc[transmission.transmission.index[0], column] = bad
    with pytest.raises(ValueError, match="Boolean"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


@pytest.mark.parametrize(
    "column",
    [
        "poa_rear_direct_raw_wm2",
        "poa_rear_circumsolar_diffuse_raw_wm2",
        "poa_rear_isotropic_sky_raw_wm2",
        "poa_rear_ground_diffuse_raw_wm2",
    ],
)
@pytest.mark.parametrize("bad", [-1.0, np.nan, np.inf, True])
def test_resolved_raw_component_type_and_bounds(column: str, bad: object) -> None:
    receivers, state, transmission = _chain()
    state = _state_copy(state)
    state.state[column] = state.state[column].astype(object)
    state.state.loc[state.state.index[0], column] = bad
    with pytest.raises(ValueError, match="finite non-negative"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


@pytest.mark.parametrize(
    "column",
    ["poa_rear_sky_diffuse_raw_wm2", "poa_rear_diffuse_raw_wm2", "poa_rear_global_raw_wm2"],
)
def test_raw_closure_tampering_is_rejected(column: str) -> None:
    receivers, state, transmission = _chain()
    state = _state_copy(state)
    state.state.loc[state.state.index[0], column] += 1.0
    with pytest.raises(ValueError, match="closure"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


@pytest.mark.parametrize(
    "column",
    [
        "rear_circumsolar_s6e_relative_optical_factor",
        "rear_isotropic_sky_s6e_relative_optical_factor",
        "rear_ground_s6e_relative_optical_factor",
    ],
)
def test_factor_internal_parity_tampering_is_rejected(column: str) -> None:
    receivers, state, transmission = _chain()
    transmission = _transmission_copy(transmission)
    transmission.transmission.loc[transmission.transmission.index[0], column] = 0.5
    with pytest.raises(ValueError, match="factor"):
        calculate_rear_effective_irradiance(receivers, state, transmission)


def test_index_mismatch_duplicate_and_reordering() -> None:
    receivers, state, transmission = _chain()
    expected = calculate_rear_effective_irradiance(receivers, state, transmission).irradiance
    reversed_state = RearOpticalStateResult(state.state.iloc[::-1], state.diagnostics)
    reversed_transmission = RearRowOpticalTransmissionResult(
        transmission.transmission.iloc[::-1], transmission.diagnostics
    )
    pd.testing.assert_frame_equal(
        calculate_rear_effective_irradiance(
            receivers[::-1], reversed_state, reversed_transmission
        ).irradiance,
        expected,
    )
    missing = _transmission_copy(transmission)
    missing = RearRowOpticalTransmissionResult(missing.transmission.iloc[:-1], missing.diagnostics)
    with pytest.raises(ValueError, match="every timestamp"):
        calculate_rear_effective_irradiance(receivers, state, missing)


def test_empty_timestamps_and_determinism() -> None:
    chain = _chain(periods=0)
    first = _calculate(chain)
    second = _calculate(chain)
    pd.testing.assert_frame_equal(first.irradiance, second.irradiance)
    assert first.irradiance.empty
    assert first.irradiance.index.names == ["time", "receiver_id"]
    assert first.diagnostics.receiver_count == 2
    assert first.diagnostics.row_count == 0


def test_no_horizon_bifacial_or_generic_factor_outputs() -> None:
    columns = _calculate(_chain()).irradiance.columns
    assert not any("horizon" in column for column in columns)
    assert not any("bifacial" in column for column in columns)
    assert "rear_total_optical_factor" not in columns
    assert "rear_diffuse_optical_factor" not in columns
