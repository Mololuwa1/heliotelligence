"""Physics and contract tests for S12K corrected transformer load loss."""

from __future__ import annotations

import importlib
import inspect
import math
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
    TransformerRatedLoadLossAggregateStrayAuthority,
    TransformerRatedLoadLossComponentAuthority,
    TransformerWindingResolvedLoadLossAuthority,
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


def _construction(
    material: str = "copper", *, winding_materials: tuple[str, str] | None = None
) -> TransformerAdvancedConstructionAuthority:
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
        winding_materials[0] if winding_materials else None,  # type: ignore[arg-type]
        "collection winding" if winding_materials else None,
        winding_materials[1] if winding_materials else None,  # type: ignore[arg-type]
        "network winding" if winding_materials else None,
    )


def _component(
    side: str = "collection_side", frequency: float = 50.0, other_stray_w: float = 1500.0
) -> TransformerRatedLoadLossComponentAuthority:
    return TransformerRatedLoadLossComponentAuthority(
        "tx-1",
        3000.0,
        500.0,
        other_stray_w,
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


def _thermal(
    value: float | None = 75.0, *, winding_values: tuple[float, float] | None = None
) -> TransformerThermalState:
    evidence = (
        TransformerTemperatureEvidence(
            value, "direct_sensor_measurement", "winding sensor", "SCADA", "high"
        )
        if value is not None
        else None
    )
    collection = (
        TransformerTemperatureEvidence(
            winding_values[0], "direct_sensor_measurement", "collection sensor", "SCADA-C", "high"
        )
        if winding_values
        else None
    )
    network = (
        TransformerTemperatureEvidence(
            winding_values[1], "direct_sensor_measurement", "network sensor", "SCADA-N", "high"
        )
        if winding_values
        else None
    )
    return TransformerThermalState(
        None, evidence, None, None, "operating state", collection, network
    )


def _context(
    *,
    p: float = 100.0,
    q: float = 0.0,
    voltage: float = 400.0,
    side: str = "collection_side",
    material: str = "copper",
    winding_temperature: float | None = 75.0,
    ratios: dict[int, float] | None = None,
    applicability: str = "declared_representative_normalized_spectrum",
    harmonic_side: str | None = None,
    harmonic_frequency: float = 50.0,
    energised: bool | None = True,
    include_h: bool = True,
    include_i: bool = True,
    include_j: bool = True,
    rated_load_w: float = 5000.0,
    extra_thermal_timestamp: pd.Timestamp | None = None,
    aggregate_evidence: bool = False,
    winding_materials: tuple[str, str] | None = None,
    winding_temperatures: tuple[float, float] | None = None,
    other_stray_w: float = 1500.0,
    winding_allocations: tuple[float, float, float, float] = (1500.0, 1500.0, 250.0, 250.0),
) -> dict[str, Any]:
    values, _ = _inputs(
        p=p,
        q=q,
        voltage=voltage,
        side=side,
        rated_load_w=rated_load_w,
        no_load_w=0.0,
        energised=energised,
    )
    g = calculate_topology_transformer_operating_solution(**values)
    construction = (
        {"tx-1": _construction(material, winding_materials=winding_materials)} if include_h else {}
    )
    explicit_component = (
        replace(
            _component(side),
            i2r_loss_w=0.0,
            winding_eddy_current_loss_w=0.0,
            reported_other_stray_loss_w=0.0,
        )
        if rated_load_w == 0.0
        else _component(side, other_stray_w=other_stray_w)
    )
    if winding_materials is not None:
        explicit_component = replace(
            explicit_component,
            winding_resolved_load_loss_authority=TransformerWindingResolvedLoadLossAuthority(
                "tx-1",
                *winding_allocations,
                75.0,
                50.0,
                "explicit_collection_and_network_winding_i2r_and_eddy_factory_loss_allocation",
                "factory design",
                "high",
            ),
        )
    component = (
        TransformerRatedLoadLossAggregateStrayAuthority(
            "tx-1",
            3_500.0,
            1_500.0,
            cast(Any, side),
            "rated_current",
            75.0,
            50.0,
            "rated_total_load_loss_i2r_and_aggregate_stray_at_factory_reference_condition",
            "factory_test_report",
            "aggregate factory evidence",
            "high",
        )
        if aggregate_evidence
        else explicit_component
    )
    components = {"tx-1": component} if include_h else {}
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
    thermal: dict[tuple[pd.Timestamp, str], TransformerThermalState] = (
        {
            (timestamps[0], "tx-1"): _thermal(
                winding_temperature, winding_values=winding_temperatures
            )
        }
        if include_j and timestamps
        else {}
    )
    if include_j and extra_thermal_timestamp is not None:
        thermal[(extra_thermal_timestamp, "tx-1")] = _thermal(winding_temperature)
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
    assert cast(str, row["transformer_corrected_load_loss_state"]).startswith("resolved_")
    assert row["resistance_temperature_constant_source_mode"] == (
        "not_required_equal_reference_temperature"
    )


@pytest.mark.parametrize("material", ["copper", "aluminium"])
def test_explicit_same_material_windings_match_legacy_result(material: str) -> None:
    legacy = _run(material=material, winding_temperature=100.0).states.iloc[0]
    explicit = _run(
        material=material,
        winding_materials=(material, material),
        winding_temperature=100.0,
    ).states.iloc[0]
    assert (
        explicit["harmonic_and_temperature_corrected_load_loss_w"]
        == legacy["harmonic_and_temperature_corrected_load_loss_w"]
    )
    assert not explicit["heterogeneous_winding_conductor_construction"]


def test_heterogeneous_windings_require_future_temperature_correction_basis() -> None:
    row = _run(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=100.0,
    ).states.iloc[0]
    assert row["heterogeneous_winding_conductor_construction"]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_winding_resolved_temperature_correction_basis_required"
    )
    assert math.isnan(row["harmonic_and_temperature_corrected_load_loss_w"])


def test_winding_resolved_side_correction_requires_separate_other_stray_proxy() -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=100.0,
        winding_temperatures=(105.0, 92.0),
    )
    thermal = values["transformer_thermal_state_authority"].states.iloc[0]
    assert thermal["winding_resolved_temperature_basis_resolved"]
    result = calculate_topology_transformer_corrected_load_loss(**values)
    row = result.states.iloc[0]
    baseline = values["transformer_operating_solution"].transformer_operating_states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_missing_other_stray_temperature_proxy_basis"
    )
    assert row["temperature_correction_basis"] == "winding_resolved"
    assert not row["winding_resolved_temperature_correction_applied"]
    assert not row["other_stray_temperature_basis_resolved"]
    assert row["transformer_load_loss_output_resolved"]
    assert not row["advanced_load_loss_correction_resolved"]
    assert row["s12g_load_loss_fallback_applied"]
    assert row["load_loss_output_fidelity"] == "s12g_positive_sequence_series_loss_baseline"
    assert row["selected_total_load_loss_w"] == baseline["p_series_active_loss_w"]
    assert math.isnan(row["harmonic_and_temperature_corrected_load_loss_w"])


@pytest.mark.parametrize(
    ("materials", "temperatures", "expected_constants"),
    [
        (("copper", "aluminium"), (95.0, 85.0), (234.5, 225.0)),
        (("aluminium", "copper"), (95.0, 85.0), (225.0, 234.5)),
        (("copper", "copper"), (95.0, 85.0), (234.5, 234.5)),
        (("aluminium", "aluminium"), (95.0, 85.0), (225.0, 225.0)),
    ],
)
def test_winding_resolved_zero_osl_side_equations_and_effective_factors(
    materials: tuple[str, str],
    temperatures: tuple[float, float],
    expected_constants: tuple[float, float],
) -> None:
    values = _context(
        material=materials[0] if materials[0] == materials[1] else "mixed_or_other_explicit",
        winding_materials=materials,
        winding_temperature=None,
        winding_temperatures=temperatures,
        other_stray_w=0.0,
        rated_load_w=3500.0,
        winding_allocations=(1200.0, 1800.0, 200.0, 300.0),
    )
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    assert row["temperature_correction_basis"] == "winding_resolved"
    assert row["winding_resolved_temperature_correction_applied"]
    assert row["other_stray_temperature_basis_mode"] == "not_applicable_zero_other_stray"
    assert not row["other_stray_structural_temperature_proxy_applied"]
    kc = (temperatures[0] + expected_constants[0]) / (75.0 + expected_constants[0])
    kn = (temperatures[1] + expected_constants[1]) / (75.0 + expected_constants[1])
    assert row["collection_winding_i2r_temperature_correction_factor"] == pytest.approx(kc)
    assert row["network_winding_i2r_temperature_correction_factor"] == pytest.approx(kn)
    assert row["collection_winding_eddy_temperature_correction_factor"] == pytest.approx(1 / kc)
    assert row["network_winding_eddy_temperature_correction_factor"] == pytest.approx(1 / kn)
    effective_i2r = (1200.0 * kc + 1800.0 * kn) / 3000.0
    effective_eddy = (200.0 / kc + 300.0 / kn) / 500.0
    assert row["i2r_temperature_correction_factor"] == pytest.approx(effective_i2r)
    assert row["winding_eddy_temperature_correction_factor"] == pytest.approx(effective_eddy)
    assert row["i2r_loss_fundamental_temperature_corrected_w"] == pytest.approx(
        row["collection_winding_i2r_loss_fundamental_temperature_corrected_w"]
        + row["network_winding_i2r_loss_fundamental_temperature_corrected_w"]
    )
    assert row["winding_eddy_loss_fundamental_temperature_corrected_w"] == pytest.approx(
        row["collection_winding_eddy_loss_fundamental_temperature_corrected_w"]
        + row["network_winding_eddy_loss_fundamental_temperature_corrected_w"]
    )
    assert row["effective_winding_ohmic_resistance_temperature_corrected_ohm_per_phase"] == (
        pytest.approx(
            row["effective_winding_ohmic_resistance_reference_ohm_per_phase"] * effective_i2r
        )
    )
    assert (
        row["selected_total_load_loss_w"] == row["harmonic_and_temperature_corrected_load_loss_w"]
    )


@pytest.mark.parametrize("material", ["copper", "aluminium"])
@pytest.mark.parametrize("other_stray_w", [0.0, 1500.0])
def test_homogeneous_winding_custom_constant_precedes_standard_and_corrects_osl(
    material: str, other_stray_w: float
) -> None:
    custom_constant = 240.0
    values = _context(
        material=material,
        winding_materials=(material, material),
        winding_temperature=88.0,
        winding_temperatures=(95.0, 85.0),
        other_stray_w=other_stray_w,
        rated_load_w=3500.0 + other_stray_w,
        winding_allocations=(1200.0, 1800.0, 200.0, 300.0),
    )
    values["winding_temperature_constant_by_transformer_id"] = {
        "tx-1": TransformerWindingResistanceTemperatureConstantAuthority(
            "tx-1",
            cast(Any, material),
            custom_constant,
            "linear_winding_resistance_temperature_constant_c",
            "certificate",
            "high",
        )
    }
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["advanced_load_loss_correction_resolved"]
    assert row["winding_resolved_temperature_correction_applied"]
    assert row["resistance_temperature_constant_source_mode"] == "explicit_authority"
    factors = [
        (95.0 + custom_constant) / (75.0 + custom_constant),
        (85.0 + custom_constant) / (75.0 + custom_constant),
    ]
    standard = 234.5 if material == "copper" else 225.0
    for side, temperature, factor in zip(
        ("collection", "network"), (95.0, 85.0), factors, strict=True
    ):
        assert row[f"{side}_winding_temperature_constant_source_mode"] == "explicit_authority"
        assert row[f"{side}_winding_resistance_temperature_constant_c"] == custom_constant
        assert row[f"{side}_winding_i2r_temperature_correction_factor"] == pytest.approx(factor)
        assert row[f"{side}_winding_i2r_temperature_correction_factor"] != pytest.approx(
            (temperature + standard) / (75.0 + standard)
        )
        assert row[f"{side}_winding_eddy_temperature_correction_factor"] == pytest.approx(
            1 / factor
        )
    assert row["i2r_temperature_correction_factor"] == pytest.approx(
        (1200.0 * factors[0] + 1800.0 * factors[1]) / 3000.0
    )
    assert row["winding_eddy_temperature_correction_factor"] == pytest.approx(
        (200.0 / factors[0] + 300.0 / factors[1]) / 500.0
    )
    if other_stray_w:
        osl_factor = (75.0 + custom_constant) / (88.0 + custom_constant)
        assert row["other_stray_temperature_basis_mode"] == "legacy_explicit_constant"
        assert row["other_stray_temperature_correction_factor"] == pytest.approx(osl_factor)
        assert row["other_stray_loss_fundamental_temperature_corrected_w"] == pytest.approx(
            row["fundamental_current_loading_ratio"] ** 2 * other_stray_w * osl_factor
        )
    else:
        assert row["other_stray_temperature_basis_mode"] == "not_applicable_zero_other_stray"


@pytest.mark.parametrize(
    ("material", "custom_material"), [("copper", "aluminium"), ("aluminium", "copper")]
)
def test_homogeneous_winding_rejects_mismatched_custom_authority(
    material: str, custom_material: str
) -> None:
    values = _context(
        material=material,
        winding_materials=(material, material),
        winding_temperatures=(95.0, 85.0),
    )
    values["winding_temperature_constant_by_transformer_id"] = {
        "tx-1": TransformerWindingResistanceTemperatureConstantAuthority(
            "tx-1",
            cast(Any, custom_material),
            240.0,
            "linear_winding_resistance_temperature_constant_c",
            "certificate",
            "high",
        )
    }
    with pytest.raises(
        ValueError, match="temperature constant material does not match S12H construction"
    ):
        calculate_topology_transformer_corrected_load_loss(**values)


@pytest.mark.parametrize("use_custom", [False, True])
def test_homogeneous_reference_side_requires_no_custom_constant(use_custom: bool) -> None:
    values = _context(
        material="copper",
        winding_materials=("copper", "copper"),
        winding_temperature=None,
        winding_temperatures=(75.0, 90.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
    )
    if use_custom:
        values["winding_temperature_constant_by_transformer_id"] = {
            "tx-1": TransformerWindingResistanceTemperatureConstantAuthority(
                "tx-1",
                "copper",
                240.0,
                "linear_winding_resistance_temperature_constant_c",
                "certificate",
                "high",
            )
        }
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["advanced_load_loss_correction_resolved"]
    assert row["collection_winding_i2r_temperature_correction_factor"] == 1.0
    assert row["collection_winding_eddy_temperature_correction_factor"] == 1.0
    assert math.isnan(row["collection_winding_resistance_temperature_constant_c"])
    assert row["collection_winding_temperature_constant_source_mode"] == (
        "not_required_equal_reference_temperature"
    )
    constant = 240.0 if use_custom else 234.5
    assert row["network_winding_i2r_temperature_correction_factor"] == pytest.approx(
        (90.0 + constant) / (75.0 + constant)
    )


def test_heterogeneous_nonzero_osl_resolves_with_explicit_aggregate_proxy_only() -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=88.0,
        winding_temperatures=(95.0, 84.0),
    )
    values["winding_temperature_constant_by_transformer_id"] = {
        "tx-1": TransformerWindingResistanceTemperatureConstantAuthority(
            "tx-1",
            "mixed_or_other_explicit",
            230.0,
            "linear_winding_resistance_temperature_constant_c",
            "explicit aggregate structural proxy",
            "high",
        )
    }
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    assert row["other_stray_temperature_basis_mode"] == (
        "explicit_aggregate_mixed_structural_proxy"
    )
    assert row["other_stray_structural_temperature_proxy_applied"]
    assert row["collection_winding_temperature_constant_source_mode"] == ("standard_copper_234p5_c")
    assert row["network_winding_temperature_constant_source_mode"] == ("standard_aluminium_225_c")
    assert row["collection_winding_resistance_temperature_constant_c"] == 234.5
    assert row["network_winding_resistance_temperature_constant_c"] == 225.0
    assert row["collection_winding_i2r_temperature_correction_factor"] == pytest.approx(
        (95.0 + 234.5) / (75.0 + 234.5)
    )
    assert row["network_winding_i2r_temperature_correction_factor"] == pytest.approx(
        (84.0 + 225.0) / (75.0 + 225.0)
    )
    assert row["collection_winding_eddy_temperature_correction_factor"] == pytest.approx(
        (75.0 + 234.5) / (95.0 + 234.5)
    )
    assert row["network_winding_eddy_temperature_correction_factor"] == pytest.approx(
        (75.0 + 225.0) / (84.0 + 225.0)
    )


def test_heterogeneous_nonzero_osl_at_aggregate_reference_needs_no_proxy_constant() -> None:
    row = _run(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=75.0,
        winding_temperatures=(95.0, 84.0),
    ).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    assert row["other_stray_temperature_basis_mode"] == ("not_required_equal_reference_temperature")
    assert not row["other_stray_structural_temperature_proxy_applied"]
    assert row["other_stray_temperature_correction_factor"] == 1.0


def test_winding_resolved_harmonics_use_rms_for_i2r_and_s12i_factor_for_eddy() -> None:
    fundamental = _run(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=None,
        winding_temperatures=(95.0, 85.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
    ).states.iloc[0]
    harmonic = _run(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=None,
        winding_temperatures=(95.0, 85.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
        ratios={1: 1.0, 5: 0.2},
    ).states.iloc[0]
    rms_squared = harmonic["total_rms_to_fundamental_current_ratio"] ** 2
    assert harmonic["i2r_loss_corrected_total_w"] == pytest.approx(
        harmonic["i2r_loss_fundamental_temperature_corrected_w"] * rms_squared
    )
    assert harmonic["winding_eddy_loss_corrected_total_w"] == pytest.approx(
        harmonic["winding_eddy_loss_fundamental_temperature_corrected_w"]
        * rms_squared
        * harmonic["winding_eddy_harmonic_loss_factor"]
    )
    assert fundamental["i2r_loss_harmonic_increment_w"] == pytest.approx(0.0)
    assert fundamental["winding_eddy_loss_harmonic_increment_w"] == pytest.approx(0.0)


def test_side_reference_temperature_needs_no_material_constant() -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("mixed_or_other_explicit", "copper"),
        winding_temperature=None,
        winding_temperatures=(75.0, 90.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
    )
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["collection_winding_i2r_temperature_correction_factor"] == 1.0
    assert row["collection_winding_temperature_constant_source_mode"] == (
        "not_required_equal_reference_temperature"
    )
    assert math.isnan(row["collection_winding_resistance_temperature_constant_c"])


def test_scalar_custom_constant_cannot_bypass_heterogeneous_winding_gate() -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=100.0,
    )
    values["winding_temperature_constant_by_transformer_id"] = {
        "tx-1": TransformerWindingResistanceTemperatureConstantAuthority(
            "tx-1",
            "mixed_or_other_explicit",
            230.0,
            "linear_winding_resistance_temperature_constant_c",
            "certificate",
            "high",
        )
    }
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_winding_resolved_temperature_correction_basis_required"
    )


def test_heterogeneous_windings_resolve_at_equal_reference_temperature() -> None:
    row = _run(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=75.0,
    ).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    assert row["i2r_temperature_correction_factor"] == 1.0


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


def test_deenergised_preserves_nonzero_factory_evidence() -> None:
    row = _run(p=0.0, q=0.0, energised=False).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_deenergised_transformer_zero_advanced_load_loss"
    )
    assert row["harmonic_and_temperature_corrected_load_loss_w"] == 0.0
    assert row["advanced_correction_vs_s12g_w"] == 0.0
    assert row["factory_total_rated_load_loss_w"] == 5000.0
    assert row["i2r_loss_reference_w"] == 3000.0
    assert row["winding_eddy_current_loss_reference_w"] == 500.0
    assert row["other_stray_loss_reference_w"] == 1500.0


def test_deenergised_missing_factory_evidence_stays_missing() -> None:
    row = _run(
        p=0.0, q=0.0, energised=False, include_h=False, include_i=False, include_j=False
    ).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_deenergised_transformer_zero_advanced_load_loss"
    )
    assert row["harmonic_and_temperature_corrected_load_loss_w"] == 0.0
    # S12B's admitted total remains visible; absent S12H component evidence stays missing.
    assert row["factory_total_rated_load_loss_w"] == 5000.0
    for column in (
        "i2r_loss_reference_w",
        "winding_eddy_current_loss_reference_w",
        "other_stray_loss_reference_w",
    ):
        assert math.isnan(row[column])


def test_aggregate_factory_evidence_does_not_enter_s12k_component_correction() -> None:
    values = _context(aggregate_evidence=True)
    s12h_row = values["transformer_loss_component_authority"].transformer_states.iloc[0]
    assert s12h_row["transformer_factory_load_loss_evidence_resolved"]
    assert not s12h_row["transformer_advanced_loss_basis_resolved"]

    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_upstream_s12h_advanced_loss_basis"
    )
    assert math.isnan(row["winding_eddy_current_loss_reference_w"])
    assert math.isnan(row["other_stray_loss_reference_w"])
    assert math.isnan(row["harmonic_and_temperature_corrected_load_loss_w"])


@pytest.mark.parametrize(
    ("kwargs", "fidelity"),
    [
        ({"include_h": False}, "unresolved"),
        ({"aggregate_evidence": True}, "aggregate_stray_exact"),
    ],
)
def test_valid_s12g_baseline_is_selected_when_advanced_basis_is_unavailable(
    kwargs: dict[str, Any], fidelity: str
) -> None:
    values = _context(**kwargs)
    result = calculate_topology_transformer_corrected_load_loss(**values)
    row = result.states.iloc[0]
    baseline = values["transformer_operating_solution"].transformer_operating_states.iloc[0][
        "p_series_active_loss_w"
    ]
    assert row["transformer_load_loss_output_resolved"]
    assert not row["advanced_load_loss_correction_resolved"]
    assert row["s12g_load_loss_fallback_applied"]
    assert row["load_loss_output_fidelity"] == "s12g_positive_sequence_series_loss_baseline"
    assert row["load_loss_fallback_reason"] == row["transformer_corrected_load_loss_state"]
    assert row["selected_fundamental_load_loss_w"] == pytest.approx(baseline)
    assert row["selected_harmonic_incremental_load_loss_w"] == 0.0
    assert row["selected_total_load_loss_w"] == pytest.approx(baseline)
    assert row["s12h_factory_load_loss_evidence_fidelity"] == fidelity
    assert result.diagnostics.s12g_load_loss_fallback_count == 1


def test_advanced_selected_output_is_an_exact_alias_of_existing_advanced_values() -> None:
    result = _run(ratios={1: 1.0, 5: 0.1}, winding_temperature=100.0)
    row = result.states.iloc[0]
    assert row["advanced_load_loss_correction_resolved"]
    assert not row["s12g_load_loss_fallback_applied"]
    assert (
        row["selected_fundamental_load_loss_w"]
        == row["temperature_corrected_sinusoidal_load_loss_w"]
    )
    assert (
        row["selected_harmonic_incremental_load_loss_w"] == row["harmonic_incremental_load_loss_w"]
    )
    assert (
        row["selected_total_load_loss_w"] == row["harmonic_and_temperature_corrected_load_loss_w"]
    )


def test_nullable_energisation_is_preserved_for_unresolved_s12g_row() -> None:
    result = _run(energised=None)
    row = result.states.iloc[0]
    assert pd.isna(row["transformer_energised"])
    assert str(result.states["transformer_energised"].dtype) == "boolean"
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_upstream_s12g_transformer_operating_solution"
    )


def test_timestamp_without_s12g_row_has_nullable_energisation() -> None:
    extra = pd.Timestamp("2030-01-01T00:00:00Z")
    result = _run(extra_thermal_timestamp=extra)
    row = result.states.loc[(extra, "tx-1")]
    assert pd.isna(row["transformer_energised"])
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_missing_s12g_transformer_operating_state"
    )


def test_current_not_active_power_controls_loss() -> None:
    low = _run(p=100.0, q=0.0).states.iloc[0]
    high = _run(p=100.0, q=100.0).states.iloc[0]
    assert high["fundamental_operating_current_a"] > low["fundamental_operating_current_a"]
    assert (
        high["harmonic_and_temperature_corrected_load_loss_w"]
        > low["harmonic_and_temperature_corrected_load_loss_w"]
    )


def test_zero_component_loss_resolves_end_to_end_at_nonzero_current() -> None:
    row = _run(rated_load_w=0.0, p=100.0).states.iloc[0]
    assert row["fundamental_operating_current_a"] > 0.0
    assert row["transformer_corrected_load_loss_state"] == (
        "resolved_harmonic_and_temperature_corrected_transformer_load_loss"
    )
    for column in (
        "i2r_loss_corrected_total_w",
        "winding_eddy_loss_corrected_total_w",
        "other_stray_loss_corrected_total_w",
        "harmonic_and_temperature_corrected_load_loss_w",
        "reconstructed_reference_sinusoidal_load_loss_w",
        "s12g_reference_load_loss_w",
        "s12g_reference_load_loss_closure_residual_w",
    ):
        assert row[column] == 0.0


def test_equal_temperature_ignores_even_explicit_custom_constant() -> None:
    values = _context(material="mixed_or_other_explicit", winding_temperature=75.0)
    authority = TransformerWindingResistanceTemperatureConstantAuthority(
        "tx-1",
        "mixed_or_other_explicit",
        0.001,
        "linear_winding_resistance_temperature_constant_c",
        "unusual documented alloy",
        "low",
    )
    values["winding_temperature_constant_by_transformer_id"] = {"tx-1": authority}
    result = calculate_topology_transformer_corrected_load_loss(**values)
    row = result.states.iloc[0]
    assert row["transformer_corrected_load_loss_state"].startswith("resolved_")
    assert row["resistance_temperature_constant_source_mode"] == (
        "not_required_equal_reference_temperature"
    )
    assert row["i2r_temperature_correction_factor"] == 1.0
    assert row["winding_eddy_temperature_correction_factor"] == 1.0
    assert row["other_stray_temperature_correction_factor"] == 1.0
    assert result.winding_temperature_constant_by_transformer_id["tx-1"] == authority


def test_overload_is_not_clamped() -> None:
    values = _context()
    parents = list(module._canonical_parents(values))
    equipment = replace(values["transformer_equipment_by_id"]["tx-1"], rated_apparent_power_va=50.0)
    g_row = parents[0].transformer_operating_states.iloc[0]
    rated_current = 50.0 / (math.sqrt(3.0) * 400.0)
    beta = g_row["collection_series_current_magnitude_a"] / rated_current
    total = g_row["p_series_active_loss_w"] / (beta * beta)
    h_frame = parents[1].transformer_states.copy(deep=True)
    row_index = h_frame.index[0]
    h_frame.loc[row_index, "i2r_loss_reference_w"] = total * 0.6
    h_frame.loc[row_index, "winding_eddy_current_loss_reference_w"] = total * 0.1
    h_frame.loc[row_index, "canonical_other_stray_loss_reference_w"] = total * 0.3
    h_frame.loc[row_index, "s12b_rated_load_loss_w"] = total
    parents[1] = replace(parents[1], transformer_states=h_frame)
    timestamp, identifier = parents[0].transformer_operating_states.index[0]
    row = module._record(timestamp, identifier, cast(Any, tuple(parents)), equipment, {}, {})
    assert cast(str, row["transformer_corrected_load_loss_state"]).startswith("resolved_")
    beta1 = cast(float, row["fundamental_current_loading_ratio"])
    beta_rms = cast(float, row["total_rms_current_loading_ratio"])
    assert beta1 > 1.0
    assert beta_rms >= beta1
    expected = beta1**2 * cast(float, row["factory_total_rated_load_loss_w"])
    assert row["reconstructed_reference_sinusoidal_load_loss_w"] == pytest.approx(expected)


def test_finite_inputs_with_derived_overflow_are_unresolved_without_infinity() -> None:
    values = _context()
    parents = list(module._canonical_parents(values))
    frame = parents[0].transformer_operating_states.copy(deep=True)
    for column in (
        "collection_series_current_magnitude_a",
        "network_series_current_magnitude_a",
    ):
        frame.iloc[0, frame.columns.get_loc(column)] = 1e308
    parents[0] = replace(parents[0], transformer_operating_states=frame)
    timestamp, identifier = frame.index[0]
    record = module._record(
        timestamp,
        identifier,
        cast(Any, tuple(parents)),
        values["transformer_equipment_by_id"][identifier],
        {},
        {},
    )
    assert record["transformer_corrected_load_loss_state"] == (
        "unresolved_nonfinite_corrected_transformer_load_loss"
    )
    derived = [record[name] for name in module._FLOAT_COLUMNS]
    assert not any(isinstance(value, float) and math.isinf(value) for value in derived)


def test_timestamp_union_is_sorted_across_all_sources() -> None:
    thermal_time = pd.Timestamp("2030-01-01T00:00:00Z")
    application_time = pd.Timestamp("2031-01-01T00:00:00Z")
    values = _context(extra_thermal_timestamp=thermal_time)
    binding = TransformerSingleConditionHarmonicSpectrumApplication(
        "s12i_single_declared_operating_condition_matches_this_timestamp",
        "separate documented acquisition",
        "PQ report",
        "high",
    )
    values["single_condition_harmonic_application_by_key"] = {(application_time, "tx-1"): binding}
    result = calculate_topology_transformer_corrected_load_loss(**values)
    actual = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))
    g_time = values["transformer_operating_solution"].transformer_operating_states.index[0][0]
    assert actual == sorted([g_time, thermal_time, application_time])
    assert result.states.loc[
        (application_time, "tx-1"), "transformer_corrected_load_loss_state"
    ] == ("unresolved_missing_s12g_transformer_operating_state")


def test_timestamp_union_rejects_incompatible_timezone_semantics() -> None:
    values = _context()
    binding = TransformerSingleConditionHarmonicSpectrumApplication(
        "s12i_single_declared_operating_condition_matches_this_timestamp",
        "incompatible clock",
        "PQ report",
        "high",
    )
    values["single_condition_harmonic_application_by_key"] = {
        (pd.Timestamp("2030-01-01T00:00:00"), "tx-1"): binding
    }
    with pytest.raises(ValueError, match="incompatible timezone semantics"):
        calculate_topology_transformer_corrected_load_loss(**values)


def test_operating_reference_side_mismatch_is_explicit_without_referral() -> None:
    values = _context()
    parents = list(module._canonical_parents(values))
    frame = parents[0].transformer_operating_states.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc("series_equivalent_reference_side")] = "network_side"
    parents[0] = replace(parents[0], transformer_operating_states=frame)
    timestamp, identifier = frame.index[0]
    record = module._record(
        timestamp,
        identifier,
        cast(Any, tuple(parents)),
        values["transformer_equipment_by_id"][identifier],
        {},
        {},
    )
    assert record["transformer_corrected_load_loss_state"] == (
        "unresolved_operating_current_reference_side_mismatch"
    )


def test_returned_mappings_are_detached_sorted_and_immutable() -> None:
    values = _context(applicability="single_declared_operating_condition")
    key = next(iter(values["transformer_thermal_state_by_key"]))
    binding = TransformerSingleConditionHarmonicSpectrumApplication(
        "s12i_single_declared_operating_condition_matches_this_timestamp",
        "matching acquisition",
        "PQ report",
        "high",
    )
    constant = TransformerWindingResistanceTemperatureConstantAuthority(
        "tx-1",
        "copper",
        234.6,
        "linear_winding_resistance_temperature_constant_c",
        "certificate",
        "high",
    )
    applications = {key: binding}
    constants = {"tx-1": constant}
    values["single_condition_harmonic_application_by_key"] = applications
    values["winding_temperature_constant_by_transformer_id"] = constants
    result = calculate_topology_transformer_corrected_load_loss(**values)
    applications.clear()
    constants.clear()
    assert type(result.single_condition_harmonic_application_by_key) is MappingProxyType
    assert type(result.winding_temperature_constant_by_transformer_id) is MappingProxyType
    assert result.single_condition_harmonic_application_by_key[key] == binding
    assert result.winding_temperature_constant_by_transformer_id["tx-1"] == constant


def test_unresolved_row_preserves_all_available_parent_evidence() -> None:
    values = _context(harmonic_side="network_side", winding_temperature=100.0)
    constant = TransformerWindingResistanceTemperatureConstantAuthority(
        "tx-1",
        "copper",
        234.6,
        "linear_winding_resistance_temperature_constant_c",
        "certificate",
        "high",
    )
    values["winding_temperature_constant_by_transformer_id"] = {"tx-1": constant}
    row = calculate_topology_transformer_corrected_load_loss(**values).states.iloc[0]
    assert row["transformer_corrected_load_loss_state"] == (
        "unresolved_harmonic_spectrum_reference_side_mismatch"
    )
    assert row["fundamental_operating_current_a"] > 0.0
    assert row["s12g_reference_load_loss_w"] > 0.0
    assert row["factory_total_rated_load_loss_w"] == 5000.0
    assert row["current_thd_ratio"] == 0.0
    assert row["average_winding_temperature_c"] == 100.0
    assert row["resistance_temperature_constant_c"] == 234.6


def test_independent_validator_never_calls_production_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _context()
    result = calculate_topology_transformer_corrected_load_loss(**values)
    parents = module._canonical_parents(values)
    timestamps = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("production builder called by validator")

    monkeypatch.setattr(module, "_record", forbidden)
    monkeypatch.setattr(module, "_frame", forbidden)
    monkeypatch.setattr(module, "_diagnostics", forbidden)
    _validate_result(
        parents,
        values["transformer_equipment_by_id"],
        {},
        {},
        timestamps,
        result,
    )


def test_winding_resolved_validator_never_calls_production_factor_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=None,
        winding_temperatures=(95.0, 85.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
    )
    result = calculate_topology_transformer_corrected_load_loss(**values)
    parents = module._canonical_parents(values)
    timestamps = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("production winding factor called by validator")

    monkeypatch.setattr(module, "_winding_factor", forbidden)
    _validate_result(
        parents,
        values["transformer_equipment_by_id"],
        {},
        {},
        timestamps,
        result,
    )


@pytest.mark.parametrize(
    "column",
    [
        "s12h_winding_resolved_advanced_correction_basis_resolved",
        "s12j_winding_resolved_temperature_basis_resolved",
        "winding_resolved_temperature_correction_applied",
        "temperature_correction_basis",
        "collection_winding_average_temperature_c",
        "network_winding_average_temperature_c",
        "collection_winding_conductor_material",
        "network_winding_conductor_material",
        "collection_winding_resistance_temperature_constant_c",
        "network_winding_temperature_constant_source_mode",
        "collection_winding_i2r_temperature_correction_factor",
        "network_winding_eddy_temperature_correction_factor",
        "collection_winding_i2r_loss_reference_w",
        "network_winding_eddy_current_loss_reference_w",
        "collection_winding_i2r_loss_corrected_total_w",
        "network_winding_eddy_loss_corrected_total_w",
        "i2r_temperature_correction_factor",
        "winding_eddy_temperature_correction_factor",
        "other_stray_temperature_basis_resolved",
        "other_stray_temperature_basis_mode",
        "selected_total_load_loss_w",
    ],
)
def test_winding_resolved_validator_rejects_new_field_tampering(column: str) -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=None,
        winding_temperatures=(95.0, 85.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
    )
    result = calculate_topology_transformer_corrected_load_loss(**values)
    parents = module._canonical_parents(values)
    timestamps = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))
    changed = result.states.copy(deep=True)
    value = changed.iloc[0][column]
    if changed[column].dtype == bool:
        replacement: object = not bool(value)
    elif isinstance(value, str):
        replacement = "tampered"
    else:
        replacement = float(value) + 1.0
    changed.iloc[0, changed.columns.get_loc(column)] = replacement
    with pytest.raises(ValueError, match="frame"):
        _validate_result(
            parents,
            values["transformer_equipment_by_id"],
            {},
            {},
            timestamps,
            replace(result, states=changed),
        )


@pytest.mark.parametrize(
    "field",
    [
        "winding_resolved_correction_basis_available_count",
        "winding_resolved_correction_applied_count",
        "legacy_scalar_correction_applied_count",
        "winding_resolved_basis_missing_count",
        "other_stray_proxy_basis_missing_count",
        "zero_other_stray_no_proxy_required_count",
        "aggregate_other_stray_proxy_applied_count",
    ],
)
def test_winding_resolved_validator_rejects_new_diagnostics_tampering(field: str) -> None:
    values = _context(
        material="mixed_or_other_explicit",
        winding_materials=("copper", "aluminium"),
        winding_temperature=None,
        winding_temperatures=(95.0, 85.0),
        other_stray_w=0.0,
        rated_load_w=3500.0,
    )
    result = calculate_topology_transformer_corrected_load_loss(**values)
    parents = module._canonical_parents(values)
    timestamps = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))
    diagnostics = replace(result.diagnostics, **{field: 99})
    with pytest.raises(ValueError, match="diagnostics"):
        _validate_result(
            parents,
            values["transformer_equipment_by_id"],
            {},
            {},
            timestamps,
            replace(result, diagnostics=diagnostics),
        )


def test_independent_validator_rejects_every_output_family_tamper() -> None:
    values = _context(ratios={1: 1.0, 5: 0.1}, winding_temperature=100.0)
    result = calculate_topology_transformer_corrected_load_loss(**values)
    parents = module._canonical_parents(values)
    timestamps = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))
    numeric_columns = (
        "fundamental_operating_current_a",
        "rated_reference_side_current_a",
        "fundamental_current_loading_ratio",
        "total_rms_current_loading_ratio",
        "current_thd_ratio",
        "winding_eddy_harmonic_loss_factor",
        "other_stray_harmonic_loss_factor",
        "resistance_temperature_constant_c",
        "i2r_temperature_correction_factor",
        "winding_eddy_temperature_correction_factor",
        "other_stray_temperature_correction_factor",
        "i2r_loss_reference_w",
        "winding_eddy_current_loss_reference_w",
        "other_stray_loss_reference_w",
        "factory_total_rated_load_loss_w",
        "effective_winding_ohmic_resistance_reference_ohm_per_phase",
        "effective_winding_ohmic_resistance_temperature_corrected_ohm_per_phase",
        "i2r_loss_fundamental_temperature_corrected_w",
        "winding_eddy_loss_harmonic_increment_w",
        "harmonic_and_temperature_corrected_load_loss_w",
        "s12g_reference_load_loss_w",
        "reconstructed_reference_sinusoidal_load_loss_w",
        "s12g_reference_load_loss_closure_residual_w",
        "advanced_correction_vs_s12g_w",
        "advanced_correction_decomposition_residual_w",
        "selected_fundamental_load_loss_w",
        "selected_harmonic_incremental_load_loss_w",
        "selected_total_load_loss_w",
    )
    text_columns = (
        "harmonic_other_stray_semantics",
        "advanced_load_loss_ownership",
        "current_loading_semantics",
        "transformer_corrected_load_loss_state",
        "transformer_operating_solution_contract",
        "transformer_corrected_load_loss_contract",
        "transformer_corrected_load_loss_model",
        "transformer_corrected_load_loss_scope",
        "load_loss_output_fidelity",
        "load_loss_fallback_reason",
        "s12h_factory_load_loss_evidence_fidelity",
        "s12h_factory_load_loss_evidence_kind",
    )
    for column in numeric_columns:
        changed = result.states.copy(deep=True)
        changed.iloc[0, changed.columns.get_loc(column)] += 1.0
        with pytest.raises(ValueError, match="frame"):
            _validate_result(
                parents,
                values["transformer_equipment_by_id"],
                {},
                {},
                timestamps,
                replace(result, states=changed),
            )
    for column in text_columns:
        changed = result.states.copy(deep=True)
        changed.iloc[0, changed.columns.get_loc(column)] = "tampered"
        with pytest.raises(ValueError, match="frame"):
            _validate_result(
                parents,
                values["transformer_equipment_by_id"],
                {},
                {},
                timestamps,
                replace(result, states=changed),
            )
    for column in (
        "transformer_load_loss_output_resolved",
        "advanced_load_loss_correction_resolved",
        "s12g_load_loss_fallback_applied",
    ):
        changed = result.states.copy(deep=True)
        changed.iloc[0, changed.columns.get_loc(column)] = not bool(changed.iloc[0][column])
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
    with pytest.raises(ValueError, match="mapping"):
        _validate_result(
            parents,
            values["transformer_equipment_by_id"],
            {},
            {},
            timestamps,
            replace(result, single_condition_harmonic_application_by_key={}),
        )
    with pytest.raises(ValueError, match="mapping"):
        _validate_result(
            parents,
            values["transformer_equipment_by_id"],
            {},
            {},
            timestamps,
            replace(result, winding_temperature_constant_by_transformer_id={}),
        )


@pytest.mark.parametrize("parent", ["S12G", "S12H", "S12I", "S12J"])
def test_each_parent_replay_rejects_frame_tampering(parent: str) -> None:
    values = _context()
    result_name, frame_name = {
        "S12G": ("transformer_operating_solution", "transformer_operating_states"),
        "S12H": ("transformer_loss_component_authority", "transformer_states"),
        "S12I": ("transformer_harmonic_current_authority", "transformer_states"),
        "S12J": ("transformer_thermal_state_authority", "states"),
    }[parent]
    supplied = values[result_name]
    frame = getattr(supplied, frame_name).copy(deep=True)
    frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
    values[result_name] = replace(supplied, **{frame_name: frame})
    with pytest.raises(ValueError, match=parent):
        calculate_topology_transformer_corrected_load_loss(**values)


def test_parent_mapping_and_diagnostics_tampering_are_rejected() -> None:
    values = _context()
    h = values["transformer_loss_component_authority"]
    values["transformer_loss_component_authority"] = replace(
        h, construction_by_id=dict(h.construction_by_id)
    )
    with pytest.raises(ValueError, match="S12H mapping"):
        calculate_topology_transformer_corrected_load_loss(**values)
    values = _context()
    j = values["transformer_thermal_state_authority"]
    values["transformer_thermal_state_authority"] = replace(
        j, diagnostics=replace(j.diagnostics, row_count=99)
    )
    with pytest.raises(ValueError, match="S12J diagnostics"):
        calculate_topology_transformer_corrected_load_loss(**values)


def test_scope_exclusions_and_semantic_guards() -> None:
    source = inspect.getsource(module)
    assert "transformer_operating_loss" not in source
    assert "Steinmetz" not in source
    assert "h0p8_harmonic_order_weighting_not_temperature_exponent" in source
    assert "replacement_for_s12g_reference_series_active_loss_not_additive" in source
    assert "p_series_active_loss_w" in source
    assert "collection_p_w" not in source
