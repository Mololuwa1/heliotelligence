"""Tests for S11B timestamped LV collection-exit voltage authority."""

from __future__ import annotations

import datetime as dt
import inspect
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig, InverterUnitConfig
from heliotelligence.physics import lv_ac_collection_voltage_authority as voltage_module
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    LvAcCollectionSegmentAuthority,
    LvAcInverterTerminalBindingAuthority,
    resolve_topology_lv_ac_collection_authority,
)
from heliotelligence.physics.lv_ac_collection_voltage_authority import (
    TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_CONTRACT_ID,
    TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_COVERAGE_SCOPE,
    TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID,
    TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_SCOPE,
    LvAcCollectionExitVoltageState,
    TopologyLvAcCollectionExitVoltageAuthorityDiagnostics,
    _validate_result,
    resolve_topology_lv_ac_collection_exit_voltage_authority,
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


def _segment(segment_id: str, source: str, destination: str) -> LvAcCollectionSegmentAuthority:
    return LvAcCollectionSegmentAuthority(
        segment_id, source, destination, 0.1, 0.02, f"schedule:{segment_id}", "high"
    )


def _binding(inverter_id: str, node_id: str) -> LvAcInverterTerminalBindingAuthority:
    return LvAcInverterTerminalBindingAuthority(
        inverter_id, node_id, "inverter_ac_output", f"drawing:{inverter_id}", "high"
    )


def _voltage(
    value: float | int = 400.0,
    *,
    source: str = "meter:exit",
    confidence: str = "high",
) -> LvAcCollectionExitVoltageState:
    return LvAcCollectionExitVoltageState(
        value, "line_to_line_rms", "lv_ac_collection_exit", source, confidence  # type: ignore[arg-type]
    )


def _single_inputs(
    *, basis: LvAcCollectionNetworkBasisAuthority | None = None
) -> tuple[Any, ...]:
    topology = _topology("inv-1")
    nodes = {
        "terminal": _node("terminal", "inverter_terminal"),
        "exit": _node("exit", "collection_exit"),
    }
    segments = {"feeder": _segment("feeder", "terminal", "exit")}
    bindings = {"inv-1": _binding("inv-1", "terminal")}
    actual_basis = _basis() if basis is None else basis
    parent = resolve_topology_lv_ac_collection_authority(
        topology, actual_basis, nodes, segments, bindings
    )
    return topology, actual_basis, nodes, segments, bindings, parent


def _resolve(
    inputs: tuple[Any, ...],
    voltages: Any,
) -> Any:
    topology, basis, nodes, segments, bindings, parent = inputs
    return resolve_topology_lv_ac_collection_exit_voltage_authority(
        topology, basis, nodes, segments, bindings, parent, voltages
    )


def _two_exit_inputs() -> tuple[Any, ...]:
    topology = _topology("inv-a", "inv-b")
    nodes = {
        "ta": _node("ta", "inverter_terminal"),
        "tb": _node("tb", "inverter_terminal"),
        "exit-b": _node("exit-b", "collection_exit"),
        "exit-a": _node("exit-a", "collection_exit"),
    }
    segments = {
        "sa": _segment("sa", "ta", "exit-a"),
        "sb": _segment("sb", "tb", "exit-b"),
    }
    bindings = {"inv-a": _binding("inv-a", "ta"), "inv-b": _binding("inv-b", "tb")}
    basis = _basis()
    parent = resolve_topology_lv_ac_collection_authority(
        topology, basis, nodes, segments, bindings
    )
    return topology, basis, nodes, segments, bindings, parent


def test_positive_voltage_exact_state_and_provenance() -> None:
    inputs = _single_inputs()
    timestamp = pd.Timestamp("2026-01-01T12:00:00Z")
    result = _resolve(
        inputs,
        {(timestamp, "exit"): _voltage(415, source="scada:v", confidence="medium")},
    )
    row = result.states.loc[(timestamp, "exit")]
    assert row["voltage_line_to_line_rms_v"] == 415.0
    assert not row["voltage_is_zero"]
    assert row["voltage_basis"] == "line_to_line_rms"
    assert row["voltage_reference_plane"] == "lv_ac_collection_exit"
    assert row["parameter_source"] == "scada:v"
    assert row["confidence"] == "medium"
    assert row["collection_exit_voltage_authority_state"] == (
        "resolved_explicit_collection_exit_voltage_state"
    )
    assert row["topology_lv_ac_collection_exit_voltage_authority_contract"] == (
        TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_CONTRACT_ID
    )
    assert row["topology_lv_ac_collection_exit_voltage_authority_model"] == (
        TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID
    )
    assert row["topology_lv_ac_collection_exit_voltage_authority_scope"] == (
        TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_SCOPE
    )
    assert row["topology_lv_ac_collection_exit_voltage_authority_coverage_scope"] == (
        TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_COVERAGE_SCOPE
    )


def test_explicit_zero_is_resolved_and_distinct_from_missing() -> None:
    inputs = _two_exit_inputs()
    timestamp = pd.Timestamp("2026-01-01")
    result = _resolve(inputs, {(timestamp, "exit-a"): _voltage(0.0)})
    zero = result.states.loc[(timestamp, "exit-a")]
    missing = result.states.loc[(timestamp, "exit-b")]
    assert zero["collection_exit_voltage_state_present"]
    assert zero["collection_exit_voltage_boundary_authority_resolved"]
    assert zero["voltage_line_to_line_rms_v"] == 0.0
    assert zero["voltage_is_zero"]
    assert not missing["collection_exit_voltage_state_present"]
    assert pd.isna(missing["voltage_line_to_line_rms_v"])
    assert pd.isna(missing["voltage_is_zero"])
    assert missing["confidence"] == ""


def test_cartesian_exit_rows_and_canonical_order_ignore_mapping_order() -> None:
    inputs = _two_exit_inputs()
    early = pd.Timestamp("2026-01-01")
    late = pd.Timestamp("2026-01-02")
    forward = {
        (early, "exit-a"): _voltage(400, source="a"),
        (early, "exit-b"): _voltage(401, source="b"),
        (late, "exit-a"): _voltage(402, source="c"),
        (late, "exit-b"): _voltage(403, source="d"),
    }
    reverse = dict(reversed(list(forward.items())))
    first = _resolve(inputs, forward)
    second = _resolve(inputs, reverse)
    pd.testing.assert_frame_equal(first.states, second.states, check_exact=True)
    assert first.diagnostics == second.diagnostics
    assert first.states.index.tolist() == [
        (early, "exit-a"),
        (early, "exit-b"),
        (late, "exit-a"),
        (late, "exit-b"),
    ]


def test_network_basis_missing_preserves_raw_voltage_but_is_unresolved() -> None:
    topology = _topology()
    nodes = {"exit": _node("exit", "collection_exit")}
    parent = resolve_topology_lv_ac_collection_authority(topology, None, nodes, {}, {})
    inputs: tuple[Any, ...] = (topology, None, nodes, {}, {}, parent)
    timestamp = pd.Timestamp("2026-01-01")
    result = _resolve(inputs, {(timestamp, "exit"): _voltage(400)})
    row = result.states.iloc[0]
    assert row["collection_exit_voltage_state_present"]
    assert row["voltage_line_to_line_rms_v"] == 400.0
    assert not row["collection_exit_voltage_boundary_authority_resolved"]
    assert row["collection_exit_voltage_authority_state"] == (
        "unresolved_no_lv_ac_network_basis_authority"
    )
    assert result.diagnostics.missing_network_basis_row_count == 1


def test_empty_mapping_with_known_exits_has_no_fabricated_timestamps() -> None:
    result = _resolve(_two_exit_inputs(), {})
    assert result.states.empty
    assert result.states.index.names == ["timestamp", "collection_exit_node_id"]
    assert result.diagnostics.collection_exit_count == 2
    assert result.diagnostics.timestamp_count == 0
    assert result.diagnostics.row_count == 0


def test_completely_empty_topology_has_stable_schema_and_dtypes() -> None:
    topology = _topology()
    basis = _basis()
    parent = resolve_topology_lv_ac_collection_authority(topology, basis, {}, {}, {})
    result = _resolve((topology, basis, {}, {}, {}, parent), {})
    assert result.states.empty
    assert result.states.index.names == ["timestamp", "collection_exit_node_id"]
    assert str(result.states["voltage_line_to_line_rms_v"].dtype) == "float64"
    assert str(result.states["voltage_is_zero"].dtype) == "boolean"
    assert str(result.states["network_basis_resolved"].dtype) == "bool"
    assert result.diagnostics == TopologyLvAcCollectionExitVoltageAuthorityDiagnostics(
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        TOPOLOGY_LV_AC_COLLECTION_EXIT_VOLTAGE_AUTHORITY_MODEL_ID,
    )


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), float("-inf"), True, "400"])
def test_invalid_voltage_domain_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        LvAcCollectionExitVoltageState(
            value, "line_to_line_rms", "lv_ac_collection_exit", "meter", "high"  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("voltage_basis", "line_to_neutral"),
        ("reference_plane", "inverter_ac_output"),
        ("parameter_source", " "),
        ("confidence", "certain"),
    ],
)
def test_invalid_voltage_metadata_rejected(field: str, value: str) -> None:
    kwargs: dict[str, object] = {
        "voltage_line_to_line_rms_v": 400.0,
        "voltage_basis": "line_to_line_rms",
        "reference_plane": "lv_ac_collection_exit",
        "parameter_source": "meter",
        "confidence": "high",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        LvAcCollectionExitVoltageState(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "key",
    [
        "bad",
        (pd.Timestamp("2026-01-01"),),
        (pd.Timestamp("2026-01-01"), "exit", "extra"),
        ("2026-01-01", "exit"),
        (dt.datetime(2026, 1, 1), "exit"),
        (pd.NaT, "exit"),
        (pd.Timestamp("2026-01-01"), " "),
    ],
)
def test_malformed_mapping_keys_rejected(key: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _resolve(_single_inputs(), {key: _voltage()})


def test_unknown_and_non_exit_nodes_rejected() -> None:
    inputs = _single_inputs()
    timestamp = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="unknown"):
        _resolve(inputs, {(timestamp, "unknown"): _voltage()})
    with pytest.raises(ValueError, match="collection_exit"):
        _resolve(inputs, {(timestamp, "terminal"): _voltage()})


def test_junction_voltage_rejected() -> None:
    topology = _topology()
    basis = _basis()
    nodes = {"junction": _node("junction", "junction"), "exit": _node("exit", "collection_exit")}
    parent = resolve_topology_lv_ac_collection_authority(topology, basis, nodes, {}, {})
    with pytest.raises(ValueError, match="collection_exit"):
        _resolve(
            (topology, basis, nodes, {}, {}, parent),
            {(pd.Timestamp("2026-01-01"), "junction"): _voltage()},
        )


def test_exact_authority_type_and_mapping_required() -> None:
    inputs = _single_inputs()
    timestamp = pd.Timestamp("2026-01-01")
    with pytest.raises(TypeError, match="mapping"):
        _resolve(inputs, [])
    with pytest.raises(TypeError, match="exact authority type"):
        _resolve(inputs, {(timestamp, "exit"): {"voltage": 400}})


def test_incompatible_mixed_timezone_timestamps_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _resolve(
            _single_inputs(),
            {
                (pd.Timestamp("2026-01-01"), "exit"): _voltage(400),
                (pd.Timestamp("2026-01-02T00:00:00Z"), "exit"): _voltage(401),
            },
        )


@pytest.mark.parametrize("tamper", ["frame", "diagnostics", "nodes", "segments"])
def test_strong_s11a_replay_rejects_tampering(tamper: str) -> None:
    inputs = list(_single_inputs())
    parent = inputs[-1]
    if tamper == "frame":
        frame = parent.inverter_states.copy(deep=True)
        frame.loc["inv-1", "collection_exit_node_id"] = "tampered"
        inputs[-1] = replace(parent, inverter_states=frame)
    elif tamper == "diagnostics":
        inputs[-1] = replace(
            parent,
            diagnostics=replace(parent.diagnostics, resolved_inverter_path_count=0),
        )
    elif tamper == "nodes":
        inputs[-1] = replace(
            parent,
            nodes_by_id=MappingProxyType({"exit": parent.nodes_by_id["exit"]}),
        )
    else:
        inputs[-1] = replace(parent, segments_by_id=MappingProxyType({}))
    with pytest.raises(RuntimeError, match="S11A"):
        _resolve(tuple(inputs), {(pd.Timestamp("2026-01-01"), "exit"): _voltage()})


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("voltage_line_to_line_rms_v", 399.0),
        ("voltage_is_zero", True),
        ("collection_exit_voltage_state_present", False),
        ("collection_exit_voltage_boundary_authority_resolved", False),
        ("voltage_basis", "tampered"),
        ("voltage_reference_plane", "tampered"),
        ("parameter_source", "tampered"),
        ("confidence", "low"),
        ("collection_exit_voltage_authority_state", "tampered"),
    ],
)
def test_private_validator_rejects_state_tampering(column: str, value: object) -> None:
    inputs = _single_inputs()
    result = _resolve(inputs, {(pd.Timestamp("2026-01-01"), "exit"): _voltage(400)})
    frame = result.states.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc(column)] = value
    with pytest.raises(RuntimeError):
        _validate_result(inputs[0], inputs[-1], replace(result, states=frame))


@pytest.mark.parametrize(
    "field",
    [
        "voltage_state_present_count",
        "voltage_state_missing_count",
        "explicit_zero_voltage_count",
        "positive_voltage_count",
        "voltage_boundary_authority_resolved_count",
        "voltage_boundary_authority_unresolved_count",
    ],
)
def test_private_validator_rejects_diagnostics_tampering(field: str) -> None:
    inputs = _single_inputs()
    result = _resolve(inputs, {(pd.Timestamp("2026-01-01"), "exit"): _voltage(400)})
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(inputs[0], inputs[-1], replace(result, diagnostics=diagnostics))


def test_private_validator_rejects_index_timestamp_and_exit_tampering() -> None:
    inputs = _single_inputs()
    result = _resolve(inputs, {(pd.Timestamp("2026-01-01"), "exit"): _voltage()})
    for bad_index in (
        pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "exit")],
            names=["timestamp", "collection_exit_node_id"],
        ),
        pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-01"), "other")],
            names=["timestamp", "collection_exit_node_id"],
        ),
    ):
        frame = result.states.copy(deep=True)
        frame.index = bad_index
        with pytest.raises(RuntimeError, match="index"):
            _validate_result(inputs[0], inputs[-1], replace(result, states=frame))


def test_mapping_and_dataframe_ownership() -> None:
    inputs = _single_inputs()
    key = (pd.Timestamp("2026-01-01"), "exit")
    supplied = {key: _voltage(400)}
    first = _resolve(inputs, supplied)
    second = _resolve(inputs, supplied)
    supplied.clear()
    assert key in first.voltage_states_by_key
    with pytest.raises(TypeError):
        first.voltage_states_by_key[key] = _voltage(410)
    first.states.loc[key, "voltage_line_to_line_rms_v"] = 999.0
    assert second.states.loc[key, "voltage_line_to_line_rms_v"] == 400.0


def test_no_temporal_or_exit_inference() -> None:
    inputs = _two_exit_inputs()
    first = pd.Timestamp("2026-01-01")
    second = pd.Timestamp("2026-01-02")
    result = _resolve(
        inputs,
        {(first, "exit-a"): _voltage(400), (second, "exit-b"): _voltage(410)},
    )
    assert pd.isna(result.states.loc[(first, "exit-b"), "voltage_line_to_line_rms_v"])
    assert pd.isna(result.states.loc[(second, "exit-a"), "voltage_line_to_line_rms_v"])


def test_source_has_no_dispatch_voltage_conversion_current_or_loss_logic() -> None:
    source = inspect.getsource(voltage_module)
    forbidden = (
        "inverter_dispatch_selection",
        "TopologyInverterDispatchSelectionResult",
        "p_selected_w",
        "q_selected_var",
        "s_selected_va",
        "grid_limit_kwac",
        "wiring_loss_ac_pct",
        "pvlib",
        "sqrt(3",
        "phase_voltage",
        "line_current",
        "i_squared_r",
    )
    for token in forbidden:
        assert token not in source
