"""Tests for S12I transformer harmonic-current authority."""

from __future__ import annotations

import inspect
import math
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_harmonic_current_authority as module
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    resolve_topology_lv_ac_collection_authority,
)
from heliotelligence.physics.transformer_authority import (
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
    resolve_transformer_static_authority,
)
from heliotelligence.physics.transformer_harmonic_current_authority import (
    HARMONIC_METHOD_REFERENCE_STANDARD,
    LOAD_CURRENT_K_FACTOR_SEMANTICS,
    TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_COVERAGE_SCOPE,
    TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID,
    TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_SCOPE,
    TopologyTransformerHarmonicCurrentAuthorityResult,
    TransformerHarmonicCurrentSpectrumAuthority,
    _validate_result,
    resolve_transformer_harmonic_current_authority,
)


def _equipment(identifier: str) -> TransformerStaticEquipmentAuthority:
    return TransformerStaticEquipmentAuthority(
        identifier,
        "two_winding",
        "balanced_three_phase",
        "line_to_line_rms",
        500_000.0,
        400.0,
        11_000.0,
        f"nameplate:{identifier}",
        "high",
    )


def _topology(identifier: str, exit_id: str) -> TransformerBoundaryTopologyAuthority:
    return TransformerBoundaryTopologyAuthority(
        identifier,
        exit_id,
        "lv_ac_collection_exit",
        f"{identifier}:collection",
        "transformer_collection_side_terminal",
        f"{identifier}:network",
        "transformer_network_side_terminal",
        "direct_electrical_boundary",
        f"drawing:{identifier}",
        "high",
    )


def _spectrum(
    identifier: str = "tx-1",
    *,
    ratios: dict[int, float] | None = None,
    plane: str = "transformer_collection_side_terminal",
    evidence_kind: str = "site_power_quality_measurement_at_transformer_terminal",
    applicability: str = "single_declared_operating_condition",
    frequency: float = 50.0,
) -> TransformerHarmonicCurrentSpectrumAuthority:
    return TransformerHarmonicCurrentSpectrumAuthority(
        identifier,
        plane,  # type: ignore[arg-type]
        "balanced_three_phase_representative_line_current",
        "per_harmonic_rms_current_ratio_to_fundamental_rms_current",
        frequency,
        {1: 1.0} if ratios is None else ratios,
        evidence_kind,  # type: ignore[arg-type]
        applicability,  # type: ignore[arg-type]
        "declared 100 percent load operating condition",
        f"pq-report:{identifier}",
        "high",
    )


def _context(
    ids: tuple[str, ...] = ("tx-1",), *, partial: str | None = None
) -> dict[str, Any]:
    topology = ElectricalTopologyConfig(inverters=[])
    basis = LvAcCollectionNetworkBasisAuthority(
        "balanced_three_phase", "line_to_line_rms", "per_phase_series", "basis", "high"
    )
    nodes = {
        f"exit-{position}": LvAcCollectionNodeAuthority(
            f"exit-{position}", "collection_exit", "drawing", "high"
        )
        for position, _ in enumerate(ids)
    }
    collection = resolve_topology_lv_ac_collection_authority(topology, basis, nodes, {}, {})
    equipment = {
        identifier: _equipment(identifier) for identifier in ids if partial != "topology-only"
    }
    boundaries = {
        identifier: _topology(identifier, f"exit-{position}")
        for position, identifier in enumerate(ids)
        if partial != "equipment-only"
    }
    static = resolve_transformer_static_authority(
        topology, basis, nodes, {}, {}, collection, equipment, boundaries
    )
    return locals()


def _resolve(
    *,
    ids: tuple[str, ...] = ("tx-1",),
    spectra: dict[str, TransformerHarmonicCurrentSpectrumAuthority] | None = None,
    partial: str | None = None,
    mutations: dict[str, Any] | None = None,
) -> TopologyTransformerHarmonicCurrentAuthorityResult:
    context = _context(ids, partial=partial)
    inputs = {
        "topology": context["topology"],
        "network_basis": context["basis"],
        "node_authority_by_id": context["nodes"],
        "segment_authority_by_id": {},
        "inverter_terminal_binding_by_inverter_id": {},
        "lv_ac_collection_authority": context["collection"],
        "transformer_equipment_by_id": context["equipment"],
        "transformer_topology_by_id": context["boundaries"],
        "transformer_static_authority": context["static"],
        "transformer_harmonic_current_spectrum_by_id": spectra or {},
    }
    inputs.update(mutations or {})
    return resolve_transformer_harmonic_current_authority(**cast(Any, inputs))


def test_pure_fundamental_characterisation() -> None:
    row = _resolve(spectra={"tx-1": _spectrum()}).transformer_states.iloc[0]
    assert row["transformer_harmonic_current_characterisation_resolved"]
    assert row["current_thd_ratio"] == 0.0
    assert row["current_thd_percent"] == 0.0
    assert row["total_rms_current_to_fundamental_ratio"] == 1.0
    assert row["fundamental_current_fraction_of_total_rms"] == 1.0
    assert row["winding_eddy_harmonic_loss_factor"] == 1.0
    assert row["other_stray_harmonic_loss_factor"] == 1.0
    assert row["load_current_k_factor"] == 1.0


def test_synthetic_spectrum_matches_independent_physics() -> None:
    ratios = {1: 1.0, 5: 0.10, 7: 0.05}
    row = _resolve(spectra={"tx-1": _spectrum(ratios=ratios)}).transformer_states.iloc[0]
    denominator = 1.0**2 + 0.10**2 + 0.05**2
    nonfundamental = 0.10**2 + 0.05**2
    eddy_numerator = 1.0**2 * 1**2 + 0.10**2 * 5**2 + 0.05**2 * 7**2
    osl_numerator = 1.0**2 * 1**0.8 + 0.10**2 * 5**0.8 + 0.05**2 * 7**0.8
    assert row["sum_current_ratio_squared"] == pytest.approx(denominator)
    assert row["nonfundamental_sum_current_ratio_squared"] == pytest.approx(nonfundamental)
    assert row["current_thd_ratio"] == pytest.approx(math.sqrt(nonfundamental))
    assert row["total_rms_current_to_fundamental_ratio"] == pytest.approx(
        math.sqrt(denominator)
    )
    assert row["winding_eddy_harmonic_loss_factor"] == pytest.approx(
        eddy_numerator / denominator
    )
    assert row["other_stray_harmonic_loss_factor"] == pytest.approx(
        osl_numerator / denominator
    )
    assert row["load_current_k_factor"] == row["winding_eddy_harmonic_loss_factor"]
    assert row["load_current_k_factor_semantics"] == LOAD_CURRENT_K_FACTOR_SEMANTICS
    assert "not_transformer_nameplate_k_rating" in row["load_current_k_factor_semantics"]


@pytest.mark.parametrize(
    ("plane", "terminal", "side"),
    [
        ("transformer_collection_side_terminal", "tx-1:collection", "collection_side"),
        ("transformer_network_side_terminal", "tx-1:network", "network_side"),
    ],
)
def test_reference_plane_selects_exact_canonical_terminal(
    plane: str, terminal: str, side: str
) -> None:
    row = _resolve(spectra={"tx-1": _spectrum(plane=plane)}).transformer_states.iloc[0]
    assert row["harmonic_current_reference_terminal_id"] == terminal
    assert row["harmonic_current_reference_side"] == side


def test_spectrum_is_sorted_immutable_and_detached_from_caller() -> None:
    original = {7: 0.05, 1: 1.0, 5: 0.1}
    authority = _spectrum(ratios=original)
    original.clear()
    assert tuple(authority.harmonic_current_ratio_by_order.items()) == (
        (1, 1.0),
        (5, 0.1),
        (7, 0.05),
    )
    assert type(authority.harmonic_current_ratio_by_order) is MappingProxyType
    with pytest.raises(TypeError):
        authority.harmonic_current_ratio_by_order[3] = 0.1  # type: ignore[index]


def test_zero_higher_harmonics_are_valid() -> None:
    row = _resolve(
        spectra={"tx-1": _spectrum(ratios={1: 1.0, 5: 0.0, 7: 0.0})}
    ).transformer_states.iloc[0]
    assert row["transformer_harmonic_current_characterisation_resolved"]
    assert row["harmonic_order_count"] == 3
    assert row["highest_harmonic_order"] == 7
    assert row["current_thd_ratio"] == 0.0


def test_missing_spectrum_state() -> None:
    row = _resolve().transformer_states.iloc[0]
    assert row["transformer_harmonic_current_authority_state"] == (
        "unresolved_missing_transformer_harmonic_current_spectrum_authority"
    )
    assert math.isnan(row["current_thd_ratio"])


def test_unresolved_static_preserves_spectrum_evidence() -> None:
    authority = _spectrum()
    result = _resolve(partial="topology-only", spectra={"tx-1": authority})
    row = result.transformer_states.iloc[0]
    assert row["transformer_harmonic_current_authority_state"] == (
        "unresolved_upstream_transformer_static_authority"
    )
    assert row["evidence_kind"] == authority.evidence_kind
    assert row["harmonic_spectrum_parameter_source"] == authority.parameter_source
    assert result.harmonic_current_spectrum_by_id["tx-1"] == authority


@pytest.mark.parametrize("order", [0, -1, True, 1.5, "5"])
def test_invalid_harmonic_orders_rejected(order: object) -> None:
    with pytest.raises(ValueError):
        _spectrum(ratios=cast(Any, {1: 1.0, order: 0.1}))


@pytest.mark.parametrize("fundamental", [0.0, 0.99, 100.0, math.nan, math.inf])
def test_invalid_fundamental_ratio_rejected(fundamental: float) -> None:
    with pytest.raises(ValueError):
        _spectrum(ratios={1: fundamental})


def test_missing_fundamental_rejected() -> None:
    with pytest.raises(ValueError):
        _spectrum(ratios={5: 0.1})


@pytest.mark.parametrize("ratio", [-0.1, True, math.nan, math.inf, -math.inf, "0.1"])
def test_invalid_higher_harmonic_ratios_rejected(ratio: object) -> None:
    with pytest.raises(ValueError):
        _spectrum(ratios=cast(Any, {1: 1.0, 5: ratio}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("transformer_id", ""),
        ("transformer_id", " tx-1"),
        ("spectrum_reference_plane", "inverter_terminal"),
        ("phase_scope", "per_phase"),
        ("current_spectrum_basis", "percent"),
        ("fundamental_frequency_hz", 0.0),
        ("fundamental_frequency_hz", True),
        ("evidence_kind", "generic_default"),
        ("evidence_kind", "manufacturer_inverter_type_test"),
        ("applicability_semantics", "annual_profile"),
        ("operating_condition_description", " "),
        ("parameter_source", ""),
        ("confidence", "certain"),
    ],
)
def test_invalid_authority_metadata_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_spectrum(), **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "evidence_kind",
    [
        "site_power_quality_measurement_at_transformer_terminal",
        "commissioning_power_quality_test_at_transformer_terminal",
        "documented_engineering_aggregation_to_transformer_terminal",
        "other_documented_transformer_terminal_spectrum",
    ],
)
def test_all_evidence_kinds_resolve(evidence_kind: str) -> None:
    row = _resolve(
        spectra={"tx-1": _spectrum(evidence_kind=evidence_kind)}
    ).transformer_states.iloc[0]
    assert row["transformer_harmonic_current_characterisation_resolved"]


@pytest.mark.parametrize(
    "applicability",
    ["single_declared_operating_condition", "declared_representative_normalized_spectrum"],
)
def test_both_applicability_semantics_resolve_without_time_application(
    applicability: str,
) -> None:
    row = _resolve(
        spectra={"tx-1": _spectrum(applicability=applicability)}
    ).transformer_states.iloc[0]
    assert row["applicability_semantics"] == applicability
    assert row["transformer_harmonic_current_characterisation_resolved"]


def test_extreme_finite_inputs_become_nonfinite_unresolved_without_infinity() -> None:
    huge_order = 10**400
    authority = _spectrum(ratios={1: 1.0, huge_order: 1.0})
    result = _resolve(spectra={"tx-1": authority})
    row = result.transformer_states.iloc[0]
    assert row["transformer_harmonic_current_authority_state"] == (
        "unresolved_nonfinite_harmonic_current_characterisation"
    )
    assert not row["transformer_harmonic_current_characterisation_resolved"]
    assert result.harmonic_current_spectrum_by_id["tx-1"] == authority
    for column in module._FLOAT_COLUMNS:
        value = row[column]
        assert math.isnan(value) or math.isfinite(value)


def test_extreme_finite_ratio_square_overflow_is_unresolved() -> None:
    authority = _spectrum(ratios={1: 1.0, 5: 1.0e308})
    row = _resolve(spectra={"tx-1": authority}).transformer_states.iloc[0]
    assert row["transformer_harmonic_current_authority_state"] == (
        "unresolved_nonfinite_harmonic_current_characterisation"
    )
    assert math.isnan(row["current_thd_percent"])


def test_nonfinite_diagnostic_is_independent_of_upstream_state_precedence() -> None:
    authority = _spectrum(ratios={1: 1.0, 5: 1.0e308})
    result = _resolve(partial="topology-only", spectra={"tx-1": authority})
    assert result.transformer_states.iloc[0][
        "transformer_harmonic_current_authority_state"
    ] == "unresolved_upstream_transformer_static_authority"
    assert result.diagnostics.unresolved_upstream_static_count == 1
    assert result.diagnostics.nonfinite_harmonic_characterisation_count == 1


def test_multiple_transformers_are_sorted_independent_and_immutable() -> None:
    result = _resolve(ids=("tx-b", "tx-a"), spectra={"tx-a": _spectrum("tx-a")})
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-b"]
    assert result.transformer_states.loc[
        "tx-a", "transformer_harmonic_current_characterisation_resolved"
    ]
    assert result.transformer_states.loc[
        "tx-b", "transformer_harmonic_current_authority_state"
    ] == "unresolved_missing_transformer_harmonic_current_spectrum_authority"
    assert type(result.harmonic_current_spectrum_by_id) is MappingProxyType


def test_mapping_validation_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="unknown"):
        _resolve(spectra={"unknown": _spectrum("unknown")})
    with pytest.raises(ValueError, match="key mismatch"):
        _resolve(spectra={"tx-1": _spectrum("tx-2")})
    with pytest.raises(TypeError, match="invalid value type"):
        _resolve(spectra=cast(Any, {"tx-1": object()}))
    with pytest.raises(TypeError, match="must be a mapping"):
        _resolve(spectra=cast(Any, [_spectrum()]))


def test_strong_s12a_replay_rejects_all_tamper_families() -> None:
    context = _context(ids=("tx-b", "tx-a"))
    static = context["static"]
    changed_frame = static.transformer_states.copy(deep=True)
    changed_frame.iloc[0, 0] = not bool(changed_frame.iloc[0, 0])
    reordered = static.transformer_states.iloc[::-1]
    mutations = (
        {"transformer_static_authority": object()},
        {"transformer_static_authority": replace(static, transformer_states=changed_frame)},
        {"transformer_static_authority": replace(static, transformer_states=reordered)},
        {
            "transformer_static_authority": replace(
                static, equipment_by_id=dict(static.equipment_by_id)
            )
        },
        {
            "transformer_static_authority": replace(
                static, topology_by_id=dict(static.topology_by_id)
            )
        },
        {
            "transformer_static_authority": replace(
                static,
                diagnostics=replace(static.diagnostics, transformer_record_count=999),
            )
        },
    )
    for mutation in mutations:
        with pytest.raises(ValueError):
            _resolve(ids=("tx-b", "tx-a"), mutations=mutation)


def test_result_validator_rejects_every_output_family_and_diagnostics() -> None:
    context = _context()
    result = _resolve(spectra={"tx-1": _spectrum(ratios={1: 1.0, 5: 0.1})})
    for column in result.transformer_states.columns:
        frame = result.transformer_states.copy(deep=True)
        value = frame.loc["tx-1", column]
        replacement: object
        if frame[column].dtype == bool:
            replacement = not bool(value)
        elif isinstance(value, str):
            replacement = "tampered"
        elif isinstance(value, int):
            replacement = value + 1
        else:
            replacement = 999.0
        frame.loc["tx-1", column] = replacement
        with pytest.raises(RuntimeError):
            _validate_result(
                context["static"],
                result.harmonic_current_spectrum_by_id,
                replace(result, transformer_states=frame),
            )
    with pytest.raises(RuntimeError):
        _validate_result(
            context["static"],
            result.harmonic_current_spectrum_by_id,
            replace(result, diagnostics=replace(result.diagnostics, transformer_count=99)),
        )
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(
            context["static"],
            result.harmonic_current_spectrum_by_id,
            replace(
                result,
                harmonic_current_spectrum_by_id=dict(result.harmonic_current_spectrum_by_id),
            ),
        )


def test_result_validator_rejects_immutable_mapping_content_and_order_tamper() -> None:
    ids = ("tx-b", "tx-a")
    spectra = {identifier: _spectrum(identifier) for identifier in ids}
    context = _context(ids)
    result = _resolve(ids=ids, spectra=spectra)
    reversed_mapping = MappingProxyType(
        dict(reversed(tuple(result.harmonic_current_spectrum_by_id.items())))
    )
    with pytest.raises(RuntimeError, match="mapping"):
        _validate_result(
            context["static"],
            result.harmonic_current_spectrum_by_id,
            replace(result, harmonic_current_spectrum_by_id=reversed_mapping),
        )
    changed = MappingProxyType(
        {
            "tx-a": _spectrum("tx-a", ratios={1: 1.0, 5: 0.2}),
            "tx-b": result.harmonic_current_spectrum_by_id["tx-b"],
        }
    )
    with pytest.raises(RuntimeError, match="mapping"):
        _validate_result(
            context["static"],
            result.harmonic_current_spectrum_by_id,
            replace(result, harmonic_current_spectrum_by_id=changed),
        )


def test_contract_diagnostics_and_scope_exclusions() -> None:
    result = _resolve(spectra={"tx-1": _spectrum()})
    assert TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_CONTRACT_ID.endswith("_v1")
    assert TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_MODEL_ID.endswith("_v1")
    assert "harmonic_loss_correction" in TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_SCOPE
    assert "explicit_normalized" in TRANSFORMER_HARMONIC_CURRENT_AUTHORITY_COVERAGE_SCOPE
    assert HARMONIC_METHOD_REFERENCE_STANDARD == "IEEE C57.110-2018"
    assert sum(count for _, count in result.diagnostics.state_counts) == 1
    source = inspect.getsource(module)
    for forbidden in (
        "transformer_loss_authority",
        "transformer_energisation_authority",
        "transformer_operating_loss",
        "transformer_network_authority",
        "transformer_series_equivalent",
        "transformer_operating_solution",
        "transformer_loss_component_authority",
    ):
        assert forbidden not in source
