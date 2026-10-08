"""Tests for S12B transformer factory-test baseline loss authority."""

from __future__ import annotations

import inspect
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_loss_authority as authority_module
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
from heliotelligence.physics.transformer_loss_authority import (
    TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_LOSS_AUTHORITY_COVERAGE_SCOPE,
    TRANSFORMER_LOSS_AUTHORITY_MODEL_ID,
    TRANSFORMER_LOSS_AUTHORITY_SCOPE,
    TopologyTransformerLossAuthorityDiagnostics,
    TransformerNoLoadLossAuthority,
    TransformerRatedLoadLossAuthority,
    _validate_result,
    resolve_transformer_loss_authority,
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


def _no_load(
    transformer_id: str = "tx-1",
    loss: float = 620.0,
    frequency: float = 50.0,
    side: str = "collection_side",
) -> TransformerNoLoadLossAuthority:
    return TransformerNoLoadLossAuthority(
        transformer_id,
        loss,
        side,  # type: ignore[arg-type]
        "rated_terminal_voltage",
        "line_to_line_rms",
        frequency,
        f"open-circuit-report:{transformer_id}",
        "high",
    )


def _rated_load(
    transformer_id: str = "tx-1",
    loss: float = 5_400.0,
    frequency: float = 50.0,
    temperature: float = 75.0,
    side: str = "network_side",
) -> TransformerRatedLoadLossAuthority:
    return TransformerRatedLoadLossAuthority(
        transformer_id,
        loss,
        side,  # type: ignore[arg-type]
        "rated_current",
        temperature,
        frequency,
        "total_rated_load_loss_including_winding_and_stray",
        f"load-loss-report:{transformer_id}",
        "medium",
    )


def _parents(
    transformer_ids: tuple[str, ...] = ("tx-1",), *, partial: str | None = None
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
    no_load: dict[str, TransformerNoLoadLossAuthority] | None = None,
    rated_load: dict[str, TransformerRatedLoadLossAuthority] | None = None,
    *,
    transformer_ids: tuple[str, ...] = ("tx-1",),
    partial: str | None = None,
    supplied_static: TopologyTransformerStaticAuthorityResult | None = None,
) -> Any:
    topology, basis, nodes, s11a, equipment, transformer_topology, static = _parents(
        transformer_ids, partial=partial
    )
    return resolve_transformer_loss_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        s11a,
        equipment,
        transformer_topology,
        supplied_static or static,
        no_load or {},
        rated_load or {},
    )


def _complete(no_load_loss: float = 620.0, rated_load_loss: float = 5_400.0) -> Any:
    return _resolve(
        {"tx-1": _no_load(loss=no_load_loss)},
        {"tx-1": _rated_load(loss=rated_load_loss)},
    )


def _static() -> TopologyTransformerStaticAuthorityResult:
    return _parents()[-1]


def test_complete_factory_test_authority_preserves_conditions_and_provenance() -> None:
    result = _complete()
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_factory_loss_authority_resolved"]
    assert row["transformer_loss_authority_state"] == (
        "resolved_transformer_factory_loss_authority"
    )
    assert row["no_load_loss_w"] == 620.0
    assert row["rated_load_loss_w"] == 5_400.0
    assert row["no_load_test_reference_side"] == "collection_side"
    assert row["load_loss_test_current_reference_side"] == "network_side"
    assert row["no_load_test_frequency_hz"] == 50.0
    assert row["load_loss_test_frequency_hz"] == 50.0
    assert row["load_loss_reference_temperature_c"] == 75.0
    assert row["load_loss_semantics"] == ("total_rated_load_loss_including_winding_and_stray")
    assert row["no_load_parameter_source"] == "open-circuit-report:tx-1"
    assert row["rated_load_parameter_source"] == "load-loss-report:tx-1"
    assert row["no_load_confidence"] == "high"
    assert row["rated_load_confidence"] == "medium"
    assert row["transformer_loss_authority_contract"] == TRANSFORMER_LOSS_AUTHORITY_CONTRACT_ID
    assert row["transformer_loss_authority_model"] == TRANSFORMER_LOSS_AUTHORITY_MODEL_ID
    assert row["transformer_loss_authority_scope"] == TRANSFORMER_LOSS_AUTHORITY_SCOPE
    assert row["transformer_loss_authority_coverage_scope"] == (
        TRANSFORMER_LOSS_AUTHORITY_COVERAGE_SCOPE
    )


@pytest.mark.parametrize(
    ("no_load_loss", "rated_load_loss"), [(0.0, 5_400.0), (620.0, 0.0), (0.0, 0.0)]
)
def test_explicit_zero_loss_is_present_and_resolved(
    no_load_loss: float, rated_load_loss: float
) -> None:
    row = _complete(no_load_loss, rated_load_loss).transformer_states.loc["tx-1"]
    assert row["transformer_factory_loss_authority_resolved"]
    assert row["no_load_loss_w"] == no_load_loss
    assert row["rated_load_loss_w"] == rated_load_loss


@pytest.mark.parametrize(
    ("no_load_present", "rated_load_present", "state"),
    [
        (True, False, "unresolved_missing_transformer_rated_load_loss_authority"),
        (False, True, "unresolved_missing_transformer_no_load_loss_authority"),
        (False, False, "unresolved_missing_transformer_no_load_loss_authority"),
    ],
)
def test_partial_and_missing_loss_authority_preserve_missing_not_zero(
    no_load_present: bool, rated_load_present: bool, state: str
) -> None:
    result = _resolve(
        {"tx-1": _no_load()} if no_load_present else {},
        {"tx-1": _rated_load()} if rated_load_present else {},
    )
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_loss_authority_state"] == state
    assert not row["transformer_factory_loss_authority_resolved"]
    if not no_load_present:
        assert pd.isna(row["no_load_loss_w"])
        assert row["no_load_test_reference_side"] == ""
    if not rated_load_present:
        assert pd.isna(row["rated_load_loss_w"])
        assert row["load_loss_semantics"] == ""


@pytest.mark.parametrize("partial", ["equipment-only", "topology-only"])
def test_complete_loss_evidence_does_not_repair_partial_static_authority(partial: str) -> None:
    row = _resolve(
        {"tx-1": _no_load()}, {"tx-1": _rated_load()}, partial=partial
    ).transformer_states.loc["tx-1"]
    assert row["transformer_no_load_loss_authority_present"]
    assert row["transformer_rated_load_loss_authority_present"]
    assert not row["transformer_static_authority_resolved"]
    assert row["transformer_loss_authority_state"] == (
        "unresolved_upstream_transformer_static_authority"
    )


def test_two_transformers_are_independent_and_follow_static_order() -> None:
    ids = ("tx-z", "tx-a")
    no_load = {"tx-z": _no_load("tx-z", 700.0), "tx-a": _no_load("tx-a", 500.0)}
    rated = {
        "tx-a": _rated_load("tx-a", 4_000.0),
        "tx-z": _rated_load("tx-z", 6_000.0),
    }
    result = _resolve(no_load, rated, transformer_ids=ids)
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-z"]
    assert result.transformer_states.loc["tx-a", "no_load_loss_w"] == 500.0
    assert result.transformer_states.loc["tx-z", "rated_load_loss_w"] == 6_000.0


def test_different_test_sides_are_valid_but_equal_frequency_is_required() -> None:
    result = _resolve(
        {"tx-1": _no_load(side="collection_side")},
        {"tx-1": _rated_load(side="network_side")},
    )
    assert result.transformer_states.loc["tx-1", "transformer_factory_loss_authority_resolved"]
    with pytest.raises(ValueError, match="frequencies"):
        _resolve(
            {"tx-1": _no_load(frequency=50.0)},
            {"tx-1": _rated_load(frequency=60.0)},
        )


def test_empty_static_universe_and_empty_loss_authority_are_stable() -> None:
    result = _resolve({}, {}, transformer_ids=())
    assert result.transformer_states.empty
    assert result.transformer_states.index.name == "transformer_id"
    assert result.diagnostics.transformer_record_count == 0
    assert type(result.no_load_loss_by_id).__name__ == "mappingproxy"
    assert type(result.rated_load_loss_by_id).__name__ == "mappingproxy"


def test_output_ownership_and_caller_mutation_isolation() -> None:
    no_load = {"tx-1": _no_load()}
    rated = {"tx-1": _rated_load()}
    first = _resolve(no_load, rated)
    second = _resolve(no_load, rated)
    no_load.clear()
    rated.clear()
    first.transformer_states.loc["tx-1", "no_load_loss_w"] = 1.0
    assert second.transformer_states.loc["tx-1", "no_load_loss_w"] == 620.0
    assert type(second.no_load_loss_by_id).__name__ == "mappingproxy"


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), float("-inf"), True])
@pytest.mark.parametrize("channel", ["no_load", "rated_load"])
def test_loss_numeric_domain_rejection(channel: str, value: object) -> None:
    original: Any = _no_load() if channel == "no_load" else _rated_load()
    field = "no_load_loss_w" if channel == "no_load" else "rated_load_loss_w"
    with pytest.raises(ValueError):
        replace(original, **{field: value})


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), True])
@pytest.mark.parametrize("channel", ["no_load", "rated_load"])
def test_frequency_domain_rejection(channel: str, value: object) -> None:
    original: Any = _no_load() if channel == "no_load" else _rated_load()
    with pytest.raises(ValueError):
        replace(original, test_frequency_hz=value)


@pytest.mark.parametrize("value", [-273.15, -300.0, float("nan"), float("inf"), True])
def test_reference_temperature_domain_rejection(value: object) -> None:
    with pytest.raises(ValueError):
        replace(_rated_load(), reference_temperature_c=cast(float, value))


@pytest.mark.parametrize(
    ("channel", "field", "value"),
    [
        ("no_load", "transformer_id", " tx-1"),
        ("no_load", "test_reference_side", "primary"),
        ("no_load", "test_voltage_condition", "nominal"),
        ("no_load", "test_voltage_basis", "phase"),
        ("no_load", "parameter_source", " "),
        ("no_load", "confidence", "certain"),
        ("rated_load", "test_current_reference_side", "primary"),
        ("rated_load", "test_current_condition", "half_load"),
        ("rated_load", "loss_semantics", "winding_only"),
        ("rated_load", "parameter_source", " source "),
        ("rated_load", "confidence", "certain"),
    ],
)
def test_identity_conditions_source_and_confidence_rejection(
    channel: str, field: str, value: str
) -> None:
    original: Any = _no_load() if channel == "no_load" else _rated_load()
    with pytest.raises(ValueError):
        replace(original, **{field: value})


def test_mapping_key_type_and_known_transformer_closure() -> None:
    with pytest.raises(ValueError, match="mapping key"):
        _resolve({"wrong": _no_load()}, {})
    with pytest.raises(TypeError, match="value type"):
        _resolve(cast(Any, {"tx-1": {}}), {})
    with pytest.raises(ValueError, match="unknown S12A"):
        _resolve({"unknown": _no_load("unknown")}, {})
    with pytest.raises(ValueError, match="unknown S12A"):
        _resolve({}, {"unknown": _rated_load("unknown")})


@pytest.mark.parametrize(
    "field", ["equipment_by_id", "topology_by_id", "transformer_states", "diagnostics"]
)
def test_strong_static_replay_rejects_parent_tampering(field: str) -> None:
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
        _resolve({}, {}, supplied_static=tampered)


@pytest.mark.parametrize("field", ["equipment_by_id", "topology_by_id"])
def test_strong_static_replay_rejects_mutable_equal_mappings(field: str) -> None:
    static = _static()
    tampered = replace(static, **cast(Any, {field: dict(getattr(static, field))}))
    with pytest.raises(ValueError, match="immutable canonical replay"):
        _resolve({}, {}, supplied_static=tampered)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("no_load_loss_w", 1.0),
        ("rated_load_loss_w", 1.0),
        ("no_load_test_frequency_hz", 60.0),
        ("load_loss_test_frequency_hz", 60.0),
        ("load_loss_reference_temperature_c", 20.0),
        ("no_load_test_reference_side", "network_side"),
        ("no_load_test_voltage_condition", "tampered"),
        ("load_loss_test_current_condition", "tampered"),
        ("load_loss_semantics", "tampered"),
        ("transformer_no_load_loss_authority_present", False),
        ("transformer_rated_load_loss_authority_present", False),
        ("transformer_factory_loss_authority_resolved", False),
        ("transformer_loss_authority_state", "tampered"),
        ("no_load_parameter_source", "tampered"),
        ("no_load_confidence", "unknown"),
        ("rated_load_parameter_source", "tampered"),
        ("rated_load_confidence", "unknown"),
        ("transformer_loss_authority_contract", "tampered"),
        ("transformer_loss_authority_model", "tampered"),
        ("transformer_loss_authority_scope", "tampered"),
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
        "no_load_loss_authority_count",
        "rated_load_loss_authority_count",
        "factory_loss_authority_resolved_count",
        "unresolved_upstream_static_count",
        "unresolved_missing_no_load_loss_count",
        "unresolved_missing_rated_load_loss_count",
    ],
)
def test_private_validator_rejects_diagnostic_tampering(field: str) -> None:
    result = _complete()
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(_static(), replace(result, diagnostics=diagnostics))


@pytest.mark.parametrize("field", ["no_load_loss_by_id", "rated_load_loss_by_id"])
def test_private_validator_rejects_mutable_result_mappings(field: str) -> None:
    result = _complete()
    tampered = replace(result, **cast(Any, {field: dict(getattr(result, field))}))
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(_static(), tampered)


def test_no_superseded_or_future_operating_assumptions_and_diagnostics_type() -> None:
    source = inspect.getsource(authority_module)
    for forbidden in (
        "wiring_loss_ac_pct",
        "impedance_percent",
        "load_loss_pct",
        "efficiency_percent",
        "K_factor",
        "harmonic_spectrum",
        "Steinmetz",
        "lv_ac_collection_operating",
        "series_resistance_ohm_per_phase",
        "magnetizing_susceptance_siemens_per_phase",
    ):
        assert forbidden not in source
    diagnostics = _complete().diagnostics
    assert type(diagnostics) is TopologyTransformerLossAuthorityDiagnostics
    assert diagnostics.model == TRANSFORMER_LOSS_AUTHORITY_MODEL_ID
