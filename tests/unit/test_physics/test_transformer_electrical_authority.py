"""Tests for S12B positive-sequence transformer electrical authority."""

from __future__ import annotations

import inspect
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_electrical_authority as authority_module
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
from heliotelligence.physics.transformer_electrical_authority import (
    TRANSFORMER_ELECTRICAL_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE,
    TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID,
    TRANSFORMER_ELECTRICAL_AUTHORITY_SCOPE,
    TopologyTransformerElectricalAuthorityDiagnostics,
    TransformerPhaseDisplacementAuthority,
    TransformerSeriesImpedanceAuthority,
    TransformerShuntAdmittanceAuthority,
    _validate_result,
    resolve_transformer_electrical_authority,
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
        f"single-line:{transformer_id}",
        "medium",
    )


def _series(
    transformer_id: str = "tx-1", resistance: float = 0.01, reactance: float = 0.04
) -> TransformerSeriesImpedanceAuthority:
    return TransformerSeriesImpedanceAuthority(
        transformer_id,
        "collection_side",
        "per_phase_referred_to_collection_side",
        resistance,
        reactance,
        f"series:{transformer_id}",
        "high",
    )


def _shunt(
    transformer_id: str = "tx-1", conductance: float = 0.0001, susceptance: float = 0.002
) -> TransformerShuntAdmittanceAuthority:
    return TransformerShuntAdmittanceAuthority(
        transformer_id,
        "collection_side",
        "per_phase_referred_to_collection_side",
        "transformer_collection_side_terminal",
        conductance,
        susceptance,
        f"shunt:{transformer_id}",
        "medium",
    )


def _phase(
    transformer_id: str = "tx-1", displacement: float = 30.0
) -> TransformerPhaseDisplacementAuthority:
    return TransformerPhaseDisplacementAuthority(
        transformer_id,
        "balanced_positive_sequence_network_side_relative_to_collection_side",
        displacement,
        f"phase:{transformer_id}",
        "low",
    )


def _parents(
    transformer_ids: tuple[str, ...] = ("tx-1",),
    *,
    partial: str | None = None,
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
        f"exit-{position}": LvAcCollectionNodeAuthority(
            f"exit-{position}", "collection_exit", "drawing", "high"
        )
        for position, _ in enumerate(transformer_ids)
    }
    s11a = resolve_topology_lv_ac_collection_authority(topology, basis, nodes, {}, {})
    equipment = {
        transformer_id: _equipment(transformer_id)
        for transformer_id in transformer_ids
        if partial != "topology-only"
    }
    transformer_topology = {
        transformer_id: _topology(transformer_id, f"exit-{position}")
        for position, transformer_id in enumerate(transformer_ids)
        if partial != "equipment-only"
    }
    static = resolve_transformer_static_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        s11a,
        equipment,
        transformer_topology,
    )
    return topology, basis, nodes, s11a, equipment, transformer_topology, static


def _resolve(
    series: dict[str, TransformerSeriesImpedanceAuthority] | None = None,
    shunt: dict[str, TransformerShuntAdmittanceAuthority] | None = None,
    phase: dict[str, TransformerPhaseDisplacementAuthority] | None = None,
    *,
    transformer_ids: tuple[str, ...] = ("tx-1",),
    partial: str | None = None,
    supplied_static: TopologyTransformerStaticAuthorityResult | None = None,
) -> Any:
    topology, basis, nodes, s11a, equipment, transformer_topology, static = _parents(
        transformer_ids, partial=partial
    )
    return resolve_transformer_electrical_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        s11a,
        equipment,
        transformer_topology,
        supplied_static or static,
        series or {},
        shunt or {},
        phase or {},
    )


def _complete(
    *,
    resistance: float = 0.01,
    reactance: float = 0.04,
    conductance: float = 0.0001,
    susceptance: float = 0.002,
    displacement: float = 30.0,
) -> Any:
    return _resolve(
        {"tx-1": _series(resistance=resistance, reactance=reactance)},
        {"tx-1": _shunt(conductance=conductance, susceptance=susceptance)},
        {"tx-1": _phase(displacement=displacement)},
    )


def _static() -> TopologyTransformerStaticAuthorityResult:
    return _parents()[-1]


def test_complete_positive_sequence_authority_and_provenance() -> None:
    result = _complete()
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_electrical_model_authority_resolved"]
    assert row["transformer_electrical_authority_state"] == (
        "resolved_transformer_electrical_model_authority"
    )
    assert row["series_resistance_ohm_per_phase"] == 0.01
    assert row["series_reactance_ohm_per_phase"] == 0.04
    assert row["shunt_conductance_siemens_per_phase"] == 0.0001
    assert row["magnetizing_susceptance_siemens_per_phase"] == 0.002
    assert row["network_side_phase_displacement_deg"] == 30.0
    assert row["series_parameter_source"] == "series:tx-1"
    assert row["shunt_parameter_source"] == "shunt:tx-1"
    assert row["phase_displacement_parameter_source"] == "phase:tx-1"
    assert row["series_confidence"] == "high"
    assert row["shunt_confidence"] == "medium"
    assert row["phase_displacement_confidence"] == "low"
    assert row["transformer_electrical_authority_contract"] == (
        TRANSFORMER_ELECTRICAL_AUTHORITY_CONTRACT_ID
    )
    assert row["transformer_electrical_authority_model"] == (
        TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID
    )
    assert row["transformer_electrical_authority_scope"] == (TRANSFORMER_ELECTRICAL_AUTHORITY_SCOPE)
    assert row["transformer_electrical_authority_coverage_scope"] == (
        TRANSFORMER_ELECTRICAL_AUTHORITY_COVERAGE_SCOPE
    )


def test_explicit_all_zero_circuit_and_phase_are_resolved_not_missing() -> None:
    result = _complete(
        resistance=0.0,
        reactance=0.0,
        conductance=0.0,
        susceptance=0.0,
        displacement=0.0,
    )
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_electrical_model_authority_resolved"]
    for column in (
        "series_resistance_ohm_per_phase",
        "series_reactance_ohm_per_phase",
        "shunt_conductance_siemens_per_phase",
        "magnetizing_susceptance_siemens_per_phase",
        "network_side_phase_displacement_deg",
    ):
        assert row[column] == 0.0


@pytest.mark.parametrize("displacement", [-180.0, -30.0, 45.0])
def test_canonical_negative_boundary_and_positive_phase(displacement: float) -> None:
    assert (
        _complete(displacement=displacement).transformer_states.loc[
            "tx-1", "network_side_phase_displacement_deg"
        ]
        == displacement
    )


def test_two_transformers_follow_canonical_s12a_order_not_mapping_order() -> None:
    ids = ("tx-z", "tx-a")
    result = _resolve(
        {name: _series(name) for name in reversed(ids)},
        {name: _shunt(name) for name in ids},
        {name: _phase(name) for name in reversed(ids)},
        transformer_ids=ids,
    )
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-z"]
    assert result.diagnostics.electrical_model_resolved_count == 2


@pytest.mark.parametrize(
    ("channels", "state"),
    [
        (("series",), "unresolved_missing_transformer_shunt_admittance_authority"),
        (("shunt",), "unresolved_missing_transformer_series_impedance_authority"),
        (("phase",), "unresolved_missing_transformer_series_impedance_authority"),
        (
            ("series", "shunt"),
            "unresolved_missing_transformer_phase_displacement_authority",
        ),
        ((), "unresolved_missing_transformer_series_impedance_authority"),
    ],
)
def test_partial_channel_authority_preserves_evidence_and_precedence(
    channels: tuple[str, ...], state: str
) -> None:
    result = _resolve(
        {"tx-1": _series()} if "series" in channels else {},
        {"tx-1": _shunt()} if "shunt" in channels else {},
        {"tx-1": _phase()} if "phase" in channels else {},
    )
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_electrical_authority_state"] == state
    assert not row["transformer_electrical_model_authority_resolved"]
    assert bool(row["transformer_series_impedance_authority_present"]) == ("series" in channels)
    if "series" not in channels:
        assert pd.isna(row["series_resistance_ohm_per_phase"])
        assert row["series_parameter_source"] == ""
    if "shunt" not in channels:
        assert pd.isna(row["shunt_conductance_siemens_per_phase"])
        assert row["shunt_placement"] == ""
    if "phase" not in channels:
        assert pd.isna(row["network_side_phase_displacement_deg"])
        assert row["phase_displacement_basis"] == ""


@pytest.mark.parametrize("partial", ["equipment-only", "topology-only"])
def test_complete_electrical_evidence_does_not_repair_partial_s12a(partial: str) -> None:
    result = _resolve(
        {"tx-1": _series()},
        {"tx-1": _shunt()},
        {"tx-1": _phase()},
        partial=partial,
    )
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_series_impedance_authority_present"]
    assert row["transformer_shunt_admittance_authority_present"]
    assert row["transformer_phase_displacement_authority_present"]
    assert not row["transformer_static_authority_resolved"]
    assert row["transformer_electrical_authority_state"] == (
        "unresolved_upstream_transformer_static_authority"
    )


def test_empty_s12a_and_s12b_are_stable_and_do_not_fabricate_rows() -> None:
    result = _resolve({}, {}, {}, transformer_ids=())
    assert result.transformer_states.empty
    assert result.transformer_states.index.name == "transformer_id"
    assert result.diagnostics.transformer_record_count == 0
    assert type(result.series_impedance_by_id).__name__ == "mappingproxy"
    for column in result.transformer_states.columns:
        expected = (
            "bool"
            if column.startswith("transformer_") and column.endswith(("resolved", "present"))
            else "float64"
            if column
            in {
                "series_resistance_ohm_per_phase",
                "series_reactance_ohm_per_phase",
                "shunt_conductance_siemens_per_phase",
                "magnetizing_susceptance_siemens_per_phase",
                "network_side_phase_displacement_deg",
            }
            else "object"
        )
        assert str(result.transformer_states[column].dtype) == expected


def test_output_ownership_and_caller_mutation_isolation() -> None:
    series = {"tx-1": _series()}
    shunt = {"tx-1": _shunt()}
    phase = {"tx-1": _phase()}
    first = _resolve(series, shunt, phase)
    second = _resolve(series, shunt, phase)
    series.clear()
    shunt.clear()
    phase.clear()
    first.transformer_states.loc["tx-1", "series_resistance_ohm_per_phase"] = 99.0
    assert type(second.series_impedance_by_id).__name__ == "mappingproxy"
    assert type(second.shunt_admittance_by_id).__name__ == "mappingproxy"
    assert type(second.phase_displacement_by_id).__name__ == "mappingproxy"
    assert second.transformer_states.loc["tx-1", "series_resistance_ohm_per_phase"] == 0.01


@pytest.mark.parametrize(
    ("authority", "field"),
    [
        ("series", "series_resistance_ohm_per_phase"),
        ("series", "series_reactance_ohm_per_phase"),
        ("shunt", "shunt_conductance_siemens_per_phase"),
        ("shunt", "magnetizing_susceptance_siemens_per_phase"),
    ],
)
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), float("-inf"), True])
def test_series_and_shunt_numeric_domains(authority: str, field: str, value: object) -> None:
    original: Any = _series() if authority == "series" else _shunt()
    with pytest.raises(ValueError):
        replace(original, **{field: value})


@pytest.mark.parametrize("value", [-180.1, 180.0, 390.0, float("nan"), float("inf"), True])
def test_phase_domain_rejects_noncanonical_or_nonfinite_values(value: object) -> None:
    with pytest.raises(ValueError):
        _phase(displacement=cast(float, value))


@pytest.mark.parametrize(
    ("authority", "field", "value"),
    [
        ("series", "transformer_id", " tx-1"),
        ("series", "parameter_reference_side", "network_side"),
        ("series", "series_impedance_basis", "per_unit"),
        ("series", "parameter_source", " "),
        ("series", "confidence", "certain"),
        ("shunt", "parameter_reference_side", "network_side"),
        ("shunt", "shunt_admittance_basis", "total_three_phase"),
        ("shunt", "shunt_placement", "network_terminal"),
        ("shunt", "parameter_source", " source "),
        ("shunt", "confidence", "certain"),
        ("phase", "phase_displacement_basis", "clock_notation"),
        ("phase", "parameter_source", ""),
        ("phase", "confidence", "certain"),
    ],
)
def test_authority_identity_basis_source_and_confidence_rejection(
    authority: str, field: str, value: str
) -> None:
    original: Any = {"series": _series(), "shunt": _shunt(), "phase": _phase()}[authority]
    with pytest.raises(ValueError):
        replace(original, **{field: value})


def test_mapping_key_type_and_known_s12a_universe_closure() -> None:
    with pytest.raises(ValueError, match="mapping key"):
        _resolve({"wrong": _series()}, {}, {})
    with pytest.raises(TypeError, match="value type"):
        _resolve(cast(Any, {"tx-1": {}}), {}, {})
    with pytest.raises(ValueError, match="unknown S12A"):
        _resolve({"unknown": _series("unknown")}, {}, {})
    with pytest.raises(ValueError, match="unknown S12A"):
        _resolve({}, {"unknown": _shunt("unknown")}, {})
    with pytest.raises(ValueError, match="unknown S12A"):
        _resolve({}, {}, {"unknown": _phase("unknown")})


@pytest.mark.parametrize(
    "field", ["equipment_by_id", "topology_by_id", "transformer_states", "diagnostics"]
)
def test_strong_s12a_replay_rejects_parent_tampering(field: str) -> None:
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
        _resolve({}, {}, {}, supplied_static=tampered)


@pytest.mark.parametrize("field", ["equipment_by_id", "topology_by_id"])
def test_strong_s12a_replay_rejects_mutable_equal_parent_mappings(field: str) -> None:
    static = _static()
    tampered = replace(static, **cast(Any, {field: dict(getattr(static, field))}))
    with pytest.raises(ValueError, match="immutable canonical replay"):
        _resolve({}, {}, {}, supplied_static=tampered)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("series_resistance_ohm_per_phase", 99.0),
        ("series_reactance_ohm_per_phase", 99.0),
        ("series_impedance_basis", "tampered"),
        ("transformer_series_impedance_authority_present", False),
        ("shunt_conductance_siemens_per_phase", 99.0),
        ("magnetizing_susceptance_siemens_per_phase", 99.0),
        ("shunt_placement", "tampered"),
        ("transformer_shunt_admittance_authority_present", False),
        ("network_side_phase_displacement_deg", 99.0),
        ("phase_displacement_basis", "tampered"),
        ("transformer_phase_displacement_authority_present", False),
        ("transformer_static_authority_resolved", False),
        ("transformer_electrical_model_authority_resolved", False),
        ("transformer_electrical_authority_state", "tampered"),
        ("series_parameter_source", "tampered"),
        ("series_confidence", "unknown"),
        ("shunt_parameter_source", "tampered"),
        ("shunt_confidence", "unknown"),
        ("phase_displacement_parameter_source", "tampered"),
        ("phase_displacement_confidence", "unknown"),
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
        "transformer_record_count",
        "static_authority_resolved_count",
        "static_authority_unresolved_count",
        "series_impedance_authority_count",
        "shunt_admittance_authority_count",
        "phase_displacement_authority_count",
        "electrical_model_resolved_count",
        "unresolved_upstream_static_count",
        "unresolved_missing_series_count",
        "unresolved_missing_shunt_count",
        "unresolved_missing_phase_displacement_count",
    ],
)
def test_private_validator_rejects_diagnostic_tampering(field: str) -> None:
    result = _complete()
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(_static(), replace(result, diagnostics=diagnostics))


@pytest.mark.parametrize(
    "field", ["series_impedance_by_id", "shunt_admittance_by_id", "phase_displacement_by_id"]
)
def test_private_validator_rejects_mutable_result_mappings(field: str) -> None:
    result = _complete()
    tampered = replace(result, **cast(Any, {field: dict(getattr(result, field))}))
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(_static(), tampered)


def test_no_operating_or_inference_dependencies_and_diagnostics_type() -> None:
    source = inspect.getsource(authority_module)
    for forbidden in (
        "lv_ac_collection_voltage_authority",
        "lv_ac_collection_operating",
        "SiteConfig",
        "wiring_loss_ac_pct",
        "vector_group",
        "impedance_percent",
        "load_loss_w",
        "no_load_loss_w",
        "excitation_current_percent",
        "efficiency_percent",
        "rated_voltage_ratio",
        "tap_position",
    ):
        assert forbidden not in source
    diagnostics = _complete().diagnostics
    assert type(diagnostics) is TopologyTransformerElectricalAuthorityDiagnostics
    assert diagnostics.model == TRANSFORMER_ELECTRICAL_AUTHORITY_MODEL_ID
