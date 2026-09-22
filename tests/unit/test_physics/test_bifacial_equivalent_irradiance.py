"""Tests for S7D-1 front/rear electrical-equivalent composition."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.geometry import PVReceiver, ReceiverKind, TriangleMesh
from heliotelligence.physics.bifacial_equivalent_irradiance import (
    _OUTPUT_COLUMNS,
    BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID,
    BIFACIAL_EQUIVALENT_IRRADIANCE_SCOPE,
    calculate_bifacial_electrical_equivalent_irradiance,
)
from heliotelligence.physics.bifacial_response import resolve_bifacial_response_parameters
from heliotelligence.physics.effective_irradiance import (
    EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
    EFFECTIVE_IRRADIANCE_MODEL_ID,
    FrontEffectiveIrradianceDiagnostics,
    FrontEffectiveIrradianceResult,
)
from heliotelligence.physics.rear_effective_irradiance import (
    REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID,
    REAR_EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
    REAR_EFFECTIVE_IRRADIANCE_MODEL_ID,
    REAR_EFFECTIVE_IRRADIANCE_SCOPE,
    RearEffectiveIrradianceDiagnostics,
    RearEffectiveIrradianceResult,
)
from tests.unit.test_physics import test_effective_irradiance as front_chain_support
from tests.unit.test_physics import test_rear_effective_irradiance as rear_chain_support


def _receivers(count: int = 1) -> list[PVReceiver]:
    mesh = TriangleMesh(
        np.asarray(((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0))),
        np.asarray(((0, 1, 2),)),
    )
    return [
        PVReceiver(
            f"r{i}", mesh, (0.3, 0.3, 1.0), (0.5, 0.0, 0.8660254038), ReceiverKind.FIXED_TABLE
        )
        for i in range(count)
    ]


def _index(ids: list[str], periods: int = 1) -> pd.MultiIndex:
    times = pd.date_range("2026-06-01", periods=periods, freq="h", tz="UTC", name="time")
    return pd.MultiIndex.from_product((times, ids), names=("time", "receiver_id"))


def _front(
    ids: list[str], *, periods: int = 1, resolved: bool = True
) -> FrontEffectiveIrradianceResult:
    index = _index(ids, periods)
    rows = []
    for _ in index:
        if resolved:
            row = {
                "surface_tilt_deg": 30.0,
                "surface_azimuth_deg": 90.0,
                "poa_front_direct_effective_wm2": 500.0,
                "poa_front_circumsolar_effective_wm2": 50.0,
                "poa_front_isotropic_effective_wm2": 100.0,
                "poa_front_horizon_effective_wm2": 20.0,
                "poa_front_ground_diffuse_effective_wm2": 30.0,
                "poa_front_sky_diffuse_effective_wm2": 170.0,
                "poa_front_diffuse_effective_wm2": 200.0,
                "poa_front_effective_optical_wm2": 700.0,
                "poa_front_global_raw_wm2": 750.0,
                **{
                    name: True
                    for name in (
                        "front_direct_effective_resolved",
                        "front_circumsolar_effective_resolved",
                        "front_isotropic_effective_resolved",
                        "front_horizon_effective_resolved",
                        "front_ground_diffuse_effective_resolved",
                    )
                },
                "front_effective_irradiance_resolved": True,
                "front_effective_irradiance_state": "resolved",
            }
        else:
            row = {
                "surface_tilt_deg": 30.0,
                "surface_azimuth_deg": 90.0,
                **{
                    name: np.nan
                    for name in (
                        "poa_front_direct_effective_wm2",
                        "poa_front_circumsolar_effective_wm2",
                        "poa_front_isotropic_effective_wm2",
                        "poa_front_horizon_effective_wm2",
                        "poa_front_ground_diffuse_effective_wm2",
                        "poa_front_sky_diffuse_effective_wm2",
                        "poa_front_diffuse_effective_wm2",
                        "poa_front_effective_optical_wm2",
                    )
                },
                **{
                    name: False
                    for name in (
                        "front_direct_effective_resolved",
                        "front_circumsolar_effective_resolved",
                        "front_isotropic_effective_resolved",
                        "front_horizon_effective_resolved",
                        "front_ground_diffuse_effective_resolved",
                    )
                },
                "front_effective_irradiance_resolved": False,
                "front_effective_irradiance_state": "unresolved_upstream_irradiance",
            }
        row.update(
            {
                "effective_irradiance_model": EFFECTIVE_IRRADIANCE_MODEL_ID,
                "effective_irradiance_coverage_scope": EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE,
                "effective_irradiance_scope": "front_surface_only",
            }
        )
        rows.append(row)
    frame = pd.DataFrame(rows, index=index)
    if not periods:
        frame = pd.DataFrame(columns=_front(ids).irradiance.columns, index=index)
    return FrontEffectiveIrradianceResult(
        frame,
        FrontEffectiveIrradianceDiagnostics(
            len(ids),
            periods,
            len(frame),
            int(resolved) * len(frame),
            int(not resolved) * len(frame),
            "perez",
            EFFECTIVE_IRRADIANCE_MODEL_ID,
        ),
    )


def _rear(
    ids: list[str], *, periods: int = 1, resolved: bool = True
) -> RearEffectiveIrradianceResult:
    index = _index(ids, periods)
    rows = []
    for _ in index:
        if resolved:
            row = {
                "poa_rear_direct_effective_wm2": 50.0,
                "poa_rear_circumsolar_diffuse_effective_wm2": 10.0,
                "poa_rear_isotropic_sky_effective_wm2": 20.0,
                "poa_rear_ground_diffuse_effective_wm2": 20.0,
                "poa_rear_sky_diffuse_effective_wm2": 30.0,
                "poa_rear_diffuse_effective_wm2": 50.0,
                "poa_rear_effective_optical_wm2": 100.0,
                "poa_rear_global_raw_wm2": 110.0,
                **{
                    name: True
                    for name in (
                        "rear_direct_effective_resolved",
                        "rear_circumsolar_effective_resolved",
                        "rear_isotropic_sky_effective_resolved",
                        "rear_ground_diffuse_effective_resolved",
                    )
                },
                "rear_effective_irradiance_resolved": True,
                "rear_effective_irradiance_state": "resolved",
            }
        else:
            row = {
                **{
                    name: np.nan
                    for name in (
                        "poa_rear_direct_effective_wm2",
                        "poa_rear_circumsolar_diffuse_effective_wm2",
                        "poa_rear_isotropic_sky_effective_wm2",
                        "poa_rear_ground_diffuse_effective_wm2",
                        "poa_rear_sky_diffuse_effective_wm2",
                        "poa_rear_diffuse_effective_wm2",
                        "poa_rear_effective_optical_wm2",
                    )
                },
                **{
                    name: False
                    for name in (
                        "rear_direct_effective_resolved",
                        "rear_circumsolar_effective_resolved",
                        "rear_isotropic_sky_effective_resolved",
                        "rear_ground_diffuse_effective_resolved",
                    )
                },
                "rear_effective_irradiance_resolved": False,
                "rear_effective_irradiance_state": "unresolved_upstream_rear_irradiance",
            }
        row.update(
            {
                "rear_effective_irradiance_contract": REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID,
                "rear_effective_irradiance_model": REAR_EFFECTIVE_IRRADIANCE_MODEL_ID,
                "rear_effective_irradiance_coverage_scope": (
                    REAR_EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE
                ),
                "rear_effective_irradiance_scope": REAR_EFFECTIVE_IRRADIANCE_SCOPE,
            }
        )
        rows.append(row)
    frame = pd.DataFrame(rows, index=index)
    if not periods:
        frame = pd.DataFrame(columns=_rear(ids).irradiance.columns, index=index)
    return RearEffectiveIrradianceResult(
        frame,
        RearEffectiveIrradianceDiagnostics(
            len(ids),
            periods,
            len(frame),
            int(resolved) * len(frame),
            int(not resolved) * len(frame),
            "isotropic",
            REAR_EFFECTIVE_IRRADIANCE_MODEL_ID,
        ),
    )


def _response(phi: float = 0.8) -> dict[str, object]:
    return resolve_bifacial_response_parameters(
        bifacial_enabled=True,
        method="direct",
        source_label="IEC report",
        source_reference="report",
        isc_bifaciality_factor=phi,
    )


def _mono() -> dict[str, object]:
    return resolve_bifacial_response_parameters(
        bifacial_enabled=False, method="monofacial_declared", source_label="declaration"
    )


def _real_front_chain(
    receivers: list[PVReceiver], *, periods: int = 1
) -> FrontEffectiveIrradianceResult:
    index = pd.date_range("2026-06-01 09:00", periods=periods, freq="h", tz="UTC", name="time")
    inputs = tuple(
        pd.Series(values[:periods], index=index)
        for values in ([800.0, 700.0], [120.0, 110.0], [700.0, 600.0], [60.0, 85.0], [90.0, 270.0])
    )
    transposition = {
        receiver.id: front_chain_support.calculate_raw_poa_transposition(
            *inputs,
            surface_tilt_deg=30.0,
            surface_azimuth_deg=90.0,
            albedo=0.2,
            model="perez-driesse",
        )
        for receiver in receivers
    }
    parameters = front_chain_support.resolve_beam_iam_parameters(
        model="ashrae",
        method="direct",
        source_label="test",
        source_reference="test-reference",
        model_parameters={"b": 0.05},
    )
    iam = {
        receiver.id: front_chain_support.calculate_beam_iam(
            transposition[receiver.id]["aoi_deg"],
            model="ashrae",
            model_parameters={"b": 0.05},
        )
        for receiver in receivers
    }
    raw = pd.DataFrame(
        {receiver.id: transposition[receiver.id]["poa_direct_raw_wm2"] for receiver in receivers}
    )
    rows = tuple(
        front_chain_support.FixedRowDefinition(f"row-{i}", (receiver.id,), 30.0, 2.0)
        for i, receiver in enumerate(receivers)
    )
    array = front_chain_support.FixedRowArrayDefinition(
        "array",
        0.0,
        0.0,
        rows,
        (rear_chain_support.FixedRowBlockingPair("row-0", "row-1", 4.0, 0.0),),
    )
    terrain = front_chain_support.calculate_terrain_horizon_direct_beam_shading(
        raw,
        inputs[3],
        inputs[4],
        scene=front_chain_support.TerrainHorizonScene(receivers, []),
    )
    fixed = front_chain_support.calculate_fixed_inter_row_direct_beam_shading(
        raw,
        inputs[3],
        inputs[4],
        scene=front_chain_support.FixedInterRowScene(receivers, [array]),
    )
    near = front_chain_support.calculate_near_object_direct_beam_shading(
        raw,
        inputs[3],
        inputs[4],
        scene=front_chain_support.NearObjectBeamScene(receivers, [], samples_per_receiver=4),
    )
    diffuse_scene = front_chain_support.DiffuseSkyScene(
        receivers, samples_per_receiver=4, sky_direction_count=64, max_rays_per_batch=31
    )
    near_authority, horizon_authority = front_chain_support._authorities(
        receivers, terrain, fixed, near, inputs[3], inputs[4]
    )
    optical = front_chain_support.assemble_receiver_optical_state(
        receivers,
        transposition,
        iam,
        terrain,
        fixed,
        near,
        diffuse_scene.calculate_visibility(),
        near_shading_authority=near_authority,
        far_horizon_authority=horizon_authority,
        rear_mode_by_receiver={receiver.id: "not_applicable" for receiver in receivers},
    )
    components = diffuse_scene.calculate_component_optical_transmission(
        horizon_zenith_count=2,
        horizon_azimuth_count=36,
        ground_direction_count=128,
        ground_plane_z_m=0.0,
        beam_iam_model_by_receiver={receiver.id: "ashrae" for receiver in receivers},
        model_parameters_by_receiver={receiver.id: {"b": 0.05} for receiver in receivers},
    )
    return front_chain_support.calculate_front_effective_irradiance(
        receivers,
        optical,
        components,
        beam_iam_parameters_by_receiver={receiver.id: parameters for receiver in receivers},
    )


def test_direct_phi_isc_and_unity_composition() -> None:
    receivers = _receivers()
    result = calculate_bifacial_electrical_equivalent_irradiance(
        receivers,
        _front(["r0"]),
        bifacial_response_parameters_by_receiver={"r0": _response()},
        rear_effective_irradiance=_rear(["r0"]),
    )
    row = result.irradiance.iloc[0]
    assert row["rear_electrical_equivalent_irradiance_wm2"] == 80.0
    assert row["bifacial_electrical_equivalent_irradiance_wm2"] == 780.0
    unity = calculate_bifacial_electrical_equivalent_irradiance(
        receivers,
        _front(["r0"]),
        bifacial_response_parameters_by_receiver={"r0": _response(1.0)},
        rear_effective_irradiance=_rear(["r0"]),
    ).irradiance.iloc[0]
    assert unity["rear_electrical_equivalent_irradiance_wm2"] == 100.0
    assert unity["bifacial_electrical_equivalent_irradiance_wm2"] == 800.0


def test_monofacial_requires_no_rear_and_rejects_rear() -> None:
    receivers = _receivers()
    row = calculate_bifacial_electrical_equivalent_irradiance(
        receivers,
        _front(["r0"]),
        bifacial_response_parameters_by_receiver={"r0": _mono()},
    ).irradiance.iloc[0]
    assert row["rear_electrical_equivalent_irradiance_wm2"] == 0.0
    assert row["rear_electrical_equivalent_state"] == "resolved_monofacial_zero"
    assert row["bifacial_electrical_equivalent_irradiance_wm2"] == 700.0
    assert np.isnan(row["poa_rear_effective_optical_wm2"])
    with pytest.raises(ValueError, match="must not receive"):
        calculate_bifacial_electrical_equivalent_irradiance(
            receivers,
            _front(["r0"]),
            bifacial_response_parameters_by_receiver={"r0": _mono()},
            rear_effective_irradiance=_rear(["r0"]),
        )


def test_bifacial_requires_rear() -> None:
    with pytest.raises(ValueError, match="required"):
        calculate_bifacial_electrical_equivalent_irradiance(
            _receivers(),
            _front(["r0"]),
            bifacial_response_parameters_by_receiver={"r0": _response()},
        )


@pytest.mark.parametrize(
    ("front_resolved", "rear_resolved", "state"),
    [
        (False, True, "unresolved_front_effective_irradiance"),
        (True, False, "unresolved_rear_effective_irradiance"),
        (False, False, "unresolved_front_and_rear_effective_irradiance"),
    ],
)
def test_unresolved_state_propagation(
    front_resolved: bool, rear_resolved: bool, state: str
) -> None:
    result = calculate_bifacial_electrical_equivalent_irradiance(
        _receivers(),
        _front(["r0"], resolved=front_resolved),
        bifacial_response_parameters_by_receiver={"r0": _response()},
        rear_effective_irradiance=_rear(["r0"], resolved=rear_resolved),
    ).irradiance.iloc[0]
    assert not result["bifacial_electrical_equivalent_resolved"]
    assert np.isnan(result["bifacial_electrical_equivalent_irradiance_wm2"])
    assert result["bifacial_electrical_equivalent_state"] == state


def test_monofacial_front_unresolved_has_zero_resolved_rear() -> None:
    row = calculate_bifacial_electrical_equivalent_irradiance(
        _receivers(),
        _front(["r0"], resolved=False),
        bifacial_response_parameters_by_receiver={"r0": _mono()},
    ).irradiance.iloc[0]
    assert row["rear_electrical_equivalent_resolved"]
    assert row["rear_electrical_equivalent_irradiance_wm2"] == 0.0
    assert row["bifacial_electrical_equivalent_state"] == "unresolved_front_effective_irradiance"


@pytest.mark.parametrize(
    "field",
    [
        "bifaciality_coefficient_kind",
        "isc_bifaciality_factor",
        "resolution_method",
        "source_label",
        "source_reference",
        "is_fallback",
        "derivation_note",
        "equivalent_irradiance_formula",
        "bifacial_response_contract",
        "bifacial_response_model",
        "bifacial_response_standard_basis",
        "bifacial_response_scope",
    ],
)
def test_s7d0_replay_rejects_tampering(field: str) -> None:
    parameters = _response()
    parameters[field] = "" if field in ("source_label", "source_reference") else "tampered"
    with pytest.raises(ValueError):
        calculate_bifacial_electrical_equivalent_irradiance(
            _receivers(),
            _front(["r0"]),
            bifacial_response_parameters_by_receiver={"r0": parameters},
            rear_effective_irradiance=_rear(["r0"]),
        )


def test_response_schema_rejects_missing_and_extra_keys() -> None:
    for mutate in ("missing", "extra"):
        parameters = _response()
        parameters.pop("derivation_note") if mutate == "missing" else parameters.update(
            {"extra": 1}
        )
        with pytest.raises(ValueError, match="15 keys"):
            calculate_bifacial_electrical_equivalent_irradiance(
                _receivers(),
                _front(["r0"]),
                bifacial_response_parameters_by_receiver={"r0": parameters},
                rear_effective_irradiance=_rear(["r0"]),
            )


@pytest.mark.parametrize(
    ("column", "rear"),
    [
        ("effective_irradiance_model", False),
        ("effective_irradiance_coverage_scope", False),
        ("effective_irradiance_scope", False),
        ("rear_effective_irradiance_contract", True),
        ("rear_effective_irradiance_model", True),
        ("rear_effective_irradiance_coverage_scope", True),
        ("rear_effective_irradiance_scope", True),
    ],
)
def test_upstream_contract_tampering(column: str, rear: bool) -> None:
    front_result, rear_result = _front(["r0"]), _rear(["r0"])
    target = rear_result.irradiance if rear else front_result.irradiance
    target.loc[target.index[0], column] = pd.NA
    with pytest.raises(ValueError, match="incompatible"):
        calculate_bifacial_electrical_equivalent_irradiance(
            _receivers(),
            front_result,
            bifacial_response_parameters_by_receiver={"r0": _response()},
            rear_effective_irradiance=rear_result,
        )


def test_closure_tampering_and_strict_boolean() -> None:
    front = _front(["r0"])
    front.irradiance.loc[front.irradiance.index[0], "poa_front_diffuse_effective_wm2"] += 1
    with pytest.raises(ValueError, match="closure"):
        calculate_bifacial_electrical_equivalent_irradiance(
            _receivers(),
            front,
            bifacial_response_parameters_by_receiver={"r0": _response()},
            rear_effective_irradiance=_rear(["r0"]),
        )
    front = _front(["r0"])
    front.irradiance["front_effective_irradiance_resolved"] = front.irradiance[
        "front_effective_irradiance_resolved"
    ].astype(object)
    front.irradiance.iloc[
        0, front.irradiance.columns.get_loc("front_effective_irradiance_resolved")
    ] = 1
    with pytest.raises(ValueError, match="Boolean"):
        calculate_bifacial_electrical_equivalent_irradiance(
            _receivers(),
            front,
            bifacial_response_parameters_by_receiver={"r0": _response()},
            rear_effective_irradiance=_rear(["r0"]),
        )


@pytest.mark.parametrize(("side", "total_resolved"), [("front", False), ("rear", False)])
def test_all_components_resolved_requires_total_resolved(side: str, total_resolved: bool) -> None:
    front, rear = _front(["r0"]), _rear(["r0"])
    target = front.irradiance if side == "front" else rear.irradiance
    prefix = "front" if side == "front" else "rear"
    target.loc[target.index[0], f"{prefix}_effective_irradiance_resolved"] = total_resolved
    target.loc[target.index[0], f"{prefix}_effective_irradiance_state"] = (
        "unresolved_component_dependency"
    )
    aggregate_columns = (
        (
            "poa_front_sky_diffuse_effective_wm2",
            "poa_front_diffuse_effective_wm2",
            "poa_front_effective_optical_wm2",
        )
        if side == "front"
        else ("poa_rear_effective_optical_wm2",)
    )
    target.loc[target.index[0], list(aggregate_columns)] = np.nan
    with pytest.raises(ValueError, match="total/component resolution"):
        calculate_bifacial_electrical_equivalent_irradiance(
            _receivers(),
            front,
            bifacial_response_parameters_by_receiver={"r0": _response()},
            rear_effective_irradiance=rear,
        )


@pytest.mark.parametrize("side", ["front", "rear"])
def test_unresolved_component_requires_total_unresolved(side: str) -> None:
    front, rear = _front(["r0"]), _rear(["r0"])
    target = front.irradiance if side == "front" else rear.irradiance
    component = (
        "poa_front_direct_effective_wm2" if side == "front" else "poa_rear_direct_effective_wm2"
    )
    flag = (
        "front_direct_effective_resolved" if side == "front" else "rear_direct_effective_resolved"
    )
    target.loc[target.index[0], component] = np.nan
    target.loc[target.index[0], flag] = False
    with pytest.raises(ValueError, match="total/component resolution"):
        calculate_bifacial_electrical_equivalent_irradiance(
            _receivers(),
            front,
            bifacial_response_parameters_by_receiver={"r0": _response()},
            rear_effective_irradiance=rear,
        )


def test_output_schema_is_stable_across_python_hash_seeds() -> None:
    code = (
        "import json; "
        "from heliotelligence.physics.bifacial_equivalent_irradiance "
        "import _OUTPUT_COLUMNS; print(json.dumps(_OUTPUT_COLUMNS))"
    )
    outputs = []
    for seed in ("1", "2"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.run(
                [sys.executable, "-c", code],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout
        )
    assert outputs[0] == outputs[1]
    assert tuple(json.loads(outputs[0])) == _OUTPUT_COLUMNS


def test_real_front_and_rear_production_chains_compose() -> None:
    receivers, state, transmission = rear_chain_support._chain(periods=1)
    front = _real_front_chain(receivers)
    rear = rear_chain_support._calculate((receivers, state, transmission))
    response = _response(0.8)
    result = calculate_bifacial_electrical_equivalent_irradiance(
        receivers,
        front,
        bifacial_response_parameters_by_receiver={receiver.id: response for receiver in receivers},
        rear_effective_irradiance=rear,
    )
    for index, row in result.irradiance.iterrows():
        front_value = front.irradiance.loc[index, "poa_front_effective_optical_wm2"]
        rear_value = rear.irradiance.loc[index, "poa_rear_effective_optical_wm2"]
        expected_rear = 0.8 * rear_value
        assert row["rear_electrical_equivalent_irradiance_wm2"] == pytest.approx(expected_rear)
        assert row["bifacial_electrical_equivalent_irradiance_wm2"] == pytest.approx(
            front_value + expected_rear
        )
        assert row["front_effective_irradiance_model"] == EFFECTIVE_IRRADIANCE_MODEL_ID
        assert row["rear_effective_irradiance_contract"] == REAR_EFFECTIVE_IRRADIANCE_CONTRACT_ID
        assert row["rear_effective_irradiance_model"] == REAR_EFFECTIVE_IRRADIANCE_MODEL_ID
        assert (
            row["rear_effective_irradiance_coverage_scope"]
            == REAR_EFFECTIVE_IRRADIANCE_COVERAGE_SCOPE
        )
        assert row["rear_effective_irradiance_scope"] == REAR_EFFECTIVE_IRRADIANCE_SCOPE


def test_reordering_empty_and_determinism() -> None:
    receivers = _receivers(2)
    parameters = {"r0": _response(0.8), "r1": _response(0.6)}
    front, rear = _front(["r0", "r1"], periods=2), _rear(["r0", "r1"], periods=2)
    first = calculate_bifacial_electrical_equivalent_irradiance(
        receivers,
        front,
        bifacial_response_parameters_by_receiver=parameters,
        rear_effective_irradiance=rear,
    )
    reordered_front = FrontEffectiveIrradianceResult(front.irradiance.iloc[::-1], front.diagnostics)
    reordered_rear = RearEffectiveIrradianceResult(rear.irradiance.iloc[::-1], rear.diagnostics)
    second = calculate_bifacial_electrical_equivalent_irradiance(
        receivers[::-1],
        reordered_front,
        bifacial_response_parameters_by_receiver=dict(reversed(list(parameters.items()))),
        rear_effective_irradiance=reordered_rear,
    )
    pd.testing.assert_frame_equal(first.irradiance, second.irradiance)
    assert (
        first.irradiance.xs("r0", level="receiver_id").iloc[0][
            "rear_electrical_equivalent_irradiance_wm2"
        ]
        == 80
    )
    assert (
        first.irradiance.xs("r1", level="receiver_id").iloc[0][
            "rear_electrical_equivalent_irradiance_wm2"
        ]
        == 60
    )
    empty_front, empty_rear = _front(["r0"], periods=0), _rear(["r0"], periods=0)
    empty = calculate_bifacial_electrical_equivalent_irradiance(
        receivers[:1],
        empty_front,
        bifacial_response_parameters_by_receiver={"r0": _response()},
        rear_effective_irradiance=empty_rear,
    )
    assert empty.irradiance.empty and empty.diagnostics.receiver_count == 1


def test_output_contract_and_non_goals() -> None:
    result = calculate_bifacial_electrical_equivalent_irradiance(
        _receivers(),
        _front(["r0"]),
        bifacial_response_parameters_by_receiver={"r0": _response()},
        rear_effective_irradiance=_rear(["r0"]),
    )
    row = result.irradiance.iloc[0]
    assert (
        row["bifacial_equivalent_irradiance_contract"] == BIFACIAL_EQUIVALENT_IRRADIANCE_CONTRACT_ID
    )
    assert row["bifacial_equivalent_irradiance_scope"] == BIFACIAL_EQUIVALENT_IRRADIANCE_SCOPE
    assert tuple(result.irradiance.columns) == _OUTPUT_COLUMNS
    forbidden = ("spectral", "temperature", "heat_flux", "absorbed", "p_dc", "p_mp")
    assert not any(any(term in column for term in forbidden) for column in result.irradiance)
