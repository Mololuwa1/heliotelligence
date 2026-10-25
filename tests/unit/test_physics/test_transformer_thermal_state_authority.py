"""Tests for S12J timestamped transformer thermal-state authority."""

from __future__ import annotations

import datetime as dt
import inspect
import math
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_thermal_state_authority as module
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
from heliotelligence.physics.transformer_loss_authority import resolve_transformer_loss_authority
from heliotelligence.physics.transformer_loss_component_authority import (
    TransformerAdvancedConstructionAuthority,
    TransformerRatedLoadLossComponentAuthority,
    TransformerWindingResolvedLoadLossAuthority,
    resolve_transformer_loss_component_authority,
)
from heliotelligence.physics.transformer_thermal_state_authority import (
    LOAD_LOSS_TEMPERATURE_QUANTITY,
    TRANSFORMER_THERMAL_STATE_AUTHORITY_CONTRACT_ID,
    TopologyTransformerThermalStateAuthorityResult,
    TransformerTemperatureEvidence,
    TransformerThermalState,
    _validate_result,
    resolve_transformer_thermal_state_authority,
)

T1 = pd.Timestamp("2026-01-01T00:00:00Z")
T2 = pd.Timestamp("2026-01-01T01:00:00Z")


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


def _boundary(identifier: str, exit_id: str) -> TransformerBoundaryTopologyAuthority:
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


def _construction(
    identifier: str = "tx-1",
    family: str = "mineral_oil_immersed",
    winding_materials: tuple[str, str] | None = None,
) -> TransformerAdvancedConstructionAuthority:
    summary = (
        "mixed_or_other_explicit"
        if winding_materials and winding_materials[0] != winding_materials[1]
        else winding_materials[0]
        if winding_materials
        else "copper"
    )
    return TransformerAdvancedConstructionAuthority(
        identifier,
        cast(Any, family),
        cast(Any, summary),
        "copper winding",
        "ONAN",
        "crgo_silicon_steel",
        "CRGO core",
        f"design:{identifier}",
        "high",
        cast(Any, winding_materials[0]) if winding_materials else None,
        "collection winding" if winding_materials else None,
        cast(Any, winding_materials[1]) if winding_materials else None,
        "network winding" if winding_materials else None,
    )


def _component(
    identifier: str = "tx-1", *, with_winding_allocation: bool = False
) -> TransformerRatedLoadLossComponentAuthority:
    component = TransformerRatedLoadLossComponentAuthority(
        identifier,
        1.0,
        0.0,
        None,
        "collection_side",
        "rated_current",
        75.0,
        50.0,
        "rated_total_load_loss_three_component_decomposition_at_factory_reference_condition",
        "manufacturer_design_data",
        "component report",
        "high",
    )
    if not with_winding_allocation:
        return component
    return replace(
        component,
        winding_resolved_load_loss_authority=TransformerWindingResolvedLoadLossAuthority(
            identifier,
            0.4,
            0.6,
            0.0,
            0.0,
            75.0,
            50.0,
            "explicit_collection_and_network_winding_i2r_and_eddy_factory_loss_allocation",
            "factory winding allocation",
            "high",
        ),
    )


def _evidence(
    value: float = 70.0,
    kind: str = "direct_sensor_measurement",
    source: str = "sensor:1",
) -> TransformerTemperatureEvidence:
    return TransformerTemperatureEvidence(
        value,
        cast(Any, kind),
        "declared_method",
        source,
        "high",
    )


def _state(
    *,
    ambient: TransformerTemperatureEvidence | None = None,
    average: TransformerTemperatureEvidence | None = None,
    hot_spot: TransformerTemperatureEvidence | None = None,
    top_oil: TransformerTemperatureEvidence | None = None,
    collection: TransformerTemperatureEvidence | None = None,
    network: TransformerTemperatureEvidence | None = None,
) -> TransformerThermalState:
    return TransformerThermalState(
        ambient,
        average,
        hot_spot,
        top_oil,
        "declared operating condition",
        collection,
        network,
    )


def _context(
    ids: tuple[str, ...] = ("tx-1",),
    *,
    families: dict[str, str] | None = None,
    missing_construction: set[str] | None = None,
    partial: str | None = None,
    with_components: bool = False,
    with_winding_allocation: bool = False,
    winding_materials: tuple[str, str] | None = None,
) -> dict[str, Any]:
    topology = ElectricalTopologyConfig(inverters=[])
    basis = LvAcCollectionNetworkBasisAuthority(
        "balanced_three_phase", "line_to_line_rms", "per_phase_series", "basis", "high"
    )
    nodes = {
        f"exit-{i}": LvAcCollectionNodeAuthority(f"exit-{i}", "collection_exit", "drawing", "high")
        for i, _ in enumerate(ids)
    }
    collection = resolve_topology_lv_ac_collection_authority(topology, basis, nodes, {}, {})
    equipment = {
        identifier: _equipment(identifier) for identifier in ids if partial != "topology-only"
    }
    boundaries = {
        identifier: _boundary(identifier, f"exit-{i}")
        for i, identifier in enumerate(ids)
        if partial != "equipment-only"
    }
    static = resolve_transformer_static_authority(
        topology, basis, nodes, {}, {}, collection, equipment, boundaries
    )
    no_load: dict[str, Any] = {}
    rated: dict[str, Any] = {}
    loss = resolve_transformer_loss_authority(
        topology, basis, nodes, {}, {}, collection, equipment, boundaries, static, no_load, rated
    )
    missing = missing_construction or set()
    constructions = {
        identifier: _construction(
            identifier,
            (families or {}).get(identifier, "mineral_oil_immersed"),
            winding_materials,
        )
        for identifier in ids
        if identifier not in missing
    }
    components = (
        {
            identifier: _component(
                identifier, with_winding_allocation=with_winding_allocation
            )
            for identifier in ids
        }
        if with_components
        else {}
    )
    s12h = resolve_transformer_loss_component_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        collection,
        equipment,
        boundaries,
        static,
        no_load,
        rated,
        loss,
        constructions,
        components,
    )
    return locals()


def _resolve(
    *,
    ids: tuple[str, ...] = ("tx-1",),
    states: Mapping[Any, Any] | None = None,
    families: dict[str, str] | None = None,
    missing_construction: set[str] | None = None,
    partial: str | None = None,
    with_components: bool = False,
    with_winding_allocation: bool = False,
    winding_materials: tuple[str, str] | None = None,
    mutations: dict[str, Any] | None = None,
) -> TopologyTransformerThermalStateAuthorityResult:
    c = _context(
        ids,
        families=families,
        missing_construction=missing_construction,
        partial=partial,
        with_components=with_components,
        with_winding_allocation=with_winding_allocation,
        winding_materials=winding_materials,
    )
    inputs = {
        "topology": c["topology"],
        "network_basis": c["basis"],
        "node_authority_by_id": c["nodes"],
        "segment_authority_by_id": {},
        "inverter_terminal_binding_by_inverter_id": {},
        "lv_ac_collection_authority": c["collection"],
        "transformer_equipment_by_id": c["equipment"],
        "transformer_topology_by_id": c["boundaries"],
        "transformer_static_authority": c["static"],
        "transformer_no_load_loss_by_id": c["no_load"],
        "transformer_rated_load_loss_by_id": c["rated"],
        "transformer_loss_authority": c["loss"],
        "transformer_construction_by_id": c["constructions"],
        "transformer_rated_load_loss_component_by_id": c["components"],
        "transformer_loss_component_authority": c["s12h"],
        "transformer_thermal_state_by_key": {} if states is None else states,
    }
    inputs.update(mutations or {})
    return resolve_transformer_thermal_state_authority(**cast(Any, inputs))


def test_minimal_average_winding_resolves_without_s12h_components() -> None:
    result = _resolve(states={(T1, "tx-1"): _state(average=_evidence())})
    row = result.states.iloc[0]
    assert row["transformer_load_loss_temperature_basis_resolved"]
    assert row["load_loss_temperature_quantity"] == LOAD_LOSS_TEMPERATURE_QUANTITY
    assert not result.diagnostics.thermal_state_missing_count


def test_full_oil_immersed_state_preserves_all_provenance() -> None:
    state = _state(
        ambient=_evidence(40.0, source="ambient"),
        average=_evidence(70.0, "documented_external_engineering_model_estimate", "model"),
        hot_spot=_evidence(65.0, "manufacturer_thermal_model_estimate", "monitor"),
        top_oil=_evidence(75.0, "scada_condition_monitoring_estimate", "scada"),
    )
    row = _resolve(states={(T1, "tx-1"): state}).states.iloc[0]
    assert row["top_oil_temperature_applicability"] == "applicable"
    assert row["ambient_air_temperature_parameter_source"] == "ambient"
    assert row["average_winding_temperature_evidence_kind"] == (
        "documented_external_engineering_model_estimate"
    )
    assert row["winding_hot_spot_temperature_c"] == 65.0
    assert row["top_oil_temperature_c"] == 75.0


def test_dry_type_without_top_oil_resolves() -> None:
    row = _resolve(
        families={"tx-1": "dry_type"},
        states={
            (T1, "tx-1"): _state(
                ambient=_evidence(30), average=_evidence(80), hot_spot=_evidence(90)
            )
        },
    ).states.iloc[0]
    assert row["transformer_load_loss_temperature_basis_resolved"]
    assert row["top_oil_temperature_applicability"] == "not_supplied"


@pytest.mark.parametrize(
    ("family", "applicability", "conflict"),
    [("dry_type", "not_applicable", True), ("other_explicit", "unknown", False)],
)
def test_top_oil_construction_context_preserves_supplementary_evidence(
    family: str, applicability: str, conflict: bool
) -> None:
    row = _resolve(
        families={"tx-1": family},
        states={(T1, "tx-1"): _state(average=_evidence(), top_oil=_evidence(60))},
    ).states.iloc[0]
    assert row["top_oil_temperature_c"] == 60.0
    assert row["top_oil_temperature_applicability"] == applicability
    assert bool(row["incompatible_supplementary_top_oil_evidence"]) is conflict
    assert row["transformer_load_loss_temperature_basis_resolved"]


@pytest.mark.parametrize("channel", ["ambient", "hot_spot", "top_oil"])
def test_missing_average_preserves_other_channel(channel: str) -> None:
    state = _state(**{channel: _evidence(45.0)})
    row = _resolve(states={(T1, "tx-1"): state}).states.iloc[0]
    assert row["transformer_thermal_state_authority_state"] == (
        "unresolved_missing_average_winding_temperature"
    )
    column = {
        "ambient": "ambient_air_temperature_c",
        "hot_spot": "winding_hot_spot_temperature_c",
        "top_oil": "top_oil_temperature_c",
    }[channel]
    assert row[column] == 45.0


def test_missing_construction_and_upstream_static_precedence_preserve_evidence() -> None:
    state = {(T1, "tx-1"): _state(average=_evidence())}
    missing = _resolve(states=state, missing_construction={"tx-1"}).states.iloc[0]
    assert missing["transformer_thermal_state_authority_state"] == (
        "unresolved_missing_transformer_construction_authority"
    )
    assert missing["average_winding_temperature_c"] == 70.0
    upstream = _resolve(states=state, partial="topology-only").states.iloc[0]
    assert upstream["transformer_thermal_state_authority_state"] == (
        "unresolved_upstream_transformer_static_authority"
    )
    assert upstream["average_winding_temperature_c"] == 70.0


def test_complete_s12h_component_basis_is_not_required() -> None:
    result = _resolve(states={(T1, "tx-1"): _state(average=_evidence())}, with_components=False)
    assert result.states.iloc[0]["transformer_construction_authority_present"]
    assert result.states.iloc[0]["transformer_load_loss_temperature_basis_resolved"]


@pytest.mark.parametrize("channel", ["ambient", "hot_spot", "top_oil"])
def test_resistance_based_evidence_rejected_outside_average(channel: str) -> None:
    evidence = _evidence(kind="resistance_based_winding_temperature_estimate")
    with pytest.raises(ValueError):
        _state(**{channel: evidence})


def test_resistance_based_average_is_accepted() -> None:
    evidence = _evidence(kind="resistance_based_winding_temperature_estimate")
    assert _state(average=evidence).average_winding_temperature == evidence


def test_existing_positional_thermal_state_constructor_remains_backward_compatible() -> None:
    state = TransformerThermalState(None, _evidence(), None, None, "legacy positional")
    assert state.collection_winding_average_temperature is None
    assert state.network_winding_average_temperature is None


def test_resistance_based_winding_evidence_is_accepted_for_both_explicit_sides() -> None:
    collection = _evidence(81.0, "resistance_based_winding_temperature_estimate", "dc-test:c")
    network = _evidence(77.0, "resistance_based_winding_temperature_estimate", "dc-test:n")
    state = _state(collection=collection, network=network)
    assert state.collection_winding_average_temperature == collection
    assert state.network_winding_average_temperature == network


@pytest.mark.parametrize(
    ("side", "present_column", "missing_column"),
    [
        (
            "collection",
            "collection_winding_average_temperature_c",
            "network_winding_average_temperature_c",
        ),
        (
            "network",
            "network_winding_average_temperature_c",
            "collection_winding_average_temperature_c",
        ),
    ],
)
def test_single_winding_channel_is_preserved_without_cross_side_inference(
    side: str, present_column: str, missing_column: str
) -> None:
    row = _resolve(states={(T1, "tx-1"): _state(**{side: _evidence(82.0)})}).states.iloc[0]
    assert row[present_column] == 82.0
    assert math.isnan(row[missing_column])
    assert row["winding_resolved_temperature_evidence_present"]
    assert not row["winding_resolved_temperature_pair_complete"]
    assert not row["winding_resolved_temperature_basis_resolved"]


@pytest.mark.parametrize("materials", [("copper", "copper"), ("copper", "aluminium")])
def test_explicit_winding_pair_resolves_independently_of_material_homogeneity(
    materials: tuple[str, str],
) -> None:
    state = _state(
        collection=_evidence(83.0, source="collection-sensor"),
        network=_evidence(74.0, "scada_condition_monitoring_estimate", "network-model"),
    )
    result = _resolve(states={(T1, "tx-1"): state}, winding_materials=materials)
    row = result.states.iloc[0]
    assert not row["transformer_load_loss_temperature_basis_resolved"]
    assert math.isnan(row["average_winding_temperature_c"])
    assert row["winding_resolved_temperature_pair_complete"]
    assert row["winding_resolved_temperature_basis_resolved"]
    assert row["collection_winding_average_temperature_c"] == 83.0
    assert row["network_winding_average_temperature_c"] == 74.0
    assert row["collection_winding_average_temperature_parameter_source"] == "collection-sensor"
    assert row["network_winding_average_temperature_parameter_source"] == "network-model"
    assert row["collection_winding_conductor_material"] == materials[0]
    assert row["network_winding_conductor_material"] == materials[1]
    assert row["conductor_authority_basis"] == "explicit_winding_resolved"
    assert result.diagnostics.winding_resolved_temperature_basis_resolved_count == 1


def test_legacy_and_winding_resolved_temperature_bases_resolve_independently() -> None:
    state = _state(
        average=_evidence(80.0, "direct_sensor_measurement", "transformer-average-sensor"),
        collection=_evidence(
            92.0,
            "resistance_based_winding_temperature_estimate",
            "collection-resistance-test",
        ),
        network=_evidence(
            74.0,
            "scada_condition_monitoring_estimate",
            "network-condition-monitor",
        ),
    )
    row = _resolve(
        states={(T1, "tx-1"): state}, winding_materials=("copper", "aluminium")
    ).states.iloc[0]
    assert row["transformer_load_loss_temperature_basis_resolved"]
    assert row["winding_resolved_temperature_basis_resolved"]
    assert row["average_winding_temperature_c"] == 80.0
    assert row["collection_winding_average_temperature_c"] == 92.0
    assert row["network_winding_average_temperature_c"] == 74.0
    assert row["average_winding_temperature_parameter_source"] == "transformer-average-sensor"
    assert row["collection_winding_average_temperature_parameter_source"] == (
        "collection-resistance-test"
    )
    assert row["network_winding_average_temperature_parameter_source"] == (
        "network-condition-monitor"
    )
    assert len(
        {
            row["average_winding_temperature_c"],
            row["collection_winding_average_temperature_c"],
            row["network_winding_average_temperature_c"],
        }
    ) == 3


def test_winding_pair_without_explicit_conductor_authority_remains_evidence_only() -> None:
    result = _resolve(
        states={(T1, "tx-1"): _state(collection=_evidence(80), network=_evidence(80))}
    )
    row = result.states.iloc[0]
    assert row["winding_resolved_temperature_pair_complete"]
    assert not row["winding_resolved_temperature_basis_resolved"]
    assert result.diagnostics.winding_resolved_temperature_pair_complete_count == 1


def test_side_evidence_survives_unresolved_static_and_missing_construction() -> None:
    states = {(T1, "tx-1"): _state(collection=_evidence(80), network=_evidence(75))}
    upstream = _resolve(
        states=states, partial="topology-only", winding_materials=("copper", "aluminium")
    ).states.iloc[0]
    missing = _resolve(states=states, missing_construction={"tx-1"}).states.iloc[0]
    for row in (upstream, missing):
        assert row["collection_winding_average_temperature_c"] == 80.0
        assert row["network_winding_average_temperature_c"] == 75.0
        assert not row["winding_resolved_temperature_basis_resolved"]


def test_side_evidence_diagnostics_distinguish_none_incomplete_and_complete() -> None:
    result = _resolve(
        ids=("tx-a", "tx-b", "tx-c"),
        states={
            (T1, "tx-a"): _state(average=_evidence()),
            (T1, "tx-b"): _state(collection=_evidence(81)),
            (T1, "tx-c"): _state(collection=_evidence(82), network=_evidence(73)),
        },
        winding_materials=("copper", "copper"),
    )
    diagnostics = result.diagnostics
    assert diagnostics.collection_winding_average_temperature_present_count == 2
    assert diagnostics.network_winding_average_temperature_present_count == 1
    assert diagnostics.winding_resolved_temperature_evidence_present_count == 2
    assert diagnostics.winding_resolved_temperature_pair_complete_count == 1
    assert diagnostics.winding_resolved_temperature_pair_incomplete_count == 1
    assert diagnostics.winding_resolved_temperature_basis_resolved_count == 1


@pytest.mark.parametrize("value", [True, math.nan, math.inf, -math.inf, -273.15, -300.0])
def test_invalid_temperature_domain_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        _evidence(cast(float, value))


def test_unusually_high_temperature_and_unusual_ordering_are_admitted() -> None:
    assert _evidence(1.0e300).temperature_c == 1.0e300
    state = _state(
        ambient=_evidence(40), average=_evidence(70), hot_spot=_evidence(65), top_oil=_evidence(75)
    )
    assert _resolve(states={(T1, "tx-1"): state}).states.iloc[0][
        "transformer_load_loss_temperature_basis_resolved"
    ]


@pytest.mark.parametrize(
    "bad_key",
    [T1, (T1,), (dt.datetime(2026, 1, 1), "tx-1"), (pd.NaT, "tx-1"), (T1, ""), (T1, " tx-1")],
)
def test_invalid_mapping_keys_rejected(bad_key: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        _resolve(states=cast(Any, {bad_key: _state(average=_evidence())}))


def test_unknown_id_wrong_state_and_mapping_types_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        _resolve(states={(T1, "unknown"): _state(average=_evidence())})
    with pytest.raises(TypeError, match="invalid value type"):
        _resolve(states=cast(Any, {(T1, "tx-1"): object()}))
    with pytest.raises(TypeError, match="must be a mapping"):
        _resolve(states=cast(Any, []))


def test_timezone_incompatibility_rejected() -> None:
    with pytest.raises(ValueError, match="incompatible timezone semantics"):
        _resolve(
            states={
                (pd.Timestamp("2026-01-01"), "tx-1"): _state(average=_evidence()),
                (T1, "tx-1"): _state(average=_evidence()),
            }
        )


def test_canonical_cross_product_and_timestamp_ordering() -> None:
    result = _resolve(
        ids=("tx-b", "tx-a"),
        states={
            (T2, "tx-a"): _state(average=_evidence()),
            (T1, "tx-a"): _state(average=_evidence()),
        },
    )
    assert result.states.index.tolist() == [(T1, "tx-a"), (T1, "tx-b"), (T2, "tx-a"), (T2, "tx-b")]
    assert result.states.loc[(T1, "tx-b"), "transformer_thermal_state_authority_state"] == (
        "unresolved_missing_transformer_thermal_state"
    )


def test_empty_input_returns_typed_empty_result() -> None:
    result = _resolve()
    assert len(result.states) == 0
    assert result.states.index.names == ["timestamp", "transformer_id"]
    assert isinstance(result.states.index.levels[0], pd.DatetimeIndex)
    assert type(result.thermal_state_by_key) is MappingProxyType
    assert result.diagnostics.timestamp_count == result.diagnostics.row_count == 0


def test_caller_mapping_mutation_cannot_change_result() -> None:
    supplied = {(T1, "tx-1"): _state(average=_evidence())}
    result = _resolve(states=supplied)
    supplied.clear()
    assert tuple(result.thermal_state_by_key) == ((T1, "tx-1"),)


def test_strong_s12h_replay_rejects_tampering() -> None:
    c = _context(ids=("tx-b", "tx-a"))
    parent = c["s12h"]
    frame = parent.transformer_states.copy(deep=True)
    frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
    mutations = (
        {"transformer_loss_component_authority": object()},
        {"transformer_loss_component_authority": replace(parent, transformer_states=frame)},
        {
            "transformer_loss_component_authority": replace(
                parent, transformer_states=parent.transformer_states.iloc[::-1]
            )
        },
        {
            "transformer_loss_component_authority": replace(
                parent, construction_by_id=dict(parent.construction_by_id)
            )
        },
        {
            "transformer_loss_component_authority": replace(
                parent, rated_load_loss_component_by_id=dict(parent.rated_load_loss_component_by_id)
            )
        },
        {
            "transformer_loss_component_authority": replace(
                parent, diagnostics=replace(parent.diagnostics, transformer_count=99)
            )
        },
    )
    for mutation in mutations:
        with pytest.raises(ValueError):
            _resolve(ids=("tx-b", "tx-a"), mutations=mutation)


def test_s12h_winding_allocation_mapping_is_strictly_replay_protected() -> None:
    context = _context(
        with_components=True,
        with_winding_allocation=True,
        winding_materials=("copper", "aluminium"),
    )
    parent = context["s12h"]
    assert tuple(parent.winding_resolved_load_loss_by_id) == ("tx-1",)
    mutable_mapping = dict(parent.winding_resolved_load_loss_by_id)
    tampered_results = (
        replace(parent, winding_resolved_load_loss_by_id=mutable_mapping),
        replace(parent, winding_resolved_load_loss_by_id=MappingProxyType({})),
    )
    for tampered in tampered_results:
        with pytest.raises(ValueError, match="winding_resolved_load_loss_by_id"):
            _resolve(
                with_components=True,
                with_winding_allocation=True,
                winding_materials=("copper", "aluminium"),
                mutations={"transformer_loss_component_authority": tampered},
            )


def test_result_validator_rejects_frame_diagnostics_and_mapping_tamper() -> None:
    state = {(T1, "tx-1"): _state(average=_evidence(), top_oil=_evidence(60))}
    c = _context()
    result = _resolve(states=state)
    for column in result.states.columns:
        frame = result.states.copy(deep=True)
        value = frame.iloc[0][column]
        replacement: object = (
            not bool(value)
            if frame[column].dtype == bool
            else ("tampered" if isinstance(value, str) else 999.0)
        )
        frame.loc[(T1, "tx-1"), column] = replacement
        with pytest.raises(RuntimeError):
            _validate_result(
                c["s12h"], result.thermal_state_by_key, [T1], replace(result, states=frame)
            )
    with pytest.raises(RuntimeError):
        _validate_result(
            c["s12h"],
            result.thermal_state_by_key,
            [T1],
            replace(result, diagnostics=replace(result.diagnostics, row_count=99)),
        )
    with pytest.raises(RuntimeError, match="immutable"):
        _validate_result(
            c["s12h"],
            result.thermal_state_by_key,
            [T1],
            replace(result, thermal_state_by_key=dict(result.thermal_state_by_key)),
        )


def test_winding_resolved_validator_is_independent_of_production_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = {(T1, "tx-1"): _state(collection=_evidence(82), network=_evidence(74))}
    context = _context(winding_materials=("copper", "aluminium"))
    result = _resolve(states=states, winding_materials=("copper", "aluminium"))

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production S12J builder invoked")

    for name in ("_record", "_record_values", "_frame", "_diagnostics", "_top_oil"):
        monkeypatch.setattr(module, name, fail)
    _validate_result(context["s12h"], result.thermal_state_by_key, [T1], result)


@pytest.mark.parametrize(
    "column",
    [
        "collection_winding_average_temperature_present",
        "network_winding_average_temperature_present",
        "winding_resolved_temperature_evidence_present",
        "winding_resolved_temperature_pair_complete",
        "winding_resolved_temperature_basis_resolved",
        "winding_resolved_conductor_authority_resolved",
        "collection_winding_average_temperature_c",
        "network_winding_average_temperature_c",
        "collection_winding_average_temperature_evidence_kind",
        "network_winding_average_temperature_method_reference",
        "collection_winding_conductor_material",
        "network_winding_conductor_material",
        "conductor_authority_basis",
        "winding_resolved_temperature_basis_semantics",
    ],
)
def test_winding_resolved_validator_rejects_new_contract_tampering(column: str) -> None:
    materials = ("copper", "aluminium")
    states = {(T1, "tx-1"): _state(collection=_evidence(82), network=_evidence(74))}
    context = _context(winding_materials=materials)
    result = _resolve(states=states, winding_materials=materials)
    frame = result.states.copy(deep=True)
    value = frame.iloc[0][column]
    if frame[column].dtype == bool:
        replacement: object = not bool(value)
    elif isinstance(value, str):
        replacement = "tampered"
    else:
        replacement = 999.0
    frame.loc[(T1, "tx-1"), column] = replacement
    with pytest.raises(RuntimeError, match="independent closure"):
        _validate_result(
            context["s12h"],
            result.thermal_state_by_key,
            [T1],
            replace(result, states=frame),
        )


@pytest.mark.parametrize(
    "field",
    [
        "collection_winding_average_temperature_present_count",
        "network_winding_average_temperature_present_count",
        "winding_resolved_temperature_evidence_present_count",
        "winding_resolved_temperature_pair_complete_count",
        "winding_resolved_temperature_pair_incomplete_count",
        "winding_resolved_temperature_basis_resolved_count",
    ],
)
def test_winding_resolved_validator_rejects_new_diagnostics_tampering(field: str) -> None:
    materials = ("copper", "aluminium")
    states = {(T1, "tx-1"): _state(collection=_evidence(82), network=_evidence(74))}
    context = _context(winding_materials=materials)
    result = _resolve(states=states, winding_materials=materials)
    diagnostics = replace(result.diagnostics, **{field: 99})
    with pytest.raises(RuntimeError, match="diagnostics failed independent closure"):
        _validate_result(
            context["s12h"],
            result.thermal_state_by_key,
            [T1],
            replace(result, diagnostics=diagnostics),
        )


def test_result_validator_rejects_immutable_mapping_order_tamper() -> None:
    states = {
        (T1, "tx-1"): _state(average=_evidence(70)),
        (T2, "tx-1"): _state(average=_evidence(75)),
    }
    context = _context()
    result = _resolve(states=states)
    reversed_mapping = MappingProxyType(
        dict(reversed(tuple(result.thermal_state_by_key.items())))
    )
    with pytest.raises(RuntimeError, match="mapping"):
        _validate_result(
            context["s12h"],
            result.thermal_state_by_key,
            [T1, T2],
            replace(result, thermal_state_by_key=reversed_mapping),
        )


def test_contract_non_actions_and_scope_exclusions() -> None:
    assert TRANSFORMER_THERMAL_STATE_AUTHORITY_CONTRACT_ID.endswith("_v1")
    row = _resolve(states={(T1, "tx-1"): _state(average=_evidence())}).states.iloc[0]
    for column in (
        "dynamic_thermal_model_applied",
        "temperature_interpolation_applied",
        "temperature_extrapolation_applied",
        "temperature_loss_correction_applied",
    ):
        assert not row[column]
    source = inspect.getsource(module)
    for forbidden in (
        "transformer_energisation_authority",
        "transformer_operating_loss",
        "transformer_network_authority",
        "transformer_series_equivalent",
        "transformer_operating_solution",
        "transformer_harmonic_current_authority",
        "Arrhenius",
    ):
        assert forbidden not in source
