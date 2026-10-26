"""Focused physics and contract tests for S12M."""

from __future__ import annotations

import cmath
import importlib
import inspect
import math
from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import transformer_advanced_operating_solution as module
from heliotelligence.physics.transformer_advanced_operating_solution import (
    ADVANCED_LOAD_LOSS_OWNERSHIP,
    ADVANCED_NO_LOAD_LOSS_OWNERSHIP,
    _validate_result,
    calculate_topology_transformer_advanced_operating_solution,
)
from heliotelligence.physics.transformer_core_no_load_loss import (
    calculate_topology_transformer_core_no_load_loss,
)
from heliotelligence.physics.transformer_corrected_load_loss import (
    TransformerWindingResistanceTemperatureConstantAuthority,
    calculate_topology_transformer_corrected_load_loss,
)
from tests.unit.test_physics import test_transformer_corrected_load_loss as ksupport
from tests.unit.test_physics.test_transformer_core_no_load_loss import _frequency, _scaling

support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_dispatch_feasibility")
_TAMPER_BUNDLE: tuple[Any, tuple[Any, Any, Any], list[pd.Timestamp]] | None = None


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


def _context(
    *,
    p: float = 100.0,
    q: float = 0.0,
    side: str = "collection_side",
    winding_temperature: float | None = 75.0,
    ratios: dict[int, float] | None = None,
    no_load_w: float = 600.0,
    advanced_core: bool = False,
    energised: bool | None = True,
    aggregate_evidence: bool = False,
    material: str = "copper",
    winding_materials: tuple[str, str] | None = None,
    winding_temperatures: tuple[float, float] | None = None,
    other_stray_w: float = 1500.0,
    rated_load_w: float = 5000.0,
    winding_allocations: tuple[float, float, float, float] = (1500.0, 1500.0, 250.0, 250.0),
    custom_constant: TransformerWindingResistanceTemperatureConstantAuthority | None = None,
) -> dict[str, Any]:
    """Build replay-consistent G/K/L parents while retaining upstream helpers."""
    original_inputs = ksupport._inputs  # type: ignore[attr-defined]

    def inputs_with_no_load(**kwargs: Any) -> Any:
        kwargs["no_load_w"] = no_load_w
        return original_inputs(**kwargs)

    ksupport._inputs = inputs_with_no_load  # type: ignore[attr-defined]
    try:
        values = ksupport._context(
            p=p,
            q=q,
            side=side,
            winding_temperature=winding_temperature,
            ratios=ratios,
            energised=energised,
            aggregate_evidence=aggregate_evidence,
            material=material,
            winding_materials=winding_materials,
            winding_temperatures=winding_temperatures,
            other_stray_w=other_stray_w,
            rated_load_w=rated_load_w,
            winding_allocations=winding_allocations,
        )
    finally:
        ksupport._inputs = original_inputs  # type: ignore[attr-defined]
    if custom_constant is not None:
        values["winding_temperature_constant_by_transformer_id"] = {"tx-1": custom_constant}
    corrected = calculate_topology_transformer_corrected_load_loss(**values)
    values["transformer_corrected_load_loss"] = corrected
    times = list(
        dict.fromkeys(
            values[
                "transformer_operating_solution"
            ].transformer_operating_states.index.get_level_values("timestamp")
        )
    )
    values["transformer_operating_frequency_by_key"] = (
        {(times[0], "tx-1"): _frequency()} if times else {}
    )
    values["transformer_core_loss_scaling_by_id"] = (
        {"tx-1": _scaling(scalable=500.0)} if advanced_core else {}
    )
    core = calculate_topology_transformer_core_no_load_loss(**values)
    values["transformer_core_no_load_loss"] = core
    return values


def _run(**kwargs: Any) -> Any:
    return calculate_topology_transformer_advanced_operating_solution(**_context(**kwargs))


def test_factory_reference_identity_reproduces_s12g_without_double_counting() -> None:
    values = _context()
    result = calculate_topology_transformer_advanced_operating_solution(**values)
    row = result.states.iloc[0]
    baseline = values["transformer_operating_solution"].transformer_operating_states.iloc[0]
    assert row["transformer_advanced_operating_solution_state"] == (
        "resolved_coupled_advanced_transformer_terminal_solution"
    )
    assert row["advanced_fundamental_effective_series_resistance_ohm_per_phase"] == (
        pytest.approx(baseline["effective_series_resistance_ohm_per_phase"])
    )
    assert row["harmonic_increment_accounting_resistance_ohm_per_phase"] == 0.0
    assert row["p_harmonic_incremental_load_loss_w"] == 0.0
    assert row["p_no_load_active_loss_w"] == 600.0
    assert row["network_terminal_voltage_line_to_line_rms_v"] == pytest.approx(
        baseline["network_terminal_voltage_line_to_line_rms_v"]
    )
    assert row["p_network_terminal_w"] == pytest.approx(baseline["p_network_terminal_w"])
    assert row["advanced_load_loss_ownership"] == ADVANCED_LOAD_LOSS_OWNERSHIP
    assert row["advanced_no_load_loss_ownership"] == ADVANCED_NO_LOAD_LOSS_OWNERSHIP
    assert math.isfinite(row["advanced_fundamental_effective_series_resistance_ohm_per_phase"])
    assert math.isfinite(row["p_advanced_load_loss_w"])
    assert math.isfinite(row["coupled_advanced_load_loss_w"])
    assert row["p_selected_load_loss_w"] == row["p_advanced_load_loss_w"]
    assert row["coupled_selected_load_loss_w"] == row["coupled_advanced_load_loss_w"]
    assert row["terminal_solution_fidelity"] == "coupled_advanced_load_loss"


def test_winding_resolved_effective_factors_flow_through_s12m_unchanged() -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=75.0,
        winding_temperatures=(95.0, 85.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
    )
    krow = values["transformer_corrected_load_loss"].states.iloc[0]
    result = calculate_topology_transformer_advanced_operating_solution(**values)
    row = result.states.iloc[0]
    assert krow["temperature_correction_basis"] == "winding_resolved"
    assert krow["advanced_load_loss_correction_resolved"]
    assert row["transformer_advanced_operating_solution_state"] == (
        "resolved_coupled_advanced_transformer_terminal_solution"
    )
    assert row["terminal_solution_fidelity"] == "coupled_advanced_load_loss"
    assert row["s12k_advanced_load_loss_correction_resolved"]
    assert krow["i2r_loss_reference_w"] * krow["i2r_temperature_correction_factor"] == (
        pytest.approx(
            krow["collection_winding_i2r_loss_reference_w"]
            * krow["collection_winding_i2r_temperature_correction_factor"]
            + krow["network_winding_i2r_loss_reference_w"]
            * krow["network_winding_i2r_temperature_correction_factor"]
        )
    )
    assert (
        krow["winding_eddy_current_loss_reference_w"]
        * krow["winding_eddy_temperature_correction_factor"]
    ) == pytest.approx(
        krow["collection_winding_eddy_current_loss_reference_w"]
        * krow["collection_winding_eddy_temperature_correction_factor"]
        + krow["network_winding_eddy_current_loss_reference_w"]
        * krow["network_winding_eddy_temperature_correction_factor"]
    )


@pytest.mark.parametrize("advanced_core", [False, True])
def test_s12g_load_loss_fallback_resolves_with_independent_s12l_fidelity(
    advanced_core: bool,
) -> None:
    values = _context(aggregate_evidence=True, advanced_core=advanced_core)
    result = calculate_topology_transformer_advanced_operating_solution(**values)
    row = result.states.iloc[0]
    s12g = values["transformer_operating_solution"].transformer_operating_states.iloc[0]
    assert row["transformer_advanced_operating_solution_state"] == (
        "resolved_coupled_transformer_terminal_solution_with_s12g_load_loss_fallback"
    )
    assert row["s12k_load_loss_output_resolved"]
    assert not row["s12k_advanced_load_loss_correction_resolved"]
    assert row["s12k_load_loss_fallback_applied"]
    assert row["transformer_terminal_output_resolved"]
    assert row["terminal_solution_fidelity"] == "coupled_s12g_load_loss_fallback"
    assert row["s12g_reference_effective_series_resistance_ohm_per_phase"] == pytest.approx(
        s12g["effective_series_resistance_ohm_per_phase"]
    )
    assert row["harmonic_increment_accounting_resistance_ohm_per_phase"] == 0.0
    assert row["retained_series_reactance_ohm_per_phase"] == pytest.approx(
        s12g["effective_series_reactance_ohm_per_phase"]
    )
    assert row["s12k_selected_load_loss_w"] == pytest.approx(s12g["p_series_active_loss_w"])
    assert row["coupled_selected_load_loss_w"] == pytest.approx(
        row["p_fundamental_series_active_loss_w"]
    )
    assert result.diagnostics.s12g_load_loss_fallback_terminal_count == 1
    for field in (
        "advanced_fundamental_effective_series_resistance_ohm_per_phase",
        "advanced_fundamental_series_resistance_delta_ohm_per_phase",
        "p_advanced_load_loss_w",
        "coupled_advanced_load_loss_w",
    ):
        assert math.isnan(row[field])


def test_full_s12g_load_and_no_load_fallback_reproduces_s12g_terminal_solution() -> None:
    values = _context(aggregate_evidence=True, advanced_core=False)
    result = calculate_topology_transformer_advanced_operating_solution(**values)
    row = result.states.iloc[0]
    baseline = values["transformer_operating_solution"].transformer_operating_states.iloc[0]
    assert row["s12k_load_loss_fallback_applied"]
    assert row["load_loss_fallback_applied"]
    assert row["terminal_solution_fidelity"] == "coupled_s12g_load_loss_fallback"
    assert row["transformer_advanced_operating_solution_state"] == (
        "resolved_coupled_transformer_terminal_solution_with_s12g_load_loss_fallback"
    )
    assert row["transformer_advanced_operating_solution_state"] != (
        "resolved_coupled_advanced_transformer_terminal_solution"
    )
    for field in (
        "collection_series_current_real_a",
        "collection_series_current_imag_a",
        "collection_series_current_magnitude_a",
        "network_series_current_real_a",
        "network_series_current_imag_a",
        "network_series_current_magnitude_a",
        "network_terminal_voltage_line_to_line_rms_v",
        "p_network_terminal_w",
        "q_network_terminal_var",
    ):
        assert row[field] == pytest.approx(baseline[field])
    assert row["p_fundamental_series_active_loss_w"] == pytest.approx(
        baseline["p_series_active_loss_w"]
    )
    assert row["p_no_load_active_loss_w"] == pytest.approx(baseline["p_no_load_active_sink_w"])
    assert row["p_total_transformer_active_loss_w"] == pytest.approx(
        baseline["p_total_transformer_active_loss_w"]
    )


def test_temperature_only_changes_fundamental_resistance_without_harmonic_sink() -> None:
    identity = _run().states.iloc[0]
    row = _run(winding_temperature=110.0).states.iloc[0]
    assert row["advanced_fundamental_effective_series_resistance_ohm_per_phase"] != pytest.approx(
        identity["advanced_fundamental_effective_series_resistance_ohm_per_phase"]
    )
    assert row["harmonic_increment_accounting_resistance_ohm_per_phase"] == 0.0
    assert row["p_advanced_load_loss_w"] == pytest.approx(row["p_fundamental_series_active_loss_w"])


def test_harmonic_increment_is_a_separate_coupled_active_sink() -> None:
    row = _run(ratios={1: 1.0, 5: 0.1, 7: 0.05}).states.iloc[0]
    assert row["harmonic_increment_accounting_resistance_ohm_per_phase"] > 0
    assert row["p_harmonic_incremental_load_loss_w"] > 0
    assert row["p_advanced_load_loss_w"] == pytest.approx(
        row["p_fundamental_series_active_loss_w"] + row["p_harmonic_incremental_load_loss_w"]
    )


def test_published_fixed_point_losses_and_phasors_are_one_consistent_iterate() -> None:
    values = _context(
        advanced_core=True,
        winding_temperature=110.0,
        ratios={1: 1.0, 5: 0.1, 7: 0.05},
        q=30.0,
    )
    row = calculate_topology_transformer_advanced_operating_solution(**values).states.iloc[0]
    core = values["transformer_core_no_load_loss"].states.iloc[0]
    vc = complex(row["collection_voltage_line_to_line_rms_v"] / math.sqrt(3.0), 0.0)
    series_power = complex(
        row["collection_p_w"]
        - row["p_no_load_active_loss_w"]
        - row["p_harmonic_incremental_load_loss_w"],
        row["collection_q_var"],
    )
    ic = (series_power / (3.0 * vc)).conjugate()
    transfer = row["network_to_collection_voltage_ratio"] * cmath.exp(
        1j * math.radians(row["network_side_phase_displacement_deg"])
    )
    network_current = ic / transfer.conjugate()
    impedance = complex(
        row["advanced_fundamental_effective_series_resistance_ohm_per_phase"],
        row["retained_series_reactance_ohm_per_phase"],
    )
    if row["series_reference_side"] == "collection_side":
        ec = vc - impedance * ic
        en = transfer * ec
        vn = en
        reference_current = ic
    else:
        ec = vc
        en = transfer * ec
        vn = en - impedance * network_current
        reference_current = network_current
    network_power = 3.0 * vn * network_current.conjugate()
    assert complex(
        row["collection_series_current_real_a"], row["collection_series_current_imag_a"]
    ) == pytest.approx(ic)
    assert complex(
        row["network_series_current_real_a"], row["network_series_current_imag_a"]
    ) == pytest.approx(network_current)
    assert row["internal_collection_excitation_voltage_line_to_line_rms_v"] == pytest.approx(
        math.sqrt(3.0) * abs(ec)
    )
    assert row["internal_network_excitation_voltage_line_to_line_rms_v"] == pytest.approx(
        math.sqrt(3.0) * abs(en)
    )
    assert complex(
        row["network_terminal_phase_voltage_real_v"],
        row["network_terminal_phase_voltage_imag_v"],
    ) == pytest.approx(vn)
    assert row["p_network_terminal_w"] == pytest.approx(network_power.real)
    assert row["q_network_terminal_var"] == pytest.approx(network_power.imag)

    harmonic_target = (
        3.0
        * row["harmonic_increment_accounting_resistance_ohm_per_phase"]
        * abs(reference_current) ** 2
    )
    assert harmonic_target - row["p_harmonic_incremental_load_loss_w"] == pytest.approx(
        row["harmonic_fixed_point_residual_w"], abs=1e-12
    )
    core_voltage = math.sqrt(3.0) * abs(
        ec if core["no_load_test_reference_side"] == "collection_side" else en
    )
    frequency_ratio = core["operating_frequency_hz"] / core["no_load_test_frequency_hz"]
    flux_ratio = (
        core_voltage / core["factory_reference_core_excitation_voltage_ll_rms_v"]
    ) / frequency_ratio
    multiplier = frequency_ratio ** core["steinmetz_frequency_exponent_alpha"] * (
        flux_ratio ** core["steinmetz_flux_density_exponent_beta"]
    )
    no_load_target = (
        core["scalable_core_loss_reference_w"] * multiplier
        + core["non_scaling_no_load_loss_reference_residual_w"]
    )
    assert no_load_target - row["p_no_load_active_loss_w"] == pytest.approx(
        row["no_load_fixed_point_residual_w"], abs=1e-12
    )
    assert abs(row["harmonic_fixed_point_residual_w"]) <= row["fixed_point_absolute_tolerance_w"]
    assert abs(row["no_load_fixed_point_residual_w"]) <= row["fixed_point_absolute_tolerance_w"]


def test_advanced_core_loss_is_re_evaluated_at_coupled_internal_voltage() -> None:
    row = _run(advanced_core=True, winding_temperature=110.0).states.iloc[0]
    assert row["s12l_advanced_core_loss_scaling_resolved"]
    assert row["s12l_core_loss_re_evaluated_in_coupled_iteration"]
    assert row["coupled_core_loss_scaling_multiplier"] > 0
    assert row["coupled_no_load_adjustment_vs_s12l_w"] != pytest.approx(0.0, abs=1e-10)


def test_s12l_factory_fallback_is_held_constant() -> None:
    row = _run().states.iloc[0]
    assert not row["s12l_advanced_core_loss_scaling_resolved"]
    assert not row["s12l_core_loss_re_evaluated_in_coupled_iteration"]
    assert row["coupled_no_load_adjustment_vs_s12l_w"] == 0.0


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
def test_both_series_reference_sides_resolve_without_impedance_referral(side: str) -> None:
    row = _run(side=side, q=30.0).states.iloc[0]
    assert row["series_reference_side"] == side
    assert row["transformer_advanced_operating_solution_state"] == (
        "resolved_coupled_advanced_transformer_terminal_solution"
    )
    assert row["active_power_conservation_residual_w"] == pytest.approx(0.0, abs=1e-6)
    assert row["reactive_power_conservation_residual_var"] == pytest.approx(0.0, abs=1e-6)


def test_deenergised_transformer_has_zero_transfer_without_fabricated_voltage() -> None:
    row = _run(p=0.0, energised=False).states.iloc[0]
    assert row["transformer_advanced_operating_solution_state"] == (
        "resolved_deenergised_transformer_zero_advanced_transfer"
    )
    assert row["p_total_transformer_active_loss_w"] == 0.0
    assert pd.isna(row["network_terminal_voltage_line_to_line_rms_v"])
    assert row["s12g_baseline_no_load_loss_w"] == 0.0


def test_controlled_iteration_limit_reports_nonconvergence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "MAXIMUM_ITERATIONS", 1)
    monkeypatch.setattr(module, "FIXED_POINT_RELATIVE_TOLERANCE", 0.0)
    monkeypatch.setattr(module, "FIXED_POINT_ABSOLUTE_TOLERANCE_W", 0.0)
    row = _run(ratios={1: 1.0, 5: 0.2}, advanced_core=True).states.iloc[0]
    assert row["transformer_advanced_operating_solution_state"] == (
        "unresolved_advanced_transformer_fixed_point_nonconvergence"
    )
    assert not row["fixed_point_converged"]
    assert row["fixed_point_iterations"] == 1
    assert pd.notna(row["no_load_fixed_point_residual_w"])
    assert pd.notna(row["harmonic_fixed_point_residual_w"])


def test_coupled_core_domain_exit_does_not_extrapolate() -> None:
    values = _context(advanced_core=True, winding_temperature=110.0)
    baseline_result = calculate_topology_transformer_advanced_operating_solution(**values)
    baseline_row = values["transformer_core_no_load_loss"].states.iloc[0]
    coupled_ratio = float(
        baseline_result.states.iloc[0]["coupled_core_flux_density_ratio_to_factory_reference"]
    )
    baseline_ratio = float(baseline_row["core_flux_density_ratio_to_factory_reference"])
    assert coupled_ratio != baseline_ratio
    core = values["transformer_core_no_load_loss"]
    frame = core.states.copy(deep=True)
    if coupled_ratio < baseline_ratio:
        frame.loc[:, "minimum_flux_density_ratio_to_reference"] = (
            coupled_ratio + baseline_ratio
        ) / 2.0
    else:
        frame.loc[:, "maximum_flux_density_ratio_to_reference"] = (
            coupled_ratio + baseline_ratio
        ) / 2.0
    parents = (
        values["transformer_operating_solution"],
        values["transformer_corrected_load_loss"],
        replace(core, states=frame),
    )
    timestamp, identifier = baseline_result.states.index[0]
    record = module._record(timestamp, identifier, parents)
    assert record["transformer_advanced_operating_solution_state"] == (
        "unresolved_coupled_core_loss_outside_s12l_scaling_domain"
    )
    assert pd.notna(record["coupled_core_flux_density_ratio_to_factory_reference"])
    assert record["fixed_point_iterations"] != 0


def test_derived_nonfinite_state_is_controlled_and_publishes_no_infinity() -> None:
    values = _context(advanced_core=True)
    g = values["transformer_operating_solution"]
    frame = g.transformer_operating_states.copy(deep=True)
    frame.loc[:, "collection_p_w"] = 1e308
    parents = (
        replace(g, transformer_operating_states=frame),
        values["transformer_corrected_load_loss"],
        values["transformer_core_no_load_loss"],
    )
    timestamp, identifier = frame.index[0]
    record = module._record(timestamp, identifier, parents)
    assert record["transformer_advanced_operating_solution_state"] == (
        "unresolved_nonfinite_advanced_transformer_operating_state"
    )
    for name in module._FLOAT:
        value = record[name]
        assert not (isinstance(value, float) and value in (float("inf"), float("-inf")))


@pytest.mark.parametrize(
    "parent_name,frame_name",
    [
        ("transformer_operating_solution", "transformer_operating_states"),
        ("transformer_corrected_load_loss", "states"),
        ("transformer_core_no_load_loss", "states"),
    ],
)
def test_parent_frame_tampering_is_rejected(parent_name: str, frame_name: str) -> None:
    values = _context()
    parent = values[parent_name]
    frame = getattr(parent, frame_name).copy(deep=True)
    frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
    values[parent_name] = replace(parent, **{frame_name: frame})
    with pytest.raises(ValueError, match="canonical replay"):
        calculate_topology_transformer_advanced_operating_solution(**values)


def test_validator_is_independent_of_production_builders_and_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _context(advanced_core=True)
    result = calculate_topology_transformer_advanced_operating_solution(**values)
    parents = module._parents(values)
    times = list(result.states.index.get_level_values("timestamp").unique())

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("production path invoked")

    for name in ("_record", "_frame", "_diagnostics", "_propose", "_base"):
        monkeypatch.setattr(module, name, fail)
    _validate_result(parents, times, result)


def test_fallback_validator_is_independent_of_production_builders_and_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _context(aggregate_evidence=True, advanced_core=False)
    result = calculate_topology_transformer_advanced_operating_solution(**values)
    assert result.states.iloc[0]["s12k_load_loss_fallback_applied"]
    parents = module._parents(values)
    times = list(result.states.index.get_level_values("timestamp").unique())

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("production fallback path invoked")

    for name in ("_record", "_frame", "_diagnostics", "_propose", "_base"):
        monkeypatch.setattr(module, name, fail)
    _validate_result(parents, times, result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("s12k_load_loss_output_resolved", False),
        ("s12k_advanced_load_loss_correction_resolved", True),
        ("s12k_load_loss_fallback_applied", False),
        ("s12k_load_loss_output_fidelity", "tampered"),
        ("s12k_selected_load_loss_w", 999.0),
        ("p_selected_load_loss_w", 999.0),
        ("coupled_selected_load_loss_w", 999.0),
        ("coupled_load_loss_adjustment_vs_s12k_selected_w", 999.0),
        ("load_loss_fallback_applied", False),
        ("terminal_solution_fidelity", "tampered"),
        ("transformer_terminal_output_resolved", False),
        ("transformer_advanced_operating_solution_state", "tampered"),
        ("advanced_fundamental_effective_series_resistance_ohm_per_phase", 1.0),
        ("p_advanced_load_loss_w", 1.0),
    ],
)
def test_fallback_validator_rejects_selected_output_and_fidelity_tampering(
    field: str, value: object
) -> None:
    values = _context(aggregate_evidence=True, advanced_core=False)
    result = calculate_topology_transformer_advanced_operating_solution(**values)
    parents = module._parents(values)
    times = list(result.states.index.get_level_values("timestamp").unique())
    changed = result.states.copy(deep=True)
    changed.loc[changed.index[0], field] = value
    with pytest.raises(ValueError, match="independent validation"):
        _validate_result(parents, times, replace(result, states=changed))


@pytest.mark.parametrize(
    "field,value",
    [
        ("advanced_fundamental_effective_series_resistance_ohm_per_phase", 999.0),
        ("harmonic_increment_accounting_resistance_ohm_per_phase", 999.0),
        ("p_no_load_active_loss_w", 999.0),
        ("p_harmonic_incremental_load_loss_w", 999.0),
        ("network_terminal_voltage_line_to_line_rms_v", 999.0),
        ("active_power_conservation_residual_w", 999.0),
        ("advanced_load_loss_ownership", "additive"),
        ("fixed_point_converged", False),
        ("s12k_load_loss_output_resolved", False),
        ("s12k_load_loss_fallback_applied", True),
        ("s12k_selected_load_loss_w", 999.0),
        ("p_selected_load_loss_w", 999.0),
        ("terminal_solution_fidelity", "tampered"),
        ("transformer_terminal_output_resolved", False),
        ("transformer_advanced_operating_solution_state", "tampered"),
        ("transformer_advanced_operating_solution_contract", "tampered"),
    ],
)
def test_independent_validator_rejects_representative_result_tampering(
    field: str, value: object
) -> None:
    global _TAMPER_BUNDLE
    if _TAMPER_BUNDLE is None:
        values = _context(advanced_core=True, ratios={1: 1.0, 5: 0.1})
        result = calculate_topology_transformer_advanced_operating_solution(**values)
        parents = module._parents(values)
        times = list(result.states.index.get_level_values("timestamp").unique())
        _TAMPER_BUNDLE = result, parents, times
    result, parents, times = _TAMPER_BUNDLE
    changed = result.states.copy(deep=True)
    changed.loc[changed.index[0], field] = value
    tampered = replace(result, states=changed)
    with pytest.raises(ValueError, match="independent validation"):
        _validate_result(parents, times, tampered)


def test_source_has_no_production_validator_alias_or_s12d_dependency() -> None:
    source = inspect.getsource(module)
    assert "_validator_record = _record" not in source
    assert "transformer_operating_loss" not in source
    schema_source = source.split("_COLUMNS =", 1)[1].split("F = TypeVar", 1)[0]
    assert "tuple(_BOOL)" not in schema_source
    assert "tuple(_FLOAT)" not in schema_source
    assert "tuple(_INT)" not in schema_source


def test_public_schema_has_explicit_unique_contract_order() -> None:
    result = _run()
    columns = tuple(result.states.columns)
    assert columns == module._COLUMNS
    assert len(module._COLUMNS) == len(set(module._COLUMNS))
    assert columns.index("transformer_energised") < columns.index("collection_p_w")
    assert columns.index("series_reference_side") < columns.index(
        "advanced_fundamental_effective_series_resistance_ohm_per_phase"
    )
    assert columns.index("fixed_point_iterations") < columns.index(
        "coupled_core_voltage_ratio_to_factory_reference"
    )
    assert columns.index("transformer_advanced_operating_solution_state") < columns.index(
        "transformer_advanced_operating_solution_contract"
    )


@pytest.fixture(scope="module")
def winding_case() -> Callable[[str], tuple[dict[str, Any], Any]]:
    """Cache canonical end-to-end cases, keeping tamper tests detached from parents."""
    cache: dict[str, tuple[dict[str, Any], Any]] = {}

    def build(name: str) -> tuple[dict[str, Any], Any]:
        if name not in cache:
            side, core_mode, loss_mode = name.split(":")
            options: dict[str, Any] = {
                "side": side,
                "q": 30.0,
                "advanced_core": core_mode == "advanced",
                "material": "mixed_or_other_explicit",
                "winding_materials": ("copper", "aluminium"),
                "winding_temperatures": (95.0, 85.0),
                "winding_temperature": None,
                "winding_allocations": (1200.0, 1800.0, 200.0, 300.0),
                "other_stray_w": 0.0,
                "rated_load_w": 3500.0,
                "ratios": {1: 1.0, 5: 0.2, 7: 0.1},
            }
            if loss_mode == "fundamental":
                options["ratios"] = {1: 1.0}
            elif loss_mode in {"aggregate_osl", "missing_osl"}:
                options.update(other_stray_w=1500.0, rated_load_w=5000.0)
                if loss_mode == "aggregate_osl":
                    options.update(
                        winding_temperature=88.0,
                        custom_constant=TransformerWindingResistanceTemperatureConstantAuthority(
                            "tx-1",
                            "mixed_or_other_explicit",
                            230.0,
                            "linear_winding_resistance_temperature_constant_c",
                            "explicit aggregate structural proxy",
                            "high",
                        ),
                    )
            elif loss_mode in {"copper", "aluminium"}:
                options.update(
                    material=loss_mode,
                    winding_materials=(loss_mode, loss_mode),
                    winding_temperature=88.0,
                    other_stray_w=1500.0,
                    rated_load_w=5000.0,
                    custom_constant=TransformerWindingResistanceTemperatureConstantAuthority(
                        "tx-1",
                        cast(Any, loss_mode),
                        240.0,
                        "linear_winding_resistance_temperature_constant_c",
                        "homogeneous winding certificate",
                        "high",
                    ),
                )
            # A module cache avoids replaying the expensive chain for each field mutation.
            with pytest.MonkeyPatch.context() as patch:
                database = support.conversion_support._database
                patch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
                patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)
                values = _context(**options)
                result = calculate_topology_transformer_advanced_operating_solution(**values)
            cache[name] = values, result
        return cache[name]

    return build


def _coefficient_closes(actual: float, expected: float) -> None:
    # Match S12M's residual-to-zero test; no relative relaxation for large losses.
    assert math.isclose(
        actual - expected,
        0.0,
        rel_tol=module._CLOSURE_REL_TOL,
        abs_tol=module._CLOSURE_ABS_TOL_W,
    )


def _assert_winding_terminal_closure(values: dict[str, Any], result: Any) -> None:
    k = values["transformer_corrected_load_loss"].states.iloc[0]
    g = values["transformer_operating_solution"].transformer_operating_states.iloc[0]
    core = values["transformer_core_no_load_loss"].states.iloc[0]
    row = result.states.iloc[0]
    assert k["temperature_correction_basis"] == "winding_resolved"
    assert k["load_loss_output_fidelity"] == "advanced_harmonic_and_temperature_corrected"
    assert row["transformer_advanced_operating_solution_state"] == (
        "resolved_coupled_advanced_transformer_terminal_solution"
    )
    assert row["terminal_solution_fidelity"] == "coupled_advanced_load_loss"
    assert row["s12k_load_loss_output_resolved"]
    assert row["s12k_advanced_load_loss_correction_resolved"]
    assert not row["s12k_load_loss_fallback_applied"]
    assert not row["load_loss_fallback_applied"]
    assert row["fixed_point_converged"]
    assert not row["coupled_thermal_iteration_applied"]
    assert not row["harmonic_voltage_drop_modeled"]

    side_i2r = math.fsum(
        k[f"{side}_winding_i2r_loss_reference_w"]
        * k[f"{side}_winding_i2r_temperature_correction_factor"]
        for side in ("collection", "network")
    )
    side_eddy = math.fsum(
        k[f"{side}_winding_eddy_current_loss_reference_w"]
        * k[f"{side}_winding_eddy_temperature_correction_factor"]
        for side in ("collection", "network")
    )
    for side in ("collection", "network"):
        assert k[f"{side}_winding_eddy_temperature_correction_factor"] == pytest.approx(
            1.0 / k[f"{side}_winding_i2r_temperature_correction_factor"],
            rel=module._CLOSURE_REL_TOL,
            abs=module._CLOSURE_ABS_TOL_W,
        )
    _coefficient_closes(
        k["i2r_loss_reference_w"] * k["i2r_temperature_correction_factor"], side_i2r
    )
    _coefficient_closes(
        k["winding_eddy_current_loss_reference_w"]
        * k["winding_eddy_temperature_correction_factor"],
        side_eddy,
    )
    aggregate_osl = (
        k["other_stray_loss_reference_w"] * k["other_stray_temperature_correction_factor"]
    )
    fundamental = math.fsum([side_i2r, side_eddy, aggregate_osl])
    s2 = k["sum_current_ratio_squared"]
    harmonic = math.fsum(
        [
            side_i2r * (s2 - 1.0),
            side_eddy * (s2 * k["winding_eddy_harmonic_loss_factor"] - 1.0),
            aggregate_osl * (s2 * k["other_stray_harmonic_loss_factor"] - 1.0),
        ]
    )
    rf = row["advanced_fundamental_effective_series_resistance_ohm_per_phase"]
    rh = row["harmonic_increment_accounting_resistance_ohm_per_phase"]
    irated = k["rated_reference_side_current_a"]
    i0 = k["fundamental_operating_current_a"]
    _coefficient_closes(3.0 * rf * irated**2, fundamental)
    _coefficient_closes(3.0 * rh * irated**2, harmonic)
    _coefficient_closes(3.0 * rf * i0**2, k["temperature_corrected_sinusoidal_load_loss_w"])
    _coefficient_closes(3.0 * rh * i0**2, k["harmonic_incremental_load_loss_w"])
    _coefficient_closes(3.0 * (rf + rh) * i0**2, k["selected_total_load_loss_w"])
    assert row["s12k_selected_load_loss_w"] == k["selected_total_load_loss_w"]

    vc = complex(row["collection_voltage_line_to_line_rms_v"] / math.sqrt(3.0), 0.0)
    ic = complex(row["collection_series_current_real_a"], row["collection_series_current_imag_a"])
    inn = complex(row["network_series_current_real_a"], row["network_series_current_imag_a"])
    transfer = row["network_to_collection_voltage_ratio"] * cmath.exp(
        1j * math.radians(row["network_side_phase_displacement_deg"])
    )
    assert inn == pytest.approx(
        ic / transfer.conjugate(), rel=module._CLOSURE_REL_TOL, abs=module._CLOSURE_ABS_TOL_W
    )
    assert ic == pytest.approx(
        (
            complex(
                row["collection_p_w"]
                - row["p_no_load_active_loss_w"]
                - row["p_harmonic_incremental_load_loss_w"],
                row["collection_q_var"],
            )
            / (3.0 * vc)
        ).conjugate(),
        rel=module._CLOSURE_REL_TOL,
        abs=module._CLOSURE_ABS_TOL_W,
    )
    side = row["series_reference_side"]
    assert side == g["series_equivalent_reference_side"]
    iref = abs(ic if side == "collection_side" else inn)
    assert (
        k["fundamental_operating_current_a"]
        == g[
            "collection_series_current_magnitude_a"
            if side == "collection_side"
            else "network_series_current_magnitude_a"
        ]
    )
    _coefficient_closes(row["p_fundamental_series_active_loss_w"], 3.0 * rf * iref**2)
    harmonic_coupled = 3.0 * rh * iref**2
    _coefficient_closes(
        harmonic_coupled - row["p_harmonic_incremental_load_loss_w"],
        row["harmonic_fixed_point_residual_w"],
    )
    assert math.isclose(
        row["p_harmonic_incremental_load_loss_w"],
        harmonic_coupled,
        rel_tol=module.FIXED_POINT_RELATIVE_TOLERANCE,
        abs_tol=module.FIXED_POINT_ABSOLUTE_TOLERANCE_W,
    )
    _coefficient_closes(
        row["coupled_selected_load_loss_w"],
        row["p_fundamental_series_active_loss_w"] + row["p_harmonic_incremental_load_loss_w"],
    )
    assert row["p_selected_load_loss_w"] == row["coupled_selected_load_loss_w"]
    assert math.isclose(
        row["coupled_selected_load_loss_w"],
        3.0 * (rf + rh) * iref**2,
        rel_tol=module.FIXED_POINT_RELATIVE_TOLERANCE,
        abs_tol=module.FIXED_POINT_ABSOLUTE_TOLERANCE_W,
    )
    x = row["retained_series_reactance_ohm_per_phase"]
    assert x == g["effective_series_reactance_ohm_per_phase"]
    # Only R_f enters the positive-sequence voltage drop. R_h is an active sink.
    ec = vc - complex(rf, x) * ic if side == "collection_side" else vc
    en = transfer * ec
    vn = en if side == "collection_side" else en - complex(rf, x) * inn
    assert complex(
        row["network_terminal_phase_voltage_real_v"], row["network_terminal_phase_voltage_imag_v"]
    ) == pytest.approx(
        vn,
        rel=module._CLOSURE_REL_TOL,
        abs=module._CLOSURE_ABS_TOL_W,
    )
    assert row["internal_collection_excitation_voltage_line_to_line_rms_v"] == pytest.approx(
        math.sqrt(3.0) * abs(ec),
        rel=module._CLOSURE_REL_TOL,
        abs=module._CLOSURE_ABS_TOL_W,
    )
    assert row["internal_network_excitation_voltage_line_to_line_rms_v"] == pytest.approx(
        math.sqrt(3.0) * abs(en),
        rel=module._CLOSURE_REL_TOL,
        abs=module._CLOSURE_ABS_TOL_W,
    )
    sn = 3.0 * vn * inn.conjugate()
    assert abs(row["p_network_terminal_w"] - sn.real) <= module._CONSERVATION_ABS_TOL
    assert abs(row["q_network_terminal_var"] - sn.imag) <= module._CONSERVATION_ABS_TOL
    assert (
        abs(
            row["collection_p_w"]
            - row["p_network_terminal_w"]
            - row["p_no_load_active_loss_w"]
            - row["p_fundamental_series_active_loss_w"]
            - row["p_harmonic_incremental_load_loss_w"]
        )
        <= module._CONSERVATION_ABS_TOL
    )
    assert (
        abs(
            row["collection_q_var"]
            - row["q_network_terminal_var"]
            - row["q_fundamental_series_consumption_var"]
        )
        <= module._CONSERVATION_ABS_TOL
    )
    assert abs(row["active_power_conservation_residual_w"]) <= module._CONSERVATION_ABS_TOL
    assert abs(row["reactive_power_conservation_residual_var"]) <= module._CONSERVATION_ABS_TOL

    if core["advanced_core_loss_scaling_resolved"]:
        assert row["s12l_core_loss_re_evaluated_in_coupled_iteration"]
        if side == "collection_side":
            assert row["coupled_no_load_adjustment_vs_s12l_w"] != pytest.approx(0.0, abs=1e-10)
        core_voltage = math.sqrt(3.0) * abs(
            ec if core["no_load_test_reference_side"] == "collection_side" else en
        )
        frequency_ratio = core["operating_frequency_hz"] / core["no_load_test_frequency_hz"]
        flux_ratio = (
            core_voltage
            / core["factory_reference_core_excitation_voltage_ll_rms_v"]
            / frequency_ratio
        )
        multiplier = frequency_ratio ** core["steinmetz_frequency_exponent_alpha"] * (
            flux_ratio ** core["steinmetz_flux_density_exponent_beta"]
        )
        target = (
            core["scalable_core_loss_reference_w"] * multiplier
            + core["non_scaling_no_load_loss_reference_residual_w"]
        )
        assert math.isclose(
            row["p_no_load_active_loss_w"],
            target,
            rel_tol=module.FIXED_POINT_RELATIVE_TOLERANCE,
            abs_tol=module.FIXED_POINT_ABSOLUTE_TOLERANCE_W,
        )
        _coefficient_closes(
            target - row["p_no_load_active_loss_w"], row["no_load_fixed_point_residual_w"]
        )
        assert row["coupled_core_loss_scaling_multiplier"] == pytest.approx(
            multiplier,
            rel=module._CLOSURE_REL_TOL,
            abs=module._CLOSURE_ABS_TOL_W,
        )
    else:
        assert not row["s12l_core_loss_re_evaluated_in_coupled_iteration"]
        assert row["p_no_load_active_loss_w"] == core["corrected_no_load_loss_w"]


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
@pytest.mark.parametrize("core_mode", ["factory", "advanced"])
@pytest.mark.parametrize("loss_mode", ["fundamental", "harmonic"])
def test_final_winding_resolved_chain_closes_at_reference_and_coupled_currents(
    winding_case: Callable[[str], tuple[dict[str, Any], Any]],
    side: str,
    core_mode: str,
    loss_mode: str,
) -> None:
    values, result = winding_case(f"{side}:{core_mode}:{loss_mode}")
    _assert_winding_terminal_closure(values, result)
    k = values["transformer_corrected_load_loss"].states.iloc[0]
    row = result.states.iloc[0]
    if loss_mode == "harmonic":
        assert k["harmonic_incremental_load_loss_w"] > 0.0
        assert row["harmonic_increment_accounting_resistance_ohm_per_phase"] > 0.0
        assert row["p_harmonic_incremental_load_loss_w"] > 0.0
        coupled_current = row[f"{side.removesuffix('_side')}_series_current_magnitude_a"]
        assert not math.isclose(coupled_current, k["fundamental_operating_current_a"], rel_tol=1e-9)
        assert not math.isclose(
            row["coupled_selected_load_loss_w"], k["selected_total_load_loss_w"], rel_tol=1e-9
        )
    else:
        assert row["harmonic_increment_accounting_resistance_ohm_per_phase"] == 0.0
        assert row["p_harmonic_incremental_load_loss_w"] == 0.0


def test_final_winding_resolved_aggregate_osl_proxy(
    winding_case: Callable[[str], tuple[dict[str, Any], Any]],
) -> None:
    values, result = winding_case("collection_side:advanced:aggregate_osl")
    k = values["transformer_corrected_load_loss"].states.iloc[0]
    assert k["other_stray_temperature_basis_mode"] == "explicit_aggregate_mixed_structural_proxy"
    for side, constant, temperature in [("collection", 234.5, 95.0), ("network", 225.0, 85.0)]:
        assert k[f"{side}_winding_resistance_temperature_constant_c"] == constant
        assert k[f"{side}_winding_i2r_temperature_correction_factor"] == pytest.approx(
            (temperature + constant) / (75.0 + constant)
        )
    assert k["other_stray_temperature_correction_factor"] == pytest.approx(
        (75.0 + 230.0) / (88.0 + 230.0)
    )
    _assert_winding_terminal_closure(values, result)


@pytest.mark.parametrize("material", ["copper", "aluminium"])
def test_final_winding_resolved_homogeneous_custom_constant(
    winding_case: Callable[[str], tuple[dict[str, Any], Any]],
    material: str,
) -> None:
    values, result = winding_case(f"collection_side:advanced:{material}")
    k = values["transformer_corrected_load_loss"].states.iloc[0]
    for side, temperature in [("collection", 95.0), ("network", 85.0)]:
        assert k[f"{side}_winding_temperature_constant_source_mode"] == "explicit_authority"
        assert k[f"{side}_winding_resistance_temperature_constant_c"] == 240.0
        assert k[f"{side}_winding_i2r_temperature_correction_factor"] == pytest.approx(
            (temperature + 240.0) / (75.0 + 240.0)
        )
    assert k["other_stray_temperature_basis_mode"] == "legacy_explicit_constant"
    _assert_winding_terminal_closure(values, result)


@pytest.mark.parametrize("core_mode", ["factory", "advanced"])
def test_final_winding_resolved_missing_osl_proxy_preserves_s12g_fallback(
    winding_case: Callable[[str], tuple[dict[str, Any], Any]],
    core_mode: str,
) -> None:
    values, result = winding_case(f"collection_side:{core_mode}:missing_osl")
    k = values["transformer_corrected_load_loss"].states.iloc[0]
    g = values["transformer_operating_solution"].transformer_operating_states.iloc[0]
    row = result.states.iloc[0]
    assert k["s12h_winding_resolved_advanced_correction_basis_resolved"]
    assert k["s12j_winding_resolved_temperature_basis_resolved"]
    assert (
        k["transformer_corrected_load_loss_state"]
        == "unresolved_missing_other_stray_temperature_proxy_basis"
    )
    assert k["transformer_load_loss_output_resolved"]
    assert not k["advanced_load_loss_correction_resolved"]
    assert not k["winding_resolved_temperature_correction_applied"]
    assert k["selected_total_load_loss_w"] == g["p_series_active_loss_w"]
    assert math.isnan(k["harmonic_and_temperature_corrected_load_loss_w"])
    assert (
        row["transformer_advanced_operating_solution_state"]
        == "resolved_coupled_transformer_terminal_solution_with_s12g_load_loss_fallback"
    )
    assert row["terminal_solution_fidelity"] == "coupled_s12g_load_loss_fallback"
    assert row["s12k_load_loss_output_resolved"]
    assert not row["s12k_advanced_load_loss_correction_resolved"]
    assert row["s12k_load_loss_fallback_applied"]
    assert row["load_loss_fallback_applied"]
    assert row["s12k_selected_load_loss_w"] == g["p_series_active_loss_w"]
    assert row["harmonic_increment_accounting_resistance_ohm_per_phase"] == 0.0
    assert row["p_harmonic_incremental_load_loss_w"] == 0.0
    for field in (
        "advanced_fundamental_effective_series_resistance_ohm_per_phase",
        "advanced_fundamental_series_resistance_delta_ohm_per_phase",
        "p_advanced_load_loss_w",
        "coupled_advanced_load_loss_w",
        "coupled_load_loss_adjustment_vs_s12k_w",
    ):
        assert math.isnan(row[field])
    current = complex(
        row["collection_series_current_real_a"], row["collection_series_current_imag_a"]
    )
    resistance = g["effective_series_resistance_ohm_per_phase"]
    _coefficient_closes(
        row["p_fundamental_series_active_loss_w"], 3.0 * resistance * abs(current) ** 2
    )
    assert row["s12g_reference_effective_series_resistance_ohm_per_phase"] == resistance
    vc = complex(row["collection_voltage_line_to_line_rms_v"] / math.sqrt(3.0), 0.0)
    transfer = row["network_to_collection_voltage_ratio"] * cmath.exp(
        1j * math.radians(row["network_side_phase_displacement_deg"])
    )
    expected_vn = transfer * (
        vc - complex(resistance, g["effective_series_reactance_ohm_per_phase"]) * current
    )
    assert complex(
        row["network_terminal_phase_voltage_real_v"], row["network_terminal_phase_voltage_imag_v"]
    ) == pytest.approx(expected_vn, rel=module._CLOSURE_REL_TOL, abs=module._CLOSURE_ABS_TOL_W)
    assert (
        row["retained_series_reactance_ohm_per_phase"]
        == g["effective_series_reactance_ohm_per_phase"]
    )
    _coefficient_closes(
        row["coupled_selected_load_loss_w"], row["p_fundamental_series_active_loss_w"]
    )
    core = values["transformer_core_no_load_loss"].states.iloc[0]
    assert (
        row["s12l_advanced_core_loss_scaling_resolved"]
        == core["advanced_core_loss_scaling_resolved"]
    )
    assert row["s12l_core_loss_re_evaluated_in_coupled_iteration"] == (core_mode == "advanced")
    assert abs(row["active_power_conservation_residual_w"]) <= module._CONSERVATION_ABS_TOL
    assert abs(row["reactive_power_conservation_residual_var"]) <= module._CONSERVATION_ABS_TOL


@pytest.mark.parametrize(
    "field",
    [
        "collection_winding_i2r_temperature_correction_factor",
        "network_winding_eddy_temperature_correction_factor",
        "other_stray_temperature_basis_mode",
        "temperature_correction_basis",
        "selected_total_load_loss_w",
    ],
)
def test_final_winding_resolved_s12k_field_tampering_fails_parent_replay(
    winding_case: Callable[[str], tuple[dict[str, Any], Any]],
    field: str,
) -> None:
    values, _ = winding_case("collection_side:advanced:harmonic")
    parent = values["transformer_corrected_load_loss"]
    frame = parent.states.copy(deep=True)
    original = frame.iloc[0][field]
    frame.loc[frame.index[0], field] = (
        "tampered" if isinstance(original, str) else float(original) + 1.0
    )
    tampered = dict(values, transformer_corrected_load_loss=replace(parent, states=frame))
    with pytest.raises(ValueError, match="S12K.*canonical replay"):
        calculate_topology_transformer_advanced_operating_solution(**tampered)


def test_final_winding_resolved_validator_is_independent(
    winding_case: Callable[[str], tuple[dict[str, Any], Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values, result = winding_case("collection_side:advanced:harmonic")
    _assert_winding_terminal_closure(values, result)
    parents = tuple(
        values[name]
        for name in (
            "transformer_operating_solution",
            "transformer_corrected_load_loss",
            "transformer_core_no_load_loss",
        )
    )
    times = list(result.states.index.get_level_values("timestamp").unique())

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("production winding-resolved S12M helper invoked")

    for name in ("_record", "_frame", "_diagnostics", "_propose", "_base"):
        monkeypatch.setattr(module, name, fail)
    _validate_result(parents, times, result)


def test_final_s12m_boundary_uses_aggregate_s12k_contract_only() -> None:
    source = inspect.getsource(module)
    for forbidden in (
        "transformer_loss_component_authority",
        "transformer_harmonic_current_authority",
        "transformer_thermal_state_authority",
        "collection_winding",
        "network_winding",
    ):
        assert forbidden not in source
