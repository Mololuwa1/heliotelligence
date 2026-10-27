from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import mv_hv_operating_solution as module
from heliotelligence.physics.mv_hv_grid_boundary_voltage_authority import (
    MvHvGridBoundaryVoltageState,
    resolve_topology_mv_hv_grid_boundary_voltage_authority,
)
from heliotelligence.physics.mv_hv_network_authority import (
    MvHvGridBoundaryAuthority,
    MvHvNetworkBasisAuthority,
    MvHvNetworkNodeAuthority,
    MvHvNetworkSegmentAuthority,
    MvHvTransformerTerminalBindingAuthority,
    MvHvVoltageLevelAuthority,
    RevenueMeterBoundaryAuthority,
    resolve_topology_mv_hv_network_authority,
)
from heliotelligence.physics.mv_hv_operating_solution import (
    METER_CUT,
    SHUNT_SEMANTICS,
    calculate_topology_mv_hv_operating_solution,
)
from heliotelligence.physics.transformer_advanced_operating_solution import (
    calculate_topology_transformer_advanced_operating_solution,
)
from tests.unit.test_physics import test_inverter_dispatch_feasibility as support
from tests.unit.test_physics.test_transformer_advanced_operating_solution import (
    _context as _s12m_context,
)


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


def _basis() -> MvHvNetworkBasisAuthority:
    return MvHvNetworkBasisAuthority(
        "balanced_three_phase",
        "line_to_line_rms",
        "per_phase_series",
        "per_phase_total_nominal_pi",
        "radial",
        "single-line",
        "high",
    )


def _node(identifier: str, kind: str) -> MvHvNetworkNodeAuthority:
    return MvHvNetworkNodeAuthority(identifier, kind, "11-kv", "single-line", "high")  # type: ignore[arg-type]


def _segment(
    resistance: float = 0.0,
    reactance: float = 0.0,
    conductance: float = 0.0,
    susceptance: float = 0.0,
) -> MvHvNetworkSegmentAuthority:
    return MvHvNetworkSegmentAuthority(
        "feeder",
        "tx-node",
        "grid-node",
        resistance,
        reactance,
        conductance,
        susceptance,
        "schedule",
        "high",
    )


def _values(
    *,
    p: float = 100.0,
    q: float = 0.0,
    resistance: float = 0.0,
    reactance: float = 0.0,
    conductance: float = 0.0,
    susceptance: float = 0.0,
    energised: bool | None = True,
    boundary_voltage: float | None = None,
    meter_node: str = "grid-node",
    fallback: bool = False,
) -> dict[str, Any]:
    values = _s12m_context(
        p=p,
        q=q,
        energised=energised,
        winding_temperature=None if fallback else 75.0,
        winding_temperatures=(95.0, 85.0) if fallback else None,
    )
    s12m = calculate_topology_transformer_advanced_operating_solution(**values)
    values["transformer_advanced_operating_solution"] = s12m
    topology = values["transformer_static_authority"].topology_by_id["tx-1"]
    values.update(
        mv_hv_network_basis=_basis(),
        mv_hv_voltage_level_by_id={
            "11-kv": MvHvVoltageLevelAuthority("11-kv", 11_000.0, "design", "high")
        },
        mv_hv_node_by_id={
            "tx-node": _node("tx-node", "transformer_terminal"),
            "grid-node": _node("grid-node", "network_exit"),
        },
        mv_hv_segment_by_id={"feeder": _segment(resistance, reactance, conductance, susceptance)},
        mv_hv_transformer_terminal_binding_by_transformer_id={
            "tx-1": MvHvTransformerTerminalBindingAuthority(
                "tx-1",
                topology.transformer_network_terminal_id,
                "tx-node",
                "transformer_network_side_terminal",
                "mv_hv_transformer_terminal_node",
                "direct_electrical_boundary",
                "single-line",
                "high",
            )
        },
        mv_hv_grid_boundary_by_id={
            "grid": MvHvGridBoundaryAuthority(
                "grid", "grid-node", "grid_interconnection_boundary", "agreement", "high"
            )
        },
        revenue_meter_boundary_by_id={
            "meter": RevenueMeterBoundaryAuthority(
                "meter",
                meter_node,
                "revenue_meter_boundary",
                "positive_plant_to_grid",
                "positive_plant_to_grid",
                "three_phase_total",
                "metering",
                "high",
            )
        },
    )
    s13a = module._call(resolve_topology_mv_hv_network_authority, values)
    values["mv_hv_network_authority"] = s13a
    timestamp = s12m.states.index.get_level_values("timestamp")[0]
    target = float(s12m.states.iloc[0]["network_terminal_voltage_line_to_line_rms_v"])
    if boundary_voltage is None:
        vf = complex(target / math.sqrt(3.0), 0.0)
        injection = complex(
            float(s12m.states.iloc[0]["p_network_terminal_w"]),
            float(s12m.states.iloc[0]["q_network_terminal_var"]),
        )
        current = (injection / (3.0 * vf)).conjugate() if injection else 0j
        current -= 0.5 * complex(conductance, susceptance) * vf
        boundary_voltage = math.sqrt(3.0) * abs(vf - complex(resistance, reactance) * current)
    values["grid_boundary_voltage_by_key"] = {
        (timestamp, "grid"): MvHvGridBoundaryVoltageState(
            boundary_voltage, "line_to_line_rms", "grid_interconnection_boundary", "SCADA", "high"
        )
    }
    s13b = module._call(resolve_topology_mv_hv_grid_boundary_voltage_authority, values)
    values["mv_hv_grid_boundary_voltage_authority"] = s13b
    return values


def _run(**kwargs: Any) -> Any:
    return calculate_topology_mv_hv_operating_solution(**_values(**kwargs))


def test_series_and_shunt_free_identity_closes_to_s12m_and_grid_meter() -> None:
    result = _run()
    tree = result.network_exit_states.iloc[0]
    tx = result.transformer_terminal_states.iloc[0]
    meter = result.revenue_meter_states.iloc[0]
    assert tree["mv_hv_operating_state"] == (
        "resolved_balanced_radial_nominal_pi_mv_hv_operating_solution"
    )
    assert tx["terminal_voltage_magnitude_consistency_satisfied"]
    assert tree["p_export_at_grid_boundary_w"] == pytest.approx(
        tx["p_network_terminal_injection_w"]
    )
    assert tree["q_export_at_grid_boundary_var"] == pytest.approx(
        tx["q_network_terminal_injection_var"]
    )
    assert meter["expected_p_at_revenue_meter_w"] == pytest.approx(
        tree["p_export_at_grid_boundary_w"]
    )
    assert tree["total_series_active_loss_w"] == 0.0
    assert tree["total_shunt_active_consumption_w"] == 0.0


def test_series_rx_equation_losses_and_tree_conservation() -> None:
    result = _run(p=1_000.0, q=300.0, resistance=0.8, reactance=1.2)
    tree = result.network_exit_states.iloc[0]
    segment = result.segment_states.iloc[0]
    assert tree["mv_hv_operating_solution_resolved"]
    current = complex(segment["series_current_real_a"], segment["series_current_imag_a"])
    delta = complex(
        segment["phase_voltage_difference_from_to_real_v"],
        segment["phase_voltage_difference_from_to_imag_v"],
    )
    assert delta == pytest.approx(complex(0.8, 1.2) * current)
    assert segment["active_series_loss_w"] == pytest.approx(3 * 0.8 * abs(current) ** 2)
    assert segment["reactive_series_consumption_var"] == pytest.approx(3 * 1.2 * abs(current) ** 2)
    assert tree["active_power_conservation_residual_w"] == pytest.approx(0.0, abs=1e-6)
    assert tree["reactive_power_conservation_residual_var"] == pytest.approx(0.0, abs=1e-6)


def test_pure_shunt_conductance_and_capacitance_signs() -> None:
    result = _run(p=600.0, conductance=1e-7, susceptance=2e-7)
    tree = result.network_exit_states.iloc[0]
    assert tree["total_shunt_active_consumption_w"] > 0
    assert tree["total_shunt_capacitive_reactive_injection_var"] > 0
    assert tree["p_export_at_grid_boundary_w"] < tree["transformer_injected_p_total_w"]
    assert tree["q_export_at_grid_boundary_var"] > tree["transformer_injected_q_total_var"]
    assert tree["shunt_susceptance_semantics"] == SHUNT_SEMANTICS


def test_nominal_pi_terminal_currents_and_branch_power_close() -> None:
    result = _run(
        p=200.0,
        q=50.0,
        resistance=0.2,
        reactance=0.3,
        conductance=1e-8,
        susceptance=2e-8,
    )
    segment = result.segment_states.iloc[0]
    sf = complex(
        segment["p_from_terminal_into_segment_w"], segment["q_from_terminal_into_segment_var"]
    )
    st = complex(segment["p_to_terminal_into_segment_w"], segment["q_to_terminal_into_segment_var"])
    expected = complex(segment["net_active_consumption_w"], segment["net_reactive_consumption_var"])
    assert sf + st == pytest.approx(expected, abs=1e-6)


def test_internal_transformer_terminal_meter_uses_gridward_branch_cut() -> None:
    result = _run(meter_node="tx-node")
    meter = result.revenue_meter_states.iloc[0]
    tx = result.transformer_terminal_states.iloc[0]
    assert meter["meter_boundary_cut_semantics"] == METER_CUT
    assert meter["expected_p_at_revenue_meter_w"] == pytest.approx(
        tx["p_network_terminal_injection_w"]
    )
    assert meter["expected_q_at_revenue_meter_var"] == pytest.approx(
        tx["q_network_terminal_injection_var"]
    )


def test_true_internal_junction_meter_uses_outgoing_full_terminal_power() -> None:
    values = _values()
    values["mv_hv_node_by_id"] = {
        "tx-node": _node("tx-node", "transformer_terminal"),
        "junction": _node("junction", "junction"),
        "grid-node": _node("grid-node", "network_exit"),
    }
    values["mv_hv_segment_by_id"] = {
        "upstream": MvHvNetworkSegmentAuthority(
            "upstream", "tx-node", "junction", 0, 0, 0, 0, "schedule", "high"
        ),
        "gridward": MvHvNetworkSegmentAuthority(
            "gridward", "junction", "grid-node", 0, 0, 0, 0, "schedule", "high"
        ),
    }
    values["revenue_meter_boundary_by_id"] = {
        "meter": RevenueMeterBoundaryAuthority(
            "meter",
            "junction",
            "revenue_meter_boundary",
            "positive_plant_to_grid",
            "positive_plant_to_grid",
            "three_phase_total",
            "metering",
            "high",
        )
    }
    values["mv_hv_network_authority"] = module._call(
        resolve_topology_mv_hv_network_authority, values
    )
    values["mv_hv_grid_boundary_voltage_authority"] = module._call(
        resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    result = calculate_topology_mv_hv_operating_solution(**values)
    meter = result.revenue_meter_states.iloc[0]
    outgoing = result.segment_states.xs("gridward", level="segment_id").iloc[0]
    assert meter["expected_p_at_revenue_meter_w"] == pytest.approx(
        outgoing["p_from_terminal_into_segment_w"]
    )
    assert meter["expected_q_at_revenue_meter_var"] == pytest.approx(
        outgoing["q_from_terminal_into_segment_var"]
    )


def test_two_transformers_merge_current_once_in_shared_downstream_segment() -> None:
    nodes = {
        "tx-a": _node("tx-a", "transformer_terminal"),
        "tx-b": _node("tx-b", "transformer_terminal"),
        "junction": _node("junction", "junction"),
        "grid-node": _node("grid-node", "network_exit"),
    }
    segments = {
        "a": MvHvNetworkSegmentAuthority("a", "tx-a", "junction", 0, 0, 0, 0, "schedule", "high"),
        "b": MvHvNetworkSegmentAuthority("b", "tx-b", "junction", 0, 0, 0, 0, "schedule", "high"),
        "shared": MvHvNetworkSegmentAuthority(
            "shared", "junction", "grid-node", 0, 0, 0, 0, "schedule", "high"
        ),
    }
    injections = {"tx-a": complex(300, 40), "tx-b": complex(500, -20)}
    solved = module._solve_tree("grid-node", 11_000.0, nodes, segments, injections)
    phase_voltage = complex(11_000 / math.sqrt(3.0), 0)
    expected = sum((power / (3 * phase_voltage)).conjugate() for power in injections.values())
    assert solved.converged
    assert solved.currents["shared"] == pytest.approx(expected)
    assert solved.currents["shared"] == pytest.approx(solved.currents["a"] + solved.currents["b"])


def test_independent_incomplete_tree_does_not_block_resolved_tree() -> None:
    values = _values()
    values["mv_hv_node_by_id"] = {
        **values["mv_hv_node_by_id"],
        "other-exit": _node("other-exit", "network_exit"),
    }
    values["mv_hv_network_authority"] = module._call(
        resolve_topology_mv_hv_network_authority, values
    )
    values["mv_hv_grid_boundary_voltage_authority"] = module._call(
        resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    result = calculate_topology_mv_hv_operating_solution(**values)
    timestamp = result.network_exit_states.index.get_level_values("timestamp")[0]
    assert result.network_exit_states.loc[
        (timestamp, "grid-node"), "mv_hv_operating_solution_resolved"
    ]
    assert result.network_exit_states.loc[(timestamp, "other-exit"), "mv_hv_operating_state"] == (
        "unresolved_network_exit_without_grid_boundary"
    )


def test_material_s12m_s13_voltage_mismatch_hides_candidate_physics() -> None:
    result = _run(boundary_voltage=9_000.0)
    tree = result.network_exit_states.iloc[0]
    assert tree["network_solve_converged"]
    assert tree["mv_hv_operating_state"] == (
        "unresolved_s12m_s13_transformer_terminal_voltage_mismatch"
    )
    assert tree["mismatched_transformer_ids"] == ("tx-1",)
    assert pd.isna(tree["p_export_at_grid_boundary_w"])
    assert pd.isna(tree["q_export_at_grid_boundary_var"])
    tx = result.transformer_terminal_states.iloc[0]
    assert pd.isna(tx["solved_s13_terminal_voltage_line_to_line_rms_v"])
    assert math.isfinite(tx["terminal_voltage_magnitude_residual_v"])
    assert not tx["terminal_voltage_magnitude_consistency_satisfied"]
    assert result.node_states["voltage_line_to_line_rms_v"].isna().all()
    assert result.segment_states["series_current_magnitude_a"].isna().all()
    assert result.revenue_meter_states["expected_meter_voltage_line_to_line_rms_v"].isna().all()
    assert result.revenue_meter_states["expected_p_at_revenue_meter_w"].isna().all()
    assert result.revenue_meter_states["expected_q_at_revenue_meter_var"].isna().all()


def test_s13b_voltage_evidence_survives_missing_s12m_row() -> None:
    values = _values()
    original_timestamp = next(iter(values["grid_boundary_voltage_by_key"]))[0]
    evidence_timestamp = original_timestamp + pd.Timedelta(hours=1)
    explicit_voltage = 10_875.0
    values["grid_boundary_voltage_by_key"] = {
        (evidence_timestamp, "grid"): MvHvGridBoundaryVoltageState(
            explicit_voltage,
            "line_to_line_rms",
            "grid_interconnection_boundary",
            "SCADA",
            "high",
        )
    }
    values["mv_hv_grid_boundary_voltage_authority"] = module._call(
        resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    result = calculate_topology_mv_hv_operating_solution(**values)
    row = result.network_exit_states.loc[(evidence_timestamp, "grid-node")]
    assert row["mv_hv_operating_state"] == ("unresolved_missing_s12m_transformer_operating_state")
    assert row["grid_boundary_present"]
    assert row["grid_boundary_voltage_resolved"]
    assert row["grid_boundary_voltage_line_to_line_rms_v"] == explicit_voltage
    assert not row["network_solve_attempted"]
    assert pd.isna(row["p_export_at_grid_boundary_w"])


def test_validator_rejects_structural_unresolved_publication_tampering() -> None:
    values = _values()
    original_timestamp = next(iter(values["grid_boundary_voltage_by_key"]))[0]
    evidence_timestamp = original_timestamp + pd.Timedelta(hours=1)
    values["grid_boundary_voltage_by_key"] = {
        (evidence_timestamp, "grid"): MvHvGridBoundaryVoltageState(
            10_875.0,
            "line_to_line_rms",
            "grid_interconnection_boundary",
            "SCADA",
            "high",
        )
    }
    values["mv_hv_grid_boundary_voltage_authority"] = module._call(
        resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    parents = module._parents(values)
    result = calculate_topology_mv_hv_operating_solution(**values)
    cases = (
        ("network_exit_states", "transformer_terminal_voltage_consistency_checked", True),
        ("network_exit_states", "solver_max_voltage_delta_v", 1.0),
        ("network_exit_states", "total_series_active_loss_w", 1.0),
        ("transformer_terminal_states", "q_network_terminal_injection_var", 1.0),
        (
            "transformer_terminal_states",
            "solved_s13_terminal_voltage_line_to_line_rms_v",
            11_000.0,
        ),
        (
            "transformer_terminal_states",
            "transformer_terminal_operating_state",
            "resolved-tamper",
        ),
        ("node_states", "voltage_line_to_line_rms_v", 11_000.0),
        ("node_states", "local_transformer_p_injection_w", 100.0),
        ("node_states", "node_operating_state", "resolved-tamper"),
        ("segment_states", "series_current_magnitude_a", 1.0),
        ("segment_states", "p_from_terminal_into_segment_w", 100.0),
        ("segment_states", "segment_operating_state", "resolved-tamper"),
        ("revenue_meter_states", "expected_meter_voltage_line_to_line_rms_v", 11_000.0),
        ("revenue_meter_states", "expected_q_at_revenue_meter_var", 500.0),
        ("revenue_meter_states", "revenue_meter_expected_state", "resolved-tamper"),
    )
    for frame_name, column, replacement in cases:
        frame = getattr(result, frame_name).copy(deep=True)
        frame.loc[(evidence_timestamp, slice(None)), column] = replacement
        with pytest.raises(RuntimeError, match="independent exact closure"):
            module._validate_result(parents, replace(result, **{frame_name: frame}))


def test_validator_rejects_mismatch_candidate_physics_leakage() -> None:
    values = _values(boundary_voltage=9_000.0)
    parents = module._parents(values)
    result = calculate_topology_mv_hv_operating_solution(**values)
    cases = (
        ("node_states", "voltage_line_to_line_rms_v", 9_000.0),
        ("segment_states", "series_current_magnitude_a", 1.0),
        ("revenue_meter_states", "expected_p_at_revenue_meter_w", 100.0),
        ("revenue_meter_states", "expected_q_at_revenue_meter_var", 50.0),
    )
    for frame_name, column, replacement in cases:
        frame = getattr(result, frame_name).copy(deep=True)
        frame.iloc[0, frame.columns.get_loc(column)] = replacement
        with pytest.raises(RuntimeError, match="independent exact closure"):
            module._validate_result(parents, replace(result, **{frame_name: frame}))


def test_validator_closes_zero_voltage_numerical_failure_diagnostics() -> None:
    values = _values(boundary_voltage=0.0)
    parents = module._parents(values)
    result = calculate_topology_mv_hv_operating_solution(**values)
    frame = result.network_exit_states.copy(deep=True)
    assert frame.iloc[0]["mv_hv_operating_state"] == (
        "unresolved_zero_grid_voltage_with_nonzero_transformer_injection"
    )
    frame.iloc[0, frame.columns.get_loc("solver_iteration_count")] = 1
    with pytest.raises(RuntimeError, match="independent exact closure"):
        module._validate_result(parents, replace(result, network_exit_states=frame))


def test_s12m_phase_angle_is_not_coupled() -> None:
    result = _run()
    tree = result.network_exit_states.iloc[0]
    assert not tree["transformer_terminal_phase_angle_coupling_applied"]
    assert tree["grid_boundary_phase_angle_treatment"] == (
        "grid_boundary_zero_angle_is_mathematical_reference_not_measurement"
    )


def test_deenergised_s12m_is_zero_injection_without_voltage_fabrication() -> None:
    result = _run(p=0.0, energised=False, boundary_voltage=11_000.0)
    tx = result.transformer_terminal_states.iloc[0]
    assert tx["p_network_terminal_injection_w"] == 0.0
    assert tx["q_network_terminal_injection_var"] == 0.0
    assert not tx["terminal_voltage_consistency_applicable"]
    assert pd.isna(tx["s12m_network_terminal_voltage_line_to_line_rms_v"])


def test_zero_grid_voltage_nonzero_injection_is_controlled() -> None:
    result = _run(boundary_voltage=0.0)
    tree = result.network_exit_states.iloc[0]
    assert tree["mv_hv_operating_state"] == (
        "unresolved_zero_grid_voltage_with_nonzero_transformer_injection"
    )
    assert not tree["network_solve_attempted"]


def test_zero_grid_voltage_zero_deenergised_injection_resolves() -> None:
    result = _run(p=0.0, energised=False, boundary_voltage=0.0)
    tree = result.network_exit_states.iloc[0]
    assert tree["mv_hv_operating_state"] == (
        "resolved_zero_grid_voltage_zero_injection_mv_hv_solution"
    )
    assert tree["network_solve_converged"]
    assert tree["solver_iteration_count"] == 0


def test_missing_boundary_voltage_timestamp_is_preserved() -> None:
    values = _values()
    values["grid_boundary_voltage_by_key"] = {}
    values["mv_hv_grid_boundary_voltage_authority"] = module._call(
        resolve_topology_mv_hv_grid_boundary_voltage_authority, values
    )
    result = calculate_topology_mv_hv_operating_solution(**values)
    assert result.network_exit_states.iloc[0]["mv_hv_operating_state"] == (
        "unresolved_missing_grid_boundary_voltage_authority"
    )


@pytest.mark.parametrize(
    "parent_name",
    [
        "transformer_advanced_operating_solution",
        "mv_hv_network_authority",
        "mv_hv_grid_boundary_voltage_authority",
    ],
)
def test_parent_frame_tampering_is_rejected(parent_name: str) -> None:
    values = _values()
    parent = values[parent_name]
    frame_name = "states" if parent_name != "mv_hv_network_authority" else "transformer_states"
    frame = getattr(parent, frame_name).copy(deep=True)
    frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
    values[parent_name] = replace(parent, **{frame_name: frame})
    with pytest.raises(ValueError, match="canonical replay"):
        calculate_topology_mv_hv_operating_solution(**values)


def test_result_schemas_and_index_order_are_deterministic() -> None:
    result = _run()
    assert tuple(result.network_exit_states.columns) == module._TREE_COLUMNS
    assert tuple(result.transformer_terminal_states.columns) == module._TX_COLUMNS
    assert tuple(result.node_states.columns) == module._NODE_COLUMNS
    assert tuple(result.segment_states.columns) == module._SEG_COLUMNS
    assert tuple(result.revenue_meter_states.columns) == module._METER_COLUMNS
    assert list(result.network_exit_states.index.names) == ["timestamp", "network_exit_node_id"]


@pytest.mark.parametrize(
    ("columns", "names", "bools", "nullable_bools", "ints", "floats", "representative"),
    [
        (
            module._TREE_COLUMNS,
            ["timestamp", "network_exit_node_id"],
            module._TREE_BOOL,
            frozenset(),
            module._TREE_INT,
            module._TREE_FLOAT,
            {
                "network_basis_resolved": "bool",
                "tree_transformer_count": "int64",
                "p_export_at_grid_boundary_w": "float64",
                "mv_hv_operating_state": "object",
            },
        ),
        (
            module._TX_COLUMNS,
            ["timestamp", "transformer_id"],
            module._TX_BOOL,
            module._TX_NULLABLE_BOOL,
            frozenset(),
            module._TX_FLOAT,
            {
                "s12m_row_present": "bool",
                "transformer_energised": "boolean",
                "p_network_terminal_injection_w": "float64",
                "s12m_operating_state": "object",
                "s12m_terminal_solution_fidelity": "object",
                "s12m_load_loss_fallback_applied": "boolean",
            },
        ),
        (
            module._NODE_COLUMNS,
            ["timestamp", "node_id"],
            module._NODE_BOOL,
            frozenset(),
            frozenset(),
            module._NODE_FLOAT,
            {
                "node_connected_to_network_exit": "bool",
                "voltage_phase_real_v": "float64",
                "node_kind": "object",
            },
        ),
        (
            module._SEG_COLUMNS,
            ["timestamp", "segment_id"],
            module._SEG_BOOL,
            frozenset(),
            frozenset(),
            module._SEG_FLOAT,
            {
                "segment_connected_to_network_exit": "bool",
                "series_current_real_a": "float64",
                "from_node_id": "object",
            },
        ),
        (
            module._METER_COLUMNS,
            ["timestamp", "revenue_meter_id"],
            module._METER_BOOL,
            frozenset(),
            frozenset(),
            module._METER_FLOAT,
            {
                "meter_connected_to_network_exit": "bool",
                "expected_p_at_revenue_meter_w": "float64",
                "revenue_meter_expected_state": "object",
            },
        ),
    ],
)
def test_empty_public_frames_have_exact_schema_and_dtypes(
    columns: tuple[str, ...],
    names: list[str],
    bools: frozenset[str],
    nullable_bools: frozenset[str],
    ints: frozenset[str],
    floats: frozenset[str],
    representative: dict[str, str],
) -> None:
    frame = module._make_frame([], [], columns, names, bools, nullable_bools, ints, floats)
    assert frame.empty
    assert tuple(frame.columns) == columns
    assert list(frame.index.names) == names
    for column, expected in representative.items():
        assert str(frame[column].dtype) == expected


@pytest.mark.parametrize(
    ("frame_name", "column"),
    [
        ("network_exit_states", "grid_boundary_id"),
        ("network_exit_states", "grid_boundary_voltage_resolved"),
        ("network_exit_states", "solver_iteration_count"),
        ("network_exit_states", "transformer_injected_p_total_w"),
        ("network_exit_states", "grid_boundary_phase_angle_treatment"),
        ("transformer_terminal_states", "s12m_operating_state"),
        ("transformer_terminal_states", "solved_s13_terminal_voltage_line_to_line_rms_v"),
        ("transformer_terminal_states", "terminal_voltage_consistency_applicable"),
        ("node_states", "voltage_phase_imag_v"),
        ("node_states", "voltage_line_to_line_rms_v"),
        ("node_states", "total_incident_half_shunt_susceptance_siemens_per_phase"),
        ("node_states", "node_operating_state"),
        ("segment_states", "from_terminal_current_real_a"),
        ("segment_states", "active_shunt_consumption_w"),
        ("segment_states", "capacitive_shunt_reactive_injection_var"),
        ("segment_states", "segment_operating_state"),
        ("revenue_meter_states", "expected_meter_voltage_line_to_line_rms_v"),
        ("revenue_meter_states", "expected_q_at_revenue_meter_var"),
        ("revenue_meter_states", "meter_boundary_cut_semantics"),
        ("revenue_meter_states", "active_power_sign_convention"),
    ],
)
def test_validator_rejects_representative_frame_tampering(frame_name: str, column: str) -> None:
    values = _values()
    parents = module._parents(values)
    result = calculate_topology_mv_hv_operating_solution(**values)
    frame = getattr(result, frame_name).copy(deep=True)
    value = frame.iloc[0][column]
    if str(frame[column].dtype) in {"bool", "boolean"}:
        replacement: object = not bool(value)
    elif isinstance(value, str):
        replacement = f"{value}-tampered"
    else:
        replacement = float(value) + 1.0
    frame.iloc[0, frame.columns.get_loc(column)] = replacement
    with pytest.raises(RuntimeError, match="independent exact closure"):
        module._validate_result(parents, replace(result, **{frame_name: frame}))


def test_validator_rejects_diagnostics_tampering() -> None:
    values = _values()
    parents = module._parents(values)
    result = calculate_topology_mv_hv_operating_solution(**values)
    tampered = replace(result, diagnostics=replace(result.diagnostics, resolved_tree_count=99))
    with pytest.raises(RuntimeError, match="diagnostics"):
        module._validate_result(parents, tampered)


def test_validator_is_independent_of_production_solver_and_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _values()
    parents = module._parents(values)
    result = calculate_topology_mv_hv_operating_solution(**values)

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("production S13C path was called")

    for name in (
        "_build_result",
        "_solve_tree",
        "_sweep_currents",
        "_forward_voltages",
        "_branch",
        "_make_frame",
        "_transformer_frame",
        "_node_frame",
        "_segment_frame",
        "_meter_frame",
    ):
        monkeypatch.setattr(module, name, fail)
    module._validate_result(parents, result)


def test_controlled_solver_nonconvergence_preserves_iteration_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = {
        "tx-node": _node("tx-node", "transformer_terminal"),
        "grid-node": _node("grid-node", "network_exit"),
    }
    segments = {"feeder": _segment(100.0, 100.0)}
    monkeypatch.setattr(module, "MAX_ITERATIONS", 1)
    solved = module._solve_tree(
        "grid-node", 11_000.0, nodes, segments, {"tx-node": complex(1e6, 1e6)}
    )
    assert not solved.converged
    assert solved.failure == "nonconvergence"
    assert solved.iterations == 1


def test_validator_closes_public_nonconvergence_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _values(p=100.0, q=50.0, resistance=100.0, reactance=100.0)
    parents = module._parents(values)
    monkeypatch.setattr(module, "MAX_ITERATIONS", 1)
    result = calculate_topology_mv_hv_operating_solution(**values)
    row = result.network_exit_states.iloc[0]
    assert row["mv_hv_operating_state"] == "unresolved_mv_hv_network_solver_nonconvergence"
    assert row["network_solve_attempted"]
    assert not row["network_solve_converged"]
    assert row["solver_iteration_count"] == 1
    assert math.isfinite(row["solver_max_voltage_delta_v"])
    frame = result.network_exit_states.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc("solver_max_voltage_delta_v")] = (
        float(row["solver_max_voltage_delta_v"]) + 1.0
    )
    with pytest.raises(RuntimeError, match="independent exact closure"):
        module._validate_result(parents, replace(result, network_exit_states=frame))


_FIDELITY_CASES: dict[str, tuple[dict[str, Any], Any]] = {}


def _fidelity_case(mode: str = "fallback") -> tuple[dict[str, Any], Any]:
    """Real canonical S12M→S13C chain, shared by downstream fidelity regressions."""
    if mode not in _FIDELITY_CASES:
        options: dict[str, Any] = {"fallback": mode != "advanced"}
        if mode == "deenergised":
            options.update(p=0.0, energised=False, boundary_voltage=11_000.0)
        if mode == "mismatch":
            options["boundary_voltage"] = 9000.0
        values = _values(**options)
        result = calculate_topology_mv_hv_operating_solution(**values)
        values["mv_hv_operating_solution"] = result
        _FIDELITY_CASES[mode] = values, result
    return _FIDELITY_CASES[mode]


def _fidelity_parents(values: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        values["transformer_advanced_operating_solution"],
        values["mv_hv_network_authority"],
        values["mv_hv_grid_boundary_voltage_authority"],
    )


def _mixed_fidelity_parents() -> tuple[Any, Any, Any]:
    """Controlled two-terminal boundary assembled from real advanced/fallback solves."""
    from heliotelligence.physics import transformer_advanced_operating_solution as s12m_module
    from tests.unit.test_physics import test_mv_hv_network_authority as network_support

    advanced, _ = _fidelity_case("advanced")
    fallback, _ = _fidelity_case()
    frames = []
    for identifier, values in [("tx-a", advanced), ("tx-b", fallback)]:
        frame = values["transformer_advanced_operating_solution"].states.copy(deep=True)
        frame.index = pd.MultiIndex.from_tuples(
            [(timestamp, identifier) for timestamp, _ in frame.index],
            names=frame.index.names,
        )
        frames.append(frame)
    frame = pd.concat(frames).sort_index()
    s12m = replace(
        advanced["transformer_advanced_operating_solution"],
        states=frame,
        diagnostics=s12m_module._diagnostics(frame, 2, 1),
    )
    values = network_support._inputs()
    values.update(network_support._parents(("tx-a", "tx-b")))
    values["mv_hv_node_by_id"] = {
        "ta": _node("ta", "transformer_terminal"),
        "tb": _node("tb", "transformer_terminal"),
        "grid-node": _node("grid-node", "network_exit"),
    }
    values["mv_hv_segment_by_id"] = {
        "a": network_support._segment("a", "ta", "grid-node"),
        "b": network_support._segment("b", "tb", "grid-node"),
    }
    values["mv_hv_grid_boundary_by_id"] = {"grid": network_support._grid("grid", "grid-node")}
    values["revenue_meter_boundary_by_id"] = {"meter": network_support._meter("meter", "grid-node")}
    values["mv_hv_transformer_terminal_binding_by_transformer_id"] = {
        "tx-a": network_support._binding("tx-a", "ta"),
        "tx-b": network_support._binding("tx-b", "tb"),
    }
    network = module._call(resolve_topology_mv_hv_network_authority, values)
    values["mv_hv_network_authority"] = network
    timestamp = frame.index[0][0]
    voltage = float(frame.iloc[0]["network_terminal_voltage_line_to_line_rms_v"])
    values["grid_boundary_voltage_by_key"] = {
        (timestamp, "grid"): MvHvGridBoundaryVoltageState(
            voltage, "line_to_line_rms", "grid_interconnection_boundary", "SCADA", "high"
        )
    }
    boundary = module._call(resolve_topology_mv_hv_grid_boundary_voltage_authority, values)
    return s12m, network, boundary


@pytest.mark.parametrize(
    "mode,fidelity,fallback",
    [
        ("advanced", "coupled_advanced_load_loss", False),
        ("fallback", "coupled_s12g_load_loss_fallback", True),
        ("deenergised", "deenergised_zero", False),
    ],
)
def test_downstream_resolved_transformer_fidelity_is_preserved(
    mode: str,
    fidelity: str,
    fallback: bool,
) -> None:
    values, result = _fidelity_case(mode)
    upstream = values["transformer_advanced_operating_solution"].states.iloc[0]
    tx = result.transformer_terminal_states.iloc[0]
    assert tx["s12m_injection_ready"]
    assert tx["s12m_operating_state"] == upstream["transformer_advanced_operating_solution_state"]
    assert (
        tx["s12m_terminal_solution_fidelity"] == fidelity == upstream["terminal_solution_fidelity"]
    )
    assert bool(tx["s12m_load_loss_fallback_applied"]) == fallback
    assert tx["p_network_terminal_injection_w"] == upstream["p_network_terminal_w"]
    assert tx["q_network_terminal_injection_var"] == upstream["q_network_terminal_var"]
    assert result.network_exit_states.iloc[0]["mv_hv_operating_solution_resolved"]
    assert result.revenue_meter_states.iloc[0]["mv_hv_operating_solution_resolved"]
    meter = result.revenue_meter_states.iloc[0]
    assert meter["expected_p_at_revenue_meter_w"] == pytest.approx(
        upstream["p_network_terminal_w"],
        rel=module.EQUATION_REL_TOL,
        abs=module.EQUATION_ABS_TOL,
    )
    assert meter["expected_q_at_revenue_meter_var"] == pytest.approx(
        upstream["q_network_terminal_var"],
        rel=module.EQUATION_REL_TOL,
        abs=module.EQUATION_ABS_TOL,
    )
    assert result.network_exit_states.iloc[0]["transformer_loss_treatment"] == (
        "transformer_losses_owned_by_s12m_not_reapplied_in_s13c"
    )
    if mode != "deenergised":
        assert tx["terminal_voltage_consistency_applicable"]
        assert tx["terminal_voltage_magnitude_consistency_satisfied"]
        assert (
            tx["s12m_network_terminal_voltage_line_to_line_rms_v"]
            == upstream["network_terminal_voltage_line_to_line_rms_v"]
        )
        assert math.isclose(
            tx["solved_s13_terminal_voltage_line_to_line_rms_v"],
            upstream["network_terminal_voltage_line_to_line_rms_v"],
            rel_tol=module.TERMINAL_VOLTAGE_REL_TOL,
            abs_tol=module.TERMINAL_VOLTAGE_ABS_TOL_V,
        )
    else:
        assert not tx["terminal_voltage_consistency_applicable"]
        assert pd.isna(tx["s12m_network_terminal_voltage_line_to_line_rms_v"])


def test_downstream_fallback_does_not_bypass_terminal_voltage_mismatch() -> None:
    values, result = _fidelity_case("mismatch")
    tx = result.transformer_terminal_states.iloc[0]
    assert tx["s12m_injection_ready"]
    assert tx["terminal_voltage_consistency_applicable"]
    assert not tx["terminal_voltage_magnitude_consistency_satisfied"]
    assert result.network_exit_states.iloc[0]["mv_hv_operating_state"] == (
        "unresolved_s12m_s13_transformer_terminal_voltage_mismatch"
    )
    module._validate_result(_fidelity_parents(values), result)


def test_downstream_mixed_advanced_and_fallback_tree_resolves() -> None:
    parents = _mixed_fidelity_parents()
    result = module._build_result(parents)
    module._validate_result(parents, result)
    tree = result.network_exit_states.iloc[0]
    assert tree["mv_hv_operating_solution_resolved"]
    assert tree["s12m_ready_transformer_count"] == 2
    assert tree["transformer_injected_p_total_w"] == pytest.approx(
        parents[0].states["p_network_terminal_w"].sum(),
        rel=module.EQUATION_REL_TOL,
        abs=module.EQUATION_ABS_TOL,
    )
    assert tree["transformer_injected_q_total_var"] == pytest.approx(
        parents[0].states["q_network_terminal_var"].sum(),
        rel=module.EQUATION_REL_TOL,
        abs=module.EQUATION_ABS_TOL,
    )
    assert result.transformer_terminal_states["s12m_load_loss_fallback_applied"].tolist() == [
        False,
        True,
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("terminal_solution_fidelity", "coupled_advanced_load_loss"),
        ("load_loss_fallback_applied", False),
        ("p_network_terminal_w", 1.0),
    ],
)
def test_downstream_fallback_s12m_canonical_replay_is_retained(field: str, value: object) -> None:
    values, _ = _fidelity_case()
    parent = values["transformer_advanced_operating_solution"]
    frame = parent.states.copy(deep=True)
    frame.at[frame.index[0], field] = value
    with pytest.raises(ValueError, match="S12M.*canonical replay"):
        calculate_topology_mv_hv_operating_solution(
            **dict(values, transformer_advanced_operating_solution=replace(parent, states=frame))
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("s12m_terminal_solution_fidelity", "coupled_advanced_load_loss"),
        ("s12m_load_loss_fallback_applied", False),
    ],
)
def test_downstream_fidelity_fields_are_independently_validated(field: str, value: object) -> None:
    values, result = _fidelity_case()
    frame = result.transformer_terminal_states.copy(deep=True)
    frame.at[frame.index[0], field] = value
    with pytest.raises(RuntimeError, match="independent exact closure"):
        module._validate_result(
            _fidelity_parents(values), replace(result, transformer_terminal_states=frame)
        )


@pytest.mark.parametrize(
    "state",
    [
        "unresolved_advanced_transformer_fixed_point_nonconvergence",
        "unresolved_nonfinite_advanced_transformer_operating_state",
        "unresolved_upstream_s12k_corrected_load_loss",
    ],
)
def test_downstream_unresolved_s12m_is_not_admitted_from_energisation(state: str) -> None:
    values, _ = _fidelity_case()
    s12m, network, boundary = _fidelity_parents(values)
    frame = s12m.states.copy(deep=True)
    frame.at[frame.index[0], "transformer_advanced_operating_solution_state"] = state
    parents = replace(s12m, states=frame), network, boundary
    result = module._build_result(parents)
    module._validate_result(parents, result)
    assert not result.transformer_terminal_states.iloc[0]["s12m_injection_ready"]
    assert result.network_exit_states.iloc[0]["mv_hv_operating_state"] == (
        "unresolved_upstream_s12m_transformer_operating_solution"
    )


def test_downstream_fallback_validator_stays_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    values, result = _fidelity_case()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production readiness/solver used by validator")

    for name in ("_build_result", "_solve_tree", "_transformer_frame", "_make_frame"):
        monkeypatch.setattr(module, name, fail)
    module._validate_result(_fidelity_parents(values), result)


def test_downstream_missing_s12m_has_no_fabricated_fidelity() -> None:
    values, _ = _fidelity_case()
    s12m, network, boundary = _fidelity_parents(values)
    parents = replace(s12m, states=s12m.states.iloc[:0].copy(deep=True)), network, boundary
    result = module._build_result(parents)
    module._validate_result(parents, result)
    row = result.transformer_terminal_states.iloc[0]
    assert not row["s12m_row_present"]
    assert not row["s12m_injection_ready"]
    assert row["s12m_terminal_solution_fidelity"] == ""
    assert pd.isna(row["s12m_load_loss_fallback_applied"])


def test_downstream_disconnected_terminal_retains_fallback_audit_only() -> None:
    values, _ = _fidelity_case()
    disconnected = dict(values, mv_hv_segment_by_id={})
    network = module._call(resolve_topology_mv_hv_network_authority, disconnected)
    disconnected["mv_hv_network_authority"] = network
    boundary = module._call(resolve_topology_mv_hv_grid_boundary_voltage_authority, disconnected)
    parents = values["transformer_advanced_operating_solution"], network, boundary
    result = module._build_result(parents)
    module._validate_result(parents, result)
    row = result.transformer_terminal_states.iloc[0]
    assert not row["transformer_connected_to_network_exit"]
    assert row["s12m_injection_ready"]
    assert row["s12m_terminal_solution_fidelity"] == "coupled_s12g_load_loss_fallback"
    assert row["s12m_load_loss_fallback_applied"]
    assert not row["mv_hv_operating_solution_resolved"]
