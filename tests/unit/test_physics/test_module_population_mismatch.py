"""Population residual composition, S8 admission and independent replay."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from functools import cache
from typing import Any

import numpy as np
import pandas as pd
import pytest

from heliotelligence.config.site import (
    ElectricalTopologyConfig,
    InverterUnitConfig,
    MPPTConfig,
    StringConfig,
)
from heliotelligence.physics import electrical
from heliotelligence.physics import module_population_mismatch as module
from tests.unit.test_physics import test_state_aware_mppt_mismatch as support
from tests.unit.test_physics.test_stage4_string_iv import _site


def authority(**changes: Any) -> module.ModulePopulationMismatchAuthority:
    values = dict(
        resolution_mode="equivalent_post_mppt_current_derate",
        equivalent_current_derate_fraction=0.02,
        mechanism_scope=module.MECHANISM_SCOPE,
        evidence_kind="validated_engineering_study",
        parameter_source="explicit independent population study",
        confidence="high",
        method_reference="validated population residual method",
        applicability_description="declared MPPT strings during the admitted study period",
    )
    values.update(changes)
    return module.ModulePopulationMismatchAuthority(**values)


@cache
def baseline(
    kind: str = "active", periods: int = 1
) -> tuple[ElectricalTopologyConfig, electrical.TopologyMPPTMismatchResult]:
    topology = support._topology(
        [
            ("mppt-1", [("a", 24), ("b", 30)]),
            ("mppt-2", [("c", 24)]),
            ("empty", []),
        ]
    )
    _, strings = support._real_s81(topology, periods=periods, zero=kind == "zero", receiver_count=3)
    if kind == "unresolved":
        strings = support._set_string_unresolved(strings, "a")
    elif kind == "mixed":
        strings = support._set_string_zero(strings, "a")
    return topology, electrical.calculate_topology_mppt_mismatch_from_string_iv(topology, strings)


def mapping(
    value: module.ModulePopulationMismatchAuthority | None = None,
) -> dict[tuple[str, str], module.ModulePopulationMismatchAuthority]:
    return {("inverter-1", "mppt-1"): value or authority()}


def apply(kind: str = "active", **kwargs: Any) -> module.ModulePopulationMismatchResult:
    topology, upstream = baseline(kind)
    return module.apply_module_population_mismatch(
        topology, upstream, authority_by_mppt=kwargs.get("authorities", mapping())
    )


def test_negligible_preserves_common_point_and_shared_loss() -> None:
    result = apply(
        authorities=mapping(
            authority(
                resolution_mode="explicit_negligible_by_evidence",
                equivalent_current_derate_fraction=0,
            )
        )
    )
    row = result.states.iloc[0]
    assert row.population_mismatch_resolved
    assert row.population_mismatch_state == "resolved_explicit_negligible_by_evidence"
    assert row.v_after_population_mismatch_v == row.v_common_mppt_v
    assert row.i_after_population_mismatch_a == row.i_common_mppt_a
    assert row.p_after_population_mismatch_w == row.p_common_mppt_w
    assert row.population_mismatch_w == 0
    assert row.total_mismatch_from_homogeneous_independent_w == row.shared_mppt_mismatch_w


def test_exact_100kw_two_percent_residual_and_total_accounting() -> None:
    topology, upstream = baseline()
    frame = upstream.operating_points.copy()
    key = frame.index[0]
    frame.loc[
        key,
        [
            "v_common_mppt_v",
            "i_common_mppt_a",
            "p_common_mppt_w",
            "p_independent_mp_w",
            "p_mismatch_w",
            "mismatch_pct",
        ],
    ] = [1000, 100, 100000, 110000, 10000, 100 * 10000 / 110000]
    supplied = replace(upstream, operating_points=frame)
    result = module.apply_module_population_mismatch(
        topology, supplied, authority_by_mppt=mapping()
    )
    row = result.states.loc[key]
    assert row.v_after_population_mismatch_v == 1000
    assert row.i_after_population_mismatch_a == 98
    assert row.p_after_population_mismatch_w == 98000
    assert row.population_mismatch_w == 2000
    assert row.shared_mppt_mismatch_w == 10000
    assert row.total_mismatch_from_homogeneous_independent_w == 12000
    assert row.total_mismatch_pct == pytest.approx(100 * 12000 / 110000)
    assert (
        row.p_after_population_mismatch_w
        == row.v_after_population_mismatch_v * row.i_after_population_mismatch_a
    )


def test_real_canonical_shared_mismatch_and_population_are_distinct() -> None:
    topology, upstream = baseline(periods=2)
    result = module.apply_module_population_mismatch(
        topology, upstream, authority_by_mppt=mapping()
    )
    for key, row in result.states.iterrows():
        assert row.shared_mppt_mismatch_w == upstream.operating_points.loc[key, "p_mismatch_w"]
        if row.population_mismatch_resolved:
            assert row.shared_mppt_mismatch_w > 0
            assert row.population_mismatch_w > 0
            assert row.total_mismatch_from_homogeneous_independent_w == pytest.approx(
                row.shared_mppt_mismatch_w + row.population_mismatch_w
            )
            assert row.total_mismatch_from_homogeneous_independent_w == pytest.approx(
                row.p_homogeneous_independent_mp_w - row.p_after_population_mismatch_w
            )
            assert row.population_mismatch_is_lower_fidelity
    assert result.states.index.identical(upstream.operating_points.index)


def test_missing_partial_authority_preserves_s8_and_leaves_adjusted_nan() -> None:
    result = apply()
    row = result.states.iloc[1]
    assert row.upstream_mppt_resolved and row.p_common_mppt_w > 0
    assert row.population_mismatch_state == "unresolved_population_mismatch_authority"
    assert not row.population_mismatch_resolved
    assert not row.population_mismatch_authority_present
    assert not row.population_mismatch_is_lower_fidelity
    assert row[list(module._ADJUSTED)].isna().all()
    assert pd.isna(row.population_mismatch_fraction)
    assert result.states.iloc[0].population_mismatch_resolved
    assert result.diagnostics.missing_authority_row_count == 1


@pytest.mark.parametrize("kind", ["unresolved", "mixed"])
def test_authority_cannot_repair_unresolved_upstream(kind: str) -> None:
    row = apply(kind).states.iloc[0]
    assert row.population_mismatch_authority_present
    assert row.population_mismatch_state == "unresolved_upstream_mppt"
    assert not row.population_mismatch_resolved
    assert row[list(module._ADJUSTED)].isna().all()
    assert (
        row.population_mismatch_fraction == 0.02
    )  # authority is retained, not numerically applied


def test_zero_generation_and_missing_zero_authority() -> None:
    result = apply("zero")
    row = result.states.iloc[0]
    assert row.population_mismatch_state == "resolved_zero_population_mismatch"
    assert row.population_mismatch_resolved
    assert row[list(module._ADJUSTED)].eq(0).all()
    assert (
        result.states.iloc[1].population_mismatch_state
        == "unresolved_population_mismatch_authority"
    )
    assert result.diagnostics.zero_row_count == 1


@pytest.mark.parametrize(
    "change",
    [
        {"equivalent_current_derate_fraction": value}
        for value in [-0.01, 0, 1, 2, np.nan, np.inf, True, np.bool_(False), "0.02", None]
    ]
    + [
        {"resolution_mode": "explicit_negligible_by_evidence"},
        {"resolution_mode": "member_resolved_mismatch"},
        {"mechanism_scope": "shared_mppt_mismatch"},
        {"evidence_kind": "legacy_config_percentage"},
        {"evidence_kind": "datasheet_power_tolerance_only"},
        {"confidence": "HIGH"},
    ],
)
def test_invalid_authority(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        authority(**change)


@pytest.mark.parametrize(
    "field",
    [
        "parameter_source",
        "method_reference",
        "applicability_description",
        "mechanism_scope",
        "evidence_kind",
        "resolution_mode",
        "confidence",
    ],
)
@pytest.mark.parametrize("value", ["", " padded", "padded ", None, 123])
def test_exact_provenance(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        authority(**{field: value})


@pytest.mark.parametrize("evidence", sorted(module._EVIDENCE))
def test_all_admitted_evidence_kinds(evidence: str) -> None:
    assert (
        apply(authorities=mapping(authority(evidence_kind=evidence)))
        .states.iloc[0]
        .population_mismatch_resolved
    )


@pytest.mark.parametrize(
    "key",
    [("missing", "mppt-1"), ("inverter-1", "empty"), "mppt-1", ("inverter-1",), ("inverter-1", 1)],
)
def test_extra_empty_or_invalid_authority_keys_rejected(key: Any) -> None:
    topology, upstream = baseline()
    with pytest.raises(ValueError):
        module.apply_module_population_mismatch(
            topology, upstream, authority_by_mppt={key: authority()}
        )


def test_immutable_authority_explicit_reuse_and_no_implicit_fanout() -> None:
    evidence = authority()
    with pytest.raises(FrozenInstanceError):
        evidence.confidence = "low"  # type: ignore[misc]
    topology, upstream = baseline()
    result = module.apply_module_population_mismatch(
        topology,
        upstream,
        authority_by_mppt={
            key: evidence for key in [("inverter-1", "mppt-1"), ("inverter-1", "mppt-2")]
        },
    )
    assert result.states.population_mismatch_resolved.all()
    assert result.diagnostics.authority_mppt_count == 2
    assert apply().diagnostics.authority_mppt_count == 1
    with pytest.raises(TypeError):
        result.diagnostics.state_counts["forged"] = 1  # type: ignore[index]
    forged = authority()
    object.__setattr__(forged, "equivalent_current_derate_fraction", 2)
    with pytest.raises(ValueError):
        module.apply_module_population_mismatch(
            topology, upstream, authority_by_mppt=mapping(forged)
        )


@pytest.mark.parametrize(
    "column,value",
    [
        ("v_common_mppt_v", 0),
        ("i_common_mppt_a", True),
        ("p_common_mppt_w", np.inf),
        ("p_independent_mp_w", 0),
        ("p_mismatch_w", 123),
        ("mismatch_pct", 99),
        ("mppt_resolved", False),
        ("mppt_resolved", 1),
        ("mppt_state", "resolved_zero_common_voltage_mppt"),
        ("configured_string_count", 3),
        ("zero_string_count", 1),
        ("unresolved_string_ids", "not-a-string"),
        ("unresolved_string_states", "forged"),
        ("topology_mppt_mismatch_model", "forged"),
        ("topology_string_iv_model", "population_resolved"),
    ],
)
def test_upstream_tamper_rejected(column: str, value: Any) -> None:
    topology, upstream = baseline()
    frame = upstream.operating_points.copy()
    frame[column] = frame[column].astype(object)
    frame.iloc[0, frame.columns.get_loc(column)] = value
    with pytest.raises(ValueError):
        module.apply_module_population_mismatch(
            topology, replace(upstream, operating_points=frame), authority_by_mppt=mapping()
        )


@pytest.mark.parametrize(
    "field", [f.name for f in fields(electrical.TopologyMPPTMismatchDiagnostics)]
)
def test_all_upstream_diagnostics_independently_reconstructed(field: str) -> None:
    topology, upstream = baseline()
    old = getattr(upstream.diagnostics, field)
    changed = replace(
        upstream.diagnostics, **{field: "forged" if isinstance(old, str) else old + 1}
    )
    with pytest.raises(ValueError):
        module.apply_module_population_mismatch(
            topology, replace(upstream, diagnostics=changed), authority_by_mppt=mapping()
        )


@pytest.mark.parametrize(
    "kind", ["duplicate", "missing", "naive", "nat", "unknown", "wrong_names", "wrong_type"]
)
def test_upstream_row_identity(kind: str) -> None:
    topology, upstream = baseline()
    frame = upstream.operating_points.copy()
    if kind == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]])
    elif kind == "missing":
        frame = frame.iloc[:1]
    else:
        keys = list(frame.index)
        if kind == "naive":
            keys = [(t.tz_localize(None), inv, mppt) for t, inv, mppt in keys]
        elif kind == "nat":
            keys[0] = (pd.NaT, keys[0][1], keys[0][2])
        elif kind == "unknown":
            keys[0] = (keys[0][0], "unknown", keys[0][2])
        frame.index = pd.MultiIndex.from_tuples(keys, names=frame.index.names)
        if kind == "wrong_names":
            frame.index = frame.index.set_names(["time", "inv", "mppt"])
        if kind == "wrong_type":
            frame.index = pd.RangeIndex(len(frame))
    with pytest.raises(ValueError):
        module.apply_module_population_mismatch(
            topology, replace(upstream, operating_points=frame), authority_by_mppt=mapping()
        )


@pytest.mark.parametrize(
    "column",
    [
        "population_mismatch_fraction",
        "population_mismatch_w",
        "v_after_population_mismatch_v",
        "i_after_population_mismatch_a",
        "p_after_population_mismatch_w",
        "shared_mppt_mismatch_w",
        "total_mismatch_from_homogeneous_independent_w",
        "total_mismatch_pct",
        "population_mismatch_resolved",
        "population_mismatch_is_lower_fidelity",
        "population_mismatch_state",
        "parameter_source",
        "mechanism_scope",
        "legacy_mismatch_percentage_consumed",
        "module_population_mismatch_model",
    ],
)
def test_result_tamper_rejected(column: str) -> None:
    topology, upstream = baseline()
    result = apply()
    frame = result.states.copy()
    old = frame.iloc[0][column]
    value = (
        not bool(old)
        if isinstance(old, (bool, np.bool_))
        else "forged"
        if isinstance(old, str)
        else old + 1
    )
    frame.iloc[0, frame.columns.get_loc(column)] = value
    with pytest.raises(ValueError):
        module.validate_module_population_mismatch(
            replace(result, states=frame), topology, upstream, authority_by_mppt=mapping()
        )


def test_validator_independent_of_all_production_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    topology, upstream = baseline()
    result = apply()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("production builder called")

    for name in ["apply_module_population_mismatch", "_record", "_frame", "_diagnostics"]:
        monkeypatch.setattr(module, name, forbidden)
    for name in [
        "calculate_physical_mismatch",
        "calculate_topology_mppt_mismatch_from_string_iv",
        "_validate_topology_mppt_mismatch_result",
    ]:
        monkeypatch.setattr(electrical, name, forbidden)
    module.validate_module_population_mismatch(
        result, topology, upstream, authority_by_mppt=mapping()
    )
    with pytest.raises(ValueError):
        module.validate_module_population_mismatch(
            replace(result, diagnostics=replace(result.diagnostics, resolved_row_count=99)),
            topology,
            upstream,
            authority_by_mppt=mapping(),
        )


def test_no_legacy_percentage_leakage_and_inputs_not_mutated() -> None:
    topology, upstream = baseline()
    before = upstream.operating_points.copy(deep=True)
    site = _site()
    site.module.mismatch_loss_pct = 1.15
    first = apply()
    site.module.mismatch_loss_pct = 37
    second = apply()
    pd.testing.assert_frame_equal(first.states, second.states)
    pd.testing.assert_frame_equal(upstream.operating_points, before)
    assert not first.states.legacy_mismatch_percentage_consumed.any()
    assert "site" not in inspect.signature(module.apply_module_population_mismatch).parameters
    assert "mismatch_loss_pct" not in inspect.getsource(module)
    assert "random" not in module.__dict__


@pytest.mark.parametrize("empty_topology", [False, True])
def test_empty_contract_and_frozen_result(empty_topology: bool) -> None:
    topology, upstream = baseline(periods=0)
    if empty_topology:
        topology = ElectricalTopologyConfig(inverters=[])
        topology, strings = support._real_s81(topology)
        upstream = electrical.calculate_topology_mppt_mismatch_from_string_iv(topology, strings)
    result = module.apply_module_population_mismatch(topology, upstream, authority_by_mppt={})
    assert result.states.empty
    assert result.states.index.identical(upstream.operating_points.index)
    assert tuple(result.states.columns) == module._COLUMNS
    assert result.diagnostics.row_count == 0
    with pytest.raises(FrozenInstanceError):
        result.states = pd.DataFrame()  # type: ignore[misc]


def test_repeated_mppt_ids_are_explicitly_scoped_to_inverter() -> None:
    topology = ElectricalTopologyConfig(
        inverters=[
            InverterUnitConfig(
                id=inv,
                mppts=[
                    MPPTConfig(id="same", strings=[StringConfig(id=inv, modules_per_string=24)])
                ],
            )
            for inv in ["inv-a", "inv-b"]
        ]
    )
    _, strings = support._real_s81(topology)
    upstream = electrical.calculate_topology_mppt_mismatch_from_string_iv(topology, strings)
    result = module.apply_module_population_mismatch(
        topology, upstream, authority_by_mppt={("inv-a", "same"): authority()}
    )
    assert result.states.population_mismatch_resolved.tolist() == [True, False]


def test_contract_identities_are_exact() -> None:
    assert (
        module.MODULE_POPULATION_MISMATCH_AUTHORITY_CONTRACT_ID
        == "explicit_intra_string_population_mismatch_residual_authority_v1"
    )
    assert module.MODULE_POPULATION_MISMATCH_CONTRACT_ID == (
        "admitted_s8_common_voltage_mppt_and_population_residual_authority_"
        "to_population_complete_dc_state_v1"
    )
    assert (
        module.MODULE_POPULATION_MISMATCH_MODEL_ID
        == "shared_mppt_physical_mismatch_plus_explicit_post_mppt_equivalent_current_derate_v1"
    )
    assert (
        module.MODULE_POPULATION_MISMATCH_SCOPE
        == "mppt_resolved_dc_after_population_mismatch_before_dc_collection"
    )
    assert (
        module.MODULE_POPULATION_MISMATCH_COVERAGE_SCOPE
        == "shared_mppt_physics_plus_explicit_lower_fidelity_intra_string_population_residual"
    )
    result = apply()
    for name, value in module._FIXED.items():
        assert result.states[name].eq(value).all()


@pytest.mark.parametrize(
    "field", [f.name for f in fields(module.ModulePopulationMismatchDiagnostics)]
)
def test_all_population_diagnostics_tamper_rejected(field: str) -> None:
    topology, upstream = baseline()
    result = apply()
    old = getattr(result.diagnostics, field)
    value = (
        {"forged": 1} if field == "state_counts" else "forged" if isinstance(old, str) else old + 1
    )
    diagnostics = replace(result.diagnostics, **{field: value})
    with pytest.raises(ValueError):
        module.validate_module_population_mismatch(
            replace(result, diagnostics=diagnostics),
            topology,
            upstream,
            authority_by_mppt=mapping(),
        )


@pytest.mark.parametrize("kind", ["zero", "unresolved"])
def test_nonfinite_or_nonzero_upstream_state_cannot_leak(kind: str) -> None:
    topology, upstream = baseline(kind)
    frame = upstream.operating_points.copy()
    frame.iloc[0, frame.columns.get_loc("p_common_mppt_w")] = 1.0 if kind == "zero" else np.inf
    with pytest.raises(ValueError):
        module.apply_module_population_mismatch(
            topology, replace(upstream, operating_points=frame), authority_by_mppt=mapping()
        )


def test_exact_parent_type_and_no_authority_are_distinct() -> None:
    topology, upstream = baseline()
    with pytest.raises(ValueError, match="exact TopologyMPPTMismatchResult"):
        module.apply_module_population_mismatch(
            topology, upstream.operating_points, authority_by_mppt={}
        )
    result = module.apply_module_population_mismatch(topology, upstream, authority_by_mppt={})
    assert result.states.upstream_mppt_resolved.all()
    assert not result.states.population_mismatch_resolved.any()
    assert result.states[list(module._ADJUSTED)].isna().all().all()


def test_result_grid_and_boolean_diagnostics_rejected() -> None:
    topology, upstream = baseline()
    result = apply()
    for frame in [result.states.iloc[:1], result.states.iloc[::-1], result.states.assign(extra=1)]:
        with pytest.raises(ValueError):
            module.validate_module_population_mismatch(
                replace(result, states=frame), topology, upstream, authority_by_mppt=mapping()
            )
    with pytest.raises(ValueError):
        module.validate_module_population_mismatch(
            replace(result, diagnostics=replace(result.diagnostics, resolved_row_count=True)),
            topology,
            upstream,
            authority_by_mppt=mapping(),
        )
