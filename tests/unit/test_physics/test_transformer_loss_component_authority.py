"""Tests for S12H transformer construction and load-loss components."""

from __future__ import annotations

import inspect
import math
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_loss_component_authority as module
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
from heliotelligence.physics.transformer_loss_authority import (
    TransformerNoLoadLossAuthority,
    TransformerRatedLoadLossAuthority,
    resolve_transformer_loss_authority,
)
from heliotelligence.physics.transformer_loss_component_authority import (
    REFERENCE_LOAD_LOSS_OWNERSHIP,
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID,
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_COVERAGE_SCOPE,
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID,
    TRANSFORMER_LOSS_COMPONENT_AUTHORITY_SCOPE,
    TransformerAdvancedConstructionAuthority,
    TransformerRatedLoadLossAggregateStrayAuthority,
    TransformerRatedLoadLossComponentAuthority,
    TransformerWindingResolvedLoadLossAuthority,
    _validate_result,
    resolve_transformer_loss_component_authority,
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
        "drawing",
        "high",
    )


def _rated(
    identifier: str = "tx-1",
    *,
    loss: float = 5_000.0,
    side: str = "collection_side",
    temperature: float = 75.0,
    frequency: float = 50.0,
    resolution: float | None = None,
    rounding: str | None = None,
) -> TransformerRatedLoadLossAuthority:
    return TransformerRatedLoadLossAuthority(
        identifier,
        loss,
        side,  # type: ignore[arg-type]
        "rated_current",
        temperature,
        frequency,
        "total_rated_load_loss_including_winding_and_stray",
        f"factory-total:{identifier}",
        "high",
        resolution,
        rounding,  # type: ignore[arg-type]
    )


def _no_load(identifier: str = "tx-1") -> TransformerNoLoadLossAuthority:
    return TransformerNoLoadLossAuthority(
        identifier,
        600.0,
        "collection_side",
        "rated_terminal_voltage",
        "line_to_line_rms",
        50.0,
        "factory-no-load",
        "high",
    )


def _construction(
    identifier: str = "tx-1",
    *,
    summary: str = "copper",
    collection: str | None = None,
    network: str | None = None,
) -> TransformerAdvancedConstructionAuthority:
    return TransformerAdvancedConstructionAuthority(
        identifier,
        "mineral_oil_immersed",
        summary,  # type: ignore[arg-type]
        "electrolytic copper windings",
        "ONAN",
        "crgo_silicon_steel",
        "grain-oriented electrical steel core",
        f"design-record:{identifier}",
        "high",
        collection,  # type: ignore[arg-type]
        f"{collection} collection winding" if collection else None,
        network,  # type: ignore[arg-type]
        f"{network} network winding" if network else None,
    )


def _winding_allocation(
    *,
    collection_i2r: float = 2_000.0,
    network_i2r: float = 1_500.0,
    collection_eddy: float = 400.0,
    network_eddy: float = 300.0,
    temperature: float = 75.0,
    frequency: float = 50.0,
) -> TransformerWindingResolvedLoadLossAuthority:
    return TransformerWindingResolvedLoadLossAuthority(
        "tx-1",
        collection_i2r,
        network_i2r,
        collection_eddy,
        network_eddy,
        temperature,
        frequency,
        "explicit_collection_and_network_winding_i2r_and_eddy_factory_loss_allocation",
        "factory winding loss schedule",
        "high",
    )


def _component(
    identifier: str = "tx-1",
    *,
    i2r: float = 3_500.0,
    eddy: float = 700.0,
    reported: float | None = None,
    side: str = "collection_side",
    temperature: float = 75.0,
    frequency: float = 50.0,
    i2r_resolution: float | None = None,
    eddy_resolution: float | None = None,
    other_resolution: float | None = None,
    rounding: str | None = None,
    winding: TransformerWindingResolvedLoadLossAuthority | None = None,
) -> TransformerRatedLoadLossComponentAuthority:
    return TransformerRatedLoadLossComponentAuthority(
        identifier,
        i2r,
        eddy,
        reported,
        side,  # type: ignore[arg-type]
        "rated_current",
        temperature,
        frequency,
        "rated_total_load_loss_three_component_decomposition_at_factory_reference_condition",
        "manufacturer_design_data",
        f"component-report:{identifier}",
        "high",
        i2r_resolution,
        eddy_resolution,
        other_resolution,
        rounding,  # type: ignore[arg-type]
        winding,
    )


def _aggregate(
    *,
    i2r: float = 3_500.0,
    reported: float | None = None,
    i2r_resolution: float | None = None,
    stray_resolution: float | None = None,
    rounding: str | None = None,
) -> TransformerRatedLoadLossAggregateStrayAuthority:
    return TransformerRatedLoadLossAggregateStrayAuthority(
        "tx-1",
        i2r,
        reported,
        "collection_side",
        "rated_current",
        75.0,
        50.0,
        "rated_total_load_loss_i2r_and_aggregate_stray_at_factory_reference_condition",
        "factory_test_report",
        "aggregate factory evidence",
        "high",
        i2r_resolution,
        stray_resolution,
        rounding,  # type: ignore[arg-type]
    )


def _context(
    ids: tuple[str, ...] = ("tx-1",),
    *,
    rated: dict[str, TransformerRatedLoadLossAuthority] | None = None,
    no_load: dict[str, TransformerNoLoadLossAuthority] | None = None,
    construction: dict[str, TransformerAdvancedConstructionAuthority] | None = None,
    components: dict[
        str,
        TransformerRatedLoadLossComponentAuthority
        | TransformerRatedLoadLossAggregateStrayAuthority,
    ]
    | None = None,
    partial: str | None = None,
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
    s11a = resolve_topology_lv_ac_collection_authority(topology, basis, nodes, {}, {})
    equipment = {
        identifier: _equipment(identifier) for identifier in ids if partial != "topology-only"
    }
    boundaries = {
        identifier: _topology(identifier, f"exit-{position}")
        for position, identifier in enumerate(ids)
        if partial != "equipment-only"
    }
    static = resolve_transformer_static_authority(
        topology, basis, nodes, {}, {}, s11a, equipment, boundaries
    )
    rated = rated or {}
    no_load = no_load or {}
    loss = resolve_transformer_loss_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        s11a,
        equipment,
        boundaries,
        static,
        no_load,
        rated,
    )
    return locals()


def _resolve(
    *,
    ids: tuple[str, ...] = ("tx-1",),
    rated: dict[str, TransformerRatedLoadLossAuthority] | None = None,
    no_load: dict[str, TransformerNoLoadLossAuthority] | None = None,
    construction: dict[str, TransformerAdvancedConstructionAuthority] | None = None,
    components: dict[
        str,
        TransformerRatedLoadLossComponentAuthority
        | TransformerRatedLoadLossAggregateStrayAuthority,
    ]
    | None = None,
    partial: str | None = None,
    mutations: dict[str, Any] | None = None,
) -> Any:
    context = _context(
        ids,
        rated=rated,
        no_load=no_load,
        construction=construction,
        components=components,
        partial=partial,
    )
    inputs = {
        "topology": context["topology"],
        "network_basis": context["basis"],
        "node_authority_by_id": context["nodes"],
        "segment_authority_by_id": {},
        "inverter_terminal_binding_by_inverter_id": {},
        "lv_ac_collection_authority": context["s11a"],
        "transformer_equipment_by_id": context["equipment"],
        "transformer_topology_by_id": context["boundaries"],
        "transformer_static_authority": context["static"],
        "transformer_no_load_loss_by_id": context["no_load"],
        "transformer_rated_load_loss_by_id": context["rated"],
        "transformer_loss_authority": context["loss"],
        "transformer_construction_by_id": context["construction"] or {},
        "transformer_rated_load_loss_component_by_id": context["components"] or {},
    }
    inputs.update(mutations or {})
    return resolve_transformer_loss_component_authority(**cast(Any, inputs))


def _complete(**kwargs: Any) -> Any:
    return _resolve(
        rated={
            "tx-1": _rated(
                **{
                    k: v
                    for k, v in kwargs.items()
                    if k in {"loss", "side", "temperature", "frequency"}
                }
            )
        },
        construction={"tx-1": _construction()},
        components={
            "tx-1": _component(
                **{
                    k: v
                    for k, v in kwargs.items()
                    if k in {"i2r", "eddy", "reported", "side", "temperature", "frequency"}
                }
            )
        },
    )


def test_complete_basis_residual_closes_to_s12b() -> None:
    result = _complete()
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_advanced_loss_basis_resolved"]
    assert row["canonical_other_stray_loss_reference_w"] == 800.0
    assert row["canonical_component_sum_w"] == 5_000.0
    assert row["component_closure_residual_w"] == 0.0
    assert row["cooling_method_code"] == "ONAN"
    assert row["reference_load_loss_ownership"] == REFERENCE_LOAD_LOSS_OWNERSHIP


@pytest.mark.parametrize("side", ["collection_side", "network_side"])
def test_both_reference_sides_resolve(side: str) -> None:
    assert _complete(side=side).transformer_states.iloc[0][
        "transformer_advanced_loss_basis_resolved"
    ]


def test_reported_other_stray_absent_present_and_inconsistent() -> None:
    absent = _complete().transformer_states.iloc[0]
    assert not absent["reported_other_stray_loss_present"]
    assert absent["other_stray_loss_residual_derived"]
    present = _complete(reported=800.0).transformer_states.iloc[0]
    assert present["reported_other_stray_loss_compatible"]
    assert not present["other_stray_loss_residual_derived"]
    near = _complete(reported=800.0000000005).transformer_states.iloc[0]
    assert near["transformer_advanced_loss_basis_resolved"]
    assert near["canonical_other_stray_loss_reference_w"] == 800.0
    incompatible = _complete(reported=801.0).transformer_states.iloc[0]
    assert incompatible["transformer_loss_component_authority_state"] == (
        "unresolved_reported_other_stray_loss_inconsistent_with_s12b_residual"
    )
    assert incompatible["reported_other_stray_loss_w"] == 801.0


def test_equality_roundoff_and_material_exceedance() -> None:
    equal = _complete(i2r=4_300.0, eddy=700.0).transformer_states.iloc[0]
    assert equal["canonical_other_stray_loss_reference_w"] == 0.0
    rounded = _complete(i2r=4_300.000000001, eddy=700.0).transformer_states.iloc[0]
    assert rounded["component_closure_roundoff_adjusted"]
    assert rounded["canonical_other_stray_loss_reference_w"] == 0.0
    exceeded = _complete(i2r=4_301.0, eddy=700.0).transformer_states.iloc[0]
    assert exceeded["transformer_loss_component_authority_state"] == (
        "unresolved_component_i2r_plus_winding_eddy_exceeds_s12b_rated_load_loss"
    )
    assert exceeded["i2r_loss_reference_w"] == 4_301.0
    assert exceeded["s12b_rated_load_loss_w"] == 5_000.0


def test_finite_component_sum_overflow_is_deterministically_unresolved() -> None:
    row = _complete(loss=1.0e308, i2r=1.0e308, eddy=1.0e308).transformer_states.iloc[0]
    assert not row["component_math_compatible"]
    assert math.isnan(row["canonical_other_stray_loss_reference_w"])
    assert row["transformer_loss_component_authority_state"] == (
        "unresolved_component_i2r_plus_winding_eddy_exceeds_s12b_rated_load_loss"
    )


def test_zero_total_loss_rules() -> None:
    assert _complete(loss=0.0, i2r=0.0, eddy=0.0, reported=0.0).transformer_states.iloc[0][
        "transformer_advanced_loss_basis_resolved"
    ]
    row = _complete(loss=0.0, i2r=0.001, eddy=0.0).transformer_states.iloc[0]
    assert not row["component_math_compatible"]


def test_no_load_missing_does_not_gate_components() -> None:
    context = _context(rated={"tx-1": _rated()})
    assert not context["loss"].transformer_states.iloc[0][
        "transformer_factory_loss_authority_resolved"
    ]
    result = _complete()
    assert result.transformer_states.iloc[0]["transformer_advanced_loss_basis_resolved"]


def test_unresolved_static_precedes_preserved_complete_s12h_evidence() -> None:
    row = _resolve(
        partial="topology-only",
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction()},
        components={"tx-1": _component()},
    ).transformer_states.iloc[0]
    assert row["transformer_loss_component_authority_state"] == (
        "unresolved_upstream_transformer_static_authority"
    )
    assert row["transformer_construction_basis_resolved"]
    assert row["transformer_load_loss_component_basis_resolved"]
    assert not row["transformer_advanced_loss_basis_resolved"]
    assert row["s12b_rated_load_loss_w"] == 5_000.0


def test_unresolved_static_gates_winding_advanced_basis_and_reference_values() -> None:
    row = _resolve(
        partial="topology-only",
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(
                summary="mixed_or_other_explicit", collection="copper", network="aluminium"
            )
        },
        components={"tx-1": _component(winding=_winding_allocation())},
    ).transformer_states.iloc[0]
    assert row["transformer_loss_component_authority_state"] == (
        "unresolved_upstream_transformer_static_authority"
    )
    assert not row["transformer_advanced_loss_basis_resolved"]
    assert not row["advanced_component_correction_eligible"]
    assert not row["winding_resolved_advanced_correction_basis_resolved"]
    for column in (
        "collection_winding_i2r_loss_reference_w",
        "network_winding_i2r_loss_reference_w",
        "collection_winding_eddy_current_loss_reference_w",
        "network_winding_eddy_current_loss_reference_w",
    ):
        assert pd.isna(row[column])


@pytest.mark.parametrize(
    ("rated", "construction", "components", "state"),
    [
        (
            {},
            {"tx-1": _construction()},
            {"tx-1": _component()},
            "unresolved_missing_s12b_rated_load_loss_authority",
        ),
        (
            {"tx-1": _rated()},
            {},
            {"tx-1": _component()},
            "unresolved_missing_transformer_advanced_construction_authority",
        ),
        (
            {"tx-1": _rated()},
            {"tx-1": _construction()},
            {},
            "unresolved_missing_transformer_rated_load_loss_component_authority",
        ),
    ],
)
def test_missing_evidence_states(
    rated: dict[str, TransformerRatedLoadLossAuthority],
    construction: dict[str, TransformerAdvancedConstructionAuthority],
    components: dict[str, TransformerRatedLoadLossComponentAuthority],
    state: str,
) -> None:
    row = _resolve(
        rated=rated, construction=construction, components=components
    ).transformer_states.iloc[0]
    assert row["transformer_loss_component_authority_state"] == state


@pytest.mark.parametrize(
    ("rated_kwargs", "component_kwargs", "state"),
    [
        (
            {},
            {"side": "network_side"},
            "unresolved_incompatible_load_loss_component_reference_side",
        ),
        (
            {},
            {"temperature": 85.0},
            "unresolved_incompatible_load_loss_component_reference_temperature",
        ),
        ({}, {"frequency": 60.0}, "unresolved_incompatible_load_loss_component_test_frequency"),
    ],
)
def test_reference_condition_mismatches_preserve_evidence(
    rated_kwargs: dict[str, Any], component_kwargs: dict[str, Any], state: str
) -> None:
    row = _resolve(
        rated={"tx-1": _rated(**rated_kwargs)},
        construction={"tx-1": _construction()},
        components={"tx-1": _component(**component_kwargs)},
    ).transformer_states.iloc[0]
    assert row["transformer_loss_component_authority_state"] == state
    assert row["s12b_rated_load_loss_w"] == 5_000.0
    assert row["i2r_loss_reference_w"] == 3_500.0
    assert row["thermal_construction_family"] == "mineral_oil_immersed"


def test_multiple_transformers_sorted_independent_and_immutable() -> None:
    ids = ("tx-b", "tx-a")
    result = _resolve(
        ids=ids,
        rated={identifier: _rated(identifier) for identifier in ids},
        construction={identifier: _construction(identifier) for identifier in ids},
        components={"tx-a": _component("tx-a")},
    )
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-b"]
    assert result.transformer_states.loc["tx-a", "transformer_advanced_loss_basis_resolved"]
    assert not result.transformer_states.loc["tx-b", "transformer_advanced_loss_basis_resolved"]
    assert type(result.construction_by_id) is MappingProxyType
    with pytest.raises(TypeError):
        result.construction_by_id["x"] = _construction("x")  # type: ignore[index]
    assert type(result.rated_load_loss_component_by_id) is MappingProxyType


def test_caller_mapping_mutation_cannot_change_result() -> None:
    construction = {"tx-1": _construction()}
    components = {"tx-1": _component()}
    result = _resolve(rated={"tx-1": _rated()}, construction=construction, components=components)
    construction.clear()
    components.clear()
    assert tuple(result.construction_by_id) == ("tx-1",)
    assert tuple(result.rated_load_loss_component_by_id) == ("tx-1",)


@pytest.mark.parametrize(
    "field,value",
    [
        ("transformer_id", ""),
        ("transformer_id", " tx-1"),
        ("conductor_material_description", ""),
        ("cooling_method_code", " "),
        ("parameter_source", ""),
        ("confidence", "certain"),
        ("thermal_construction_family", "wet"),
        ("winding_conductor_material", "silver"),
        ("core_material_family", "iron"),
    ],
)
def test_construction_rejects_invalid_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_construction(), **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,value",
    [
        ("i2r_loss_w", -1.0),
        ("i2r_loss_w", True),
        ("winding_eddy_current_loss_w", math.nan),
        ("reported_other_stray_loss_w", math.inf),
        ("reference_temperature_c", -273.15),
        ("reference_temperature_c", True),
        ("reference_temperature_c", math.inf),
        ("test_frequency_hz", 0.0),
        ("test_frequency_hz", True),
        ("test_frequency_hz", -math.inf),
        ("test_current_reference_side", "primary"),
        ("test_current_condition", "nominal"),
        ("component_basis_semantics", "percentages"),
        ("decomposition_method", "estimated"),
        ("parameter_source", " source"),
        ("confidence", "certain"),
    ],
)
def test_component_rejects_invalid_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_component(), **{field: value})  # type: ignore[arg-type]


def test_mapping_rejects_unknown_mismatch_and_wrong_type() -> None:
    with pytest.raises(ValueError, match="unknown"):
        _resolve(construction={"unknown": _construction("unknown")})
    with pytest.raises(ValueError, match="key mismatch"):
        _resolve(construction={"tx-1": _construction("tx-2")})
    with pytest.raises(TypeError, match="invalid value type"):
        _resolve(construction=cast(Any, {"tx-1": object()}))
    with pytest.raises(TypeError, match="must be a mapping"):
        _resolve(construction=cast(Any, [_construction()]))


def test_strong_parent_replay_rejects_frame_mapping_and_diagnostics_tampering() -> None:
    context = _context(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction()},
        components={"tx-1": _component()},
    )
    base = {
        "rated": {"tx-1": _rated()},
        "construction": {"tx-1": _construction()},
        "components": {"tx-1": _component()},
    }
    static_frame = context["static"].transformer_states.copy(deep=True)
    static_frame.iloc[0, 0] = not bool(static_frame.iloc[0, 0])
    loss_frame = context["loss"].transformer_states.copy(deep=True)
    loss_frame.iloc[0, 0] = not bool(loss_frame.iloc[0, 0])
    mutations = (
        {
            "transformer_static_authority": replace(
                context["static"], transformer_states=static_frame
            )
        },
        {
            "transformer_static_authority": replace(
                context["static"], equipment_by_id=dict(context["static"].equipment_by_id)
            )
        },
        {
            "transformer_static_authority": replace(
                context["static"], topology_by_id=dict(context["static"].topology_by_id)
            )
        },
        {
            "transformer_static_authority": replace(
                context["static"],
                diagnostics=replace(context["static"].diagnostics, transformer_record_count=99),
            )
        },
        {"transformer_loss_authority": replace(context["loss"], transformer_states=loss_frame)},
        {
            "transformer_loss_authority": replace(
                context["loss"], rated_load_loss_by_id=dict(context["loss"].rated_load_loss_by_id)
            )
        },
        {
            "transformer_loss_authority": replace(
                context["loss"], no_load_loss_by_id=dict(context["loss"].no_load_loss_by_id)
            )
        },
        {
            "transformer_loss_authority": replace(
                context["loss"],
                diagnostics=replace(context["loss"].diagnostics, transformer_record_count=99),
            )
        },
    )
    for mutation in mutations:
        with pytest.raises(ValueError):
            _resolve(**cast(Any, base), mutations=mutation)


def test_strong_parent_replay_rejects_wrong_types_and_reordered_frames() -> None:
    context = _context(ids=("tx-b", "tx-a"))
    reversed_static_frame = context["static"].transformer_states.iloc[::-1]
    reversed_loss_frame = context["loss"].transformer_states.iloc[::-1]
    for mutation in (
        {"transformer_static_authority": object()},
        {"transformer_loss_authority": object()},
        {
            "transformer_static_authority": replace(
                context["static"], transformer_states=reversed_static_frame
            )
        },
        {
            "transformer_loss_authority": replace(
                context["loss"], transformer_states=reversed_loss_frame
            )
        },
    ):
        with pytest.raises(ValueError):
            _resolve(ids=("tx-b", "tx-a"), mutations=mutation)


def test_validator_rejects_each_contract_family_and_diagnostics_tamper() -> None:
    context = _context(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction()},
        components={"tx-1": _component()},
    )
    result = _complete()
    for column in (
        "s12b_rated_load_loss_w",
        "i2r_loss_reference_w",
        "winding_eddy_current_loss_reference_w",
        "canonical_other_stray_loss_reference_w",
        "canonical_component_sum_w",
        "component_closure_residual_w",
        "component_reference_side_compatible",
        "component_reference_temperature_compatible",
        "component_test_frequency_compatible",
        "component_math_compatible",
        "reported_other_stray_loss_compatible",
        "transformer_construction_basis_resolved",
        "transformer_load_loss_component_basis_resolved",
        "transformer_advanced_loss_basis_resolved",
        "transformer_factory_load_loss_evidence_resolved",
        "source_resolution_authority_present",
        "source_resolution_applied",
        "strict_point_component_closure_resolved",
        "resolution_bounded_closure_resolved",
        "aggregate_stray_basis_resolved",
        "advanced_component_correction_eligible",
        "legacy_homogeneous_conductor_basis_resolved",
        "winding_resolved_conductor_authority_present",
        "winding_resolved_conductor_authority_resolved",
        "winding_resolved_i2r_allocation_authority_present",
        "winding_resolved_i2r_allocation_resolved",
        "winding_i2r_allocation_closure_satisfied",
        "winding_resolved_winding_eddy_allocation_authority_present",
        "winding_resolved_winding_eddy_allocation_resolved",
        "winding_eddy_allocation_closure_satisfied",
        "winding_resolved_advanced_correction_basis_resolved",
        "conductor_authority_basis",
        "factory_load_loss_evidence_fidelity",
        "rated_load_loss_lower_bound_w",
        "derived_other_stray_loss_upper_bound_w",
        "thermal_construction_family",
        "winding_conductor_material",
        "collection_winding_conductor_material",
        "collection_winding_conductor_description",
        "network_winding_conductor_material",
        "network_winding_conductor_description",
        "collection_winding_i2r_loss_reference_w",
        "network_winding_i2r_loss_reference_w",
        "collection_winding_eddy_current_loss_reference_w",
        "network_winding_eddy_current_loss_reference_w",
        "cooling_method_code",
        "core_material_family",
        "construction_parameter_source",
        "construction_confidence",
        "component_parameter_source",
        "component_confidence",
        "decomposition_method",
        "reference_load_loss_ownership",
        "transformer_static_authority_contract",
        "transformer_static_authority_model",
        "transformer_loss_authority_contract",
        "transformer_loss_authority_model",
        "transformer_loss_component_authority_contract",
        "transformer_loss_component_authority_model",
        "transformer_loss_component_authority_scope",
        "transformer_loss_component_authority_coverage_scope",
        "transformer_loss_component_authority_state",
    ):
        frame = result.transformer_states.copy(deep=True)
        original = frame.loc["tx-1", column]
        replacement: object = (
            not bool(original)
            if frame[column].dtype == bool
            else ("tampered" if isinstance(original, str) else 123.0)
        )
        frame.loc["tx-1", column] = replacement
        with pytest.raises(RuntimeError):
            _validate_result(
                context["static"],
                context["loss"],
                result.construction_by_id,
                result.rated_load_loss_component_by_id,
                replace(result, transformer_states=frame),
            )
    for field in (
        "transformer_count",
        "ambiguous_mixed_conductor_basis_count",
        "winding_i2r_closure_failure_count",
        "winding_eddy_closure_failure_count",
        "winding_resolved_advanced_basis_resolved_count",
    ):
        with pytest.raises(RuntimeError):
            _validate_result(
                context["static"],
                context["loss"],
                result.construction_by_id,
                result.rated_load_loss_component_by_id,
                replace(
                    result,
                    diagnostics=replace(result.diagnostics, **{field: 99}),
                ),
            )
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(
            context["static"],
            context["loss"],
            result.construction_by_id,
            result.rated_load_loss_component_by_id,
            replace(result, construction_by_id=dict(result.construction_by_id)),
        )


def test_validator_rejects_reordered_immutable_mappings() -> None:
    ids = ("tx-b", "tx-a")
    constructions = {identifier: _construction(identifier) for identifier in ids}
    components = {identifier: _component(identifier) for identifier in ids}
    rated = {identifier: _rated(identifier) for identifier in ids}
    context = _context(ids, rated=rated, construction=constructions, components=components)
    result = _resolve(ids=ids, rated=rated, construction=constructions, components=components)
    reversed_construction = MappingProxyType(dict(reversed(result.construction_by_id.items())))
    with pytest.raises(RuntimeError, match="mapping"):
        _validate_result(
            context["static"],
            context["loss"],
            result.construction_by_id,
            result.rated_load_loss_component_by_id,
            replace(result, construction_by_id=reversed_construction),
        )


def test_diagnostics_count_all_conditions_independently_of_state_precedence() -> None:
    ids = ("tx-b", "tx-a")
    result = _resolve(
        ids=ids,
        rated={"tx-a": _rated("tx-a")},
        construction={},
        components={"tx-a": _component("tx-a", side="network_side")},
    )
    diagnostics = result.diagnostics
    assert diagnostics.missing_s12b_rated_load_count == 1
    assert diagnostics.missing_construction_count == 2
    assert diagnostics.missing_component_count == 1
    assert diagnostics.incompatible_side_count == 1
    assert sum(count for _, count in diagnostics.state_counts) == diagnostics.transformer_count


def test_contract_constants_and_scope_exclusions() -> None:
    assert TRANSFORMER_LOSS_COMPONENT_AUTHORITY_CONTRACT_ID.endswith("_v1")
    assert TRANSFORMER_LOSS_COMPONENT_AUTHORITY_MODEL_ID.endswith("_v1")
    assert "harmonic_thermal" in TRANSFORMER_LOSS_COMPONENT_AUTHORITY_SCOPE
    assert "three_component" in TRANSFORMER_LOSS_COMPONENT_AUTHORITY_COVERAGE_SCOPE
    source = inspect.getsource(module)
    for forbidden in (
        "transformer_series_equivalent",
        "transformer_operating_loss",
        "transformer_operating_solution",
        "harmonic_spectrum",
        "top_oil_temperature",
        "steinmetz",
        "magnetising_current",
    ):
        assert forbidden not in source


def test_resolution_bounded_explicit_evidence_does_not_gain_advanced_eligibility() -> None:
    result = _resolve(
        rated={"tx-1": _rated(loss=5_000.0, resolution=100.0, rounding="nearest_increment")},
        construction={"tx-1": _construction()},
        components={
            "tx-1": _component(
                i2r=4_600.0,
                eddy=450.0,
                i2r_resolution=100.0,
                eddy_resolution=100.0,
                rounding="nearest_increment",
            )
        },
    )
    row = result.transformer_states.iloc[0]
    assert row["transformer_factory_load_loss_evidence_resolved"]
    assert row["factory_load_loss_evidence_fidelity"] == (
        "explicit_three_component_resolution_bounded"
    )
    assert row["source_resolution_applied"]
    assert not row["transformer_load_loss_component_basis_resolved"]
    assert not row["transformer_advanced_loss_basis_resolved"]
    assert not row["advanced_component_correction_eligible"]
    assert pd.isna(row["canonical_other_stray_loss_reference_w"])


def test_aggregate_stray_exact_preserves_unknown_component_split() -> None:
    result = _resolve(
        rated={"tx-1": _rated(loss=5_000.0)},
        construction={"tx-1": _construction()},
        components={"tx-1": _aggregate(reported=1_500.0)},
    )
    row = result.transformer_states.iloc[0]
    assert row["factory_load_loss_evidence_fidelity"] == "aggregate_stray_exact"
    assert row["derived_aggregate_stray_loss_nominal_w"] == 1_500.0
    assert row["derived_aggregate_stray_loss_lower_bound_w"] == 1_500.0
    assert row["derived_aggregate_stray_loss_upper_bound_w"] == 1_500.0
    assert pd.isna(row["winding_eddy_current_loss_reference_w"])
    assert pd.isna(row["canonical_other_stray_loss_reference_w"])
    assert row["aggregate_stray_basis_resolved"]
    assert row["aggregate_stray_math_compatible"]
    assert row["reported_aggregate_stray_loss_compatible"]
    assert not row["strict_point_component_closure_resolved"]
    assert row["strict_point_factory_evidence_closure_resolved"]
    assert not row["transformer_advanced_loss_basis_resolved"]
    assert not row["advanced_component_correction_eligible"]


def test_aggregate_stray_without_report_is_valid_residual_evidence() -> None:
    row = _resolve(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction()},
        components={"tx-1": _aggregate()},
    ).transformer_states.iloc[0]
    assert row["transformer_factory_load_loss_evidence_resolved"]
    assert row["derived_aggregate_stray_loss_nominal_w"] == 1_500.0


def test_aggregate_stray_resolution_can_admit_nominal_i2r_above_total() -> None:
    row = _resolve(
        rated={"tx-1": _rated(loss=5_000.0, resolution=100.0, rounding="nearest_increment")},
        construction={"tx-1": _construction()},
        components={
            "tx-1": _aggregate(
                i2r=5_050.0,
                i2r_resolution=100.0,
                rounding="nearest_increment",
            )
        },
    ).transformer_states.iloc[0]
    assert row["factory_load_loss_evidence_fidelity"] == ("aggregate_stray_resolution_bounded")
    assert row["source_resolution_applied"]
    assert row["aggregate_stray_math_compatible"]
    assert not row["strict_point_component_closure_resolved"]
    assert not row["strict_point_factory_evidence_closure_resolved"]
    assert not row["transformer_advanced_loss_basis_resolved"]


def test_aggregate_stray_strict_i2r_above_total_is_unresolved() -> None:
    row = _resolve(
        rated={"tx-1": _rated(loss=5_000.0)},
        construction={"tx-1": _construction()},
        components={"tx-1": _aggregate(i2r=5_001.0)},
    ).transformer_states.iloc[0]
    assert row["factory_load_loss_evidence_fidelity"] == "unresolved"
    assert row["transformer_loss_component_authority_state"] == (
        "unresolved_aggregate_i2r_exceeds_s12b_rated_load_loss"
    )
    assert not row["aggregate_stray_math_compatible"]
    assert row["reported_aggregate_stray_loss_compatible"]
    assert not row["transformer_factory_load_loss_evidence_resolved"]


def test_incompatible_exact_aggregate_report_has_aggregate_specific_diagnostics() -> None:
    result = _resolve(
        rated={"tx-1": _rated(loss=5_000.0)},
        construction={"tx-1": _construction()},
        components={"tx-1": _aggregate(i2r=3_500.0, reported=1_700.0)},
    )
    row = result.transformer_states.iloc[0]
    assert row["transformer_loss_component_authority_state"] == (
        "unresolved_reported_aggregate_stray_loss_inconsistent_with_s12b_residual"
    )
    assert row["aggregate_stray_math_compatible"]
    assert not row["reported_aggregate_stray_loss_compatible"]
    assert not row["component_math_compatible"]
    assert not row["reported_other_stray_loss_compatible"]
    assert result.diagnostics.aggregate_stray_math_incompatible_count == 0
    assert result.diagnostics.reported_aggregate_stray_incompatible_count == 1
    assert result.diagnostics.component_math_incompatible_count == 0
    assert result.diagnostics.reported_other_stray_incompatible_count == 0


@pytest.mark.parametrize(
    ("reported", "stray_resolution", "resolved"),
    [(1_700.0, 100.0, False), (1_550.0, 100.0, True)],
)
def test_reported_aggregate_stray_requires_documentary_interval_overlap(
    reported: float, stray_resolution: float, resolved: bool
) -> None:
    row = _resolve(
        rated={"tx-1": _rated(loss=5_000.0, resolution=100.0, rounding="nearest_increment")},
        construction={"tx-1": _construction()},
        components={
            "tx-1": _aggregate(
                reported=reported,
                i2r_resolution=100.0,
                stray_resolution=stray_resolution,
                rounding="nearest_increment",
            )
        },
    ).transformer_states.iloc[0]
    assert bool(row["transformer_factory_load_loss_evidence_resolved"]) is resolved


@pytest.mark.parametrize(("material", "basis"), [("copper", True), ("aluminium", True)])
def test_legacy_homogeneous_conductor_basis_is_preserved(material: str, basis: bool) -> None:
    row = _resolve(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction(summary=material)},
        components={"tx-1": _component()},
    ).transformer_states.iloc[0]
    assert bool(row["legacy_homogeneous_conductor_basis_resolved"]) is basis
    assert row["conductor_authority_basis"] == "legacy_homogeneous"
    assert not row["winding_resolved_conductor_authority_present"]


def test_legacy_mixed_conductor_does_not_invent_winding_split() -> None:
    row = _resolve(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction(summary="mixed_or_other_explicit")},
        components={"tx-1": _component()},
    ).transformer_states.iloc[0]
    assert row["conductor_authority_basis"] == "unresolved_ambiguous"
    assert row["collection_winding_conductor_material"] == ""
    assert row["network_winding_conductor_material"] == ""


def test_conductor_diagnostics_distinguish_missing_ambiguous_and_resolved() -> None:
    missing = _resolve(
        rated={"tx-1": _rated()}, construction={}, components={"tx-1": _component()}
    )
    assert missing.transformer_states.iloc[0]["conductor_authority_basis"] == "missing"
    assert missing.diagnostics.ambiguous_mixed_conductor_basis_count == 0

    mixed = _resolve(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction(summary="mixed_or_other_explicit")},
        components={"tx-1": _component()},
    )
    assert mixed.diagnostics.ambiguous_mixed_conductor_basis_count == 1

    legacy = _complete()
    explicit = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(summary="copper", collection="copper", network="copper")
        },
        components={"tx-1": _component(winding=_winding_allocation())},
    )
    assert legacy.diagnostics.ambiguous_mixed_conductor_basis_count == 0
    assert explicit.diagnostics.ambiguous_mixed_conductor_basis_count == 0


@pytest.mark.parametrize(
    ("summary", "collection", "network"),
    [("copper", "copper", "copper"), ("aluminium", "aluminium", "aluminium")],
)
def test_same_material_winding_construction_resolves(
    summary: str, collection: str, network: str
) -> None:
    row = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(summary=summary, collection=collection, network=network)
        },
        components={"tx-1": _component(winding=_winding_allocation())},
    ).transformer_states.iloc[0]
    assert row["winding_resolved_conductor_authority_resolved"]
    assert row["winding_resolved_advanced_correction_basis_resolved"]


def test_heterogeneous_construction_and_exact_winding_allocation_resolve() -> None:
    result = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(
                summary="mixed_or_other_explicit", collection="copper", network="aluminium"
            )
        },
        components={"tx-1": _component(winding=_winding_allocation())},
    )
    row = result.transformer_states.iloc[0]
    assert row["winding_resolved_i2r_allocation_resolved"]
    assert row["winding_resolved_winding_eddy_allocation_resolved"]
    assert row["collection_winding_i2r_loss_reference_w"] == 2_000.0
    assert row["network_winding_i2r_loss_reference_w"] == 1_500.0
    assert type(result.winding_resolved_load_loss_by_id) is MappingProxyType


def test_winding_allocation_mapping_tampering_is_rejected() -> None:
    context = _context(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(
                summary="mixed_or_other_explicit", collection="copper", network="aluminium"
            )
        },
        components={"tx-1": _component(winding=_winding_allocation())},
    )
    result = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(
                summary="mixed_or_other_explicit", collection="copper", network="aluminium"
            )
        },
        components={"tx-1": _component(winding=_winding_allocation())},
    )
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(
            context["static"],
            context["loss"],
            result.construction_by_id,
            result.rated_load_loss_component_by_id,
            replace(
                result,
                winding_resolved_load_loss_by_id=dict(
                    result.winding_resolved_load_loss_by_id
                ),
            ),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"summary": "copper", "collection": "copper", "network": "aluminium"},
        {"summary": "copper", "collection": "copper", "network": None},
    ],
)
def test_contradictory_or_partial_winding_construction_is_rejected(
    kwargs: dict[str, str | None],
) -> None:
    with pytest.raises(ValueError):
        _construction(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("winding", "i2r_ok", "eddy_ok"),
    [
        (_winding_allocation(collection_i2r=2_001.0), False, True),
        (_winding_allocation(collection_eddy=401.0), True, False),
    ],
)
def test_winding_allocation_requires_independent_exact_component_closure(
    winding: TransformerWindingResolvedLoadLossAuthority, i2r_ok: bool, eddy_ok: bool
) -> None:
    row = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(
                summary="mixed_or_other_explicit", collection="copper", network="aluminium"
            )
        },
        components={"tx-1": _component(winding=winding)},
    ).transformer_states.iloc[0]
    assert bool(row["winding_resolved_i2r_allocation_resolved"]) is i2r_ok
    assert bool(row["winding_resolved_winding_eddy_allocation_resolved"]) is eddy_ok
    assert not row["winding_resolved_advanced_correction_basis_resolved"]
    assert pd.isna(row["collection_winding_i2r_loss_reference_w"])


def test_reference_mismatch_does_not_masquerade_as_winding_closure_failure() -> None:
    result = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(summary="copper", collection="copper", network="copper")
        },
        components={
            "tx-1": _component(winding=_winding_allocation(temperature=80.0))
        },
    )
    row = result.transformer_states.iloc[0]
    assert row["winding_i2r_allocation_closure_satisfied"]
    assert row["winding_eddy_allocation_closure_satisfied"]
    assert not row["winding_resolved_i2r_allocation_resolved"]
    assert result.diagnostics.winding_i2r_closure_failure_count == 0
    assert result.diagnostics.winding_eddy_closure_failure_count == 0


@pytest.mark.parametrize(
    ("winding", "i2r_failures", "eddy_failures"),
    [
        (_winding_allocation(collection_i2r=2_001.0), 1, 0),
        (_winding_allocation(collection_eddy=401.0), 0, 1),
    ],
)
def test_winding_closure_diagnostics_measure_only_numerical_sum_failure(
    winding: TransformerWindingResolvedLoadLossAuthority,
    i2r_failures: int,
    eddy_failures: int,
) -> None:
    result = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(summary="copper", collection="copper", network="copper")
        },
        components={"tx-1": _component(winding=winding)},
    )
    assert result.diagnostics.winding_i2r_closure_failure_count == i2r_failures
    assert result.diagnostics.winding_eddy_closure_failure_count == eddy_failures


def test_unresolved_parent_with_exact_winding_sums_has_no_closure_failure() -> None:
    result = _resolve(
        rated={"tx-1": _rated()},
        construction={
            "tx-1": _construction(summary="copper", collection="copper", network="copper")
        },
        components={
            "tx-1": _component(reported=900.0, winding=_winding_allocation())
        },
    )
    assert not result.transformer_states.iloc[0]["transformer_advanced_loss_basis_resolved"]
    assert result.diagnostics.winding_i2r_closure_failure_count == 0
    assert result.diagnostics.winding_eddy_closure_failure_count == 0


def test_s12h_validator_is_independent_of_production_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction()},
        components={"tx-1": _aggregate()},
    )
    result = _resolve(
        rated={"tx-1": _rated()},
        construction={"tx-1": _construction()},
        components={"tx-1": _aggregate()},
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production builder used")

    for name in (
        "_source_interval",
        "_evidence",
        "_winding_evidence",
        "_closure",
        "_build_record",
        "_frame",
        "_diagnostics",
    ):
        monkeypatch.setattr(module, name, fail)
    _validate_result(
        context["static"],
        context["loss"],
        result.construction_by_id,
        result.rated_load_loss_component_by_id,
        result,
    )


def test_winding_validator_is_independent_of_production_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    construction = {
        "tx-1": _construction(
            summary="mixed_or_other_explicit", collection="copper", network="aluminium"
        )
    }
    components = {"tx-1": _component(winding=_winding_allocation())}
    context = _context(
        rated={"tx-1": _rated()}, construction=construction, components=components
    )
    result = _resolve(
        rated={"tx-1": _rated()}, construction=construction, components=components
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production builder used")

    for name in (
        "_source_interval",
        "_evidence",
        "_winding_evidence",
        "_closure",
        "_build_record",
        "_frame",
        "_diagnostics",
    ):
        monkeypatch.setattr(module, name, fail)
    _validate_result(
        context["static"],
        context["loss"],
        result.construction_by_id,
        result.rated_load_loss_component_by_id,
        result,
    )
