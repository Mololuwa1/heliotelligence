"""Physics and contract tests for S12L transformer no-load/core loss."""

from __future__ import annotations

import cmath
import importlib
import math
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import transformer_core_no_load_loss as module
from heliotelligence.physics.transformer_core_no_load_loss import (
    CORRECTED_NO_LOAD_LOSS_OWNERSHIP,
    OPERATING_WAVEFORM_BASIS,
    REFERENCE_WAVEFORM_BASIS,
    RESIDUAL_SEMANTICS,
    SCALING_SEMANTICS,
    TransformerNormalizedCoreLossScalingAuthority,
    TransformerOperatingFrequencyState,
    _validate_result,
    calculate_topology_transformer_core_no_load_loss,
)
from heliotelligence.physics.transformer_operating_solution import (
    calculate_topology_transformer_operating_solution,
)
from tests.unit.test_physics.test_transformer_operating_solution import _inputs

support: Any = importlib.import_module("tests.unit.test_physics.test_inverter_dispatch_feasibility")


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


def _frequency(value: float = 50.0) -> TransformerOperatingFrequencyState:
    return TransformerOperatingFrequencyState(
        value, "direct_power_quality_measurement", "PQ meter", "high"
    )


def _scaling(
    *,
    scalable: float = 500.0,
    minimum_frequency: float = 0.5,
    maximum_frequency: float = 2.0,
    minimum_flux: float = 0.5,
    maximum_flux: float = 2.0,
    alpha: float = 1.5,
    beta: float = 2.5,
) -> TransformerNormalizedCoreLossScalingAuthority:
    return TransformerNormalizedCoreLossScalingAuthority(
        "tx-1",
        scalable,
        alpha,
        beta,
        minimum_frequency,
        maximum_frequency,
        minimum_flux,
        maximum_flux,
        cast(Any, REFERENCE_WAVEFORM_BASIS),
        cast(Any, OPERATING_WAVEFORM_BASIS),
        cast(Any, SCALING_SEMANTICS),
        cast(Any, RESIDUAL_SEMANTICS),
        "factory curve fit",
        "valid around declared reference",
        "high",
    )


def _context(
    *,
    voltage: float = 400.0,
    frequency: float | None = 50.0,
    scaling: TransformerNormalizedCoreLossScalingAuthority | None = None,
    no_load_w: float = 600.0,
    energised: bool | None = True,
    side: str = "collection_side",
) -> dict[str, Any]:
    values, _ = _inputs(
        p=0.0,
        q=0.0,
        voltage=voltage,
        no_load_w=no_load_w,
        energised=energised,
        side=side,
    )
    operating = calculate_topology_transformer_operating_solution(**values)
    timestamps = list(
        dict.fromkeys(operating.transformer_operating_states.index.get_level_values("timestamp"))
    )
    values.update(
        {
            "transformer_operating_solution": operating,
            "transformer_operating_frequency_by_key": (
                {(timestamps[0], "tx-1"): _frequency(frequency)}
                if frequency is not None and timestamps
                else {}
            ),
            "transformer_core_loss_scaling_by_id": (
                {"tx-1": scaling} if scaling is not None else {}
            ),
        }
    )
    return values


def _run(**kwargs: Any) -> Any:
    return calculate_topology_transformer_core_no_load_loss(**_context(**kwargs))


def test_missing_scaling_uses_explicit_factory_fallback() -> None:
    row = _run().states.iloc[0]
    assert row["transformer_core_no_load_loss_state"] == (
        "resolved_factory_reference_no_load_loss_fallback_missing_core_scaling_authority"
    )
    assert row["corrected_no_load_loss_w"] == 600.0
    assert row["advanced_no_load_correction_vs_s12g_w"] == 0.0
    assert row["transformer_no_load_loss_output_resolved"]
    assert not row["advanced_core_loss_scaling_resolved"]
    assert row["corrected_no_load_loss_ownership"] == CORRECTED_NO_LOAD_LOSS_OWNERSHIP


def test_reference_identity_has_no_double_counting() -> None:
    row = _run(no_load_w=0.0, scaling=_scaling(scalable=0.0)).states.iloc[0]
    assert row["transformer_core_no_load_loss_state"] == (
        "resolved_voltage_frequency_corrected_transformer_no_load_core_loss"
    )
    for name in (
        "operating_voltage_ratio_to_factory_reference",
        "operating_frequency_ratio_to_factory_reference",
        "core_flux_density_ratio_to_factory_reference",
        "core_loss_scaling_multiplier",
    ):
        assert row[name] == pytest.approx(1.0)
    assert row["voltage_frequency_corrected_no_load_loss_w"] == pytest.approx(0.0)
    assert row["advanced_no_load_correction_vs_s12g_w"] == pytest.approx(0.0)


def test_nonzero_reference_identity_closes_to_s12g_factory_loss() -> None:
    row = _run(scaling=_scaling()).states.iloc[0]
    assert row["operating_frequency_ratio_to_factory_reference"] == 1.0
    assert row["operating_voltage_ratio_to_factory_reference"] == pytest.approx(1.0, rel=2e-5)
    assert row["core_flux_density_ratio_to_factory_reference"] == pytest.approx(1.0, rel=2e-5)
    assert row["core_loss_scaling_multiplier"] == pytest.approx(1.0, rel=4e-5)
    assert row["corrected_no_load_loss_w"] == pytest.approx(
        row["s12g_reference_no_load_loss_w"], rel=4e-5
    )
    assert row["advanced_no_load_correction_vs_s12g_w"] == pytest.approx(0.0, abs=0.02)


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
def test_internal_excitation_reconstruction_for_both_series_sides(side: str) -> None:
    values = _context(side=side, scaling=_scaling())
    result = calculate_topology_transformer_core_no_load_loss(**values)
    row = result.states.iloc[0]
    g = values["transformer_operating_solution"].transformer_operating_states.iloc[0]
    vc = complex(g["collection_phase_voltage_real_v"], g["collection_phase_voltage_imag_v"])
    ic = complex(g["collection_series_current_real_a"], g["collection_series_current_imag_a"])
    vn = complex(
        g["network_terminal_phase_voltage_real_v"], g["network_terminal_phase_voltage_imag_v"]
    )
    current_n = complex(g["network_series_current_real_a"], g["network_series_current_imag_a"])
    impedance = complex(
        g["effective_series_resistance_ohm_per_phase"],
        g["effective_series_reactance_ohm_per_phase"],
    )
    k = g["network_to_collection_voltage_ratio"] * cmath.exp(
        1j * math.radians(g["network_side_phase_displacement_deg"])
    )
    ec = vc - impedance * ic if side == "collection_side" else vc
    en = k * ec
    en_check = vn if side == "collection_side" else vn + impedance * current_n
    assert row["baseline_internal_collection_excitation_voltage_ll_rms_v"] == pytest.approx(
        math.sqrt(3.0) * abs(ec)
    )
    assert row["baseline_internal_network_excitation_voltage_ll_rms_v"] == pytest.approx(
        math.sqrt(3.0) * abs(en)
    )
    assert abs(en - en_check) <= max(1e-8, 1e-9 * max(abs(en), abs(en_check)))


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
def test_factory_reference_side_selects_matching_voltage(side: str) -> None:
    values = _context(scaling=_scaling())
    parents = module._canonical_parents(values)
    no_load = replace(parents[1].no_load_loss_by_id["tx-1"], test_reference_side=cast(Any, side))
    loss = replace(parents[1], no_load_loss_by_id=MappingProxyType({"tx-1": no_load}))
    timestamp = next(iter(values["transformer_operating_frequency_by_key"]))[0]
    row = module._record(
        timestamp,
        "tx-1",
        (parents[0], loss, parents[2]),
        parents[0].equipment_by_id["tx-1"],
        values["transformer_operating_frequency_by_key"],
        values["transformer_core_loss_scaling_by_id"],
    )
    equipment = values["transformer_equipment_by_id"]["tx-1"]
    selected = (
        "baseline_internal_collection_excitation_voltage_ll_rms_v"
        if side == "collection_side"
        else "baseline_internal_network_excitation_voltage_ll_rms_v"
    )
    rated = (
        equipment.collection_side_rated_line_to_line_rms_v
        if side == "collection_side"
        else equipment.network_side_rated_line_to_line_rms_v
    )
    assert row["operating_core_excitation_voltage_ll_rms_v"] == row[selected]
    assert row["factory_reference_core_excitation_voltage_ll_rms_v"] == rated


def test_partial_scalable_loss_preserves_constant_residual() -> None:
    row = _run(voltage=360.0, scaling=_scaling(scalable=500.0)).states.iloc[0]
    expected_multiplier = row["operating_voltage_ratio_to_factory_reference"] ** 2.5
    assert row["non_scaling_no_load_loss_reference_residual_w"] == 100.0
    assert row["core_loss_scaling_multiplier"] == pytest.approx(expected_multiplier)
    assert row["corrected_no_load_loss_w"] == pytest.approx(500.0 * expected_multiplier + 100.0)


def test_constant_v_over_f_separates_frequency_from_flux() -> None:
    row = _run(voltage=440.0, frequency=55.0, scaling=_scaling()).states.iloc[0]
    rf = row["operating_frequency_ratio_to_factory_reference"]
    rb = row["core_flux_density_ratio_to_factory_reference"]
    assert rb == pytest.approx(row["operating_voltage_ratio_to_factory_reference"] / rf)
    assert row["core_loss_scaling_multiplier"] == pytest.approx(rf**1.5 * rb**2.5)


@pytest.mark.parametrize("frequency", [None, 200.0])
def test_missing_or_outside_frequency_falls_back(frequency: float | None) -> None:
    result = _run(frequency=frequency, scaling=_scaling())
    row = result.states.iloc[0]
    expected = (
        "resolved_factory_reference_no_load_loss_fallback_missing_operating_frequency"
        if frequency is None
        else "resolved_factory_reference_no_load_loss_fallback_outside_core_scaling_domain"
    )
    assert row["transformer_core_no_load_loss_state"] == expected
    assert row["corrected_no_load_loss_w"] == 600.0
    assert row["advanced_no_load_correction_vs_s12g_w"] == 0.0


def test_materially_excess_scalable_reference_is_unresolved() -> None:
    row = _run(scaling=_scaling(scalable=601.0)).states.iloc[0]
    assert row["transformer_core_no_load_loss_state"] == (
        "unresolved_core_scaling_reference_loss_exceeds_s12b_no_load_loss"
    )
    assert math.isnan(row["corrected_no_load_loss_w"])


def test_reference_component_tiny_exceedance_is_roundoff_adjusted() -> None:
    row = _run(scaling=_scaling(scalable=600.0 * (1.0 + 5e-13))).states.iloc[0]
    assert row["reference_component_closure_roundoff_adjusted"]
    assert row["non_scaling_no_load_loss_reference_residual_w"] == 0.0


def test_nonfinite_derived_scaling_is_explicitly_unresolved() -> None:
    row = _run(voltage=440.0, scaling=_scaling(alpha=1e308, beta=1e308)).states.iloc[0]
    assert row["transformer_core_no_load_loss_state"] == (
        "unresolved_nonfinite_corrected_no_load_core_loss"
    )
    derived = row[list(module._FLOAT_COLUMNS)]
    assert not any(math.isinf(value) for value in derived if not pd.isna(value))


def test_flux_domain_outside_falls_back_without_extrapolation() -> None:
    authority = _scaling(minimum_flux=0.99, maximum_flux=1.01)
    row = _run(voltage=360.0, frequency=50.0, scaling=authority).states.iloc[0]
    assert row["operating_frequency_ratio_to_factory_reference"] == 1.0
    assert row["core_flux_density_ratio_to_factory_reference"] < 0.99
    assert row["transformer_core_no_load_loss_state"] == (
        "resolved_factory_reference_no_load_loss_fallback_outside_core_scaling_domain"
    )
    assert row["corrected_no_load_loss_w"] == row["s12g_reference_no_load_loss_w"]
    assert row["advanced_no_load_correction_vs_s12g_w"] == 0.0
    assert not row["advanced_core_loss_scaling_resolved"]


def test_deenergised_preserves_factory_evidence_but_operating_loss_is_zero() -> None:
    row = _run(energised=False, scaling=_scaling()).states.iloc[0]
    assert row["transformer_core_no_load_loss_state"] == (
        "resolved_deenergised_transformer_zero_no_load_loss"
    )
    assert row["s12b_factory_no_load_loss_w"] == 600.0
    assert row["corrected_no_load_loss_w"] == 0.0


@pytest.mark.parametrize(
    "kind",
    [
        "direct_power_quality_measurement",
        "scada_grid_frequency",
        "documented_external_frequency_state",
        "declared_nominal_frequency_for_timestamp",
    ],
)
def test_frequency_evidence_kinds(kind: str) -> None:
    value = TransformerOperatingFrequencyState(50.0, cast(Any, kind), "source", "medium")
    assert value.evidence_kind == kind


@pytest.mark.parametrize("value", [True, 0.0, -1.0, math.nan, math.inf, "50"])
def test_invalid_frequency_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        TransformerOperatingFrequencyState(cast(Any, value), "scada_grid_frequency", "x", "high")


def test_frequency_key_validation_and_timestamp_union() -> None:
    values = _context()
    with pytest.raises(ValueError, match="pd.Timestamp"):
        values["transformer_operating_frequency_by_key"] = {
            (datetime(2025, 1, 2), "tx-1"): _frequency()
        }
        calculate_topology_transformer_core_no_load_loss(**values)
    values = _context()
    t2 = pd.Timestamp("2027-01-02", tz="UTC")
    values["transformer_operating_frequency_by_key"] = {(t2, "tx-1"): _frequency()}
    result = calculate_topology_transformer_core_no_load_loss(**values)
    assert result.states.index.get_level_values("timestamp").tolist() == sorted(
        result.states.index.get_level_values("timestamp").tolist()
    )
    assert result.states.loc[(t2, "tx-1"), "transformer_core_no_load_loss_state"] == (
        "unresolved_missing_s12g_transformer_operating_state"
    )


def test_incompatible_timezone_semantics_are_rejected() -> None:
    values = _context()
    values["transformer_operating_frequency_by_key"] = {
        (pd.Timestamp("2027-01-02"), "tx-1"): _frequency()
    }
    with pytest.raises(ValueError, match="incompatible timezone semantics"):
        calculate_topology_transformer_core_no_load_loss(**values)


@pytest.mark.parametrize(
    ("parent_key", "frame_name"),
    [
        ("transformer_static_authority", "transformer_states"),
        ("transformer_loss_authority", "transformer_states"),
        ("transformer_operating_solution", "transformer_operating_states"),
    ],
)
def test_public_resolution_rejects_parent_frame_tampering(parent_key: str, frame_name: str) -> None:
    values = _context(scaling=_scaling())
    parent = values[parent_key]
    frame = getattr(parent, frame_name).copy(deep=True)
    frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
    values[parent_key] = replace(parent, **{frame_name: frame})
    with pytest.raises(ValueError, match="canonical replay"):
        calculate_topology_transformer_core_no_load_loss(**values)


def test_input_mapping_detachment_and_result_immutability() -> None:
    values = _context(scaling=_scaling())
    frequencies = dict(values["transformer_operating_frequency_by_key"])
    scalings = dict(values["transformer_core_loss_scaling_by_id"])
    values["transformer_operating_frequency_by_key"] = frequencies
    values["transformer_core_loss_scaling_by_id"] = scalings
    result = calculate_topology_transformer_core_no_load_loss(**values)
    frequencies.clear()
    scalings.clear()
    assert type(result.operating_frequency_by_key) is MappingProxyType
    assert type(result.core_loss_scaling_by_id) is MappingProxyType
    assert len(result.operating_frequency_by_key) == 1
    assert len(result.core_loss_scaling_by_id) == 1


def test_nullable_energisation_for_frequency_only_row() -> None:
    values = _context()
    t2 = pd.Timestamp("2027-01-02", tz="UTC")
    values["transformer_operating_frequency_by_key"] = {(t2, "tx-1"): _frequency()}
    result = calculate_topology_transformer_core_no_load_loss(**values)
    assert str(result.states["transformer_energised"].dtype) == "boolean"
    assert pd.isna(result.states.loc[(t2, "tx-1"), "transformer_energised"])


def test_result_validator_rejects_frame_diagnostics_and_mappings() -> None:
    values = _context(scaling=_scaling())
    result = calculate_topology_transformer_core_no_load_loss(**values)
    parents = module._canonical_parents(values)
    times = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))
    frame = result.states.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc("core_loss_scaling_multiplier")] = 9.0
    with pytest.raises(ValueError, match="frame"):
        _validate_result(
            parents,
            parents[0].equipment_by_id,
            result.operating_frequency_by_key,
            result.core_loss_scaling_by_id,
            times,
            replace(result, states=frame),
        )


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("baseline_internal_collection_excitation_voltage_ll_rms_v", 9.0),
        ("operating_core_excitation_voltage_ll_rms_v", 9.0),
        ("operating_frequency_hz", 9.0),
        ("core_flux_density_ratio_to_factory_reference", 9.0),
        ("core_loss_scaling_multiplier", 9.0),
        ("corrected_no_load_loss_w", 9.0),
        ("advanced_no_load_correction_vs_s12g_w", 9.0),
        ("advanced_core_loss_scaling_resolved", False),
        ("corrected_no_load_loss_ownership", "tampered"),
        ("transformer_core_no_load_loss_state", "tampered"),
        ("transformer_core_no_load_loss_contract", "tampered"),
    ],
)
def test_independent_validator_rejects_representative_result_tampering(
    column: str, replacement: object
) -> None:
    values = _context(scaling=_scaling())
    result = calculate_topology_transformer_core_no_load_loss(**values)
    parents = module._canonical_parents(values)
    times = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))
    frame = result.states.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc(column)] = replacement
    with pytest.raises(ValueError, match="independent validation"):
        _validate_result(
            parents,
            parents[0].equipment_by_id,
            result.operating_frequency_by_key,
            result.core_loss_scaling_by_id,
            times,
            replace(result, states=frame),
        )
    with pytest.raises(ValueError, match="mapping"):
        _validate_result(
            parents,
            parents[0].equipment_by_id,
            result.operating_frequency_by_key,
            result.core_loss_scaling_by_id,
            times,
            replace(result, operating_frequency_by_key=dict(result.operating_frequency_by_key)),
        )
    with pytest.raises(ValueError, match="diagnostics"):
        _validate_result(
            parents,
            parents[0].equipment_by_id,
            result.operating_frequency_by_key,
            result.core_loss_scaling_by_id,
            times,
            replace(result, diagnostics=replace(result.diagnostics, row_count=99)),
        )


def test_validator_does_not_call_production_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    values = _context(scaling=_scaling())
    result = calculate_topology_transformer_core_no_load_loss(**values)
    parents = module._canonical_parents(values)
    times = list(dict.fromkeys(result.states.index.get_level_values("timestamp")))

    def fail(*args: object, **kwargs: object) -> None:
        pytest.fail("production builder called")

    for name in ("_record", "_frame", "_diagnostics"):
        monkeypatch.setattr(module, name, fail)
    _validate_result(
        parents,
        parents[0].equipment_by_id,
        result.operating_frequency_by_key,
        result.core_loss_scaling_by_id,
        times,
        result,
    )
    source = module.__loader__.get_source(module.__name__)  # type: ignore[union-attr]
    assert "_VALIDATOR_RECORD_IMPL = _record" not in source


def test_scope_has_no_s12k_or_disallowed_physics() -> None:
    source = module.__loader__.get_source(module.__name__)  # type: ignore[union-attr]
    assert "transformer_corrected_load_loss" not in source
    for forbidden in ("voltage_thd", "magnetising", "inrush", "arrhenius"):
        assert forbidden not in source.lower()
