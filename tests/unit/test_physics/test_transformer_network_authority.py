"""Tests for S12E transformer positive-sequence network authority."""

from __future__ import annotations

import inspect
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_network_authority as authority_module
from heliotelligence.physics.lv_ac_collection_authority import (
    LvAcCollectionNetworkBasisAuthority,
    LvAcCollectionNodeAuthority,
    TopologyLvAcCollectionAuthorityResult,
    resolve_topology_lv_ac_collection_authority,
)
from heliotelligence.physics.transformer_authority import (
    TopologyTransformerStaticAuthorityResult,
    TransformerBoundaryTopologyAuthority,
    TransformerStaticEquipmentAuthority,
    resolve_transformer_static_authority,
)
from heliotelligence.physics.transformer_network_authority import (
    TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_NETWORK_AUTHORITY_COVERAGE_SCOPE,
    TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID,
    TRANSFORMER_NETWORK_AUTHORITY_SCOPE,
    TopologyTransformerNetworkAuthorityDiagnostics,
    TransformerShortCircuitImpedanceAuthority,
    TransformerVoltageTransferAuthority,
    _validate_result,
    resolve_transformer_network_authority,
)


def _basis() -> LvAcCollectionNetworkBasisAuthority:
    return LvAcCollectionNetworkBasisAuthority(
        "balanced_three_phase", "line_to_line_rms", "per_phase_series", "basis", "high"
    )


def _equipment(transformer_id: str) -> TransformerStaticEquipmentAuthority:
    return TransformerStaticEquipmentAuthority(
        transformer_id,
        "two_winding",
        "balanced_three_phase",
        "line_to_line_rms",
        500_000.0,
        400.0,
        11_000.0,
        f"nameplate:{transformer_id}",
        "high",
    )


def _topology(transformer_id: str, exit_id: str) -> TransformerBoundaryTopologyAuthority:
    return TransformerBoundaryTopologyAuthority(
        transformer_id,
        exit_id,
        "lv_ac_collection_exit",
        f"{transformer_id}:collection",
        "transformer_collection_side_terminal",
        f"{transformer_id}:network",
        "transformer_network_side_terminal",
        "direct_electrical_boundary",
        f"drawing:{transformer_id}",
        "medium",
    )


def _transfer(
    transformer_id: str = "tx-1",
    ratio: float = 27.5,
    phase: float = 0.0,
    reference: str = "fixed_non_tapped_transformer_ratio",
) -> TransformerVoltageTransferAuthority:
    return TransformerVoltageTransferAuthority(
        transformer_id,
        "positive_sequence",
        "line_to_line_rms",
        "line_to_line_rms",
        "fixed_effective_no_load_ratio",
        "network_to_collection_line_to_line_voltage_magnitude_ratio",
        reference,  # type: ignore[arg-type]
        ratio,
        "network_side_positive_sequence_voltage_leads_collection_side_positive_deg",
        phase,
        f"ratio-report:{transformer_id}",
        "high",
    )


def _impedance(
    transformer_id: str = "tx-1",
    magnitude: float = 0.06,
    reference: str = "fixed_non_tapped_transformer_ratio",
) -> TransformerShortCircuitImpedanceAuthority:
    return TransformerShortCircuitImpedanceAuthority(
        transformer_id,
        "positive_sequence",
        "total_two_winding_series_short_circuit_impedance_magnitude",
        "per_unit_on_s12a_rated_apparent_power_and_corresponding_rated_terminal_voltage_bases",
        reference,  # type: ignore[arg-type]
        magnitude,
        "rated_current",
        75.0,
        50.0,
        f"short-circuit-report:{transformer_id}",
        "medium",
    )


def _parents(
    transformer_ids: tuple[str, ...] = ("tx-1",), partial: str | None = None
) -> tuple[
    ElectricalTopologyConfig,
    LvAcCollectionNetworkBasisAuthority,
    dict[str, LvAcCollectionNodeAuthority],
    TopologyLvAcCollectionAuthorityResult,
    dict[str, TransformerStaticEquipmentAuthority],
    dict[str, TransformerBoundaryTopologyAuthority],
    TopologyTransformerStaticAuthorityResult,
]:
    topology = ElectricalTopologyConfig(inverters=[])
    basis = _basis()
    nodes = {
        f"exit-{i}": LvAcCollectionNodeAuthority(f"exit-{i}", "collection_exit", "drawing", "high")
        for i, _ in enumerate(transformer_ids)
    }
    s11a = resolve_topology_lv_ac_collection_authority(topology, basis, nodes, {}, {})
    equipment = {
        identifier: _equipment(identifier)
        for identifier in transformer_ids
        if partial != "topology-only"
    }
    tx_topology = {
        identifier: _topology(identifier, f"exit-{i}")
        for i, identifier in enumerate(transformer_ids)
        if partial != "equipment-only"
    }
    static = resolve_transformer_static_authority(
        topology, basis, nodes, {}, {}, s11a, equipment, tx_topology
    )
    return topology, basis, nodes, s11a, equipment, tx_topology, static


def _resolve(
    transfer: dict[str, TransformerVoltageTransferAuthority] | None = None,
    impedance: dict[str, TransformerShortCircuitImpedanceAuthority] | None = None,
    *,
    transformer_ids: tuple[str, ...] = ("tx-1",),
    partial: str | None = None,
    supplied_static: TopologyTransformerStaticAuthorityResult | None = None,
) -> Any:
    topology, basis, nodes, s11a, equipment, tx_topology, static = _parents(
        transformer_ids, partial
    )
    return resolve_transformer_network_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        s11a,
        equipment,
        tx_topology,
        supplied_static or static,
        transfer or {},
        impedance or {},
    )


def _complete(*, partial: str | None = None, ratio: float = 27.5, phase: float = 0.0) -> Any:
    return _resolve(
        {"tx-1": _transfer(ratio=ratio, phase=phase)}, {"tx-1": _impedance()}, partial=partial
    )


def _static() -> TopologyTransformerStaticAuthorityResult:
    return _parents()[-1]


@pytest.mark.parametrize("partial", [None, "equipment-only"])
def test_complete_network_authority_resolves_with_or_without_topology(partial: str | None) -> None:
    result = _complete(partial=partial)
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_positive_sequence_network_authority_resolved"]
    assert (
        row["transformer_network_authority_state"]
        == "resolved_transformer_positive_sequence_network_authority"
    )
    assert row["network_to_collection_voltage_ratio"] == 27.5
    assert row["short_circuit_impedance_magnitude_pu"] == 0.06
    assert bool(row["transformer_topology_authority_present"]) is (partial is None)
    assert (
        row["transformer_network_authority_contract"] == TRANSFORMER_NETWORK_AUTHORITY_CONTRACT_ID
    )
    assert row["transformer_network_authority_model"] == TRANSFORMER_NETWORK_AUTHORITY_MODEL_ID
    assert row["transformer_network_authority_scope"] == TRANSFORMER_NETWORK_AUTHORITY_SCOPE
    assert (
        row["transformer_network_authority_coverage_scope"]
        == TRANSFORMER_NETWORK_AUTHORITY_COVERAGE_SCOPE
    )


@pytest.mark.parametrize("phase", [0.0, 30.0, -30.0, -180.0])
def test_explicit_canonical_phase_displacement_is_preserved(phase: float) -> None:
    assert (
        _complete(phase=phase).transformer_states.loc["tx-1", "network_side_phase_displacement_deg"]
        == phase
    )


@pytest.mark.parametrize("ratio", [27.5, 28.25])
def test_explicit_ratio_need_not_equal_s12a_rated_base_ratio(ratio: float) -> None:
    row = _complete(ratio=ratio).transformer_states.loc["tx-1"]
    assert row["network_to_collection_voltage_ratio"] == ratio
    assert row["transformer_positive_sequence_network_authority_resolved"]


@pytest.mark.parametrize(
    "reference",
    ["fixed_non_tapped_transformer_ratio", "principal_tapping"],
)
def test_explicit_compatible_ratio_reference_conditions_resolve(reference: str) -> None:
    result = _resolve(
        {"tx-1": _transfer(reference=reference)},
        {"tx-1": _impedance(reference=reference)},
    )
    row = result.transformer_states.loc["tx-1"]
    assert row["ratio_reference_condition"] == reference
    assert row["short_circuit_impedance_ratio_reference_condition"] == reference
    assert row["transformer_positive_sequence_network_authority_resolved"]


def test_incompatible_ratio_reference_conditions_preserve_evidence_unresolved() -> None:
    result = _resolve(
        {"tx-1": _transfer(reference="principal_tapping")},
        {"tx-1": _impedance(reference="fixed_non_tapped_transformer_ratio")},
    )
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_voltage_transfer_authority_present"]
    assert row["transformer_short_circuit_impedance_authority_present"]
    assert not row["transformer_positive_sequence_network_authority_resolved"]
    assert row["transformer_network_authority_state"] == (
        "unresolved_incompatible_transformer_transfer_and_impedance_reference_conditions"
    )
    assert result.diagnostics.unresolved_incompatible_reference_conditions_count == 1


def test_reference_condition_is_explicit_and_never_inferred_from_rated_ratio() -> None:
    with pytest.raises(ValueError, match="ratio_reference_condition"):
        replace(_transfer(), ratio_reference_condition=cast(Any, None))
    with pytest.raises(ValueError, match="ratio_reference_condition"):
        replace(_impedance(), ratio_reference_condition=cast(Any, None))
    with pytest.raises(TypeError):
        TransformerShortCircuitImpedanceAuthority(  # type: ignore[call-arg]
            transformer_id="tx-1",
            phase_sequence="positive_sequence",
            impedance_semantics="total_two_winding_series_short_circuit_impedance_magnitude",
            impedance_basis=(
                "per_unit_on_s12a_rated_apparent_power_and_"
                "corresponding_rated_terminal_voltage_bases"
            ),
            short_circuit_impedance_magnitude_pu=0.06,
            test_current_condition="rated_current",
            reference_temperature_c=75.0,
            test_frequency_hz=50.0,
            parameter_source="report",
            confidence="high",
        )


def test_equipment_only_resolution_is_not_static_or_boundary_operating_readiness() -> None:
    row = _complete(partial="equipment-only").transformer_states.loc["tx-1"]
    assert row["transformer_positive_sequence_network_authority_resolved"]
    assert not row["transformer_static_authority_resolved"]
    assert not row["transformer_topology_authority_present"]
    assert not row["transformer_boundary_operating_readiness_established"]


def test_impedance_only_preserves_shared_positive_sequence_evidence() -> None:
    row = _resolve({}, {"tx-1": _impedance()}).transformer_states.loc["tx-1"]
    assert row["phase_sequence"] == "positive_sequence"
    assert row["short_circuit_impedance_ratio_reference_condition"] == (
        "fixed_non_tapped_transformer_ratio"
    )


@pytest.mark.parametrize(
    ("transfer", "impedance", "state"),
    [
        (True, False, "unresolved_missing_transformer_short_circuit_impedance_authority"),
        (False, True, "unresolved_missing_transformer_voltage_transfer_authority"),
        (False, False, "unresolved_missing_transformer_voltage_transfer_authority"),
    ],
)
def test_partial_channels_preserve_missing_not_defaults(
    transfer: bool, impedance: bool, state: str
) -> None:
    result = _resolve(
        {"tx-1": _transfer()} if transfer else {}, {"tx-1": _impedance()} if impedance else {}
    )
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_network_authority_state"] == state
    if not transfer:
        assert pd.isna(row["network_to_collection_voltage_ratio"])
        assert pd.isna(row["network_side_phase_displacement_deg"])
    if not impedance:
        assert pd.isna(row["short_circuit_impedance_magnitude_pu"])


def test_topology_only_preserves_evidence_but_lacks_equipment_basis() -> None:
    row = _complete(partial="topology-only").transformer_states.loc["tx-1"]
    assert (
        row["transformer_voltage_transfer_authority_present"]
        and row["transformer_short_circuit_impedance_authority_present"]
    )
    assert not row["transformer_positive_sequence_network_authority_resolved"]
    assert (
        row["transformer_network_authority_state"]
        == "unresolved_missing_transformer_equipment_basis_authority"
    )


def test_two_transformers_are_independent_sorted_and_preserve_provenance() -> None:
    ids = ("tx-z", "tx-a")
    result = _resolve(
        {"tx-z": _transfer("tx-z", 20.0, 30.0), "tx-a": _transfer("tx-a", 25.0, -30.0)},
        {"tx-a": _impedance("tx-a", 0.04), "tx-z": _impedance("tx-z", 0.08)},
        transformer_ids=ids,
    )
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-z"]
    assert (
        result.transformer_states.loc["tx-z", "voltage_transfer_parameter_source"]
        == "ratio-report:tx-z"
    )
    assert result.transformer_states.loc["tx-a", "short_circuit_impedance_confidence"] == "medium"


def test_empty_universe_and_mapping_ownership_are_stable() -> None:
    empty = _resolve({}, {}, transformer_ids=())
    assert (
        empty.transformer_states.empty and empty.transformer_states.index.name == "transformer_id"
    )
    assert empty.diagnostics.transformer_count == 0
    transfer = {"tx-1": _transfer()}
    impedance = {"tx-1": _impedance()}
    result = _resolve(transfer, impedance)
    transfer.clear()
    impedance.clear()
    assert len(result.voltage_transfer_by_id) == len(result.short_circuit_impedance_by_id) == 1
    assert (
        type(result.voltage_transfer_by_id).__name__
        == type(result.short_circuit_impedance_by_id).__name__
        == "mappingproxy"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network_to_collection_voltage_ratio", 0.0),
        ("network_to_collection_voltage_ratio", -1.0),
        ("network_to_collection_voltage_ratio", True),
        ("network_to_collection_voltage_ratio", float("nan")),
        ("network_to_collection_voltage_ratio", float("inf")),
        ("network_side_phase_displacement_deg", -180.1),
        ("network_side_phase_displacement_deg", 180.0),
        ("network_side_phase_displacement_deg", True),
        ("network_side_phase_displacement_deg", float("nan")),
    ],
)
def test_transfer_numeric_domains_reject_invalid(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_transfer(), **cast(Any, {field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase_sequence", "negative_sequence"),
        ("collection_voltage_basis", "phase"),
        ("network_voltage_basis", "phase"),
        ("ratio_state_semantics", "tap"),
        ("ratio_semantics", "turns_ratio"),
        ("ratio_reference_condition", "unspecified"),
        ("phase_displacement_semantics", "opposite"),
        ("parameter_source", " "),
        ("confidence", "certain"),
        ("transformer_id", " tx-1"),
    ],
)
def test_transfer_semantics_and_provenance_reject_invalid(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        replace(_transfer(), **cast(Any, {field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("short_circuit_impedance_magnitude_pu", 0.0),
        ("short_circuit_impedance_magnitude_pu", -1.0),
        ("short_circuit_impedance_magnitude_pu", True),
        ("short_circuit_impedance_magnitude_pu", float("nan")),
        ("reference_temperature_c", -273.15),
        ("reference_temperature_c", True),
        ("reference_temperature_c", float("inf")),
        ("test_frequency_hz", 0.0),
        ("test_frequency_hz", True),
        ("test_frequency_hz", float("nan")),
    ],
)
def test_impedance_numeric_domains_reject_invalid(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_impedance(), **cast(Any, {field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase_sequence", "zero_sequence"),
        ("impedance_semantics", "leakage"),
        ("impedance_basis", "ohms"),
        ("ratio_reference_condition", "unspecified"),
        ("test_current_condition", "half_current"),
        ("parameter_source", " report "),
        ("confidence", "certain"),
        ("transformer_id", ""),
    ],
)
def test_impedance_semantics_and_provenance_reject_invalid(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        replace(_impedance(), **cast(Any, {field: value}))


def test_mapping_closure_and_unknown_transformers_are_rejected() -> None:
    with pytest.raises(ValueError, match="mapping key"):
        _resolve({"wrong": _transfer()}, {})
    with pytest.raises(TypeError, match="value type"):
        _resolve(cast(Any, {"tx-1": {}}), {})
    with pytest.raises(ValueError, match="unknown S12A"):
        _resolve({"unknown": _transfer("unknown")}, {})
    with pytest.raises(ValueError, match="unknown S12A"):
        _resolve({}, {"unknown": _impedance("unknown")})


@pytest.mark.parametrize(
    "field", ["equipment_by_id", "topology_by_id", "transformer_states", "diagnostics"]
)
def test_strong_static_replay_rejects_tampering(field: str) -> None:
    static = _static()
    if field == "equipment_by_id":
        tampered = replace(static, equipment_by_id=MappingProxyType({}))
    elif field == "topology_by_id":
        tampered = replace(static, topology_by_id=MappingProxyType({}))
    elif field == "transformer_states":
        frame = static.transformer_states.copy(deep=True)
        frame.loc["tx-1", "rated_apparent_power_va"] = 1.0
        tampered = replace(static, transformer_states=frame)
    else:
        tampered = replace(
            static, diagnostics=replace(static.diagnostics, transformer_record_count=99)
        )
    with pytest.raises(ValueError, match="canonical replay"):
        _resolve(supplied_static=tampered)


@pytest.mark.parametrize("field", ["equipment_by_id", "topology_by_id"])
def test_strong_static_replay_rejects_mutable_equal_mapping(field: str) -> None:
    static = _static()
    tampered = replace(static, **cast(Any, {field: dict(getattr(static, field))}))
    with pytest.raises(ValueError, match="immutable canonical replay"):
        _resolve(supplied_static=tampered)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("transformer_equipment_authority_present", False),
        ("transformer_topology_authority_present", False),
        ("transformer_voltage_transfer_authority_present", False),
        ("transformer_short_circuit_impedance_authority_present", False),
        ("transformer_positive_sequence_network_authority_resolved", False),
        ("transformer_boundary_operating_readiness_established", True),
        ("ratio_reference_condition", "principal_tapping"),
        ("network_to_collection_voltage_ratio", 1.0),
        ("network_side_phase_displacement_deg", 1.0),
        ("short_circuit_impedance_magnitude_pu", 0.1),
        ("short_circuit_impedance_ratio_reference_condition", "principal_tapping"),
        ("short_circuit_reference_temperature_c", 20.0),
        ("short_circuit_test_frequency_hz", 60.0),
        ("voltage_transfer_parameter_source", "tampered"),
        ("voltage_transfer_confidence", "unknown"),
        ("short_circuit_impedance_parameter_source", "tampered"),
        ("short_circuit_impedance_confidence", "unknown"),
        ("transformer_network_authority_state", "tampered"),
        ("transformer_network_authority_contract", "tampered"),
        ("transformer_network_authority_model", "tampered"),
        ("transformer_network_authority_scope", "tampered"),
        ("transformer_network_authority_coverage_scope", "tampered"),
    ],
)
def test_private_validator_rejects_state_tampering(column: str, value: object) -> None:
    result = _complete()
    frame = result.transformer_states.copy(deep=True)
    frame.loc["tx-1", column] = value
    with pytest.raises(RuntimeError):
        _validate_result(_static(), replace(result, transformer_states=frame))


@pytest.mark.parametrize(
    "field",
    [
        "transformer_count",
        "equipment_authority_present_count",
        "topology_authority_present_count",
        "static_authority_resolved_count",
        "voltage_transfer_authority_count",
        "short_circuit_impedance_authority_count",
        "positive_sequence_network_authority_resolved_count",
        "unresolved_missing_equipment_basis_count",
        "unresolved_missing_voltage_transfer_count",
        "unresolved_missing_short_circuit_impedance_count",
        "unresolved_incompatible_reference_conditions_count",
    ],
)
def test_private_validator_rejects_diagnostic_tampering(field: str) -> None:
    result = _complete()
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(_static(), replace(result, diagnostics=diagnostics))


@pytest.mark.parametrize("field", ["voltage_transfer_by_id", "short_circuit_impedance_by_id"])
def test_private_validator_rejects_mutable_mapping(field: str) -> None:
    result = _complete()
    tampered = replace(result, **cast(Any, {field: dict(getattr(result, field))}))
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(_static(), tampered)


def test_module_has_no_cross_channel_or_operating_dependencies() -> None:
    source = inspect.getsource(authority_module)
    for forbidden in (
        "transformer_loss_authority",
        "transformer_energisation_authority",
        "transformer_operating_loss",
        "lv_ac_collection_operating",
        "series_resistance",
        "series_reactance",
        "magnetizing",
        "P_LL",
        "beta_I",
        "vector_group",
        "tap_schedule",
        "timestamped_tap",
        "oltc_controller",
    ):
        assert forbidden not in source
    assert type(_complete().diagnostics) is TopologyTransformerNetworkAuthorityDiagnostics
