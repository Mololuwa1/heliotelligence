"""Tests for S8-3C common-voltage aggregation at the MPPT-input plane."""

from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

import heliotelligence.physics.dc_collection as dc_collection  # type: ignore[import-untyped]
from heliotelligence.config.site import (  # type: ignore[import-untyped]
    DcBranchPathConfig,
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    SiteConfig,
    StringConfig,
)
from heliotelligence.physics.dc_collection import (
    MPPT_INPUT_COMMON_VOLTAGE_CONTRACT_ID,
    MPPT_INPUT_COMMON_VOLTAGE_COVERAGE_SCOPE,
    MPPT_INPUT_COMMON_VOLTAGE_MODEL_ID,
    MPPT_INPUT_COMMON_VOLTAGE_SCOPE,
    MPPT_INPUT_REFERENCE_PLANE,
    STRING_TERMINAL_REFERENCE_PLANE,
    TopologyMpptInputOperatingPointResult,
    TopologyMpptInputStringIVResult,
    calculate_topology_mppt_input_operating_points,
    calculate_topology_mppt_input_string_iv,
    resolve_dc_branch_path_authority,
)
from heliotelligence.physics.electrical import (  # type: ignore[import-untyped]
    calculate_topology_mppt_mismatch_from_string_iv,
)

s8_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_state_aware_mppt_mismatch"
)
branch_support: Any = importlib.import_module(
    "tests.unit.test_physics.test_dc_branch_iv_transform"
)


def _path(resistance: float | None) -> DcBranchPathConfig | None:
    if resistance is None:
        return None
    return DcBranchPathConfig(
        series_resistance_ohm=resistance,
        parameter_source="as_built_schedule:test",
        confidence="high",
    )


def _topology(
    mppts: list[tuple[str, list[tuple[str, float | None]]]],
    *,
    inverter_id: str = "inverter-1",
) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inverter_id,
                mppts=[
                    MPPTConfig(
                        id=mppt_id,
                        strings=[
                            StringConfig(
                                id=string_id,
                                modules_per_string=24,
                                dc_branch_path=_path(resistance),
                            )
                            for string_id, resistance in strings
                        ],
                    )
                    for mppt_id, strings in mppts
                ],
            )
        ]
    )


def _s8b(
    topology: ElectricalTopologyConfig,
    *,
    zero: bool = False,
    periods: int = 1,
    receiver_count: int | None = None,
) -> tuple[Any, TopologyMpptInputStringIVResult]:
    count = receiver_count or max(topology.string_count, 1)
    _, s81 = s8_support._real_s81(
        topology,
        zero=zero,
        periods=periods,
        receiver_count=count,
    )
    return s81, calculate_topology_mppt_input_string_iv(
        topology,
        s81,
        resolve_dc_branch_path_authority(topology),
    )


def _run(
    topology: ElectricalTopologyConfig,
    value: TopologyMpptInputStringIVResult,
) -> TopologyMpptInputOperatingPointResult:
    return calculate_topology_mppt_input_operating_points(topology, value)


def _curve_like(
    result: TopologyMpptInputStringIVResult,
    string_id: str,
    voltage: list[float],
    current: list[float],
) -> pd.DataFrame:
    state = result.states.xs(string_id, level="string_id").iloc[0]
    timestamp = result.states.index.get_level_values("timestamp")[0]
    volts = np.asarray(voltage, dtype=float)
    amps = np.asarray(current, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": [timestamp] * len(volts),
            "curve_point": range(len(volts)),
            "voltage_v": volts,
            "current_a": amps,
            "power_w": volts * amps,
            "effective_irradiance_wm2": [
                state["spectral_electrical_equivalent_irradiance_wm2"]
            ]
            * len(volts),
            "tier_used": [state["tier_used"]] * len(volts),
            "fit_quality": [state["fit_quality"]] * len(volts),
        }
    )


def _replace_curves(
    result: TopologyMpptInputStringIVResult,
    replacements: dict[str, pd.DataFrame],
) -> TopologyMpptInputStringIVResult:
    curves = {
        key: replacements.get(key, value).copy(deep=True)
        for key, value in result.mppt_input_iv_curves_by_string_id.items()
    }
    diagnostics = replace(
        result.diagnostics,
        output_curve_row_count=sum(len(curve) for curve in curves.values()),
    )
    return replace(result, mppt_input_iv_curves_by_string_id=curves, diagnostics=diagnostics)


def test_zero_resistance_exact_parity_with_s82() -> None:
    topology = _topology([("mppt-1", [("string-a", 0.0), ("string-b", 0.0)])])
    s81, transformed = _s8b(topology)

    ideal = calculate_topology_mppt_mismatch_from_string_iv(topology, s81)
    result = _run(topology, transformed)
    source = ideal.operating_points.iloc[0]
    sink = result.operating_points.iloc[0]

    assert sink["v_mppt_input_v"] == source["v_common_mppt_v"]
    assert sink["i_mppt_input_a"] == source["i_common_mppt_a"]
    assert sink["p_mppt_input_w"] == source["p_common_mppt_w"]
    assert sink["p_independent_mppt_input_w"] == source["p_independent_mp_w"]
    assert sink["p_mppt_input_mismatch_w"] == source["p_mismatch_w"]
    assert sink["mppt_input_mismatch_pct"] == source["mismatch_pct"]


@pytest.mark.parametrize("resistance", [0.0, 0.5])
def test_single_active_string_has_zero_common_voltage_mismatch(
    resistance: float,
) -> None:
    topology = _topology([("mppt-1", [("string-1", resistance)])])
    s81, transformed = _s8b(topology)

    result = _run(topology, transformed)
    row = result.operating_points.iloc[0]

    assert row["mppt_input_state"] == "resolved_mppt_input_common_voltage"
    assert row["p_mppt_input_mismatch_w"] == pytest.approx(0.0)
    assert row["mppt_input_mismatch_pct"] == pytest.approx(0.0)
    if resistance:
        source_mpp = float(s81.string_iv_curves_by_string_id["string-1"]["power_w"].max())
        assert row["p_mppt_input_w"] < source_mpp


def test_two_string_analytic_mismatch_at_mppt_input() -> None:
    topology = _topology([("mppt-1", [("string-a", 0.0), ("string-b", 0.0)])])
    _, transformed = _s8b(topology)
    changed = _replace_curves(
        transformed,
        {
            "string-a": _curve_like(
                transformed, "string-a", [0.0, 1.0, 2.0, 4.0], [10.0, 10.0, 2.0, 0.0]
            ),
            "string-b": _curve_like(
                transformed, "string-b", [0.0, 1.0, 2.0, 4.0], [4.0, 4.0, 4.0, 0.0]
            ),
        },
    )

    row = _run(topology, changed).operating_points.iloc[0]

    assert row["p_independent_mppt_input_w"] == pytest.approx(18.0)
    assert row["p_mppt_input_w"] == pytest.approx(14.0)
    assert row["p_mppt_input_mismatch_w"] == pytest.approx(4.0)
    assert row["v_mppt_input_v"] == pytest.approx(1.0)
    assert row["i_mppt_input_a"] == pytest.approx(14.0)


def test_different_branch_resistances_are_transformed_before_aggregation() -> None:
    topology = _topology([("mppt-1", [("string-a", 0.0), ("string-b", 0.7)])])
    _, transformed = _s8b(topology)
    curve_a = transformed.mppt_input_iv_curves_by_string_id["string-a"]
    curve_b = transformed.mppt_input_iv_curves_by_string_id["string-b"]
    assert not curve_a[["voltage_v", "power_w"]].equals(curve_b[["voltage_v", "power_w"]])

    row = _run(topology, transformed).operating_points.iloc[0]

    assert row["mppt_input_state"] == "resolved_mppt_input_common_voltage"
    assert row["p_mppt_input_w"] == pytest.approx(
        row["v_mppt_input_v"] * row["i_mppt_input_a"]
    )


def test_all_zero_and_mixed_active_zero_state_semantics() -> None:
    topology = _topology([("mppt-1", [("string-a", 0.2), ("string-b", 0.4)])])
    _, all_zero = _s8b(topology, zero=True)
    zero_row = _run(topology, all_zero).operating_points.iloc[0]
    assert zero_row["mppt_input_state"] == "resolved_zero_mppt_input_common_voltage"
    assert zero_row[
        [
            "v_mppt_input_v",
            "i_mppt_input_a",
            "p_mppt_input_w",
            "p_independent_mppt_input_w",
            "p_mppt_input_mismatch_w",
            "mppt_input_mismatch_pct",
        ]
    ].eq(0.0).all()

    _, s81 = s8_support._real_s81(topology, receiver_count=2)
    mixed_s81 = s8_support._set_string_zero(s81, "string-b")
    mixed = calculate_topology_mppt_input_string_iv(
        topology, mixed_s81, resolve_dc_branch_path_authority(topology)
    )
    mixed_row = _run(topology, mixed).operating_points.iloc[0]
    assert mixed_row["mppt_input_state"] == (
        "unresolved_mixed_active_zero_requires_blocking_model"
    )
    assert pd.isna(mixed_row["p_mppt_input_w"])


def test_unresolved_member_causes_and_summaries_are_preserved() -> None:
    missing_topology = _topology([("mppt-1", [("string-1", None)])])
    _, missing = _s8b(missing_topology)
    missing_row = _run(missing_topology, missing).operating_points.iloc[0]
    assert missing_row["mppt_input_state"] == "unresolved_member_mppt_input_iv"
    assert missing_row["unresolved_string_states"] == (
        "unresolved_no_explicit_dc_branch_path"
    )

    topology = _topology([("mppt-1", [("string-1", 1000.0)])])
    s81 = branch_support._replace_curve(
        branch_support._real_s81(topology),
        "string-1",
        [0.0, 5.0, 10.0],
        [5.0, 5.0, 5.0],
    )
    no_domain = calculate_topology_mppt_input_string_iv(
        topology, s81, resolve_dc_branch_path_authority(topology)
    )
    row = _run(topology, no_domain).operating_points.iloc[0]
    assert row["unresolved_string_states"] == (
        "unresolved_no_nonnegative_mppt_input_voltage_domain"
    )

    upstream_topology = _topology([("mppt-1", [("string-1", 0.0)])])
    _, active = s8_support._real_s81(upstream_topology)
    unresolved_s81 = s8_support._set_string_unresolved(active, "string-1")
    upstream = calculate_topology_mppt_input_string_iv(
        upstream_topology,
        unresolved_s81,
        resolve_dc_branch_path_authority(upstream_topology),
    )
    upstream_row = _run(upstream_topology, upstream).operating_points.iloc[0]
    assert upstream_row["unresolved_string_states"] == (
        "unresolved_receiver_module_electrical"
    )


def test_repeated_mppt_ids_multiple_mppts_and_empty_mppt_order() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id="inverter-b",
                mppts=[
                    MPPTConfig(id="mppt-1", strings=[]),
                    MPPTConfig(
                        id="mppt-2",
                        strings=[
                            StringConfig(
                                id="string-b",
                                modules_per_string=24,
                                dc_branch_path=_path(0.0),
                            )
                        ],
                    ),
                ],
            ),
            InverterUnitConfig(
                id="inverter-a",
                mppts=[
                    MPPTConfig(
                        id="mppt-1",
                        strings=[
                            StringConfig(
                                id="string-a",
                                modules_per_string=24,
                                dc_branch_path=_path(0.0),
                            )
                        ],
                    )
                ],
            ),
        ]
    )
    _, transformed = _s8b(topology, receiver_count=2)

    result = _run(topology, transformed)

    assert result.operating_points.index.droplevel("timestamp").tolist() == [
        ("inverter-b", "mppt-2"),
        ("inverter-a", "mppt-1"),
    ]
    assert result.diagnostics.populated_mppt_count == 2
    assert result.diagnostics.empty_mppt_count == 1
    assert result.diagnostics.physics_call_count == 2


def test_empty_topology_is_deterministic() -> None:
    topology = ElectricalTopologyConfig(inverters=[])
    _, transformed = _s8b(topology)

    result = _run(topology, transformed)

    assert result.operating_points.empty
    assert result.operating_points.index.names == ["timestamp", "inverter_id", "mppt_id"]
    assert result.diagnostics.state_row_count == 0
    assert result.diagnostics.physics_call_count == 0


@pytest.mark.parametrize(
    "column",
    [
        "dc_branch_iv_transform_contract",
        "dc_branch_iv_transform_model",
        "dc_branch_iv_transform_scope",
        "source_reference_plane",
        "sink_reference_plane",
        "inverter_id",
        "mppt_id",
        "dc_branch_path_state",
        "mppt_input_iv_resolved",
    ],
)
def test_tampered_state_is_rejected_before_physics(
    monkeypatch: pytest.MonkeyPatch,
    column: str,
) -> None:
    topology = _topology([("mppt-1", [("string-1", 0.0)])])
    _, valid = _s8b(topology)
    states = valid.states.copy(deep=True)
    states.iloc[0, states.columns.get_loc(column)] = (
        not bool(states.iloc[0][column])
        if column == "mppt_input_iv_resolved"
        else "forged"
    )
    tampered = replace(valid, states=states)
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("physics must not run")

    monkeypatch.setattr(dc_collection.electrical, "calculate_physical_mismatch", forbidden)
    with pytest.raises(ValueError):
        _run(topology, tampered)
    assert calls == 0


def test_curve_keys_curve_values_duplicate_index_and_diagnostics_tamper_rejected() -> None:
    topology = _topology([("mppt-1", [("string-1", 0.0)])])
    _, valid = _s8b(topology)

    unexpected = replace(valid, mppt_input_iv_curves_by_string_id={"other": pd.DataFrame()})
    with pytest.raises(ValueError):
        _run(topology, unexpected)

    curve = valid.mppt_input_iv_curves_by_string_id["string-1"].copy(deep=True)
    curve.loc[0, "power_w"] += 1.0
    with pytest.raises(ValueError):
        _run(topology, _replace_curves(valid, {"string-1": curve}))

    states = pd.concat([valid.states, valid.states.iloc[[0]]])
    with pytest.raises(ValueError):
        _run(topology, replace(valid, states=states))

    with pytest.raises(ValueError):
        _run(
            topology,
            replace(
                valid,
                diagnostics=replace(valid.diagnostics, resolved_state_count=99),
            ),
        )


def test_inputs_are_immutable_outputs_owned_and_calls_deterministic() -> None:
    topology = _topology([("mppt-1", [("string-1", 0.4)])])
    _, transformed = _s8b(topology)
    topology_before = topology.model_copy(deep=True)
    states_before = transformed.states.copy(deep=True)
    curve_before = transformed.mppt_input_iv_curves_by_string_id["string-1"].copy(deep=True)

    first = _run(topology, transformed)
    second = _run(topology, transformed)

    assert topology == topology_before
    pd.testing.assert_frame_equal(transformed.states, states_before)
    pd.testing.assert_frame_equal(
        transformed.mppt_input_iv_curves_by_string_id["string-1"], curve_before
    )
    pd.testing.assert_frame_equal(first.operating_points, second.operating_points)
    assert first.diagnostics == second.diagnostics
    first.operating_points.iloc[0, 0] = 999
    pd.testing.assert_frame_equal(transformed.states, states_before)


def test_legacy_wiring_percentage_and_zone_do_not_affect_s83c() -> None:
    topology = _topology([("mppt-1", [("string-1", 0.2)])])
    topology.inverters[0].mppts[0].strings[0].zone_id = "zone-a"
    _, transformed = _s8b(topology)
    first = _run(topology, transformed)
    site = SiteConfig.model_validate(
        {
            "id": "site",
            "name": "non-authority",
            "latitude": 0.0,
            "longitude": 0.0,
            "timezone": "UTC",
            "capacity_kwp": 1.0,
            "solcast_resource_id": "resource",
            "module": {"wiring_loss_dc_pct": 99.0},
        }
    )
    assert site.module.wiring_loss_dc_pct == 99.0
    changed = topology.model_copy(deep=True)
    changed.inverters[0].mppts[0].strings[0].zone_id = "unrelated"

    second = _run(changed, transformed)

    pd.testing.assert_frame_equal(first.operating_points, second.operating_points)


def test_contract_provenance_and_diagnostic_closure() -> None:
    topology = _topology([("mppt-1", [("string-1", 0.0)])])
    _, transformed = _s8b(topology)
    result = _run(topology, transformed)
    row = result.operating_points.iloc[0]

    assert row["source_reference_plane"] == STRING_TERMINAL_REFERENCE_PLANE
    assert row["sink_reference_plane"] == MPPT_INPUT_REFERENCE_PLANE
    assert row["mppt_input_common_voltage_contract"] == (
        MPPT_INPUT_COMMON_VOLTAGE_CONTRACT_ID
    )
    assert row["mppt_input_common_voltage_model"] == MPPT_INPUT_COMMON_VOLTAGE_MODEL_ID
    assert row["mppt_input_common_voltage_scope"] == MPPT_INPUT_COMMON_VOLTAGE_SCOPE
    assert row["mppt_input_common_voltage_coverage_scope"] == (
        MPPT_INPUT_COMMON_VOLTAGE_COVERAGE_SCOPE
    )
    assert result.diagnostics.resolved_mppt_state_count == (
        result.diagnostics.active_mppt_state_count
        + result.diagnostics.zero_mppt_state_count
    )
