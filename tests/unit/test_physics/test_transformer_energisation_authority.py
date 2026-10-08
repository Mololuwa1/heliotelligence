"""Tests for S12C timestamped transformer energisation-state authority."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_energisation_authority as module
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
from heliotelligence.physics.transformer_energisation_authority import (
    TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_ENERGISATION_AUTHORITY_COVERAGE_SCOPE,
    TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID,
    TRANSFORMER_ENERGISATION_AUTHORITY_SCOPE,
    TopologyTransformerEnergisationAuthorityDiagnostics,
    TransformerEnergisationState,
    _validate_result,
    resolve_transformer_energisation_authority,
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


def _state(
    energised: bool,
    *,
    source: str = "interpreted-scada:evidence",
    confidence: str = "high",
) -> TransformerEnergisationState:
    return TransformerEnergisationState(
        energised,
        "transformer_energised_state",
        source,
        cast(Any, confidence),
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
        topology, basis, nodes, {}, {}, s11a, equipment, transformer_topology
    )
    return topology, basis, nodes, s11a, equipment, transformer_topology, static


def _resolve(
    states: dict[tuple[pd.Timestamp, str], TransformerEnergisationState] | None = None,
    *,
    transformer_ids: tuple[str, ...] = ("tx-1",),
    partial: str | None = None,
    supplied_static: object | None = None,
) -> Any:
    topology, basis, nodes, s11a, equipment, transformer_topology, static = _parents(
        transformer_ids, partial=partial
    )
    return resolve_transformer_energisation_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        s11a,
        equipment,
        transformer_topology,
        static if supplied_static is None else cast(Any, supplied_static),
        states or {},
    )


def test_explicit_true_is_resolved_with_exact_provenance() -> None:
    timestamp = pd.Timestamp("2026-01-01 10:00")
    result = _resolve({(timestamp, "tx-1"): _state(True)})
    row = result.states.loc[(timestamp, "tx-1")]
    assert row["transformer_static_authority_resolved"]
    assert row["transformer_energisation_state_present"]
    assert row["transformer_energisation_authority_resolved"]
    assert bool(row["transformer_energised"]) is True
    assert row["energisation_state_semantics"] == "transformer_energised_state"
    assert row["energisation_parameter_source"] == "interpreted-scada:evidence"
    assert row["energisation_confidence"] == "high"
    assert row["transformer_energisation_authority_state"] == (
        "resolved_transformer_energised"
    )
    assert row["transformer_energisation_authority_contract"] == (
        TRANSFORMER_ENERGISATION_AUTHORITY_CONTRACT_ID
    )
    assert row["transformer_energisation_authority_model"] == (
        TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID
    )
    assert row["transformer_energisation_authority_scope"] == (
        TRANSFORMER_ENERGISATION_AUTHORITY_SCOPE
    )
    assert row["transformer_energisation_authority_coverage_scope"] == (
        TRANSFORMER_ENERGISATION_AUTHORITY_COVERAGE_SCOPE
    )


def test_explicit_false_is_resolved_and_distinct_from_missing() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    result = _resolve(
        {(timestamp, "tx-1"): _state(False, source="operator-confirmed", confidence="medium")},
        transformer_ids=("tx-1", "tx-2"),
    )
    explicit = result.states.loc[(timestamp, "tx-1")]
    missing = result.states.loc[(timestamp, "tx-2")]
    assert explicit["transformer_energisation_state_present"]
    assert explicit["transformer_energisation_authority_resolved"]
    assert bool(explicit["transformer_energised"]) is False
    assert explicit["transformer_energisation_authority_state"] == (
        "resolved_transformer_deenergised"
    )
    assert explicit["energisation_parameter_source"] == "operator-confirmed"
    assert not missing["transformer_energisation_state_present"]
    assert not missing["transformer_energisation_authority_resolved"]
    assert pd.isna(missing["transformer_energised"])
    assert missing["energisation_parameter_source"] == ""
    assert missing["energisation_confidence"] == ""
    assert missing["transformer_energisation_authority_state"] == (
        "unresolved_missing_transformer_energisation_state"
    )


def test_two_transformers_and_two_timestamps_form_canonical_cartesian_frame() -> None:
    early = pd.Timestamp("2026-01-01 10:00")
    late = pd.Timestamp("2026-01-01 11:00")
    supplied = {
        (late, "tx-b"): _state(False),
        (early, "tx-b"): _state(True),
        (early, "tx-a"): _state(False),
    }
    result = _resolve(supplied, transformer_ids=("tx-b", "tx-a"))
    assert result.states.index.tolist() == [
        (early, "tx-a"),
        (early, "tx-b"),
        (late, "tx-a"),
        (late, "tx-b"),
    ]
    assert result.states.index.names == ["timestamp", "transformer_id"]
    assert pd.isna(result.states.loc[(late, "tx-a"), "transformer_energised"])
    assert result.diagnostics.row_count == 4
    assert result.diagnostics.energisation_state_present_count == 3
    assert result.diagnostics.energisation_state_missing_count == 1
    assert result.diagnostics.explicitly_energised_count == 1
    assert result.diagnostics.explicitly_deenergised_count == 2


@pytest.mark.parametrize(
    ("partial", "energised"), [("equipment-only", True), ("topology-only", False)]
)
def test_partial_s12a_does_not_erase_explicit_energisation(
    partial: str, energised: bool
) -> None:
    timestamp = pd.Timestamp("2026-01-01")
    row = _resolve(
        {(timestamp, "tx-1"): _state(energised)}, partial=partial
    ).states.loc[(timestamp, "tx-1")]
    assert not row["transformer_static_authority_resolved"]
    assert row["transformer_energisation_authority_resolved"]
    assert bool(row["transformer_energised"]) is energised


def test_empty_evidence_with_known_transformers_has_stable_empty_frame() -> None:
    result = _resolve({}, transformer_ids=("tx-1", "tx-2"))
    assert result.states.empty
    assert result.states.index.names == ["timestamp", "transformer_id"]
    assert result.diagnostics.transformer_count == 2
    assert result.diagnostics.timestamp_count == 0
    assert result.diagnostics.row_count == 0
    assert type(result.energisation_states_by_key).__name__ == "mappingproxy"
    assert str(result.states["transformer_energised"].dtype) == "boolean"


def test_completely_empty_s12a_and_s12c_are_stable() -> None:
    result = _resolve({}, transformer_ids=())
    assert result.states.empty
    assert result.diagnostics == TopologyTransformerEnergisationAuthorityDiagnostics(
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, TRANSFORMER_ENERGISATION_AUTHORITY_MODEL_ID
    )


@pytest.mark.parametrize(
    "timestamp",
    [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01", tz="Europe/London")],
)
def test_naive_and_timezone_aware_timestamps_are_preserved(timestamp: pd.Timestamp) -> None:
    result = _resolve({(timestamp, "tx-1"): _state(True)})
    assert result.states.index.tolist() == [(timestamp, "tx-1")]
    assert next(iter(result.energisation_states_by_key))[0] == timestamp


def test_mapping_and_dataframe_ownership_are_independent() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    supplied = {(timestamp, "tx-1"): _state(True)}
    first = _resolve(supplied)
    supplied.clear()
    second = _resolve({(timestamp, "tx-1"): _state(True)})
    first.states.loc[(timestamp, "tx-1"), "energisation_parameter_source"] = "tampered"
    assert len(first.energisation_states_by_key) == 1
    assert second.states.loc[(timestamp, "tx-1"), "energisation_parameter_source"] == (
        "interpreted-scada:evidence"
    )
    with pytest.raises(TypeError):
        cast(
            dict[tuple[pd.Timestamp, str], TransformerEnergisationState],
            first.energisation_states_by_key,
        )[(timestamp, "tx-1")] = _state(False)


@pytest.mark.parametrize(
    "energised", [1, 0, "true", "false", None, np.bool_(True)]
)
def test_energised_requires_exact_builtin_bool(energised: object) -> None:
    with pytest.raises(ValueError, match="exact built-in bool"):
        TransformerEnergisationState(
            cast(Any, energised), "transformer_energised_state", "source", "high"
        )


@pytest.mark.parametrize(
    ("semantics", "source", "confidence"),
    [
        ("wrong", "source", "high"),
        ("transformer_energised_state", "", "high"),
        ("transformer_energised_state", " source", "high"),
        ("transformer_energised_state", "source ", "high"),
        ("transformer_energised_state", "source", "certain"),
    ],
)
def test_state_metadata_domain_is_exact(
    semantics: str, source: str, confidence: str
) -> None:
    with pytest.raises(ValueError):
        TransformerEnergisationState(
            True, cast(Any, semantics), source, cast(Any, confidence)
        )


@pytest.mark.parametrize(
    "key",
    [
        "not-a-tuple",
        (pd.Timestamp("2026-01-01"),),
        (pd.Timestamp("2026-01-01"), "tx-1", "extra"),
        ("2026-01-01", "tx-1"),
        (datetime(2026, 1, 1), "tx-1"),
        (pd.NaT, "tx-1"),
        (pd.Timestamp("2026-01-01"), ""),
        (pd.Timestamp("2026-01-01"), " tx-1"),
        (pd.Timestamp("2026-01-01"), "tx-1 "),
        (pd.Timestamp("2026-01-01"), "unknown"),
    ],
)
def test_mapping_key_domain_is_exact(key: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _resolve(cast(Any, {key: _state(True)}))


def test_wrong_state_object_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="exact authority type"):
        _resolve(cast(Any, {(pd.Timestamp("2026-01-01"), "tx-1"): {"energised": True}}))


def test_mixed_naive_and_aware_timestamps_are_rejected_without_normalisation() -> None:
    with pytest.raises(ValueError, match="incompatible timezone"):
        _resolve(
            {
                (pd.Timestamp("2026-01-01"), "tx-1"): _state(True),
                (pd.Timestamp("2026-01-01", tz="UTC"), "tx-1"): _state(False),
            }
        )


def test_unknown_transformer_cannot_be_created_by_s12c() -> None:
    with pytest.raises(ValueError, match="unknown S12A transformer"):
        _resolve({(pd.Timestamp("2026-01-01"), "tx-2"): _state(True)})


def test_parent_wrong_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="result type"):
        _resolve(supplied_static=object())


@pytest.mark.parametrize("mapping_name", ["equipment_by_id", "topology_by_id"])
def test_mutable_but_equal_parent_mapping_is_rejected(mapping_name: str) -> None:
    static = _parents()[-1]
    tampered = (
        replace(static, equipment_by_id=dict(static.equipment_by_id))
        if mapping_name == "equipment_by_id"
        else replace(static, topology_by_id=dict(static.topology_by_id))
    )
    with pytest.raises(ValueError, match="immutable canonical replay"):
        _resolve(supplied_static=tampered)


def test_tampered_parent_frame_and_diagnostics_are_rejected() -> None:
    static = _parents()[-1]
    frame = static.transformer_states.copy(deep=True)
    frame.loc["tx-1", "rated_apparent_power_va"] = 1.0
    with pytest.raises(ValueError, match="transformer states"):
        _resolve(supplied_static=replace(static, transformer_states=frame))
    diagnostics = replace(static.diagnostics, resolved_transformer_count=0)
    with pytest.raises(ValueError, match="diagnostics"):
        _resolve(supplied_static=replace(static, diagnostics=diagnostics))


@pytest.mark.parametrize("mapping_name", ["equipment_by_id", "topology_by_id"])
def test_tampered_parent_mapping_is_rejected(mapping_name: str) -> None:
    static = _parents()[-1]
    altered = dict(getattr(static, mapping_name))
    altered.clear()
    tampered = (
        replace(static, equipment_by_id=MappingProxyType(altered))
        if mapping_name == "equipment_by_id"
        else replace(static, topology_by_id=MappingProxyType(altered))
    )
    with pytest.raises(ValueError, match="canonical replay"):
        _resolve(supplied_static=tampered)


def _valid_result() -> tuple[TopologyTransformerStaticAuthorityResult, Any]:
    timestamp = pd.Timestamp("2026-01-01")
    static = _parents(("tx-1", "tx-2"))[-1]
    result = _resolve(
        {(timestamp, "tx-1"): _state(True), (timestamp, "tx-2"): _state(False)},
        transformer_ids=("tx-1", "tx-2"),
    )
    return static, result


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("transformer_static_authority_resolved", False),
        ("transformer_energisation_state_present", False),
        ("transformer_energisation_authority_resolved", False),
        ("transformer_energised", False),
        ("energisation_state_semantics", "wrong"),
        ("energisation_parameter_source", "wrong"),
        ("energisation_confidence", "low"),
        ("transformer_energisation_authority_state", "wrong"),
        ("transformer_static_authority_contract", "wrong"),
        ("transformer_static_authority_model", "wrong"),
        ("transformer_energisation_authority_contract", "wrong"),
        ("transformer_energisation_authority_model", "wrong"),
        ("transformer_energisation_authority_scope", "wrong"),
        ("transformer_energisation_authority_coverage_scope", "wrong"),
    ],
)
def test_validator_rejects_state_tampering(column: str, value: object) -> None:
    static, result = _valid_result()
    frame = result.states.copy(deep=True)
    frame.iloc[0, frame.columns.get_loc(column)] = value
    with pytest.raises(RuntimeError):
        _validate_result(static, replace(result, states=frame))


@pytest.mark.parametrize(
    "field",
    [
        "transformer_count",
        "static_authority_resolved_transformer_count",
        "timestamp_count",
        "row_count",
        "energisation_state_present_count",
        "energisation_state_missing_count",
        "energisation_authority_resolved_count",
        "energisation_authority_unresolved_count",
        "explicitly_energised_count",
        "explicitly_deenergised_count",
    ],
)
def test_validator_rejects_diagnostic_tampering(field: str) -> None:
    static, result = _valid_result()
    diagnostics = replace(
        result.diagnostics, **{field: getattr(result.diagnostics, field) + 1}
    )
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate_result(static, replace(result, diagnostics=diagnostics))


def test_validator_rejects_mutable_result_mapping() -> None:
    static, result = _valid_result()
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(
            static,
            replace(result, energisation_states_by_key=dict(result.energisation_states_by_key)),
        )


def test_validator_rejects_tampered_index_and_missing_value() -> None:
    static, result = _valid_result()
    frame = result.states.copy(deep=True)
    frame.index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-02"), "tx-1"), (pd.Timestamp("2026-01-01"), "tx-2")],
        names=["timestamp", "transformer_id"],
    )
    with pytest.raises(RuntimeError, match="index/order"):
        _validate_result(static, replace(result, states=frame))


def test_exact_dtypes_for_nonempty_and_missing_rows() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    result = _resolve(
        {(timestamp, "tx-1"): _state(True)}, transformer_ids=("tx-1", "tx-2")
    )
    for column in (
        "transformer_static_authority_resolved",
        "transformer_energisation_state_present",
        "transformer_energisation_authority_resolved",
    ):
        assert str(result.states[column].dtype) == "bool"
    assert str(result.states["transformer_energised"].dtype) == "boolean"
    for column in set(result.states.columns) - {
        "transformer_static_authority_resolved",
        "transformer_energisation_state_present",
        "transformer_energisation_authority_resolved",
        "transformer_energised",
    }:
        assert str(result.states[column].dtype) == "object"


def test_source_contains_no_forbidden_operating_or_inference_dependencies() -> None:
    source = inspect.getsource(module)
    forbidden = (
        "transformer_loss_authority",
        "lv_ac_collection_voltage_authority",
        "lv_ac_collection_operating",
        "inverter_dispatch_selection",
        "wiring_loss_ac_pct",
        "forward_fill",
        "backfill",
        "interpolate",
        "resample",
        "nearest",
        "daylight",
        "irradiance",
        "sun_position",
    )
    for term in forbidden:
        assert term not in source
