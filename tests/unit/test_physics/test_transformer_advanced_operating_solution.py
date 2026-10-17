"""Focused physics and contract tests for S12M."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import replace
from typing import Any

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
    winding_temperature: float = 75.0,
    ratios: dict[int, float] | None = None,
    no_load_w: float = 600.0,
    advanced_core: bool = False,
    energised: bool | None = True,
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
        )
    finally:
        ksupport._inputs = original_inputs  # type: ignore[attr-defined]
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


def test_derived_nonfinite_state_is_controlled_and_publishes_no_infinity() -> None:
    values = _context()
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
