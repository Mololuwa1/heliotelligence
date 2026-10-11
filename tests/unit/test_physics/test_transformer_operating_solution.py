"""Tests for S12G balanced transformer terminal operating solution."""

from __future__ import annotations

import importlib
import inspect
import math
from dataclasses import replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import transformer_operating_solution as module
from heliotelligence.physics.transformer_energisation_authority import (
    resolve_transformer_energisation_authority,
)
from heliotelligence.physics.transformer_loss_authority import (
    TransformerRatedLoadLossAuthority,
    resolve_transformer_loss_authority,
)
from heliotelligence.physics.transformer_network_authority import (
    TransformerShortCircuitImpedanceAuthority,
    TransformerVoltageTransferAuthority,
    resolve_transformer_network_authority,
)
from heliotelligence.physics.transformer_operating_solution import (
    LOAD_DEPENDENT_ACTIVE_LOSS_OWNERSHIP,
    NO_LOAD_ACTIVE_LOSS_OWNERSHIP,
    OUTPUT_REFERENCE_PLANE,
    S12D_OPERATING_LOSS_TREATMENT,
    _validate_result,
    calculate_topology_transformer_operating_solution,
)
from heliotelligence.physics.transformer_series_equivalent import (
    TransformerRatedLoadLossReferenceConditionAuthority,
    resolve_transformer_series_equivalent,
)

s12d: Any = importlib.import_module("tests.unit.test_physics.test_transformer_operating_loss")
s10b: Any = importlib.import_module("tests.unit.test_physics.test_inverter_dispatch_feasibility")


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        inverter_lookup, "_load_cec_inverter_database", s10b.conversion_support._database
    )
    monkeypatch.setattr(
        inverter_envelope_lookup, "_load_cec_inverter_database", s10b.conversion_support._database
    )


def _transfer(ratio: float, phase: float) -> TransformerVoltageTransferAuthority:
    return TransformerVoltageTransferAuthority(
        "tx-1",
        "positive_sequence",
        "line_to_line_rms",
        "line_to_line_rms",
        "fixed_effective_no_load_ratio",
        "network_to_collection_line_to_line_voltage_magnitude_ratio",
        "fixed_non_tapped_transformer_ratio",
        ratio,
        "network_side_positive_sequence_voltage_leads_collection_side_positive_deg",
        phase,
        "factory-ratio",
        "high",
    )


def _impedance(side: str, magnitude: float) -> TransformerShortCircuitImpedanceAuthority:
    return TransformerShortCircuitImpedanceAuthority(
        "tx-1",
        "positive_sequence",
        "total_two_winding_series_short_circuit_impedance_magnitude",
        "per_unit_on_s12a_rated_apparent_power_and_explicit_reference_side_"
        "rated_line_to_line_voltage",
        "fixed_non_tapped_transformer_ratio",
        side,  # type: ignore[arg-type]
        magnitude,
        "rated_current",
        75.0,
        50.0,
        "factory-impedance",
        "high",
    )


_S11_NAMES = (
    "topology",
    "topology_string_iv",
    "branch_authority",
    "mppt_input_string_iv",
    "mppt_input_operating_points",
    "cec_sam_name_by_inverter_id",
    "inverter_authority",
    "mppt_current_limit_by_key",
    "inverter_dc_envelope",
    "inverter_ac",
    "pre_limit_ac",
    "inverter_power_accounting",
    "ac_capability_by_inverter_id",
    "ac_capability_authority",
    "reactive_power_request_by_key",
    "pqs_capability",
    "thermal_derating_by_inverter_id",
    "thermal_derating_authority",
    "inverter_temperature_by_key",
    "temperature_capability",
    "active_power_dispatch_request_by_key",
    "dispatch_request_authority",
    "dispatch_feasibility",
    "dispatch_selection",
    "network_basis",
    "node_authority_by_id",
    "segment_authority_by_id",
    "inverter_terminal_binding_by_inverter_id",
    "lv_ac_collection_authority",
    "collection_exit_voltage_by_key",
    "collection_exit_voltage_authority",
)


def _inputs(
    *,
    p: float | None = 100.0,
    q: float | None = 0.0,
    voltage: float | None = 400.0,
    energised: bool | None = True,
    no_load_w: float = 600.0,
    rated_load_w: float = 5_000.0,
    phase: float = 0.0,
    ratio: float = 27.5,
    side: str = "collection_side",
    magnitude: float = 0.06,
    include_no_load: bool = True,
    include_transfer: bool = True,
    include_series_reference: bool = True,
    extra_energisation_timestamp: pd.Timestamp | None = None,
    timezone_aware_energisation: bool = False,
) -> tuple[dict[str, Any], tuple[Any, ...]]:
    raw, s11c, static, _loss, energisation, _ = s12d._bundle(
        p=p, q=q, voltage=voltage, energised=energised, rated_s=500_000.0
    )
    inputs = dict(zip(_S11_NAMES, raw[:31], strict=True))
    equipment, topology_map = raw[32], raw[33]
    no_load = {"tx-1": s12d._no_load("tx-1", no_load_w)} if include_no_load else {}
    rated_load = {
        "tx-1": TransformerRatedLoadLossAuthority(
            "tx-1",
            rated_load_w,
            side,  # type: ignore[arg-type]
            "rated_current",
            75.0,
            50.0,
            "total_rated_load_loss_including_winding_and_stray",
            "factory-load-loss",
            "high",
        )
    }
    common = (
        inputs["topology"],
        inputs["network_basis"],
        inputs["node_authority_by_id"],
        inputs["segment_authority_by_id"],
        inputs["inverter_terminal_binding_by_inverter_id"],
        inputs["lv_ac_collection_authority"],
        equipment,
        topology_map,
    )
    energisation_by_key = dict(raw[38])
    original_key = next(iter(energisation_by_key), None)
    if original_key is not None and timezone_aware_energisation:
        state_value = energisation_by_key.pop(original_key)
        energisation_by_key[(original_key[0].tz_localize(None), original_key[1])] = state_value
    if original_key is not None and extra_energisation_timestamp is not None:
        energisation_by_key[(extra_energisation_timestamp, original_key[1])] = raw[38][original_key]
    energisation = resolve_transformer_energisation_authority(
        *common, static, energisation_by_key
    )
    loss = resolve_transformer_loss_authority(*common, static, no_load, rated_load)
    transfer = {"tx-1": _transfer(ratio, phase)} if include_transfer else {}
    impedance = {"tx-1": _impedance(side, magnitude)}
    network = resolve_transformer_network_authority(*common, static, transfer, impedance)
    references = {
        "tx-1": TransformerRatedLoadLossReferenceConditionAuthority(
            "tx-1", "fixed_non_tapped_transformer_ratio", "factory-test", "high"
        )
    } if include_series_reference else {}
    series = resolve_transformer_series_equivalent(
        *common, static, no_load, rated_load, loss, transfer, impedance, network, references
    )
    inputs.update(
        {
            "lv_ac_collection_operating_solution": s11c,
            "transformer_equipment_by_id": equipment,
            "transformer_topology_by_id": topology_map,
            "transformer_static_authority": static,
            "transformer_no_load_loss_by_id": no_load,
            "transformer_rated_load_loss_by_id": rated_load,
            "transformer_loss_authority": loss,
            "transformer_energisation_by_key": energisation_by_key,
            "transformer_energisation_authority": energisation,
            "transformer_voltage_transfer_by_id": transfer,
            "transformer_short_circuit_impedance_by_id": impedance,
            "transformer_network_authority": network,
            "transformer_rated_load_loss_reference_condition_by_id": references,
            "transformer_series_equivalent": series,
        }
    )
    return inputs, (s11c, static, loss, energisation, network, series)


def _run(**kwargs: Any) -> Any:
    return calculate_topology_transformer_operating_solution(**_inputs(**kwargs)[0])


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
@pytest.mark.parametrize("phase", [0.0, 30.0, -30.0])
def test_zero_current_ideal_transfer_with_positive_impedance(side: str, phase: float) -> None:
    row = _run(
        side=side, phase=phase, p=0.0, q=0.0, no_load_w=0.0
    ).transformer_operating_states.iloc[0]
    assert row["transformer_terminal_operating_solution_resolved"]
    assert row["network_terminal_voltage_line_to_line_rms_v"] == pytest.approx(11_000.0)
    assert row["network_terminal_phase_angle_deg"] == pytest.approx(phase)
    for name in (
        "collection_series_current_magnitude_a",
        "network_series_current_magnitude_a",
        "p_network_terminal_w",
        "q_network_terminal_var",
        "p_series_active_loss_w",
        "q_series_consumption_var",
        "p_total_transformer_active_loss_w",
    ):
        assert row[name] == pytest.approx(0.0)


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
def test_positive_pure_reactance_transforms_current_and_consumes_q(side: str) -> None:
    row = _run(
        side=side, p=100.0, q=0.0, no_load_w=0.0, rated_load_w=0.0
    ).transformer_operating_states.iloc[0]
    assert row["effective_series_resistance_ohm_per_phase"] == 0.0, row[
        "transformer_operating_solution_state"
    ]
    assert row["effective_series_reactance_ohm_per_phase"] > 0.0
    assert row["network_series_current_magnitude_a"] == pytest.approx(
        row["collection_series_current_magnitude_a"] / 27.5
    )
    assert row["p_series_active_loss_w"] == pytest.approx(0.0)
    assert row["q_series_consumption_var"] > 0.0
    assert row["collection_q_var"] == pytest.approx(
        row["q_network_terminal_var"] + row["q_series_consumption_var"]
    )
    assert row["collection_p_w"] == pytest.approx(row["p_network_terminal_w"])


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
def test_nonzero_rx_closes_series_and_terminal_power(side: str) -> None:
    row = _run(side=side, p=120.0, q=40.0).transformer_operating_states.iloc[0]
    reference_current = (
        row["collection_series_current_magnitude_a"]
        if side == "collection_side"
        else row["network_series_current_magnitude_a"]
    )
    assert row["p_series_active_loss_w"] == pytest.approx(
        3.0 * row["effective_series_resistance_ohm_per_phase"] * reference_current**2
    )
    assert row["q_series_consumption_var"] == pytest.approx(
        3.0 * row["effective_series_reactance_ohm_per_phase"] * reference_current**2
    )
    assert row["active_power_conservation_residual_w"] == pytest.approx(0.0, abs=1e-8)
    assert row["reactive_power_conservation_residual_var"] == pytest.approx(0.0, abs=1e-8)


def test_explicit_ratio_differs_from_rated_quotient() -> None:
    row = _run(ratio=20.0, p=0.0, q=0.0, no_load_w=0.0).transformer_operating_states.iloc[0]
    assert row["network_terminal_voltage_line_to_line_rms_v"] == pytest.approx(8_000.0)


@pytest.mark.parametrize("p", [0.0, 300.0, 1_000.0])
def test_no_load_sink_allows_reverse_and_forward_flow(p: float) -> None:
    row = _run(p=p, q=0.0, no_load_w=600.0).transformer_operating_states.iloc[0]
    assert row["p_entering_series_transfer_w"] == pytest.approx(row["collection_p_w"] - 600.0)
    if row["collection_p_w"] < 600.0:
        assert row["p_network_terminal_w"] < 0.0
    assert row["p_total_transformer_active_loss_w"] == pytest.approx(
        row["p_no_load_active_sink_w"] + row["p_series_active_loss_w"]
    )


def test_deenergised_and_zero_voltage_states() -> None:
    clean = _run(energised=False, p=0.0, q=0.0).transformer_operating_states.iloc[0]
    assert (
        clean["transformer_operating_solution_state"]
        == "resolved_deenergised_transformer_no_transfer"
    )
    assert math.isnan(clean["network_terminal_voltage_line_to_line_rms_v"])
    conflict = _run(energised=False, p=100.0).transformer_operating_states.iloc[0]
    assert (
        conflict["transformer_operating_solution_state"]
        == "unresolved_deenergised_transformer_with_nonzero_collection_transfer"
    )
    zero_v = _run(energised=True, p=0.0, q=0.0, voltage=0.0).transformer_operating_states.iloc[0]
    assert (
        zero_v["transformer_operating_solution_state"]
        == "unresolved_energised_transformer_with_zero_collection_voltage"
    )


def test_loss_ownership_and_reference_planes() -> None:
    row = _run().transformer_operating_states.iloc[0]
    assert row["load_dependent_active_loss_ownership"] == LOAD_DEPENDENT_ACTIVE_LOSS_OWNERSHIP
    assert row["no_load_active_loss_ownership"] == NO_LOAD_ACTIVE_LOSS_OWNERSHIP
    assert row["s12d_operating_loss_treatment"] == S12D_OPERATING_LOSS_TREATMENT
    assert row["output_reference_plane"] == OUTPUT_REFERENCE_PLANE
    assert (
        row["s11_collection_exit_node_id"],
        row["transformer_collection_terminal_id"],
        row["transformer_network_terminal_id"],
    ) == ("exit", "tx-1:collection", "tx-1:network")


def test_missing_energisation_is_primary_and_empty_timestamp_universe_is_stable() -> None:
    inputs, _ = _inputs(energised=None)
    result = calculate_topology_transformer_operating_solution(**inputs)
    assert (
        result.transformer_operating_states.iloc[0]["transformer_operating_solution_state"]
        == "unresolved_missing_transformer_energisation_state"
    )
    assert result.diagnostics.row_count == 1  # S11C supplies the timestamp.


def test_nonfinite_derivation_is_explicit_state_not_exception() -> None:
    row = _run(
        side="network_side", ratio=1e-308, p=100.0, q=0.0, no_load_w=0.0
    ).transformer_operating_states.iloc[0]
    assert not row["transformer_terminal_operating_solution_resolved"]
    assert (
        row["transformer_operating_solution_state"]
        == "unresolved_nonfinite_transformer_operating_state"
    )
    for name in (
        "network_series_current_magnitude_a",
        "network_terminal_phase_voltage_magnitude_v",
        "p_series_active_loss_w",
        "q_series_consumption_var",
    ):
        assert math.isnan(float(row[name]))


def test_unresolved_operation_preserves_static_evidence() -> None:
    row = _run(p=100_000.0, q=0.0).transformer_operating_states.iloc[0]
    assert row["transformer_operating_solution_state"] == (
        "unresolved_s11_collection_exit_operating_solution"
    )
    assert row["network_to_collection_voltage_ratio"] == 27.5
    assert row["network_side_phase_displacement_deg"] == 0.0
    assert row["series_equivalent_reference_side"] == "collection_side"
    assert row["effective_series_resistance_ohm_per_phase"] >= 0.0
    assert row["effective_series_reactance_ohm_per_phase"] > 0.0
    assert math.isnan(row["network_terminal_phase_voltage_real_v"])


@pytest.mark.parametrize(
    ("options", "state"),
    [
        (
            {"include_no_load": False},
            "unresolved_missing_transformer_no_load_loss_authority",
        ),
        (
            {"include_transfer": False},
            "unresolved_upstream_transformer_positive_sequence_network_authority",
        ),
        (
            {"include_series_reference": False},
            "unresolved_upstream_transformer_series_equivalent",
        ),
    ],
)
def test_missing_parent_authority_states(options: dict[str, Any], state: str) -> None:
    row = _run(**options).transformer_operating_states.iloc[0]
    assert row["transformer_operating_solution_state"] == state
    assert not row["transformer_terminal_operating_solution_resolved"]


def test_s12c_only_timestamp_exposes_missing_s11_state_and_orders_rows() -> None:
    extra = pd.Timestamp("2030-01-01 00:00:00", tz="UTC")
    result = _run(extra_energisation_timestamp=extra)
    states = result.transformer_operating_states
    assert states.index.is_monotonic_increasing
    row = states.loc[(extra, "tx-1")]
    assert (
        row["transformer_operating_solution_state"]
        == "unresolved_missing_s11_collection_exit_operating_state"
    )
    assert row["network_to_collection_voltage_ratio"] == 27.5
    assert math.isnan(row["network_terminal_phase_voltage_real_v"])


def test_incompatible_timestamp_timezone_semantics_are_rejected() -> None:
    inputs, _ = _inputs(timezone_aware_energisation=True)
    with pytest.raises(ValueError, match="incompatible timezone semantics"):
        calculate_topology_transformer_operating_solution(**inputs)


def test_private_validator_rejects_state_and_diagnostics_tampering() -> None:
    inputs, parents = _inputs()
    result = calculate_topology_transformer_operating_solution(**inputs)
    for column in (
        "network_terminal_phase_voltage_real_v",
        "network_terminal_voltage_line_to_line_rms_v",
        "network_terminal_phase_angle_deg",
        "network_series_current_real_a",
        "network_series_current_magnitude_a",
        "collection_series_current_magnitude_a",
        "p_network_terminal_w",
        "q_network_terminal_var",
        "p_series_active_loss_w",
        "q_series_consumption_var",
        "p_total_transformer_active_loss_w",
        "active_power_conservation_residual_w",
        "network_to_collection_voltage_ratio",
        "network_side_phase_displacement_deg",
        "series_equivalent_reference_side",
        "effective_series_resistance_ohm_per_phase",
        "transformer_network_terminal_id",
        "output_reference_plane",
        "load_dependent_active_loss_ownership",
        "no_load_active_loss_ownership",
        "frequency_correction_applied",
        "transformer_operating_solution_state",
    ):
        frame = result.transformer_operating_states.copy(deep=True)
        original = frame.iloc[0, frame.columns.get_loc(column)]
        if column.endswith("_applied") or column == "excitation_no_load_q_modeled":
            replacement: object = not bool(original)
        elif isinstance(original, str):
            replacement = "tampered"
        else:
            replacement = 123.0
        frame.iloc[0, frame.columns.get_loc(column)] = replacement
        try:
            _validate_result(parents, replace(result, transformer_operating_states=frame))
        except RuntimeError:
            pass
        else:
            pytest.fail(f"validator accepted tampered {column}")
    with pytest.raises(RuntimeError):
        _validate_result(
            parents, replace(result, diagnostics=replace(result.diagnostics, row_count=99))
        )
    frame = result.transformer_operating_states.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc("transformer_operating_solution_state")] = (
        "unresolved_nonfinite_transformer_operating_state"
    )
    counts = tuple(
        (name, 1 if name == "unresolved_nonfinite_transformer_operating_state" else 0)
        for name, _ in result.diagnostics.state_counts
    )
    diagnostics = replace(
        result.diagnostics,
        resolved_energised_count=0,
        unresolved_count=1,
        state_counts=counts,
    )
    with pytest.raises(RuntimeError):
        _validate_result(
            parents,
            replace(result, transformer_operating_states=frame, diagnostics=diagnostics),
        )


def test_strong_replay_rejects_each_tampered_parent() -> None:
    inputs, _ = _inputs()
    names = (
        "lv_ac_collection_operating_solution",
        "transformer_static_authority",
        "transformer_loss_authority",
        "transformer_energisation_authority",
        "transformer_network_authority",
        "transformer_series_equivalent",
    )
    frames = (
        "collection_exit_states",
        "transformer_states",
        "transformer_states",
        "states",
        "transformer_states",
        "transformer_states",
    )
    for name, frame_name in zip(names, frames, strict=True):
        parent = inputs[name]
        frame = getattr(parent, frame_name).copy(deep=True)
        frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
        tampered = dict(inputs)
        tampered[name] = replace(parent, **{frame_name: frame})
        with pytest.raises(RuntimeError):
            calculate_topology_transformer_operating_solution(**tampered)


def test_scope_excludes_s12d_excitation_and_future_stages() -> None:
    source = inspect.getsource(module)
    for forbidden in (
        "transformer_operating_loss",
        "p_load_reference_temperature_baseline_w",
        "p_total_reference_condition_baseline_w",
        "shunt_admittance",
        "magnetising_current",
        "tap_schedule",
        "revenue_meter",
        "wiring_loss_ac_pct",
    ):
        assert forbidden not in source
