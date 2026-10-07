"""Tests for S12A static transformer equipment and boundary authority."""

from __future__ import annotations

import inspect
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig, InverterUnitConfig
from heliotelligence.physics import transformer_authority as authority_module
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    TopologyLvAcCollectionAuthorityResult,
    resolve_topology_lv_ac_collection_authority,
)
from heliotelligence.physics.transformer_authority import (
    TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_STATIC_AUTHORITY_COVERAGE_SCOPE,
    TRANSFORMER_STATIC_AUTHORITY_MODEL_ID,
    TRANSFORMER_STATIC_AUTHORITY_SCOPE,
    TopologyTransformerStaticAuthorityDiagnostics,
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
    _validate_result,
    resolve_transformer_static_authority,
)


def _basis() -> LvAcCollectionNetworkBasisAuthority:
    return LvAcCollectionNetworkBasisAuthority(
        "balanced_three_phase", "line_to_line_rms", "per_phase_series", "basis", "high"
    )


def _s11a_inputs(
    exits: tuple[str, ...] = ("exit-a",), *, include_inverter: bool = True
) -> tuple[
    ElectricalTopologyConfig,
    dict[str, LvAcCollectionNodeAuthority],
    dict[str, LvAcCollectionSegmentAuthority],
    dict[str, LvAcInverterTerminalBindingAuthority],
]:
    topology = ElectricalTopologyConfig(
        inverters=[InverterUnitConfig(id="inv-1")] if include_inverter else []
    )
    nodes = {
        exit_id: LvAcCollectionNodeAuthority(exit_id, "collection_exit", "drawing", "high")
        for exit_id in exits
    }
    segments: dict[str, LvAcCollectionSegmentAuthority] = {}
    bindings: dict[str, LvAcInverterTerminalBindingAuthority] = {}
    if include_inverter:
        nodes["terminal"] = LvAcCollectionNodeAuthority(
            "terminal", "inverter_terminal", "drawing", "high"
        )
        segments["feeder"] = LvAcCollectionSegmentAuthority(
            "feeder", "terminal", exits[0], 0.1, 0.02, "schedule", "high"
        )
        bindings["inv-1"] = LvAcInverterTerminalBindingAuthority(
            "inv-1", "terminal", "inverter_ac_output", "drawing", "high"
        )
    return topology, nodes, segments, bindings


def _equipment(
    transformer_id: str = "tx-1",
    *,
    rated_power: float = 500_000.0,
    collection_voltage: float = 400.0,
    network_voltage: float = 11_000.0,
) -> TransformerStaticEquipmentAuthority:
    return TransformerStaticEquipmentAuthority(
        transformer_id,
        "two_winding",
        "balanced_three_phase",
        "line_to_line_rms",
        rated_power,
        collection_voltage,
        network_voltage,
        f"nameplate:{transformer_id}",
        "high",
    )


def _transformer_topology(
    transformer_id: str = "tx-1", exit_id: str = "exit-a"
) -> TransformerBoundaryTopologyAuthority:
    return TransformerBoundaryTopologyAuthority(
        transformer_id,
        exit_id,
        "lv_ac_collection_exit",
        f"{transformer_id}:collection",
        "transformer_collection_side_terminal",
        f"{transformer_id}:network",
        "transformer_network_side_terminal",
        "direct_electrical_boundary",
        f"single-line:{transformer_id}",
        "medium",
    )


def _resolve(
    equipment: dict[str, TransformerStaticEquipmentAuthority] | None = None,
    transformer_topology: dict[str, TransformerBoundaryTopologyAuthority] | None = None,
    *,
    exits: tuple[str, ...] = ("exit-a",),
    include_inverter: bool = True,
    supplied_s11a: TopologyLvAcCollectionAuthorityResult | None = None,
) -> Any:
    topology, nodes, segments, bindings = _s11a_inputs(exits, include_inverter=include_inverter)
    resolved_basis = _basis()
    s11a = resolve_topology_lv_ac_collection_authority(
        topology,
        resolved_basis,
        nodes,
        segments,
        bindings,
    )
    return resolve_transformer_static_authority(
        topology,
        resolved_basis,
        nodes,
        segments,
        bindings,
        supplied_s11a or s11a,
        equipment or {},
        transformer_topology or {},
    )


def _full_result() -> Any:
    return _resolve({"tx-1": _equipment()}, {"tx-1": _transformer_topology()})


def _canonical_s11a(
    exits: tuple[str, ...] = ("exit-a",),
    *,
    basis: LvAcCollectionNetworkBasisAuthority | None = None,
) -> TopologyLvAcCollectionAuthorityResult:
    topology, nodes, segments, bindings = _s11a_inputs(exits)
    return resolve_topology_lv_ac_collection_authority(
        topology, _basis() if basis is None else basis, nodes, segments, bindings
    )


def test_fully_resolved_transformer_and_exact_provenance() -> None:
    result = _full_result()
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_static_authority_resolved"]
    assert row["transformer_static_authority_state"] == "resolved_transformer_static_authority"
    assert row["rated_apparent_power_va"] == 500_000.0
    assert row["s11_collection_exit_node_id"] == "exit-a"
    assert row["equipment_parameter_source"] == "nameplate:tx-1"
    assert row["topology_parameter_source"] == "single-line:tx-1"
    assert row["equipment_confidence"] == "high"
    assert row["topology_confidence"] == "medium"
    assert row["transformer_static_authority_contract"] == TRANSFORMER_STATIC_AUTHORITY_CONTRACT_ID
    assert row["transformer_static_authority_model"] == TRANSFORMER_STATIC_AUTHORITY_MODEL_ID
    assert row["transformer_static_authority_scope"] == TRANSFORMER_STATIC_AUTHORITY_SCOPE
    assert row["transformer_static_authority_coverage_scope"] == (
        TRANSFORMER_STATIC_AUTHORITY_COVERAGE_SCOPE
    )


def test_two_transformers_use_sorted_union_and_distinct_exits() -> None:
    equipment = {name: _equipment(name) for name in ("tx-z", "tx-a")}
    transformer_topology = {
        "tx-z": _transformer_topology("tx-z", "exit-z"),
        "tx-a": _transformer_topology("tx-a", "exit-a"),
    }
    result = _resolve(equipment, transformer_topology, exits=("exit-z", "exit-a"))
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-z"]
    assert result.diagnostics.resolved_transformer_count == 2
    assert result.diagnostics.bound_s11_collection_exit_count == 2
    assert result.diagnostics.transformer_terminal_count == 4


def test_equipment_only_and_topology_only_preserve_known_authority() -> None:
    result = _resolve(
        {"equipment-only": _equipment("equipment-only")},
        {"topology-only": _transformer_topology("topology-only")},
    )
    equipment_row = result.transformer_states.loc["equipment-only"]
    topology_row = result.transformer_states.loc["topology-only"]
    assert equipment_row["transformer_static_authority_state"] == (
        "unresolved_missing_transformer_topology_authority"
    )
    assert equipment_row["rated_apparent_power_va"] == 500_000.0
    assert equipment_row["s11_collection_exit_node_id"] == ""
    assert topology_row["transformer_static_authority_state"] == (
        "unresolved_missing_transformer_equipment_authority"
    )
    assert pd.isna(topology_row["rated_apparent_power_va"])
    assert topology_row["s11_collection_exit_node_id"] == "exit-a"


@pytest.mark.parametrize(
    ("collection_voltage", "network_voltage"), [(400.0, 400.0), (11_000.0, 400.0)]
)
def test_equal_and_collection_side_higher_rated_voltages_are_valid(
    collection_voltage: float, network_voltage: float
) -> None:
    equipment = _equipment(collection_voltage=collection_voltage, network_voltage=network_voltage)
    result = _resolve({"tx-1": equipment}, {"tx-1": _transformer_topology()})
    assert result.transformer_states.loc["tx-1", "transformer_static_authority_resolved"]


def test_missing_s11_network_basis_does_not_gate_explicit_static_binding() -> None:
    topology, nodes, segments, bindings = _s11a_inputs()
    s11a = resolve_topology_lv_ac_collection_authority(topology, None, nodes, segments, bindings)
    result = resolve_transformer_static_authority(
        topology,
        None,
        nodes,
        segments,
        bindings,
        s11a,
        {"tx-1": _equipment()},
        {"tx-1": _transformer_topology()},
    )
    assert result.transformer_states.loc["tx-1", "transformer_static_authority_resolved"]


def test_empty_authority_does_not_infer_transformers_from_s11_exits() -> None:
    result = _resolve({}, {}, exits=("exit-a", "exit-b"))
    assert result.transformer_states.empty
    assert result.transformer_states.index.name == "transformer_id"
    assert result.diagnostics.transformer_record_count == 0
    assert result.diagnostics.s11_collection_exit_count == 2
    assert result.diagnostics.bound_s11_collection_exit_count == 0
    assert all(
        str(result.transformer_states[column].dtype) == "bool"
        for column in (
            "transformer_equipment_authority_present",
            "transformer_topology_authority_present",
            "s11_collection_exit_binding_resolved",
            "transformer_static_authority_resolved",
        )
    )


def test_completely_empty_s11_and_transformer_authority_is_stable() -> None:
    result = _resolve({}, {}, exits=(), include_inverter=False)
    assert result.transformer_states.empty
    assert result.diagnostics.s11_collection_exit_count == 0


def test_outputs_are_immutable_and_independently_owned() -> None:
    equipment = {"tx-1": _equipment()}
    transformer_topology = {"tx-1": _transformer_topology()}
    first = _resolve(equipment, transformer_topology)
    second = _resolve(equipment, transformer_topology)
    equipment.clear()
    transformer_topology.clear()
    first.transformer_states.loc["tx-1", "rated_apparent_power_va"] = 1.0
    assert type(first.equipment_by_id).__name__ == "mappingproxy"
    assert type(first.topology_by_id).__name__ == "mappingproxy"
    assert second.transformer_states.loc["tx-1", "rated_apparent_power_va"] == 500_000.0


@pytest.mark.parametrize(
    "field",
    [
        "rated_apparent_power_va",
        "collection_side_rated_line_to_line_rms_v",
        "network_side_rated_line_to_line_rms_v",
    ],
)
@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), float("-inf"), True])
def test_equipment_numeric_domains_reject_invalid_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "transformer_id": "tx",
        "transformer_type": "two_winding",
        "phase_configuration": "balanced_three_phase",
        "voltage_basis": "line_to_line_rms",
        "rated_apparent_power_va": 1.0,
        "collection_side_rated_line_to_line_rms_v": 1.0,
        "network_side_rated_line_to_line_rms_v": 1.0,
        "parameter_source": "source",
        "confidence": "high",
    }
    values[field] = value
    with pytest.raises(ValueError):
        TransformerStaticEquipmentAuthority(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transformer_id", ""),
        ("transformer_id", " tx"),
        ("transformer_type", "three_winding"),
        ("phase_configuration", "single_phase"),
        ("voltage_basis", "line_to_neutral"),
        ("parameter_source", ""),
        ("parameter_source", " source "),
        ("confidence", "certain"),
    ],
)
def test_equipment_rejects_invalid_identity_enums_and_provenance(field: str, value: str) -> None:
    values = {
        "transformer_id": "tx",
        "transformer_type": "two_winding",
        "phase_configuration": "balanced_three_phase",
        "voltage_basis": "line_to_line_rms",
        "rated_apparent_power_va": 1.0,
        "collection_side_rated_line_to_line_rms_v": 1.0,
        "network_side_rated_line_to_line_rms_v": 1.0,
        "parameter_source": "source",
        "confidence": "high",
    }
    values[field] = value
    with pytest.raises(ValueError):
        TransformerStaticEquipmentAuthority(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transformer_id", " tx"),
        ("s11_collection_exit_node_id", ""),
        ("s11_reference_plane", "inverter_ac_output"),
        ("transformer_collection_reference_plane", "collection"),
        ("transformer_network_reference_plane", "network"),
        ("connection_semantics", "inferred"),
        ("parameter_source", " "),
        ("confidence", "certain"),
    ],
)
def test_topology_rejects_invalid_identity_enums_and_provenance(field: str, value: str) -> None:
    values = {
        "transformer_id": "tx",
        "s11_collection_exit_node_id": "exit-a",
        "s11_reference_plane": "lv_ac_collection_exit",
        "transformer_collection_terminal_id": "tx:c",
        "transformer_collection_reference_plane": "transformer_collection_side_terminal",
        "transformer_network_terminal_id": "tx:n",
        "transformer_network_reference_plane": "transformer_network_side_terminal",
        "connection_semantics": "direct_electrical_boundary",
        "parameter_source": "source",
        "confidence": "high",
    }
    values[field] = value
    with pytest.raises(ValueError):
        TransformerBoundaryTopologyAuthority(**values)  # type: ignore[arg-type]


def test_topology_rejects_same_terminal_identity() -> None:
    with pytest.raises(ValueError, match="must differ"):
        replace(_transformer_topology(), transformer_network_terminal_id="tx-1:collection")


@pytest.mark.parametrize("node_kind", ["inverter_terminal", "junction"])
def test_binding_requires_explicit_collection_exit(node_kind: str) -> None:
    topology, nodes, segments, bindings = _s11a_inputs()
    wrong_node_id = "terminal" if node_kind == "inverter_terminal" else "wrong"
    if node_kind == "junction":
        nodes["wrong"] = LvAcCollectionNodeAuthority("wrong", node_kind, "source", "high")  # type: ignore[arg-type]
    s11a = resolve_topology_lv_ac_collection_authority(
        topology, _basis(), nodes, segments, bindings
    )
    with pytest.raises(ValueError, match="collection_exit"):
        resolve_transformer_static_authority(
            topology,
            _basis(),
            nodes,
            segments,
            bindings,
            s11a,
            {},
            {"tx-1": _transformer_topology(exit_id=wrong_node_id)},
        )


def test_unknown_exit_duplicate_exit_and_duplicate_terminal_are_rejected() -> None:
    with pytest.raises(ValueError, match="collection_exit"):
        _resolve({}, {"tx-1": _transformer_topology(exit_id="unknown")})
    with pytest.raises(ValueError, match="at most one"):
        _resolve(
            {},
            {
                "a": _transformer_topology("a"),
                "b": _transformer_topology("b"),
            },
        )
    duplicate = replace(
        _transformer_topology("b", "exit-b"),
        transformer_collection_terminal_id="a:collection",
    )
    with pytest.raises(ValueError, match="globally unique"):
        _resolve(
            {},
            {"a": _transformer_topology("a"), "b": duplicate},
            exits=("exit-a", "exit-b"),
        )


def test_mapping_key_and_value_type_closure() -> None:
    with pytest.raises(ValueError, match="mapping key"):
        _resolve({"wrong": _equipment("tx-1")}, {})
    with pytest.raises(ValueError, match="mapping key"):
        _resolve({}, {"wrong": _transformer_topology("tx-1")})
    with pytest.raises(TypeError, match="value type"):
        _resolve(cast(Any, {"tx": {}}), {})
    with pytest.raises(TypeError, match="value type"):
        _resolve({}, cast(Any, {"tx": {}}))


@pytest.mark.parametrize(
    "parent_field",
    ["inverter_states", "diagnostics", "nodes_by_id", "segments_by_id", "bindings"],
)
def test_strong_s11a_replay_rejects_tampering(parent_field: str) -> None:
    topology, nodes, segments, bindings = _s11a_inputs()
    canonical = resolve_topology_lv_ac_collection_authority(
        topology, _basis(), nodes, segments, bindings
    )
    if parent_field == "inverter_states":
        frame = canonical.inverter_states.copy(deep=True)
        frame.loc["inv-1", "collection_exit_node_id"] = "tampered"
        supplied = replace(canonical, inverter_states=frame)
    elif parent_field == "diagnostics":
        supplied = replace(
            canonical,
            diagnostics=replace(canonical.diagnostics, collection_exit_node_count=99),
        )
    elif parent_field == "nodes_by_id":
        supplied = replace(canonical, nodes_by_id=MappingProxyType({}))
    elif parent_field == "segments_by_id":
        supplied = replace(canonical, segments_by_id=MappingProxyType({}))
    else:
        supplied = replace(canonical, inverter_terminal_binding_by_inverter_id=MappingProxyType({}))
    with pytest.raises(ValueError, match="canonical replay"):
        resolve_transformer_static_authority(
            topology, _basis(), nodes, segments, bindings, supplied, {}, {}
        )


@pytest.mark.parametrize(
    "mapping_field",
    ["nodes_by_id", "segments_by_id", "inverter_terminal_binding_by_inverter_id"],
)
def test_strong_s11a_replay_rejects_mutable_equal_mappings(mapping_field: str) -> None:
    topology, nodes, segments, bindings = _s11a_inputs()
    canonical = resolve_topology_lv_ac_collection_authority(
        topology, _basis(), nodes, segments, bindings
    )
    supplied = replace(
        canonical,
        **cast(Any, {mapping_field: dict(getattr(canonical, mapping_field))}),
    )
    with pytest.raises(ValueError, match="immutable canonical replay"):
        resolve_transformer_static_authority(
            topology, _basis(), nodes, segments, bindings, supplied, {}, {}
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("rated_apparent_power_va", 1.0),
        ("collection_side_rated_line_to_line_rms_v", 1.0),
        ("network_side_rated_line_to_line_rms_v", 1.0),
        ("transformer_type", "tampered"),
        ("s11_collection_exit_node_id", "tampered"),
        ("transformer_collection_terminal_id", "tampered"),
        ("transformer_network_terminal_id", "tampered"),
        ("connection_semantics", "tampered"),
        ("transformer_equipment_authority_present", False),
        ("transformer_topology_authority_present", False),
        ("transformer_static_authority_resolved", False),
        ("transformer_static_authority_state", "tampered"),
        ("equipment_parameter_source", "tampered"),
        ("equipment_confidence", "low"),
        ("topology_parameter_source", "tampered"),
        ("topology_confidence", "low"),
    ],
)
def test_private_validator_rejects_state_tampering(column: str, value: object) -> None:
    result = _full_result()
    frame = result.transformer_states.copy(deep=True)
    frame.loc["tx-1", column] = value
    tampered = replace(result, transformer_states=frame)
    with pytest.raises(RuntimeError):
        _validate_result(_canonical_s11a(), tampered)


@pytest.mark.parametrize(
    "field",
    [
        "transformer_record_count",
        "resolved_transformer_count",
        "equipment_only_transformer_count",
        "topology_only_transformer_count",
        "bound_s11_collection_exit_count",
        "transformer_terminal_count",
    ],
)
def test_private_validator_rejects_diagnostic_tampering(field: str) -> None:
    result = _full_result()
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(_canonical_s11a(), replace(result, diagnostics=diagnostics))


def test_private_validator_rejects_mutable_result_mappings() -> None:
    result = _full_result()
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(
            _canonical_s11a(), replace(result, equipment_by_id=dict(result.equipment_by_id))
        )


def test_module_has_no_s11b_s11c_or_operating_transformer_model() -> None:
    source = inspect.getsource(authority_module)
    assert "lv_ac_collection_voltage_authority" not in source
    assert "lv_ac_collection_operating" not in source
    for forbidden in (
        "tap_position",
        "vector_group",
        "phase_shift",
        "copper_loss",
        "core_loss",
        "wiring_loss_ac_pct",
        "rated_voltage_ratio",
    ):
        assert forbidden not in source


def test_diagnostics_type_and_exact_model() -> None:
    diagnostics = _full_result().diagnostics
    assert type(diagnostics) is TopologyTransformerStaticAuthorityDiagnostics
    assert diagnostics.model == TRANSFORMER_STATIC_AUTHORITY_MODEL_ID
    assert diagnostics.transformer_record_count == (
        diagnostics.resolved_transformer_count
        + diagnostics.equipment_only_transformer_count
        + diagnostics.topology_only_transformer_count
    )
