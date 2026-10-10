"""Tests for S12F factory-reference transformer series-equivalent derivation."""

from __future__ import annotations

import inspect
import math
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.config.site import ElectricalTopologyConfig
from heliotelligence.physics import transformer_series_equivalent as module
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
    TransformerRatedLoadLossAuthority,
    resolve_transformer_loss_authority,
)
from heliotelligence.physics.transformer_network_authority import (
    TransformerShortCircuitImpedanceAuthority,
    TransformerVoltageTransferAuthority,
    resolve_transformer_network_authority,
)
from heliotelligence.physics.transformer_series_equivalent import (
    TRANSFORMER_SERIES_EQUIVALENT_CONTRACT_ID,
    TRANSFORMER_SERIES_EQUIVALENT_COVERAGE_SCOPE,
    TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID,
    TRANSFORMER_SERIES_EQUIVALENT_SCOPE,
    TopologyTransformerSeriesEquivalentDiagnostics,
    TransformerRatedLoadLossReferenceConditionAuthority,
    _validate_result,
    resolve_transformer_series_equivalent,
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
        "drawing",
        "high",
    )


def _rated_load(
    transformer_id: str = "tx-1",
    loss: float = 5_000.0,
    side: str = "collection_side",
    temperature: float = 75.0,
    frequency: float = 50.0,
) -> TransformerRatedLoadLossAuthority:
    return TransformerRatedLoadLossAuthority(
        transformer_id,
        loss,
        side,  # type: ignore[arg-type]
        "rated_current",
        temperature,
        frequency,
        "total_rated_load_loss_including_winding_and_stray",
        f"load-loss:{transformer_id}",
        "high",
    )


def _transfer(
    transformer_id: str = "tx-1",
    ratio: float = 27.5,
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
        0.0,
        f"ratio:{transformer_id}",
        "high",
    )


def _impedance(
    transformer_id: str = "tx-1",
    magnitude: float = 0.06,
    side: str = "collection_side",
    reference: str = "fixed_non_tapped_transformer_ratio",
    temperature: float = 75.0,
    frequency: float = 50.0,
) -> TransformerShortCircuitImpedanceAuthority:
    return TransformerShortCircuitImpedanceAuthority(
        transformer_id,
        "positive_sequence",
        "total_two_winding_series_short_circuit_impedance_magnitude",
        "per_unit_on_s12a_rated_apparent_power_and_explicit_reference_side_"
        "rated_line_to_line_voltage",
        reference,  # type: ignore[arg-type]
        side,  # type: ignore[arg-type]
        magnitude,
        "rated_current",
        temperature,
        frequency,
        f"impedance:{transformer_id}",
        "medium",
    )


def _reference(
    transformer_id: str = "tx-1",
    condition: str = "fixed_non_tapped_transformer_ratio",
) -> TransformerRatedLoadLossReferenceConditionAuthority:
    return TransformerRatedLoadLossReferenceConditionAuthority(
        transformer_id,
        condition,  # type: ignore[arg-type]
        f"test-sheet:{transformer_id}",
        "medium",
    )


def _context(
    transformer_ids: tuple[str, ...] = ("tx-1",),
    *,
    partial: str | None = None,
    rated_load: dict[str, TransformerRatedLoadLossAuthority] | None = None,
    transfer: dict[str, TransformerVoltageTransferAuthority] | None = None,
    impedance: dict[str, TransformerShortCircuitImpedanceAuthority] | None = None,
) -> dict[str, Any]:
    topology = ElectricalTopologyConfig(inverters=[])
    basis = LvAcCollectionNetworkBasisAuthority(
        "balanced_three_phase", "line_to_line_rms", "per_phase_series", "basis", "high"
    )
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
    tx_topology = {
        transformer_id: _topology(transformer_id, f"exit-{position}")
        for position, transformer_id in enumerate(transformer_ids)
        if partial != "equipment-only"
    }
    static = resolve_transformer_static_authority(
        topology, basis, nodes, {}, {}, s11a, equipment, tx_topology
    )
    rated_load = rated_load or {}
    loss = resolve_transformer_loss_authority(
        topology, basis, nodes, {}, {}, s11a, equipment, tx_topology, static, {}, rated_load
    )
    transfer = transfer or {}
    impedance = impedance or {}
    network = resolve_transformer_network_authority(
        topology,
        basis,
        nodes,
        {},
        {},
        s11a,
        equipment,
        tx_topology,
        static,
        transfer,
        impedance,
    )
    return locals()


def _resolve(
    *,
    transformer_ids: tuple[str, ...] = ("tx-1",),
    partial: str | None = None,
    rated_load: dict[str, TransformerRatedLoadLossAuthority] | None = None,
    transfer: dict[str, TransformerVoltageTransferAuthority] | None = None,
    impedance: dict[str, TransformerShortCircuitImpedanceAuthority] | None = None,
    references: dict[str, TransformerRatedLoadLossReferenceConditionAuthority] | None = None,
    mutations: dict[str, Any] | None = None,
) -> Any:
    context = _context(
        transformer_ids,
        partial=partial,
        rated_load=rated_load,
        transfer=transfer,
        impedance=impedance,
    )
    if mutations:
        context.update(mutations)
    return resolve_transformer_series_equivalent(
        context["topology"],
        context["basis"],
        context["nodes"],
        {},
        {},
        context["s11a"],
        context["equipment"],
        context["tx_topology"],
        context["static"],
        {},
        context["rated_load"],
        context["loss"],
        context["transfer"],
        context["impedance"],
        context["network"],
        references or {},
    )


def _complete(
    *,
    side: str = "collection_side",
    loss: float = 5_000.0,
    magnitude: float = 0.06,
    ratio: float = 27.5,
    partial: str | None = None,
) -> Any:
    return _resolve(
        partial=partial,
        rated_load={"tx-1": _rated_load(loss=loss, side=side)},
        transfer={"tx-1": _transfer(ratio=ratio)},
        impedance={"tx-1": _impedance(magnitude=magnitude, side=side)},
        references={"tx-1": _reference()},
    )


@pytest.mark.parametrize(
    ("side", "voltage"), [("collection_side", 400.0), ("network_side", 11_000.0)]
)
def test_compatible_series_equivalent_closes_all_equations(side: str, voltage: float) -> None:
    result = _complete(side=side)
    row = result.transformer_states.loc["tx-1"]
    assert row["transformer_series_equivalent_resolved"]
    assert not row["transformer_boundary_operating_readiness_established"]
    assert row["series_equivalent_reference_side"] == side
    assert row["reference_side_rated_line_to_line_rms_v"] == voltage
    s, p = 500_000.0, 5_000.0
    i = s / (math.sqrt(3.0) * voltage)
    z_base = voltage**2 / s
    r_pu = p / s
    x_pu = math.sqrt(0.06**2 - r_pu**2)
    assert row["reference_side_rated_current_a"] == pytest.approx(i)
    assert row["effective_series_resistance_pu"] == pytest.approx(r_pu)
    assert row["effective_series_reactance_pu"] == pytest.approx(x_pu)
    assert row["short_circuit_impedance_base_ohm_per_phase"] == pytest.approx(z_base)
    assert row["effective_series_resistance_ohm_per_phase"] == pytest.approx(r_pu * z_base)
    assert row["effective_series_reactance_ohm_per_phase"] == pytest.approx(x_pu * z_base)
    assert 3.0 * i**2 * row["effective_series_resistance_ohm_per_phase"] == pytest.approx(p)
    assert row["effective_series_resistance_pu"] ** 2 + row[
        "effective_series_reactance_pu"
    ] ** 2 == pytest.approx(0.06**2)
    assert row["effective_series_resistance_semantics"].startswith(
        "effective_factory_short_circuit_series_resistance"
    )


def test_zero_load_loss_and_exact_impedance_equality() -> None:
    zero = _complete(loss=0.0).transformer_states.loc["tx-1"]
    assert zero["effective_series_resistance_pu"] == 0.0
    assert zero["effective_series_reactance_pu"] == pytest.approx(0.06)
    equal = _complete(loss=30_000.0, magnitude=0.06).transformer_states.loc["tx-1"]
    assert equal["effective_series_reactance_pu"] == 0.0


def test_tiny_roundoff_is_zero_but_material_inconsistency_is_unresolved() -> None:
    tiny = _complete(loss=30_000.000000000004, magnitude=0.06).transformer_states.loc["tx-1"]
    assert tiny["transformer_series_equivalent_resolved"]
    assert tiny["effective_series_reactance_pu"] == 0.0
    bad = _complete(loss=31_000.0, magnitude=0.06).transformer_states.loc["tx-1"]
    assert not bad["transformer_series_equivalent_resolved"]
    assert bad["transformer_series_equivalent_state"] == (
        "unresolved_factory_load_loss_exceeds_short_circuit_impedance_capability"
    )
    assert math.isnan(bad["effective_series_resistance_pu"])


@pytest.mark.parametrize(
    ("kwargs", "state"),
    [
        ({"rated_load": {}}, "unresolved_missing_transformer_rated_load_loss_authority"),
        (
            {"transfer": {}, "impedance": {}},
            "unresolved_missing_transformer_positive_sequence_network_authority",
        ),
        (
            {"transfer": {"tx-1": _transfer()}, "impedance": {}},
            "unresolved_missing_transformer_positive_sequence_network_authority",
        ),
        (
            {"references": {}},
            "unresolved_missing_rated_load_loss_reference_condition_authority",
        ),
    ],
)
def test_missing_evidence_precedence(kwargs: dict[str, Any], state: str) -> None:
    base: dict[str, Any] = {
        "rated_load": {"tx-1": _rated_load()},
        "transfer": {"tx-1": _transfer()},
        "impedance": {"tx-1": _impedance()},
        "references": {"tx-1": _reference()},
    }
    base.update(kwargs)
    row = _resolve(**base).transformer_states.loc["tx-1"]
    assert row["transformer_series_equivalent_state"] == state


@pytest.mark.parametrize(
    ("rated", "impedance", "reference", "state"),
    [
        (
            _rated_load(side="network_side"),
            _impedance(side="collection_side"),
            _reference(),
            "unresolved_incompatible_short_circuit_reference_sides",
        ),
        (
            _rated_load(),
            _impedance(reference="principal_tapping"),
            _reference(),
            "unresolved_missing_transformer_positive_sequence_network_authority",
        ),
        (
            _rated_load(),
            _impedance(temperature=85.0),
            _reference(),
            "unresolved_incompatible_short_circuit_reference_temperatures",
        ),
        (
            _rated_load(),
            _impedance(frequency=60.0),
            _reference(),
            "unresolved_incompatible_short_circuit_test_frequencies",
        ),
    ],
)
def test_incompatible_factory_conditions_are_unresolved(
    rated: TransformerRatedLoadLossAuthority,
    impedance: TransformerShortCircuitImpedanceAuthority,
    reference: TransformerRatedLoadLossReferenceConditionAuthority,
    state: str,
) -> None:
    transfer = _transfer(
        reference=impedance.ratio_reference_condition
        if state != "unresolved_missing_transformer_positive_sequence_network_authority"
        else "fixed_non_tapped_transformer_ratio"
    )
    row = _resolve(
        rated_load={"tx-1": rated},
        transfer={"tx-1": transfer},
        impedance={"tx-1": impedance},
        references={"tx-1": reference},
    ).transformer_states.loc["tx-1"]
    assert row["transformer_series_equivalent_state"] == state


def test_load_loss_ratio_condition_mismatch_after_resolved_s12e() -> None:
    row = _resolve(
        rated_load={"tx-1": _rated_load()},
        transfer={"tx-1": _transfer(reference="principal_tapping")},
        impedance={"tx-1": _impedance(reference="principal_tapping")},
        references={"tx-1": _reference(condition="fixed_non_tapped_transformer_ratio")},
    ).transformer_states.loc["tx-1"]
    assert row["transformer_series_equivalent_state"] == (
        "unresolved_incompatible_short_circuit_ratio_reference_conditions"
    )


@pytest.mark.parametrize("value", [None, "", " ", "nominal_tap", True])
def test_reference_condition_authority_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        replace(_reference(), ratio_reference_condition=cast(Any, value))
    with pytest.raises(TypeError):
        TransformerRatedLoadLossReferenceConditionAuthority(  # type: ignore[call-arg]
            transformer_id="tx-1", parameter_source="report", confidence="high"
        )


def test_ratio_difference_does_not_change_same_side_calculation() -> None:
    first = _complete(ratio=20.0).transformer_states.loc["tx-1"]
    second = _complete(ratio=31.0).transformer_states.loc["tx-1"]
    assert (
        first["effective_series_resistance_ohm_per_phase"]
        == second["effective_series_resistance_ohm_per_phase"]
    )
    assert (
        first["effective_series_reactance_ohm_per_phase"]
        == second["effective_series_reactance_ohm_per_phase"]
    )


def test_equipment_only_resolves_without_boundary_readiness() -> None:
    row = _complete(partial="equipment-only").transformer_states.loc["tx-1"]
    assert row["transformer_series_equivalent_resolved"]
    assert not row["transformer_boundary_operating_readiness_established"]


def test_topology_only_is_unresolved_missing_equipment() -> None:
    row = _resolve(
        partial="topology-only",
        rated_load={"tx-1": _rated_load()},
        transfer={"tx-1": _transfer()},
        impedance={"tx-1": _impedance()},
        references={"tx-1": _reference()},
    ).transformer_states.loc["tx-1"]
    assert row["transformer_series_equivalent_state"] == (
        "unresolved_missing_transformer_equipment_basis_authority"
    )


def test_multiple_transformers_are_sorted_independent_and_immutable() -> None:
    ids = ("tx-b", "tx-a")
    rated = {
        identifier: _rated_load(identifier, loss=4_000.0 + i * 1_000)
        for i, identifier in enumerate(ids)
    }
    transfer = {identifier: _transfer(identifier) for identifier in ids}
    impedance = {identifier: _impedance(identifier) for identifier in ids}
    references = {identifier: _reference(identifier) for identifier in ids}
    result = _resolve(
        transformer_ids=ids,
        rated_load=rated,
        transfer=transfer,
        impedance=impedance,
        references=references,
    )
    assert result.transformer_states.index.tolist() == ["tx-a", "tx-b"]
    assert type(result.rated_load_loss_reference_condition_by_id) is MappingProxyType
    with pytest.raises(TypeError):
        result.rated_load_loss_reference_condition_by_id["x"] = _reference("x")  # type: ignore[index]
    references.clear()
    assert len(result.rated_load_loss_reference_condition_by_id) == 2


def test_empty_transformer_universe_has_stable_empty_result() -> None:
    result = _resolve(transformer_ids=())
    assert result.transformer_states.empty
    assert result.transformer_states.index.name == "transformer_id"
    assert result.diagnostics.transformer_count == 0
    assert type(result.rated_load_loss_reference_condition_by_id) is MappingProxyType


def test_reference_mapping_closure_rejects_unknown_mismatch_and_wrong_type() -> None:
    with pytest.raises(ValueError, match="unknown transformer"):
        _resolve(references={"unknown": _reference("unknown")})
    with pytest.raises(ValueError, match="key mismatch"):
        _resolve(references={"tx-1": _reference("tx-2")})
    with pytest.raises(TypeError, match="invalid value type"):
        _resolve(references=cast(Any, {"tx-1": {}}))


@pytest.mark.parametrize("parent", ["static", "loss", "network"])
def test_strong_parent_replay_rejects_tampered_frames(parent: str) -> None:
    rated = {"tx-1": _rated_load()}
    transfer = {"tx-1": _transfer()}
    impedance = {"tx-1": _impedance()}
    context = _context(rated_load=rated, transfer=transfer, impedance=impedance)
    supplied = context[parent]
    frame = supplied.transformer_states.copy(deep=True)
    frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
    context[parent] = replace(supplied, transformer_states=frame)
    with pytest.raises(
        ValueError, match=f"S12{'A' if parent == 'static' else 'B' if parent == 'loss' else 'E'}"
    ):
        _resolve(
            rated_load=rated,
            transfer=transfer,
            impedance=impedance,
            references={"tx-1": _reference()},
            mutations=context,
        )


@pytest.mark.parametrize(
    ("parent", "field"),
    [
        ("static", "equipment_by_id"),
        ("loss", "rated_load_loss_by_id"),
        ("network", "short_circuit_impedance_by_id"),
    ],
)
def test_strong_parent_replay_rejects_mutable_content_equal_mappings(
    parent: str, field: str
) -> None:
    rated = {"tx-1": _rated_load()}
    transfer = {"tx-1": _transfer()}
    impedance = {"tx-1": _impedance()}
    context = _context(rated_load=rated, transfer=transfer, impedance=impedance)
    supplied = context[parent]
    context[parent] = replace(supplied, **{field: dict(getattr(supplied, field))})
    with pytest.raises(ValueError, match="immutable canonical replay"):
        _resolve(
            rated_load=rated,
            transfer=transfer,
            impedance=impedance,
            references={"tx-1": _reference()},
            mutations=context,
        )


def test_private_validator_rejects_state_and_diagnostics_tampering() -> None:
    result = _complete()
    context = _context(
        rated_load={"tx-1": _rated_load()},
        transfer={"tx-1": _transfer()},
        impedance={"tx-1": _impedance()},
    )
    frame = result.transformer_states.copy(deep=True)
    frame.loc["tx-1", "effective_series_resistance_pu"] = 0.5
    with pytest.raises(RuntimeError):
        _validate_result(
            context["static"],
            context["loss"],
            context["network"],
            replace(result, transformer_states=frame),
        )
    diagnostics = replace(result.diagnostics, series_equivalent_resolved_count=0)
    with pytest.raises(RuntimeError):
        _validate_result(
            context["static"],
            context["loss"],
            context["network"],
            replace(result, diagnostics=diagnostics),
        )


def test_contract_provenance_and_determinism() -> None:
    first, second = _complete(), _complete()
    pd.testing.assert_frame_equal(first.transformer_states, second.transformer_states)
    row = first.transformer_states.loc["tx-1"]
    assert (
        row["transformer_series_equivalent_contract"] == TRANSFORMER_SERIES_EQUIVALENT_CONTRACT_ID
    )
    assert row["transformer_series_equivalent_model"] == TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID
    assert row["transformer_series_equivalent_scope"] == TRANSFORMER_SERIES_EQUIVALENT_SCOPE
    assert (
        row["transformer_series_equivalent_coverage_scope"]
        == TRANSFORMER_SERIES_EQUIVALENT_COVERAGE_SCOPE
    )
    assert first.diagnostics.model == TRANSFORMER_SERIES_EQUIVALENT_MODEL_ID
    assert isinstance(first.diagnostics, TopologyTransformerSeriesEquivalentDiagnostics)


def test_scope_excludes_operating_excitation_and_superseded_direct_rx() -> None:
    source = inspect.getsource(module)
    forbidden = (
        "transformer_energisation_authority",
        "transformer_operating_loss",
        "lv_ac_collection_operating",
        "shunt_admittance",
        "tap_schedule",
        "timestamped_tap",
        "oltc_controller",
        "TransformerSeriesImpedanceAuthority",
    )
    for term in forbidden:
        assert term not in source
    assert "no_load_loss_by_id" in source  # replay only; it is not used in the decomposition
    assert "effective_factory_short_circuit_series_resistance" in source
