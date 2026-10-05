"""Tests for S11A static LV AC collection authority."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig, InverterUnitConfig
from heliotelligence.physics import lv_ac_collection_authority as authority_module
from heliotelligence.physics.lv_ac_collection_authority import (
    TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID,
    TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_SCOPE,
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    TopologyLvAcCollectionAuthorityDiagnostics,
    _validate_result,
    resolve_topology_lv_ac_collection_authority,
)


def _topology(*inverter_ids: str) -> ElectricalTopologyConfig:
    return ElectricalTopologyConfig(
        inverters=[InverterUnitConfig(id=inverter_id) for inverter_id in inverter_ids]
    )


def _basis() -> LvAcCollectionNetworkBasisAuthority:
    return LvAcCollectionNetworkBasisAuthority(
        "balanced_three_phase", "line_to_line_rms", "per_phase_series", "drawing:basis", "high"
    )


def _node(node_id: str, kind: str) -> LvAcCollectionNodeAuthority:
    return LvAcCollectionNodeAuthority(node_id, kind, f"drawing:{node_id}", "high")  # type: ignore[arg-type]


def _segment(
    segment_id: str,
    source: str,
    destination: str,
    resistance: float = 0.1,
    reactance: float = 0.02,
) -> LvAcCollectionSegmentAuthority:
    return LvAcCollectionSegmentAuthority(
        segment_id,
        source,
        destination,
        resistance,
        reactance,
        f"schedule:{segment_id}",
        "high",
    )


def _binding(inverter_id: str, node_id: str) -> LvAcInverterTerminalBindingAuthority:
    return LvAcInverterTerminalBindingAuthority(
        inverter_id, node_id, "inverter_ac_output", f"drawing:{inverter_id}", "high"
    )


def _resolve(
    topology: ElectricalTopologyConfig,
    nodes: dict[str, LvAcCollectionNodeAuthority] | None = None,
    segments: dict[str, LvAcCollectionSegmentAuthority] | None = None,
    bindings: dict[str, LvAcInverterTerminalBindingAuthority] | None = None,
    basis: LvAcCollectionNetworkBasisAuthority | None = None,
) -> Any:
    return resolve_topology_lv_ac_collection_authority(
        topology,
        _basis() if basis is None else basis,
        nodes or {},
        segments or {},
        bindings or {},
    )


def _single(
    *, resistance: float = 0.1, reactance: float = 0.02
) -> tuple[
    ElectricalTopologyConfig,
    dict[str, LvAcCollectionNodeAuthority],
    dict[str, LvAcCollectionSegmentAuthority],
    dict[str, LvAcInverterTerminalBindingAuthority],
]:
    topology = _topology("inv-1")
    nodes = {
        "terminal": _node("terminal", "inverter_terminal"),
        "exit": _node("exit", "collection_exit"),
    }
    segments = {"feeder": _segment("feeder", "terminal", "exit", resistance, reactance)}
    bindings = {"inv-1": _binding("inv-1", "terminal")}
    return topology, nodes, segments, bindings


@pytest.mark.parametrize(("resistance", "reactance"), [(0.0, 0.0), (0.1, 0.0), (0.1, 0.02)])
def test_single_inverter_direct_path_and_explicit_impedance(
    resistance: float, reactance: float
) -> None:
    topology, nodes, segments, bindings = _single(resistance=resistance, reactance=reactance)
    result = _resolve(topology, nodes, segments, bindings)
    row = result.inverter_states.iloc[0]
    assert row["lv_ac_collection_authority_resolved"]
    assert row["lv_ac_collection_authority_state"] == ("resolved_lv_ac_collection_path_authority")
    assert row["terminal_node_id"] == "terminal"
    assert row["collection_exit_node_id"] == "exit"
    assert row["path_segment_ids"] == ("feeder",)
    assert row["path_segment_count"] == 1
    assert result.segments_by_id["feeder"].series_resistance_ohm_per_phase == resistance
    assert result.segments_by_id["feeder"].series_reactance_ohm_per_phase == reactance


def test_two_inverters_merge_through_one_shared_segment() -> None:
    topology = _topology("inv-a", "inv-b")
    nodes = {
        "ta": _node("ta", "inverter_terminal"),
        "tb": _node("tb", "inverter_terminal"),
        "j": _node("j", "junction"),
        "exit": _node("exit", "collection_exit"),
    }
    segments = {
        "a-j": _segment("a-j", "ta", "j"),
        "b-j": _segment("b-j", "tb", "j"),
        "shared": _segment("shared", "j", "exit"),
    }
    bindings = {"inv-a": _binding("inv-a", "ta"), "inv-b": _binding("inv-b", "tb")}
    result = _resolve(topology, nodes, segments, bindings)
    assert result.inverter_states.loc["inv-a", "path_segment_ids"] == ("a-j", "shared")
    assert result.inverter_states.loc["inv-b", "path_segment_ids"] == ("b-j", "shared")
    assert list(result.segments_by_id).count("shared") == 1


def test_multi_level_path_order_is_terminal_to_exit() -> None:
    topology = _topology("inv-1")
    nodes = {
        "t": _node("t", "inverter_terminal"),
        "j1": _node("j1", "junction"),
        "j2": _node("j2", "junction"),
        "e": _node("e", "collection_exit"),
    }
    segments = {
        "s2": _segment("s2", "j1", "j2"),
        "s3": _segment("s3", "j2", "e"),
        "s1": _segment("s1", "t", "j1"),
    }
    result = _resolve(topology, nodes, segments, {"inv-1": _binding("inv-1", "t")})
    assert result.inverter_states.loc["inv-1", "path_segment_ids"] == ("s1", "s2", "s3")


def test_two_independent_collection_trees_and_direct_exit_merges() -> None:
    topology = _topology("a", "b", "c")
    nodes = {
        **{name: _node(name, "inverter_terminal") for name in ("ta", "tb", "tc")},
        "e1": _node("e1", "collection_exit"),
        "e2": _node("e2", "collection_exit"),
    }
    segments = {
        "a": _segment("a", "ta", "e1"),
        "b": _segment("b", "tb", "e1"),
        "c": _segment("c", "tc", "e2"),
    }
    bindings = {
        "a": _binding("a", "ta"),
        "b": _binding("b", "tb"),
        "c": _binding("c", "tc"),
    }
    states = _resolve(topology, nodes, segments, bindings).inverter_states
    assert states.loc["a", "collection_exit_node_id"] == "e1"
    assert states.loc["b", "collection_exit_node_id"] == "e1"
    assert states.loc["c", "collection_exit_node_id"] == "e2"


def test_mapping_order_never_changes_canonical_inverter_order() -> None:
    topology = _topology("inv-a", "inv-b")
    nodes = {
        "ta": _node("ta", "inverter_terminal"),
        "tb": _node("tb", "inverter_terminal"),
        "exit": _node("exit", "collection_exit"),
    }
    segments = {
        "sa": _segment("sa", "ta", "exit"),
        "sb": _segment("sb", "tb", "exit"),
    }
    bindings = {"inv-a": _binding("inv-a", "ta"), "inv-b": _binding("inv-b", "tb")}
    first = _resolve(topology, nodes, segments, bindings)
    second = _resolve(
        topology,
        dict(reversed(list(nodes.items()))),
        dict(reversed(list(segments.items()))),
        dict(reversed(list(bindings.items()))),
    )
    pd.testing.assert_frame_equal(first.inverter_states, second.inverter_states, check_exact=True)
    assert first.diagnostics == second.diagnostics
    assert first.inverter_states.index.tolist() == ["inv-a", "inv-b"]


def test_partial_backbone_and_missing_binding_remain_unresolved() -> None:
    topology = _topology("inv-1")
    nodes = {"j": _node("j", "junction"), "exit": _node("exit", "collection_exit")}
    segments = {"backbone": _segment("backbone", "j", "exit")}
    row = _resolve(topology, nodes, segments, {}).inverter_states.iloc[0]
    assert row["lv_ac_collection_authority_state"] == "unresolved_no_inverter_terminal_binding"
    assert row["terminal_node_id"] == ""
    assert row["path_segment_ids"] == ()
    assert pd.isna(row["path_segment_count"])


def test_bound_terminal_incomplete_path_is_valid_partial_authority() -> None:
    topology = _topology("inv-1")
    nodes = {
        "t": _node("t", "inverter_terminal"),
        "j": _node("j", "junction"),
    }
    segments = {"known": _segment("known", "t", "j")}
    row = _resolve(
        topology, nodes, segments, {"inv-1": _binding("inv-1", "t")}
    ).inverter_states.iloc[0]
    assert row["inverter_terminal_binding_resolved"]
    assert not row["path_to_collection_exit_resolved"]
    assert row["path_segment_ids"] == ()
    assert row["lv_ac_collection_authority_state"] == (
        "unresolved_inverter_terminal_path_to_collection_exit"
    )


def test_transformer_like_node_name_does_not_infer_collection_exit_kind() -> None:
    topology = _topology("inv-1")
    nodes = {
        "t": _node("t", "inverter_terminal"),
        "transformer-1": _node("transformer-1", "junction"),
    }
    segments = {"s": _segment("s", "t", "transformer-1")}
    row = _resolve(
        topology, nodes, segments, {"inv-1": _binding("inv-1", "t")}
    ).inverter_states.iloc[0]
    assert not row["path_to_collection_exit_resolved"]
    assert row["collection_exit_node_id"] == ""


def test_missing_network_basis_has_precedence_without_erasing_path_evidence() -> None:
    topology, nodes, segments, bindings = _single()
    result = resolve_topology_lv_ac_collection_authority(topology, None, nodes, segments, bindings)
    row = result.inverter_states.iloc[0]
    assert not row["network_basis_resolved"]
    assert row["path_to_collection_exit_resolved"]
    assert not row["lv_ac_collection_authority_resolved"]
    assert row["lv_ac_collection_authority_state"] == (
        "unresolved_no_lv_ac_network_basis_authority"
    )
    assert result.diagnostics.resolved_inverter_path_count == 1
    assert result.diagnostics.unresolved_inverter_count == 0


def test_empty_topology_has_stable_schema_and_zero_diagnostics() -> None:
    result = resolve_topology_lv_ac_collection_authority(
        ElectricalTopologyConfig(), None, {}, {}, {}
    )
    assert result.inverter_states.empty
    assert result.inverter_states.index.name == "inverter_id"
    assert all(
        str(result.inverter_states[column].dtype) == "bool"
        for column in (
            "network_basis_resolved",
            "inverter_terminal_binding_resolved",
            "path_to_collection_exit_resolved",
            "lv_ac_collection_authority_resolved",
        )
    )
    assert str(result.inverter_states["path_segment_count"].dtype) == "Int64"
    assert result.diagnostics == TopologyLvAcCollectionAuthorityDiagnostics(
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID
    )


def test_empty_topology_accepts_junction_exit_backbone_only() -> None:
    nodes = {"j": _node("j", "junction"), "exit": _node("exit", "collection_exit")}
    result = _resolve(
        ElectricalTopologyConfig(),
        nodes,
        {"s": _segment("s", "j", "exit")},
    )
    assert result.diagnostics.node_count == 2
    assert result.diagnostics.segment_count == 1


@pytest.mark.parametrize(
    ("mapping_name", "mapping"),
    [
        ("node", {"wrong": _node("node", "junction")}),
        ("segment", {"wrong": _segment("segment", "a", "b")}),
        ("binding", {"wrong": _binding("inv-1", "terminal")}),
    ],
)
def test_mapping_key_identity_mismatch_is_rejected(
    mapping_name: str, mapping: dict[str, Any]
) -> None:
    topology = _topology("inv-1")
    kwargs: dict[str, Any] = {"nodes": {}, "segments": {}, "bindings": {}}
    kwargs[{"node": "nodes", "segment": "segments", "binding": "bindings"}[mapping_name]] = mapping
    with pytest.raises(ValueError, match="mapping key"):
        _resolve(topology, **kwargs)


def test_unknown_inverter_binding_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown inverter"):
        _resolve(_topology("known"), {}, {}, {"other": _binding("other", "t")})


@pytest.mark.parametrize("kind", ["junction", "collection_exit"])
def test_binding_to_nonterminal_is_rejected(kind: str) -> None:
    with pytest.raises(ValueError, match="inverter_terminal node"):
        _resolve(
            _topology("inv-1"),
            {"n": _node("n", kind)},
            {},
            {"inv-1": _binding("inv-1", "n")},
        )


def test_two_inverters_cannot_share_one_terminal() -> None:
    with pytest.raises(ValueError, match="only one inverter"):
        _resolve(
            _topology("a", "b"),
            {"t": _node("t", "inverter_terminal")},
            {},
            {"a": _binding("a", "t"), "b": _binding("b", "t")},
        )


def test_unbound_supplied_terminal_is_rejected_without_name_inference() -> None:
    with pytest.raises(ValueError, match="every supplied inverter_terminal"):
        _resolve(_topology("inverter-1"), {"inverter-1": _node("inverter-1", "inverter_terminal")})


def test_segment_missing_node_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown node"):
        _resolve(
            ElectricalTopologyConfig(),
            {"j": _node("j", "junction")},
            {"s": _segment("s", "j", "missing")},
        )


def test_self_loop_is_rejected() -> None:
    with pytest.raises(ValueError, match="self loops"):
        _resolve(
            ElectricalTopologyConfig(),
            {"j": _node("j", "junction")},
            {"s": _segment("s", "j", "j")},
        )


def test_directed_cycle_is_rejected() -> None:
    nodes = {"a": _node("a", "junction"), "b": _node("b", "junction")}
    segments = {"ab": _segment("ab", "a", "b"), "ba": _segment("ba", "b", "a")}
    with pytest.raises(ValueError, match="cycle"):
        _resolve(ElectricalTopologyConfig(), nodes, segments)


def test_two_outgoing_segments_are_rejected() -> None:
    nodes = {
        "j": _node("j", "junction"),
        "e1": _node("e1", "collection_exit"),
        "e2": _node("e2", "collection_exit"),
    }
    segments = {"one": _segment("one", "j", "e1"), "two": _segment("two", "j", "e2")}
    with pytest.raises(ValueError, match="at most one outgoing"):
        _resolve(ElectricalTopologyConfig(), nodes, segments)


def test_segment_from_exit_is_rejected() -> None:
    nodes = {"e": _node("e", "collection_exit"), "j": _node("j", "junction")}
    with pytest.raises(ValueError, match="must not originate"):
        _resolve(ElectricalTopologyConfig(), nodes, {"s": _segment("s", "e", "j")})


def test_segment_into_terminal_is_rejected() -> None:
    nodes = {"j": _node("j", "junction"), "t": _node("t", "inverter_terminal")}
    bindings = {"inv": _binding("inv", "t")}
    with pytest.raises(ValueError, match="must not receive"):
        _resolve(_topology("inv"), nodes, {"s": _segment("s", "j", "t")}, bindings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("series_resistance_ohm_per_phase", -1.0),
        ("series_reactance_ohm_per_phase", -1.0),
        ("series_resistance_ohm_per_phase", float("nan")),
        ("series_reactance_ohm_per_phase", float("nan")),
        ("series_resistance_ohm_per_phase", float("inf")),
        ("series_reactance_ohm_per_phase", float("inf")),
        ("series_resistance_ohm_per_phase", True),
        ("series_reactance_ohm_per_phase", False),
    ],
)
def test_invalid_segment_numeric_values_are_rejected(field: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "segment_id": "s",
        "from_node_id": "a",
        "to_node_id": "b",
        "series_resistance_ohm_per_phase": 0.1,
        "series_reactance_ohm_per_phase": 0.02,
        "parameter_source": "schedule",
        "confidence": "high",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        LvAcCollectionSegmentAuthority(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", " ", " leading", "trailing "])
def test_blank_or_ambiguous_ids_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        _node(value, "junction")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: LvAcCollectionNetworkBasisAuthority(
            "single_phase",  # type: ignore[arg-type]
            "line_to_line_rms",
            "per_phase_series",
            "source",
            "high",
        ),
        lambda: LvAcCollectionNetworkBasisAuthority(
            "balanced_three_phase",
            "line_to_neutral",  # type: ignore[arg-type]
            "per_phase_series",
            "source",
            "high",
        ),
        lambda: LvAcCollectionNetworkBasisAuthority(
            "balanced_three_phase",
            "line_to_line_rms",
            "total_series",  # type: ignore[arg-type]
            "source",
            "high",
        ),
        lambda: LvAcCollectionNodeAuthority(
            "n",
            "bus",  # type: ignore[arg-type]
            "source",
            "high",
        ),
        lambda: LvAcCollectionNodeAuthority("n", "junction", " ", "high"),
        lambda: LvAcCollectionNodeAuthority(
            "n",
            "junction",
            "source",
            "certain",  # type: ignore[arg-type]
        ),
    ],
)
def test_invalid_enums_source_and_confidence_are_rejected(factory: Any) -> None:
    with pytest.raises(ValueError):
        factory()


def test_authority_types_are_frozen_and_exact_type_admission_is_required() -> None:
    basis = _basis()
    with pytest.raises(FrozenInstanceError):
        basis.parameter_source = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError, match="exact authority type"):
        loose_nodes: Any = {"x": {"node_id": "x"}}
        resolve_topology_lv_ac_collection_authority(
            ElectricalTopologyConfig(),
            basis,
            loose_nodes,
            {},
            {},
        )


def test_binding_reference_plane_is_exact() -> None:
    with pytest.raises(ValueError, match="reference_plane"):
        LvAcInverterTerminalBindingAuthority(
            "inv",
            "terminal",
            "ac_output",  # type: ignore[arg-type]
            "drawing",
            "high",
        )


def test_segment_requires_both_direct_r_and_x_authority() -> None:
    with pytest.raises(TypeError):
        LvAcCollectionSegmentAuthority(  # type: ignore[call-arg]
            segment_id="s",
            from_node_id="a",
            to_node_id="b",
            series_resistance_ohm_per_phase=0.1,
            parameter_source="schedule",
            confidence="high",
        )


def test_result_mappings_are_immutable_independent_copies_and_frames_are_owned() -> None:
    topology, nodes, segments, bindings = _single()
    first = _resolve(topology, nodes, segments, bindings)
    second = _resolve(topology, nodes, segments, bindings)
    nodes.clear()
    segments.clear()
    bindings.clear()
    assert set(first.nodes_by_id) == {"terminal", "exit"}
    assert isinstance(first.nodes_by_id, MappingProxyType)
    with pytest.raises(TypeError):
        first.nodes_by_id["x"] = _node("x", "junction")  # type: ignore[index]
    first.inverter_states.iloc[0, first.inverter_states.columns.get_loc("terminal_node_id")] = "x"
    assert second.inverter_states.iloc[0]["terminal_node_id"] == "terminal"


def test_provenance_and_diagnostics_close_exactly() -> None:
    topology, nodes, segments, bindings = _single(resistance=0.0, reactance=0.0)
    result = _resolve(topology, nodes, segments, bindings)
    row = result.inverter_states.iloc[0]
    assert row["topology_lv_ac_collection_authority_contract"] == (
        TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_CONTRACT_ID
    )
    assert row["topology_lv_ac_collection_authority_model"] == (
        TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID
    )
    assert row["topology_lv_ac_collection_authority_scope"] == (
        TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_SCOPE
    )
    assert row["topology_lv_ac_collection_authority_coverage_scope"] == (
        TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_COVERAGE_SCOPE
    )
    assert result.diagnostics.resolved_inverter_path_count == 1
    assert result.diagnostics.zero_impedance_segment_count == 1
    assert result.diagnostics.model == TOPOLOGY_LV_AC_COLLECTION_AUTHORITY_MODEL_ID


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("path_segment_ids", ("tampered",)),
        ("collection_exit_node_id", "other-exit"),
        ("path_segment_count", 2),
        ("path_to_collection_exit_resolved", False),
        ("lv_ac_collection_authority_resolved", False),
        (
            "lv_ac_collection_authority_state",
            "unresolved_inverter_terminal_path_to_collection_exit",
        ),
        ("terminal_node_id", "other-terminal"),
    ],
)
def test_independent_validator_rejects_inverter_state_tampering(column: str, value: object) -> None:
    topology, nodes, segments, bindings = _single()
    result = _resolve(topology, nodes, segments, bindings)
    states = result.inverter_states.copy(deep=True)
    states.iloc[0, states.columns.get_loc(column)] = value
    with pytest.raises(RuntimeError, match="LV AC collection"):
        _validate_result(topology, replace(result, inverter_states=states))


@pytest.mark.parametrize(
    "changes",
    [
        {"resolved_inverter_path_count": 0, "unresolved_inverter_count": 1},
        {"represented_inverter_count": 0},
        {"zero_impedance_segment_count": 0, "nonzero_impedance_segment_count": 1},
    ],
)
def test_independent_validator_rejects_diagnostics_tampering(changes: dict[str, int]) -> None:
    topology, nodes, segments, bindings = _single(resistance=0.0, reactance=0.0)
    result = _resolve(topology, nodes, segments, bindings)
    diagnostics = replace(result.diagnostics, **changes)
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(topology, replace(result, diagnostics=diagnostics))


def test_validator_does_not_use_production_row_or_diagnostics_builders_as_oracles() -> None:
    validator_source = inspect.getsource(_validate_result)
    assert "_inverter_record(" not in validator_source
    assert "_trace_path(" not in validator_source
    assert "_diagnostics(" not in validator_source


def test_no_operating_or_inference_fields_exist() -> None:
    topology = _topology("inverter-1")
    result = _resolve(topology)
    row = result.inverter_states.iloc[0]
    assert row["lv_ac_collection_authority_state"] == "unresolved_no_inverter_terminal_binding"
    forbidden = {
        "p_selected_w",
        "q_selected_var",
        "s_selected_va",
        "nominal_voltage_v",
        "current_a",
        "voltage_drop_v",
        "i2r_loss_w",
        "grid_limit_kwac",
        "wiring_loss_ac_pct",
        "cable_length_m",
    }
    assert forbidden.isdisjoint(result.inverter_states.columns)
    assert not result.nodes_by_id
    assert not result.segments_by_id
    source = inspect.getsource(authority_module)
    for forbidden_source in (
        "inverter_dispatch_selection",
        "pvlib",
        "grid_limit_kwac",
        "wiring_loss_ac_pct",
        "nominal_voltage_v",
    ):
        assert forbidden_source not in source
