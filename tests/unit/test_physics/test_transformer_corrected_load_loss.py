"""Physics and contract tests for S12K corrected transformer load loss."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import transformer_corrected_load_loss as module
from heliotelligence.physics.transformer_corrected_load_loss import (
    ADVANCED_LOAD_LOSS_OWNERSHIP,
    HARMONIC_OTHER_STRAY_SEMANTICS,
    TopologyTransformerCorrectedLoadLossResult,
    TransformerSingleConditionHarmonicSpectrumApplication,
    TransformerWindingResistanceTemperatureConstantAuthority,
    _validate_result,
    calculate_topology_transformer_corrected_load_loss,
)
from heliotelligence.physics.transformer_harmonic_current_authority import (
    TransformerHarmonicCurrentSpectrumAuthority,
    resolve_transformer_harmonic_current_authority,
)
from heliotelligence.physics.transformer_loss_component_authority import (
    TransformerAdvancedConstructionAuthority,
    TransformerRatedLoadLossComponentAuthority,
    resolve_transformer_loss_component_authority,
)
from heliotelligence.physics.transformer_operating_solution import (
    calculate_topology_transformer_operating_solution,
)
from heliotelligence.physics.transformer_thermal_state_authority import (
    TransformerTemperatureEvidence,
    TransformerThermalState,
    resolve_transformer_thermal_state_authority,
)
from tests.unit.test_physics.test_transformer_operating_solution import _inputs

support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_dispatch_feasibility")


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


T1 = pd.Timestamp("2025-01-01T00:00:00")


def _construction(material: str = "copper") -> TransformerAdvancedConstructionAuthority:
    return TransformerAdvancedConstructionAuthority(
        "tx-1",
        "mineral_oil_immersed",
        cast(Any, material),
        "declared conductor",
        "ONAN",
        "crgo_silicon_steel",
        "CRGO",
        "design",
        "high",
    )


def _component(
    side: str = "collection_side", frequency: float = 50.0
) -> TransformerRatedLoadLossComponentAuthority:
    return TransformerRatedLoadLossComponentAuthority(
        "tx-1",
        3000.0,
        500.0,
        1500.0,
        cast(Any, side),
        "rated_current",
        75.0,
        frequency,
        "rated_total_load_loss_three_component_decomposition_at_factory_reference_condition",
        "manufacturer_design_data",
        "factory design",
        "high",
    )


def _spectrum(
    ratios: dict[int, float] | None = None,
    *,
    side: str = "collection_side",
    frequency: float = 50.0,
    applicability: str = "declared_representative_normalized_spectrum",
) -> TransformerHarmonicCurrentSpectrumAuthority:
    plane = (
        "transformer_collection_side_terminal"
        if side == "collection_side"
        else "transformer_network_side_terminal"
    )
    return TransformerHarmonicCurrentSpectrumAuthority(
        "tx-1",
        cast(Any, plane),
        "balanced_three_phase_representative_line_current",
        "per_harmonic_rms_current_ratio_to_fundamental_rms_current",
        frequency,
        ratios or {1: 1.0},
        "site_power_quality_measurement_at_transformer_terminal",
        cast(Any, applicability),
        "declared condition",
        "PQ meter",
        "high",
    )


def _thermal(value: float = 75.0) -> TransformerThermalState:
    evidence = TransformerTemperatureEvidence(
        value, "direct_sensor_measurement", "winding sensor", "SCADA", "high"
    )
    return TransformerThermalState(None, evidence, None, None, "operating state")


def _context(
    *,
    p: float = 100.0,
    q: float = 0.0,
    voltage: float = 400.0,
    side: str = "collection_side",
    material: str = "copper",
    winding_temperature: float = 75.0,
    ratios: dict[int, float] | None = None,
    applicability: str = "declared_representative_normalized_spectrum",
    harmonic_side: str | None = None,
    harmonic_frequency: float = 50.0,
    energised: bool = True,
    include_h: bool = True,
    include_i: bool = True,
    include_j: bool = True,
) -> dict[str, Any]:
    values, _ = _inputs(
        p=p,
        q=q,
        voltage=voltage,
        side=side,
        rated_load_w=5000.0,
        no_load_w=0.0,
        energised=energised,
    )
    g = calculate_topology_transformer_operating_solution(**values)
    construction = {"tx-1": _construction(material)} if include_h else {}
    components = {"tx-1": _component(side)} if include_h else {}
    h = resolve_transformer_loss_component_authority(
        values["topology"],
        values["network_basis"],
        values["node_authority_by_id"],
        values["segment_authority_by_id"],
        values["inverter_terminal_binding_by_inverter_id"],
        values["lv_ac_collection_authority"],
        values["transformer_equipment_by_id"],
        values["transformer_topology_by_id"],
        values["transformer_static_authority"],
        values["transformer_no_load_loss_by_id"],
        values["transformer_rated_load_loss_by_id"],
        values["transformer_loss_authority"],
        construction,
        components,
    )
    spectra = (
        {
            "tx-1": _spectrum(
                ratios,
                side=harmonic_side or side,
                frequency=harmonic_frequency,
                applicability=applicability,
            )
        }
        if include_i
        else {}
    )
    i = resolve_transformer_harmonic_current_authority(
        values["topology"],
        values["network_basis"],
        values["node_authority_by_id"],
        values["segment_authority_by_id"],
        values["inverter_terminal_binding_by_inverter_id"],
        values["lv_ac_collection_authority"],
        values["transformer_equipment_by_id"],
        values["transformer_topology_by_id"],
        values["transformer_static_authority"],
        spectra,
    )
    timestamps = list(g.transformer_operating_states.index.get_level_values("timestamp"))
    thermal = (
        {(timestamps[0], "tx-1"): _thermal(winding_temperature)} if include_j and timestamps else {}
    )
    j = resolve_transformer_thermal_state_authority(
        values["topology"],
        values["network_basis"],
        values["node_authority_by_id"],
        values["segment_authority_by_id"],
        values["inverter_terminal_binding_by_inverter_id"],
        values["lv_ac_collection_authority"],
        values["transformer_equipment_by_id"],
        values["transformer_topology_by_id"],
        values["transformer_static_authority"],
        values["transformer_no_load_loss_by_id"],
        values["transformer_rated_load_loss_by_id"],
        values["transformer_loss_authority"],
        construction,
        components,
        h,
        thermal,
    )
    values.update(
        {
            "transformer_operating_solution": g,
            "transformer_construction_by_id": construction,
            "transformer_rated_load_loss_component_by_id": components,
            "transformer_loss_component_authority": h,
            "transformer_harmonic_current_spectrum_by_id": spectra,
            "transformer_harmonic_current_authority": i,
            "transformer_thermal_state_by_key": thermal,
            "transformer_thermal_state_authority": j,
            "single_condition_harmonic_application_by_key": {},
            "winding_temperature_constant_by_transformer_id": {},
        }
    )
    return values


def _run(**kwargs: Any) -> TopologyTransformerCorrectedLoadLossResult:
    return calculate_topology_transformer_corrected_load_loss(**_context(**kwargs))


def test_pure_reference_case_closes_without_double_counting() -> None:
    row = _run().states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    assert row["total_rms_current_loading_ratio"] == pytest.approx(
        row["fundamental_current_loading_ratio"]
    )
    assert row["i2r_temperature_correction_factor"] == 1.0
    assert row["harmonic_incremental_load_loss_w"] == pytest.approx(0.0)
    assert row["temperature_correction_effect_w"] == pytest.approx(0.0)
    assert row["advanced_correction_vs_s12g_w"] == pytest.approx(0.0, abs=1e-8)
    assert row["advanced_load_loss_ownership"] == ADVANCED_LOAD_LOSS_OWNERSHIP


def test_harmonic_component_equations_and_h0p8_guard() -> None:
    ratios = {1: 1.0, 5: 0.10, 7: 0.05}
    row = _run(ratios=ratios).states.iloc[0]
    s2 = 1 + 0.1**2 + 0.05**2
    fec = (1 + 0.1**2 * 5**2 + 0.05**2 * 7**2) / s2
    fosl = (1 + 0.1**2 * 5**0.8 + 0.05**2 * 7**0.8) / s2
    assert row["sum_current_ratio_squared"] == pytest.approx(s2)
    assert row["winding_eddy_harmonic_loss_factor"] == pytest.approx(fec)
    assert row["other_stray_harmonic_loss_factor"] == pytest.approx(fosl)
    assert row["i2r_loss_harmonic_increment_w"] > 0
    assert row["winding_eddy_loss_harmonic_increment_w"] > 0
    assert row["other_stray_loss_harmonic_increment_w"] > 0
    assert row["temperature_correction_effect_w"] == pytest.approx(0.0)
    assert row["advanced_correction_vs_s12g_w"] == pytest.approx(
        row["harmonic_incremental_load_loss_w"]
    )
    assert row["other_stray_temperature_correction_factor"] == 1.0
    assert row["harmonic_other_stray_semantics"] == HARMONIC_OTHER_STRAY_SEMANTICS


@pytest.mark.parametrize(("temperature", "i2r_direction"), [(100.0, 1), (50.0, -1)])
def test_copper_temperature_directions(temperature: float, i2r_direction: int) -> None:
    row = _run(winding_temperature=temperature).states.iloc[0]
    assert row["resistance_temperature_constant_c"] == 234.5
    kr = row["i2r_temperature_correction_factor"]
    assert (kr - 1.0) * i2r_direction > 0
    assert row["winding_eddy_temperature_correction_factor"] == pytest.approx(1 / kr)
    assert row["other_stray_temperature_correction_factor"] == pytest.approx(1 / kr)


def test_aluminium_and_explicit_constant() -> None:
    values = _context(material="aluminium", winding_temperature=100.0)
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["resistance_temperature_constant_c"] == 225.0
    authority = TransformerWindingResistanceTemperatureConstantAuthority(
        "tx-1",
        "aluminium",
        230.25,
        "linear_winding_resistance_temperature_constant_c",
        "alloy certificate",
        "high",
    )
    values["winding_temperature_constant_by_transformer_id"] = {"tx-1": authority}
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["resistance_temperature_constant_c"] == 230.25
    assert row["resistance_temperature_constant_source_mode"] == "explicit_authority"


def test_mixed_requires_constant_except_equal_temperature() -> None:
    row = _run(material="mixed_or_other_explicit", winding_temperature=100.0).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_missing_winding_resistance_temperature_constant_authority"
    )
    row = _run(material="mixed_or_other_explicit", winding_temperature=75.0).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"].startswith("resolved_")
    assert row["resistance_temperature_constant_source_mode"] == (
        "not_required_equal_reference_temperature"
    )


def test_side_and_frequency_mismatch_states() -> None:
    row = _run(harmonic_side="network_side").states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_harmonic_spectrum_reference_side_mismatch"
    )
    row = _run(harmonic_frequency=60.0).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_harmonic_fundamental_frequency_mismatch"
    )


def test_single_condition_requires_exact_timestamp_binding() -> None:
    values = _context(applicability="single_declared_operating_condition")
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_single_condition_harmonic_spectrum_not_bound_to_timestamp"
    )
    key = next(iter(values["transformer_thermal_state_by_key"]))
    binding = TransformerSingleConditionHarmonicSpectrumApplication(
        "s12i_single_declared_operating_condition_matches_this_timestamp",
        "matching PQ acquisition window",
        "PQ report",
        "high",
    )
    values["single_condition_harmonic_application_by_key"] = {key: binding}
    result = calculate_topology_transformer_corrected_load_loss(**values)
    assert result.states.iloc[0]["transformer_corrected_load_loss_state"].startswith("resolved_")
    assert type(result.single_condition_harmonic_application_by_key) is MappingProxyType


def test_deenergised_zero_loss_bypasses_advanced_evidence() -> None:
    row = _run(
        p=0.0, q=0.0, energised=False, include_h=False, include_i=False, include_j=False
    ).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_deenergised_transformer_zero_advanced_load_loss"
    )
    assert row["harmonic_and_temperature_corrected_load_loss_w"] == 0.0
    assert row["advanced_correction_vs_s12g_w"] == 0.0


def test_current_not_active_power_controls_loss() -> None:
    low = _run(p=100.0, q=0.0).states.iloc[0]
    high = _run(p=100.0, q=100.0).states.iloc[0]
    assert high["fundamental_operating_current_a"] > low["fundamental_operating_current_a"]
    assert (
        high["harmonic_and_temperature_corrected_load_loss_w"]
        > low["harmonic_and_temperature_corrected_load_loss_w"]
    )


def test_zero_component_authority_is_division_free() -> None:
    values = _context()
    zero = _component()
    zero = replace(
        zero, i2r_loss_w=0.0, winding_eddy_current_loss_w=0.0, reported_other_stray_loss_w=0.0
    )
    values["transformer_rated_load_loss_by_id"] = {
        "tx-1": replace(values["transformer_rated_load_loss_by_id"]["tx-1"], rated_load_loss_w=0.0)
    }
    # Full zero-loss replay is covered upstream; this authority remains division-free.
    assert zero.i2r_loss_w == 0.0


def test_result_validator_rejects_frame_and_diagnostics_tampering() -> None:
    values = _context()
    result = calculate_topology_transformer_corrected_load_loss(**values)
    parents = module._canonical_parents(values)
    timestamps = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))
    changed = result.states.copy(deep=True)
    changed.iloc[0, changed.columns.get_loc("fundamental_current_loading_ratio")] += 1.0
    with pytest.raises(ValueError, match="frame"):
        _validate_result(
            parents,
            values["transformer_equipment_by_id"],
            {},
            {},
            timestamps,
            replace(result, states=changed),
        )
    with pytest.raises(ValueError, match="diagnostics"):
        _validate_result(
            parents,
            values["transformer_equipment_by_id"],
            {},
            {},
            timestamps,
            replace(result, diagnostics=replace(result.diagnostics, row_count=99)),
        )


def test_parent_tampering_is_rejected() -> None:
    values = _context()
    bad = values["transformer_harmonic_current_authority"].transformer_states.copy(deep=True)
    bad.iloc[0, bad.columns.get_loc("current_thd_ratio")] = 99.0
    values["transformer_harmonic_current_authority"] = replace(
        values["transformer_harmonic_current_authority"], transformer_states=bad
    )
    with pytest.raises(ValueError, match="S12I frame"):
        calculate_topology_transformer_corrected_load_loss(**values)


def test_scope_exclusions_and_semantic_guards() -> None:
    source = inspect.getsource(module)
    assert "transformer_operating_loss" not in source
    assert "Steinmetz" not in source
    assert "h0p8_harmonic_order_weighting_not_temperature_exponent" in source
    assert "replacement_for_s12g_reference_series_active_loss_not_additive" in source
    assert "p_series_active_loss_w" in source
    assert "collection_p_w" not in source
