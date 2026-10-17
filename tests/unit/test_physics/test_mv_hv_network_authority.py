from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from heliotelligence.physics import mv_hv_network_authority as module
from heliotelligence.physics.lv_ac_collection_authority import (
    resolve_topology_lv_ac_collection_authority,
)
from heliotelligence.physics.mv_hv_network_authority import (
    MV_HV_NETWORK_AUTHORITY_CONTRACT_ID,
    MV_HV_NETWORK_AUTHORITY_MODEL_ID,
    MvHvGridBoundaryAuthority,
    MvHvNetworkBasisAuthority,
    MvHvNetworkNodeAuthority,
    MvHvNetworkSegmentAuthority,
    MvHvTransformerTerminalBindingAuthority,
    MvHvVoltageLevelAuthority,
    RevenueMeterBoundaryAuthority,
    resolve_topology_mv_hv_network_authority,
)
from heliotelligence.physics.transformer_authority import resolve_transformer_static_authority
from tests.unit.test_physics.test_transformer_authority import (
    _basis,
    _equipment,
    _s11a_inputs,
    _transformer_topology,
)


def _network_basis() -> MvHvNetworkBasisAuthority:
    return MvHvNetworkBasisAuthority(
        "balanced_three_phase",
        "line_to_line_rms",
        "per_phase_series",
        "per_phase_total_nominal_pi",
        "radial",
        "single-line",
        "high",
    )


def _level(identifier: str = "11-kv", voltage: float = 11_000.0) -> MvHvVoltageLevelAuthority:
    return MvHvVoltageLevelAuthority(identifier, voltage, "design", "high")


def _node(identifier: str, kind: str, level: str = "11-kv") -> MvHvNetworkNodeAuthority:
    return MvHvNetworkNodeAuthority(identifier, kind, level, "single-line", "high")  # type: ignore[arg-type]


def _segment(
    identifier: str,
    source: str,
    target: str,
    *,
    level_values: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> MvHvNetworkSegmentAuthority:
    return MvHvNetworkSegmentAuthority(
        identifier, source, target, *level_values, "cable schedule", "high"
    )


def _binding(transformer: str, node: str) -> MvHvTransformerTerminalBindingAuthority:
    return MvHvTransformerTerminalBindingAuthority(
        transformer,
        f"{transformer}:network",
        node,
        "transformer_network_side_terminal",
        "mv_hv_transformer_terminal_node",
        "direct_electrical_boundary",
        "single-line",
        "high",
    )


def _grid(identifier: str, node: str) -> MvHvGridBoundaryAuthority:
    return MvHvGridBoundaryAuthority(
        identifier, node, "grid_interconnection_boundary", "grid agreement", "high"
    )


def _meter(identifier: str, node: str) -> RevenueMeterBoundaryAuthority:
    return RevenueMeterBoundaryAuthority(
        identifier,
        node,
        "revenue_meter_boundary",
        "positive_plant_to_grid",
        "positive_plant_to_grid",
        "three_phase_total",
        "metering diagram",
        "high",
    )


def _parents(
    transformer_ids: tuple[str, ...] = ("tx-1",),
) -> dict[str, Any]:
    exits = tuple(f"exit-{index}" for index in range(len(transformer_ids)))
    topology, nodes, segments, bindings = _s11a_inputs(exits)
    s11_basis = _basis()
    s11 = resolve_topology_lv_ac_collection_authority(
        topology, s11_basis, nodes, segments, bindings
    )
    equipment = {identifier: _equipment(identifier) for identifier in transformer_ids}
    transformer_topology = {
        identifier: _transformer_topology(identifier, exits[index])
        for index, identifier in enumerate(transformer_ids)
    }
    s12a = resolve_transformer_static_authority(
        topology,
        s11_basis,
        nodes,
        segments,
        bindings,
        s11,
        equipment,
        transformer_topology,
    )
    return {
        "topology": topology,
        "network_basis": s11_basis,
        "node_authority_by_id": nodes,
        "segment_authority_by_id": segments,
        "inverter_terminal_binding_by_inverter_id": bindings,
        "lv_ac_collection_authority": s11,
        "transformer_equipment_by_id": equipment,
        "transformer_topology_by_id": transformer_topology,
        "transformer_static_authority": s12a,
    }


def _inputs() -> dict[str, Any]:
    return {
        **_parents(),
        "mv_hv_network_basis": _network_basis(),
        "mv_hv_voltage_level_by_id": {"11-kv": _level()},
        "mv_hv_node_by_id": {
            "tx-node": _node("tx-node", "transformer_terminal"),
            "exit": _node("exit", "network_exit"),
        },
        "mv_hv_segment_by_id": {"feeder": _segment("feeder", "tx-node", "exit")},
        "mv_hv_transformer_terminal_binding_by_transformer_id": {
            "tx-1": _binding("tx-1", "tx-node")
        },
        "mv_hv_grid_boundary_by_id": {"grid": _grid("grid", "exit")},
        "revenue_meter_boundary_by_id": {"meter": _meter("meter", "exit")},
    }


def _resolve(values: dict[str, Any] | None = None) -> Any:
    return resolve_topology_mv_hv_network_authority(**(values or _inputs()))


def test_no_authority_is_gracefully_unresolved() -> None:
    values = _inputs()
    values.update(
        mv_hv_network_basis=None,
        mv_hv_voltage_level_by_id={},
        mv_hv_node_by_id={},
        mv_hv_segment_by_id={},
        mv_hv_transformer_terminal_binding_by_transformer_id={},
        mv_hv_grid_boundary_by_id={},
        revenue_meter_boundary_by_id={},
    )
    row = _resolve(values).transformer_states.loc["tx-1"]
    assert row["mv_hv_network_authority_state"] == "unresolved_no_mv_hv_network_basis_authority"
    assert not row["mv_hv_network_authority_resolved"]


def test_simple_tree_meter_and_grid_are_distinct_colocated_authorities() -> None:
    result = _resolve()
    row = result.transformer_states.loc["tx-1"]
    assert row["mv_hv_network_authority_state"] == (
        "resolved_mv_hv_network_and_meter_boundary_authority"
    )
    assert row["path_segment_ids"] == ("feeder",)
    assert row["revenue_meter_colocated_with_grid_boundary"]
    assert result.grid_boundary_by_id["grid"].reference_plane == "grid_interconnection_boundary"
    assert result.revenue_meter_boundary_by_id["meter"].reference_plane == (
        "revenue_meter_boundary"
    )
    assert result.diagnostics.zero_series_impedance_segment_count == 1
    assert result.diagnostics.zero_shunt_admittance_segment_count == 1


def test_internal_meter_and_nonzero_nominal_pi_values_are_preserved() -> None:
    values = _inputs()
    values["mv_hv_node_by_id"]["junction"] = _node("junction", "junction")
    values["mv_hv_segment_by_id"] = {
        "a": _segment("a", "tx-node", "junction", level_values=(0.2, 0.3, 1e-6, 2e-6)),
        "b": _segment("b", "junction", "exit"),
    }
    values["revenue_meter_boundary_by_id"] = {"meter": _meter("meter", "junction")}
    result = _resolve(values)
    row = result.transformer_states.loc["tx-1"]
    assert row["path_segment_ids"] == ("a", "b")
    assert row["revenue_meter_node_id"] == "junction"
    assert not row["revenue_meter_colocated_with_grid_boundary"]
    assert result.segments_by_id["a"].total_shunt_susceptance_siemens_per_phase == 2e-6
    assert result.diagnostics.nonzero_series_impedance_segment_count == 1
    assert result.diagnostics.nonzero_shunt_admittance_segment_count == 1


def test_two_transformers_can_merge_to_one_meter() -> None:
    values = _inputs()
    values.update(_parents(("tx-a", "tx-b")))
    values["mv_hv_node_by_id"] = {
        "ta": _node("ta", "transformer_terminal"),
        "tb": _node("tb", "transformer_terminal"),
        "j": _node("j", "junction"),
        "exit": _node("exit", "network_exit"),
    }
    values["mv_hv_segment_by_id"] = {
        "a": _segment("a", "ta", "j"),
        "b": _segment("b", "tb", "j"),
        "c": _segment("c", "j", "exit"),
    }
    values["mv_hv_transformer_terminal_binding_by_transformer_id"] = {
        "tx-a": _binding("tx-a", "ta"),
        "tx-b": _binding("tx-b", "tb"),
    }
    values["revenue_meter_boundary_by_id"] = {"meter": _meter("meter", "j")}
    result = _resolve(values)
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-b"]
    assert result.transformer_states["mv_hv_network_authority_resolved"].all()


def test_two_independent_trees_use_separate_meters() -> None:
    values = _inputs()
    values.update(_parents(("tx-a", "tx-b")))
    values["mv_hv_node_by_id"] = {
        name: _node(name, kind)
        for name, kind in {
            "ta": "transformer_terminal",
            "tb": "transformer_terminal",
            "ea": "network_exit",
            "eb": "network_exit",
        }.items()
    }
    values["mv_hv_segment_by_id"] = {
        "a": _segment("a", "ta", "ea"),
        "b": _segment("b", "tb", "eb"),
    }
    values["mv_hv_transformer_terminal_binding_by_transformer_id"] = {
        "tx-a": _binding("tx-a", "ta"),
        "tx-b": _binding("tx-b", "tb"),
    }
    values["mv_hv_grid_boundary_by_id"] = {
        "ga": _grid("ga", "ea"),
        "gb": _grid("gb", "eb"),
    }
    values["revenue_meter_boundary_by_id"] = {
        "ma": _meter("ma", "ea"),
        "mb": _meter("mb", "eb"),
    }
    result = _resolve(values)
    assert result.transformer_states.loc["tx-a", "revenue_meter_id"] == "ma"
    assert result.transformer_states.loc["tx-b", "revenue_meter_id"] == "mb"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("cross_voltage", "cross voltage levels"),
        ("unknown_transformer", "unknown transformer"),
        ("terminal_mismatch", "does not match canonical"),
        ("unbound_terminal", "requires exactly one binding"),
        ("exit_origin", "cannot originate"),
        ("terminal_receive", "cannot receive"),
        ("multiple_outgoing", "at most one outgoing"),
        ("cycle", "directed cycle"),
    ],
)
def test_structural_contradictions_are_rejected(mutation: str, message: str) -> None:
    values = _inputs()
    if mutation == "cross_voltage":
        values["mv_hv_voltage_level_by_id"]["33-kv"] = _level("33-kv", 33_000.0)
        values["mv_hv_node_by_id"]["exit"] = _node("exit", "network_exit", "33-kv")
    elif mutation == "unknown_transformer":
        values["mv_hv_transformer_terminal_binding_by_transformer_id"] = {
            "ghost": _binding("ghost", "tx-node")
        }
    elif mutation == "terminal_mismatch":
        values["mv_hv_transformer_terminal_binding_by_transformer_id"]["tx-1"] = replace(
            _binding("tx-1", "tx-node"), transformer_network_terminal_id="wrong"
        )
    elif mutation == "unbound_terminal":
        values["mv_hv_node_by_id"]["orphan"] = _node("orphan", "transformer_terminal")
    elif mutation == "exit_origin":
        values["mv_hv_segment_by_id"] = {"bad": _segment("bad", "exit", "tx-node")}
    elif mutation == "terminal_receive":
        values["mv_hv_node_by_id"]["junction"] = _node("junction", "junction")
        values["mv_hv_segment_by_id"] = {"bad": _segment("bad", "junction", "tx-node")}
    elif mutation == "multiple_outgoing":
        values["mv_hv_node_by_id"]["exit-2"] = _node("exit-2", "network_exit")
        values["mv_hv_segment_by_id"]["second"] = _segment("second", "tx-node", "exit-2")
    else:
        values["mv_hv_node_by_id"] = {
            "tx-node": _node("tx-node", "transformer_terminal"),
            "a": _node("a", "junction"),
            "b": _node("b", "junction"),
        }
        values["mv_hv_segment_by_id"] = {
            "start": _segment("start", "tx-node", "a"),
            "ab": _segment("ab", "a", "b"),
            "ba": _segment("ba", "b", "a"),
        }
        values["mv_hv_grid_boundary_by_id"] = {}
        values["revenue_meter_boundary_by_id"] = {}
    with pytest.raises(ValueError, match=message):
        _resolve(values)


def test_missing_or_off_path_meter_preserves_topology_but_does_not_resolve() -> None:
    values = _inputs()
    values["mv_hv_node_by_id"]["other"] = _node("other", "junction")
    values["revenue_meter_boundary_by_id"] = {"meter": _meter("meter", "other")}
    row = _resolve(values).transformer_states.loc["tx-1"]
    assert row["path_to_network_exit_resolved"]
    assert row["grid_boundary_resolved"]
    assert not row["revenue_meter_on_transformer_path"]
    assert row["mv_hv_network_authority_state"] == (
        "unresolved_no_revenue_meter_boundary_on_path"
    )
    assert row["path_segment_ids"] == ("feeder",)


def test_multiple_meters_on_one_path_are_rejected() -> None:
    values = _inputs()
    values["revenue_meter_boundary_by_id"]["second"] = _meter("second", "tx-node")
    with pytest.raises(ValueError, match="ambiguous"):
        _resolve(values)


def test_mappings_are_detached_immutable_and_ordered() -> None:
    values = _inputs()
    supplied = values["mv_hv_node_by_id"]
    result = _resolve(values)
    supplied["later"] = _node("later", "junction")
    assert "later" not in result.nodes_by_id
    assert type(result.nodes_by_id) is MappingProxyType
    with pytest.raises(TypeError):
        result.nodes_by_id["later"] = _node("later", "junction")  # type: ignore[index]
    assert tuple(result.nodes_by_id) == ("exit", "tx-node")


def test_canonical_s12a_parent_frame_tampering_is_rejected() -> None:
    values = _inputs()
    parent = values["transformer_static_authority"]
    frame = parent.transformer_states.copy(deep=True)
    frame.loc["tx-1", "transformer_static_authority_resolved"] = False
    values["transformer_static_authority"] = replace(parent, transformer_states=frame)
    with pytest.raises(ValueError, match="canonical replay"):
        _resolve(values)


def test_independent_validator_does_not_call_production_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _inputs()
    result = _resolve(values)
    canonical = values["transformer_static_authority"]

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("production builder called")

    monkeypatch.setattr(module, "_record", fail)
    monkeypatch.setattr(module, "_frame", fail)
    monkeypatch.setattr(module, "_diagnostics", fail)
    monkeypatch.setattr(module, "_validate_graph", fail)
    monkeypatch.setattr(module, "_validate_boundaries", fail)
    module._validate_result(canonical, result)


@pytest.mark.parametrize(
    "target",
    ["frame", "diagnostics"],
)
def test_result_and_diagnostics_tampering_is_rejected(target: str) -> None:
    values = _inputs()
    result = _resolve(values)
    if target == "frame":
        frame = result.transformer_states.copy(deep=True)
        frame.loc["tx-1", "grid_boundary_id"] = "tampered"
        tampered = replace(result, transformer_states=frame)
    else:
        tampered = replace(
            result,
            diagnostics=replace(result.diagnostics, fully_resolved_transformer_count=0),
        )
    with pytest.raises(ValueError):
        module._validate_result(values["transformer_static_authority"], tampered)


def test_public_schema_is_explicit_unique_and_deterministic() -> None:
    result = _resolve()
    assert tuple(result.transformer_states.columns) == module._COLUMNS
    assert len(module._COLUMNS) == len(set(module._COLUMNS))
    assert module._COLUMNS[0] == "network_basis_resolved"
    assert module._COLUMNS[-1] == "mv_hv_network_authority_coverage_scope"
    source = module.__loader__.get_source(module.__name__)  # type: ignore[union-attr]
    assert "tuple(_BOOL_COLUMNS)" not in source
    assert result.transformer_states.loc["tx-1", "mv_hv_network_authority_contract"] == (
        MV_HV_NETWORK_AUTHORITY_CONTRACT_ID
    )
    assert result.diagnostics.model == MV_HV_NETWORK_AUTHORITY_MODEL_ID
