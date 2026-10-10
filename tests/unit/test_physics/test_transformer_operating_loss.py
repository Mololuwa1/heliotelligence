"""Tests for S12D baseline transformer operating active-loss evaluation."""

from __future__ import annotations

import importlib
import inspect
import math
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import (
    inverter_envelope_lookup,
    inverter_lookup,
)
from heliotelligence.physics import (
    transformer_operating_loss as module,
)
from heliotelligence.physics.transformer_authority import (
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
    resolve_transformer_static_authority,
)
from heliotelligence.physics.transformer_energisation_authority import (
    TransformerEnergisationState,
    resolve_transformer_energisation_authority,
)
from heliotelligence.physics.transformer_loss_authority import (
    TransformerNoLoadLossAuthority,
    TransformerRatedLoadLossAuthority,
    resolve_transformer_loss_authority,
)
from heliotelligence.physics.transformer_operating_loss import (
    TRANSFORMER_OPERATING_LOSS_CONTRACT_ID,
    TRANSFORMER_OPERATING_LOSS_COVERAGE_SCOPE,
    TRANSFORMER_OPERATING_LOSS_MODEL_ID,
    TRANSFORMER_OPERATING_LOSS_SCOPE,
    _validate_result,
    calculate_topology_transformer_operating_loss,
)

s11c_tests: Any = importlib.import_module("tests.unit.test_physics.test_lv_ac_collection_operating")
s10b_tests: Any = importlib.import_module(
    "tests.unit.test_physics.test_inverter_dispatch_feasibility"
)


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inverter_lookup,
        "_load_cec_inverter_database",
        s10b_tests.conversion_support._database,
    )
    monkeypatch.setattr(
        inverter_envelope_lookup,
        "_load_cec_inverter_database",
        s10b_tests.conversion_support._database,
    )


def _equipment(transformer_id: str, rated_s: float = 500.0, rated_v: float = 400.0) -> Any:
    return TransformerStaticEquipmentAuthority(
        transformer_id,
        "two_winding",
        "balanced_three_phase",
        "line_to_line_rms",
        rated_s,
        rated_v,
        11_000.0,
        f"nameplate:{transformer_id}",
        "high",
    )


def _topology(transformer_id: str, exit_id: str = "exit") -> Any:
    return TransformerBoundaryTopologyAuthority(
        transformer_id,
        exit_id,
        "lv_ac_collection_exit",
        f"{transformer_id}:collection",
        "transformer_collection_side_terminal",
        f"{transformer_id}:network",
        "transformer_network_side_terminal",
        "direct_electrical_boundary",
        "single-line",
        "high",
    )


def _no_load(transformer_id: str, value: float = 600.0) -> Any:
    return TransformerNoLoadLossAuthority(
        transformer_id,
        value,
        "collection_side",
        "rated_terminal_voltage",
        "line_to_line_rms",
        50.0,
        "open-circuit-test",
        "high",
    )


def _rated_load(transformer_id: str, value: float = 5_000.0) -> Any:
    return TransformerRatedLoadLossAuthority(
        transformer_id,
        value,
        "network_side",
        "rated_current",
        75.0,
        50.0,
        "total_rated_load_loss_including_winding_and_stray",
        "load-loss-test",
        "high",
    )


def _energised(value: bool) -> TransformerEnergisationState:
    return TransformerEnergisationState(
        value, "transformer_energised_state", "interpreted-state", "high"
    )


def _bundle(
    *,
    p: float | None = 100.0,
    q: float | None = 0.0,
    voltage: float | None = 400.0,
    energised: bool | None = True,
    energisation_offset_hours: int = 0,
    no_load: bool = True,
    rated_load: bool = True,
    rated_s: float = 500.0,
    rated_v: float = 400.0,
    topology_present: bool = True,
    equipment_present: bool = True,
) -> tuple[tuple[Any, ...], Any, Any, Any, Any, Any]:
    arguments, dispatch, network, _ = s11c_tests._public_setup(p=p, q=q, voltage_value=voltage)
    s11c = s11c_tests._public(arguments)
    topology = arguments[0]
    basis, nodes, segments, bindings, s11a = arguments[24:29]
    equipment = {"tx-1": _equipment("tx-1", rated_s, rated_v)} if equipment_present else {}
    transformer_topology = {"tx-1": _topology("tx-1")} if topology_present else {}
    static = resolve_transformer_static_authority(
        topology, basis, nodes, segments, bindings, s11a, equipment, transformer_topology
    )
    no_load_mapping = {"tx-1": _no_load("tx-1")} if no_load else {}
    rated_load_mapping = {"tx-1": _rated_load("tx-1")} if rated_load else {}
    loss = resolve_transformer_loss_authority(
        topology,
        basis,
        nodes,
        segments,
        bindings,
        s11a,
        equipment,
        transformer_topology,
        static,
        no_load_mapping,
        rated_load_mapping,
    )
    timestamp = pd.Timestamp(dispatch.dispatch.index[0][0]) + pd.Timedelta(
        hours=energisation_offset_hours
    )
    energisation_mapping = (
        {(timestamp, "tx-1"): _energised(energised)} if energised is not None else {}
    )
    energisation_authority = resolve_transformer_energisation_authority(
        topology,
        basis,
        nodes,
        segments,
        bindings,
        s11a,
        equipment,
        transformer_topology,
        static,
        energisation_mapping,
    )
    public_arguments = arguments + (
        s11c,
        equipment,
        transformer_topology,
        static,
        no_load_mapping,
        rated_load_mapping,
        loss,
        energisation_mapping,
        energisation_authority,
    )
    return public_arguments, s11c, static, loss, energisation_authority, network


def _run(**kwargs: Any) -> Any:
    return calculate_topology_transformer_operating_loss(*_bundle(**kwargs)[0])


def test_resolved_energised_loss_closes_all_current_and_loss_equations() -> None:
    result = _run(p=100.0, q=30.0, voltage=400.0)
    row = result.transformer_loss_states.iloc[0]
    s_value = math.hypot(
        row["p_delivered_at_collection_exit_w"], row["q_delivered_at_collection_exit_var"]
    )
    expected_operating = s_value / (math.sqrt(3.0) * 400.0)
    expected_rated = 500.0 / (math.sqrt(3.0) * 400.0)
    beta = expected_operating / expected_rated
    assert row["collection_side_operating_current_a"] == pytest.approx(expected_operating)
    assert row["collection_side_rated_current_a"] == pytest.approx(expected_rated)
    assert row["collection_current_loading_fraction"] == pytest.approx(beta)
    assert row["collection_current_loading_fraction_squared"] == pytest.approx(beta**2)
    assert row["p_no_load_reference_condition_baseline_w"] == 600.0
    assert row["p_load_reference_temperature_baseline_w"] == pytest.approx(5_000.0 * beta**2)
    assert row["p_total_reference_condition_baseline_w"] == pytest.approx(600.0 + 5_000.0 * beta**2)
    assert row["transformer_operating_loss_state"] == (
        "resolved_energised_transformer_reference_condition_baseline_loss"
    )
    assert row["transformer_operating_loss_contract"] == TRANSFORMER_OPERATING_LOSS_CONTRACT_ID
    assert row["transformer_operating_loss_model"] == TRANSFORMER_OPERATING_LOSS_MODEL_ID
    assert row["transformer_operating_loss_scope"] == TRANSFORMER_OPERATING_LOSS_SCOPE
    assert row["transformer_operating_loss_coverage_scope"] == (
        TRANSFORMER_OPERATING_LOSS_COVERAGE_SCOPE
    )


def test_rated_current_point_produces_beta_one_and_factory_rated_load_loss() -> None:
    first = _run(p=100.0, voltage=400.0)
    delivered = float(first.transformer_loss_states.iloc[0]["s_delivered_vector_magnitude_va"])
    result = _run(p=100.0, voltage=400.0, rated_s=delivered)
    row = result.transformer_loss_states.iloc[0]
    assert row["collection_current_loading_fraction"] == pytest.approx(1.0)
    assert row["p_load_reference_temperature_baseline_w"] == pytest.approx(5_000.0)
    assert row["p_total_reference_condition_baseline_w"] == pytest.approx(5_600.0)


def test_half_current_produces_quarter_rated_load_loss() -> None:
    first = _run(p=100.0, voltage=400.0)
    delivered = float(first.transformer_loss_states.iloc[0]["s_delivered_vector_magnitude_va"])
    row = _run(p=100.0, voltage=400.0, rated_s=2.0 * delivered).transformer_loss_states.iloc[0]
    assert row["collection_current_loading_fraction"] == pytest.approx(0.5)
    assert row["p_load_reference_temperature_baseline_w"] == pytest.approx(1_250.0)


def test_current_ratio_uses_operating_voltage_not_only_apparent_power_ratio() -> None:
    row = _run(
        p=100.0, q=0.0, voltage=320.0, rated_s=200.0, rated_v=400.0
    ).transformer_loss_states.iloc[0]
    delivered_ratio = row["s_delivered_vector_magnitude_va"] / row["rated_apparent_power_va"]
    expected = delivered_ratio * 400.0 / 320.0
    assert row["collection_current_loading_fraction"] == pytest.approx(expected)
    assert row["collection_current_loading_fraction"] != pytest.approx(delivered_ratio)
    assert row["p_load_reference_temperature_baseline_w"] == pytest.approx(5_000.0 * expected**2)


def test_reactive_power_increases_current_and_load_loss_at_same_p() -> None:
    unity = _run(p=100.0, q=0.0).transformer_loss_states.iloc[0]
    reactive = _run(p=100.0, q=80.0).transformer_loss_states.iloc[0]
    assert reactive["s_delivered_vector_magnitude_va"] > unity["s_delivered_vector_magnitude_va"]
    assert (
        reactive["collection_side_operating_current_a"]
        > unity["collection_side_operating_current_a"]
    )
    assert (
        reactive["collection_current_loading_fraction"]
        > unity["collection_current_loading_fraction"]
    )
    assert (
        reactive["p_load_reference_temperature_baseline_w"]
        > unity["p_load_reference_temperature_baseline_w"]
    )


def test_voltage_sensitivity_changes_current_at_same_selected_power() -> None:
    low = _run(p=100.0, voltage=320.0).transformer_loss_states.iloc[0]
    high = _run(p=100.0, voltage=480.0).transformer_loss_states.iloc[0]
    assert low["collection_side_operating_current_a"] > high["collection_side_operating_current_a"]
    assert low["collection_current_loading_fraction"] > high["collection_current_loading_fraction"]
    assert (
        low["p_load_reference_temperature_baseline_w"]
        > high["p_load_reference_temperature_baseline_w"]
    )


def test_overload_is_not_clamped_or_made_unresolved() -> None:
    row = _run(p=100.0, rated_s=50.0).transformer_loss_states.iloc[0]
    assert row["collection_current_loading_fraction"] > 1.0
    assert bool(row["collection_current_exceeds_rated"])
    assert row["p_load_reference_temperature_baseline_w"] > row["factory_rated_load_loss_w"]
    assert row["total_active_loss_baseline_resolved"]


def test_energised_zero_transfer_at_positive_voltage_applies_only_no_load() -> None:
    row = _run(p=0.0, q=0.0, voltage=400.0).transformer_loss_states.iloc[0]
    assert row["collection_side_operating_current_a"] == pytest.approx(0.0)
    assert row["p_load_reference_temperature_baseline_w"] == pytest.approx(0.0)
    assert row["p_total_reference_condition_baseline_w"] == pytest.approx(600.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "energised": False,
            "p": 0.0,
            "q": 0.0,
            "no_load": False,
            "rated_load": False,
        },
        {
            "energised": False,
            "energisation_offset_hours": 1,
            "no_load": False,
            "rated_load": False,
        },
        {"energised": False, "p": 0.0, "q": 0.0},
    ],
)
def test_clean_deenergised_state_is_definitive_zero(kwargs: dict[str, Any]) -> None:
    rows = _run(**kwargs).transformer_loss_states
    row = rows.loc[rows["transformer_energisation_authority_resolved"]].iloc[0]
    assert row["transformer_operating_loss_state"] == ("resolved_deenergised_transformer_zero_loss")
    assert row["p_no_load_reference_condition_baseline_w"] == 0.0
    assert row["p_load_reference_temperature_baseline_w"] == 0.0
    assert row["p_total_reference_condition_baseline_w"] == 0.0


def test_deenergised_nonzero_transfer_is_unresolved_contradiction() -> None:
    row = _run(energised=False, p=100.0).transformer_loss_states.iloc[0]
    assert row["transformer_operating_loss_state"] == (
        "unresolved_deenergised_transformer_with_nonzero_collection_transfer"
    )
    assert not row["total_active_loss_baseline_resolved"]
    assert pd.isna(row["p_total_reference_condition_baseline_w"])


@pytest.mark.parametrize(
    ("no_load", "rated_load", "no_load_resolved", "load_resolved", "state"),
    [
        (True, False, True, False, "unresolved_missing_transformer_rated_load_loss_authority"),
        (False, True, False, True, "unresolved_missing_transformer_no_load_loss_authority"),
    ],
)
def test_energised_partial_factory_authority_preserves_component_resolution(
    no_load: bool, rated_load: bool, no_load_resolved: bool, load_resolved: bool, state: str
) -> None:
    row = _run(no_load=no_load, rated_load=rated_load).transformer_loss_states.iloc[0]
    assert (
        row["no_load_loss_component_resolved"] is no_load_resolved
        or bool(row["no_load_loss_component_resolved"]) is no_load_resolved
    )
    assert bool(row["load_loss_component_resolved"]) is load_resolved
    assert not row["total_active_loss_baseline_resolved"]
    assert row["transformer_operating_loss_state"] == state


def test_energised_s12c_only_timestamp_preserves_no_load_but_not_load_component() -> None:
    rows = _run(energisation_offset_hours=1).transformer_loss_states
    row = rows.loc[rows["transformer_energisation_authority_resolved"]].iloc[0]
    assert not row["s11_operating_state_present"]
    assert row["no_load_loss_component_resolved"]
    assert not row["load_loss_component_resolved"]
    assert row["p_no_load_reference_condition_baseline_w"] == 600.0
    assert row["transformer_operating_loss_state"] == (
        "unresolved_missing_s11_collection_exit_operating_state"
    )


def test_missing_energisation_is_not_inferred_from_s11c() -> None:
    row = _run(energised=None).transformer_loss_states.iloc[0]
    assert not row["transformer_energisation_authority_resolved"]
    assert pd.isna(row["transformer_energised"])
    assert row["transformer_operating_loss_state"] == (
        "unresolved_missing_transformer_energisation_state"
    )
    assert pd.isna(row["p_total_reference_condition_baseline_w"])


def test_energised_zero_voltage_is_unresolved_and_never_divides_by_zero() -> None:
    row = _run(p=0.0, q=0.0, voltage=0.0).transformer_loss_states.iloc[0]
    assert row["s11_operating_solution_resolved"]
    assert row["transformer_operating_loss_state"] == (
        "unresolved_energised_transformer_with_zero_collection_voltage"
    )
    assert pd.isna(row["collection_side_operating_current_a"])
    assert pd.isna(row["p_load_reference_temperature_baseline_w"])


def test_timestamp_union_exposes_s11c_only_and_s12c_only_rows() -> None:
    rows = _run(energisation_offset_hours=1).transformer_loss_states
    assert len(rows) == 2
    assert rows.iloc[0]["transformer_operating_loss_state"] == (
        "unresolved_missing_transformer_energisation_state"
    )
    assert rows.iloc[1]["transformer_operating_loss_state"] == (
        "unresolved_missing_s11_collection_exit_operating_state"
    )


def test_correction_flags_and_factory_provenance_are_explicitly_uncorrected() -> None:
    row = _run().transformer_loss_states.iloc[0]
    assert row["factory_load_loss_reference_temperature_c"] == 75.0
    assert row["factory_no_load_test_frequency_hz"] == 50.0
    assert row["factory_load_loss_test_frequency_hz"] == 50.0
    for column in (
        "no_load_voltage_correction_applied",
        "load_loss_temperature_correction_applied",
        "frequency_correction_applied",
        "harmonic_correction_applied",
    ):
        assert not row[column]


def test_empty_transformer_universe_produces_stable_empty_result() -> None:
    arguments, _, _, _, _, _ = _bundle()
    values = list(arguments)
    topology, basis, nodes, segments, bindings, s11a = values[0], *values[24:29]
    static = resolve_transformer_static_authority(
        topology, basis, nodes, segments, bindings, s11a, {}, {}
    )
    loss = resolve_transformer_loss_authority(
        topology, basis, nodes, segments, bindings, s11a, {}, {}, static, {}, {}
    )
    energisation = resolve_transformer_energisation_authority(
        topology, basis, nodes, segments, bindings, s11a, {}, {}, static, {}
    )
    values[32:41] = [{}, {}, static, {}, {}, loss, {}, energisation]
    result = calculate_topology_transformer_operating_loss(*values)
    assert result.transformer_loss_states.empty
    assert result.transformer_loss_states.index.names == ["timestamp", "transformer_id"]
    assert result.diagnostics.transformer_count == 0
    assert result.diagnostics.row_count == 0


@pytest.mark.parametrize("parent", ["s11c", "s12a", "s12b", "s12c"])
def test_strong_parent_replay_rejects_frame_or_diagnostic_tampering(parent: str) -> None:
    arguments, *_ = _bundle()
    values = list(arguments)
    index = {"s11c": 31, "s12a": 34, "s12b": 37, "s12c": 39}[parent]
    supplied = values[index]
    if parent == "s11c":
        frame = supplied.collection_exit_states.copy(deep=True)
        frame.iloc[0, frame.columns.get_loc("p_delivered_at_collection_exit_w")] += 1.0
        values[index] = replace(supplied, collection_exit_states=frame)
    elif parent == "s12a":
        values[index] = replace(
            supplied, diagnostics=replace(supplied.diagnostics, resolved_transformer_count=0)
        )
    elif parent == "s12b":
        frame = supplied.transformer_states.copy(deep=True)
        frame.iloc[
            0,
            frame.columns.get_loc("factory_no_load_loss_w")
            if "factory_no_load_loss_w" in frame.columns
            else frame.columns.get_loc("no_load_loss_w"),
        ] += 1.0
        values[index] = replace(supplied, transformer_states=frame)
    else:
        values[index] = replace(
            supplied, diagnostics=replace(supplied.diagnostics, explicitly_energised_count=0)
        )
    with pytest.raises(RuntimeError, match=parent.upper()):
        calculate_topology_transformer_operating_loss(*values)


@pytest.mark.parametrize(
    ("parent_index", "field"),
    [
        (34, "equipment_by_id"),
        (34, "topology_by_id"),
        (37, "no_load_loss_by_id"),
        (37, "rated_load_loss_by_id"),
        (39, "energisation_states_by_key"),
    ],
)
def test_strong_parent_replay_rejects_mutable_equal_mappings(parent_index: int, field: str) -> None:
    values = list(_bundle()[0])
    parent = values[parent_index]
    values[parent_index] = replace(parent, **{field: dict(getattr(parent, field))})
    with pytest.raises(RuntimeError, match="immutable"):
        calculate_topology_transformer_operating_loss(*values)


def _validator_context() -> tuple[Any, Any, Any, Any, Any]:
    arguments, s11c, static, loss, energisation, _ = _bundle(p=100.0, q=20.0)
    result = calculate_topology_transformer_operating_loss(*arguments)
    return s11c, static, loss, energisation, result


@pytest.mark.parametrize(
    "column",
    [
        "s11_collection_exit_node_id",
        "transformer_static_authority_resolved",
        "transformer_factory_loss_authority_resolved",
        "transformer_energisation_authority_resolved",
        "transformer_energised",
        "s11_operating_state_present",
        "s11_operating_solution_resolved",
        "collection_exit_voltage_line_to_line_rms_v",
        "p_delivered_at_collection_exit_w",
        "q_delivered_at_collection_exit_var",
        "s_delivered_vector_magnitude_va",
        "rated_apparent_power_va",
        "collection_side_rated_line_to_line_rms_v",
        "collection_side_rated_current_a",
        "collection_side_operating_current_a",
        "collection_current_loading_fraction",
        "collection_current_loading_fraction_squared",
        "collection_current_exceeds_rated",
        "factory_no_load_loss_w",
        "factory_rated_load_loss_w",
        "p_no_load_reference_condition_baseline_w",
        "p_load_reference_temperature_baseline_w",
        "p_total_reference_condition_baseline_w",
        "no_load_loss_component_resolved",
        "load_loss_component_resolved",
        "total_active_loss_baseline_resolved",
        "no_load_voltage_correction_applied",
        "frequency_correction_applied",
        "transformer_operating_loss_state",
        "transformer_operating_loss_contract",
        "transformer_operating_loss_model",
        "transformer_operating_loss_scope",
        "transformer_operating_loss_coverage_scope",
    ],
)
def test_validator_rejects_result_tampering(column: str) -> None:
    s11c, static, loss, energisation, result = _validator_context()
    frame = result.transformer_loss_states.copy(deep=True)
    position = frame.columns.get_loc(column)
    value = frame.iloc[0, position]
    if column in module._BOOL_COLUMNS or column in module._NULLABLE_BOOL_COLUMNS:
        replacement: object = not bool(value)
    elif isinstance(value, str):
        replacement = "tampered"
    else:
        replacement = float(value) + 1.0
    frame.iloc[0, position] = replacement
    with pytest.raises(RuntimeError):
        _validate_result(
            s11c, static, loss, energisation, replace(result, transformer_loss_states=frame)
        )


@pytest.mark.parametrize(
    "field",
    [
        field
        for field in module.TopologyTransformerOperatingLossDiagnostics.__dataclass_fields__
        if field != "model"
    ],
)
def test_validator_rejects_diagnostic_tampering(field: str) -> None:
    s11c, static, loss, energisation, result = _validator_context()
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(s11c, static, loss, energisation, replace(result, diagnostics=diagnostics))


def test_source_excludes_forbidden_models_and_inference() -> None:
    source = inspect.getsource(module)
    forbidden = (
        "wiring_loss_ac_pct",
        "transformer_loss_pct",
        "K-factor",
        "Steinmetz",
        "network_side_voltage",
        "network_side_power",
        "kilowatt_hour",
        "winding_temperature",
        "forward_fill",
        "interpolate",
        "resample",
    )
    for term in forbidden:
        assert term not in source
