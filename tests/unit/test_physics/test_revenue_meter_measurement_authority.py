from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import revenue_meter_measurement_authority as module
from heliotelligence.physics.mv_hv_network_authority import (
    resolve_topology_mv_hv_network_authority,
)
from heliotelligence.physics.revenue_meter_measurement_authority import (
    REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID,
    RevenueMeterMeasuredPowerState,
    resolve_topology_revenue_meter_measurement_authority,
)
from tests.unit.test_physics.test_mv_hv_network_authority import (
    _inputs as _s13a_inputs,
)
from tests.unit.test_physics.test_mv_hv_network_authority import (
    _meter,
    _node,
)

T1 = pd.Timestamp("2026-01-01T00:00:00Z")
T2 = pd.Timestamp("2026-01-01T00:05:00Z")


def _measurement(
    p: float = 1_000.0,
    q: float = 200.0,
    *,
    temporal: str = "instantaneous_snapshot",
    interval: float | None = None,
) -> RevenueMeterMeasuredPowerState:
    return RevenueMeterMeasuredPowerState(
        p,
        q,
        "revenue_meter_boundary",
        "positive_plant_to_grid",
        "positive_plant_to_grid",
        "three_phase_total",
        "primary_engineering_units_at_revenue_meter_boundary",
        temporal,  # type: ignore[arg-type]
        interval,
        "revenue meter historian",
        "high",
    )


def _inputs(
    evidence: dict[tuple[pd.Timestamp, str], RevenueMeterMeasuredPowerState] | None = None,
) -> dict[str, Any]:
    values = _s13a_inputs()
    parent = resolve_topology_mv_hv_network_authority(**values)
    return {
        **values,
        "mv_hv_network_authority": parent,
        "revenue_meter_measured_power_by_key": (
            evidence if evidence is not None else {(T1, "meter"): _measurement()}
        ),
    }


def _resolve(values: dict[str, Any] | None = None) -> Any:
    return resolve_topology_revenue_meter_measurement_authority(**(values or _inputs()))


def _two_meter_inputs() -> dict[str, Any]:
    values = _s13a_inputs()
    values["mv_hv_node_by_id"] = {
        **values["mv_hv_node_by_id"],
        "junction": _node("junction", "junction"),
    }
    values["revenue_meter_boundary_by_id"] = {
        "meter-a": _meter("meter-a", "exit"),
        "meter-b": _meter("meter-b", "junction"),
    }
    parent = resolve_topology_mv_hv_network_authority(**values)
    return {
        **values,
        "mv_hv_network_authority": parent,
        "revenue_meter_measured_power_by_key": {
            (T2, "meter-b"): _measurement(-300.0, 50.0),
            (T1, "meter-a"): _measurement(500.0, -20.0),
        },
    }


@pytest.mark.parametrize(
    ("p", "q"),
    [(1_000.0, 200.0), (-1_000.0, -200.0), (1_000.0, -200.0)],
)
def test_signed_power_resolves_without_sign_conversion(p: float, q: float) -> None:
    result = _resolve(_inputs({(T1, "meter"): _measurement(p, q)}))
    row = result.states.loc[(T1, "meter")]
    assert row["measured_active_power_w"] == p
    assert row["measured_reactive_power_var"] == q
    assert row["measured_apparent_power_magnitude_va"] == math.hypot(p, q)
    assert row["measured_power_authority_resolved"]
    assert row["revenue_meter_measurement_authority_state"] == (
        "resolved_explicit_revenue_meter_measured_power_state"
    )


def test_explicit_zero_is_distinct_from_missing() -> None:
    values = _two_meter_inputs()
    values["revenue_meter_measured_power_by_key"] = {
        (T1, "meter-a"): _measurement(0.0, 0.0)
    }
    result = _resolve(values)
    present = result.states.loc[(T1, "meter-a")]
    missing = result.states.loc[(T1, "meter-b")]
    assert present["measured_active_power_is_zero"]
    assert present["measured_reactive_power_is_zero"]
    assert present["measured_apparent_power_magnitude_va"] == 0.0
    assert pd.isna(missing["measured_active_power_is_zero"])
    assert pd.isna(missing["measured_active_power_w"])


def test_two_meter_timestamp_cartesian_closure_has_no_inference() -> None:
    result = _resolve(_two_meter_inputs())
    assert tuple(result.states.index) == (
        (T1, "meter-a"),
        (T1, "meter-b"),
        (T2, "meter-a"),
        (T2, "meter-b"),
    )
    assert pd.isna(result.states.loc[(T1, "meter-b"), "measured_active_power_w"])
    assert pd.isna(result.states.loc[(T2, "meter-a"), "measured_active_power_w"])
    assert result.diagnostics.measured_power_state_missing_count == 2


def test_static_meter_context_and_colocation_are_preserved_when_missing() -> None:
    values = _two_meter_inputs()
    values["revenue_meter_measured_power_by_key"] = {(T1, "meter-a"): _measurement()}
    result = _resolve(values)
    colocated = result.states.loc[(T1, "meter-a")]
    internal = result.states.loc[(T1, "meter-b")]
    assert colocated["revenue_meter_colocated_with_grid_boundary"]
    assert colocated["colocated_grid_boundary_id"] == "grid"
    assert not internal["revenue_meter_colocated_with_grid_boundary"]
    assert pd.isna(internal["colocated_grid_boundary_id"])
    assert internal["revenue_meter_node_id"] == "junction"
    assert internal["revenue_meter_reference_plane"] == "revenue_meter_boundary"
    assert internal["measurement_reference_plane"] == ""
    assert internal["active_power_sign_convention"] == "positive_plant_to_grid"
    assert internal["power_basis"] == "three_phase_total"
    assert internal["revenue_meter_measurement_authority_state"] == (
        "unresolved_missing_revenue_meter_measured_power_state"
    )


def test_snapshot_and_interval_average_temporal_semantics() -> None:
    snapshot = _measurement()
    interval = _measurement(
        temporal="interval_average_ending_at_timestamp", interval=300.0
    )
    result = _resolve(_inputs({(T1, "meter"): snapshot, (T2, "meter"): interval}))
    assert result.states.loc[(T1, "meter"), "measurement_time_semantics"] == (
        "instantaneous_snapshot"
    )
    assert pd.isna(result.states.loc[(T1, "meter"), "averaging_interval_seconds"])
    assert result.states.loc[(T2, "meter"), "measurement_time_semantics"] == (
        "interval_average_ending_at_timestamp"
    )
    assert result.states.loc[(T2, "meter"), "averaging_interval_seconds"] == 300.0
    assert result.diagnostics.instantaneous_snapshot_state_count == 1
    assert result.diagnostics.interval_average_state_count == 1


@pytest.mark.parametrize(
    ("temporal", "interval"),
    [
        ("instantaneous_snapshot", 60.0),
        ("interval_average_ending_at_timestamp", None),
        ("interval_average_ending_at_timestamp", 0.0),
        ("interval_average_ending_at_timestamp", -1.0),
        ("interval_average_ending_at_timestamp", float("inf")),
        ("interval_average_ending_at_timestamp", True),
    ],
)
def test_invalid_temporal_combinations_are_rejected(
    temporal: str, interval: object
) -> None:
    with pytest.raises(ValueError):
        _measurement(temporal=temporal, interval=interval)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["active_power_w", "reactive_power_var"])
@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf"), float("-inf")])
def test_invalid_signed_power_values_are_rejected(field: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "active_power_w": 1.0,
        "reactive_power_var": 2.0,
        "reference_plane": "revenue_meter_boundary",
        "active_power_sign_convention": "positive_plant_to_grid",
        "reactive_power_sign_convention": "positive_plant_to_grid",
        "power_basis": "three_phase_total",
        "measurement_value_basis": "primary_engineering_units_at_revenue_meter_boundary",
        "measurement_time_semantics": "instantaneous_snapshot",
        "averaging_interval_seconds": None,
        "parameter_source": "source",
        "confidence": "high",
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=field):
        RevenueMeterMeasuredPowerState(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "key",
    [T1, (T1,), (datetime(2026, 1, 1), "meter"), ("2026-01-01", "meter"), (pd.NaT, "meter")],
)
def test_malformed_keys_and_timestamp_types_are_rejected(key: object) -> None:
    values = _inputs()
    values["revenue_meter_measured_power_by_key"] = {key: _measurement()}
    with pytest.raises((TypeError, ValueError)):
        _resolve(values)


@pytest.mark.parametrize("identifier", ["unknown", "exit", "grid", " meter"])
def test_unknown_meter_and_boundary_identity_substitutions_are_rejected(
    identifier: str,
) -> None:
    values = _inputs()
    values["revenue_meter_measured_power_by_key"] = {(T1, identifier): _measurement()}
    with pytest.raises(ValueError):
        _resolve(values)


def test_incompatible_timezone_semantics_are_rejected() -> None:
    values = _inputs()
    values["revenue_meter_measured_power_by_key"] = {
        (T1, "meter"): _measurement(),
        (pd.Timestamp("2026-01-02"), "meter"): _measurement(),
    }
    with pytest.raises(ValueError, match="incompatible timezone semantics"):
        _resolve(values)


def test_exact_s13a_meter_semantics_are_required() -> None:
    state = _measurement()
    object.__setattr__(state, "power_basis", "per_phase")
    values = _inputs({(T1, "meter"): state})
    with pytest.raises(ValueError, match="semantics do not match"):
        _resolve(values)


def test_missing_network_basis_does_not_invalidate_measurement() -> None:
    values = _s13a_inputs()
    values["mv_hv_network_basis"] = None
    parent = resolve_topology_mv_hv_network_authority(**values)
    result = _resolve(
        {
            **values,
            "mv_hv_network_authority": parent,
            "revenue_meter_measured_power_by_key": {(T1, "meter"): _measurement()},
        }
    )
    row = result.states.loc[(T1, "meter")]
    assert not row["network_basis_resolved"]
    assert row["measured_power_authority_resolved"]
    assert result.diagnostics.missing_network_basis_row_count == 1


def test_empty_evidence_and_empty_meter_universe_have_stable_schema() -> None:
    empty = _resolve(_inputs({}))
    assert empty.states.empty
    assert list(empty.states.index.names) == ["timestamp", "revenue_meter_id"]
    assert tuple(empty.states.columns) == module._COLUMNS
    assert str(empty.states["measured_active_power_is_zero"].dtype) == "boolean"
    values = _s13a_inputs()
    values["revenue_meter_boundary_by_id"] = {}
    parent = resolve_topology_mv_hv_network_authority(**values)
    no_meters = _resolve(
        {
            **values,
            "mv_hv_network_authority": parent,
            "revenue_meter_measured_power_by_key": {},
        }
    )
    assert no_meters.states.empty
    assert no_meters.diagnostics.revenue_meter_count == 0


def test_mapping_order_is_canonical_and_result_is_detached_immutable() -> None:
    values = _two_meter_inputs()
    supplied = values["revenue_meter_measured_power_by_key"]
    reverse = {key: value for key, value in reversed(tuple(supplied.items()))}
    one = _resolve(values)
    two = _resolve({**values, "revenue_meter_measured_power_by_key": reverse})
    pd.testing.assert_frame_equal(one.states, two.states, check_exact=True)
    assert tuple(one.measured_power_states_by_key.items()) == tuple(
        two.measured_power_states_by_key.items()
    )
    supplied.clear()
    assert len(one.measured_power_states_by_key) == 2
    assert type(one.measured_power_states_by_key) is MappingProxyType
    with pytest.raises(TypeError):
        one.measured_power_states_by_key[(T1, "meter-a")] = _measurement()  # type: ignore[index]


@pytest.mark.parametrize(
    "component",
    [
        "revenue_meter_boundary_by_id",
        "nodes_by_id",
        "grid_boundary_by_id",
        "transformer_states",
        "diagnostics",
    ],
)
def test_strong_s13a_replay_rejects_tampering(component: str) -> None:
    values = _inputs()
    parent = values["mv_hv_network_authority"]
    if component == "transformer_states":
        changed = parent.transformer_states.copy(deep=True)
        changed.iloc[0, 0] = not changed.iloc[0, 0]
        tampered = replace(parent, transformer_states=changed)
    elif component == "diagnostics":
        tampered = replace(
            parent, diagnostics=replace(parent.diagnostics, revenue_meter_boundary_count=99)
        )
    else:
        mapping = dict(getattr(parent, component))
        mapping.pop(next(iter(mapping)))
        tampered = replace(parent, **{component: MappingProxyType(mapping)})
    values["mv_hv_network_authority"] = tampered
    with pytest.raises(RuntimeError, match="supplied S13A"):
        _resolve(values)


def test_validator_is_independent_of_production_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _inputs()
    result = _resolve(values)

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("production builder was called")

    for name in ("_record", "_frame", "_diagnostics"):
        monkeypatch.setattr(module, name, fail)
    module._validate_result(values["mv_hv_network_authority"], result)


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("measured_power_state_present", False),
        ("measured_power_authority_resolved", False),
        ("revenue_meter_node_id", "wrong"),
        ("revenue_meter_reference_plane", "wrong"),
        ("revenue_meter_colocated_with_grid_boundary", False),
        ("measured_active_power_w", 2.0),
        ("measured_reactive_power_var", 3.0),
        ("measured_apparent_power_magnitude_va", 4.0),
        ("measured_active_power_is_zero", True),
        ("measurement_time_semantics", "wrong"),
        ("averaging_interval_seconds", 60.0),
        ("parameter_source", "wrong"),
        ("revenue_meter_measurement_authority_state", "wrong"),
        ("revenue_meter_measurement_authority_contract", "wrong"),
        ("revenue_meter_measurement_authority_model", "wrong"),
    ],
)
def test_independent_validator_rejects_frame_tampering(
    column: str, replacement: object
) -> None:
    values = _inputs()
    result = _resolve(values)
    changed = result.states.copy(deep=True)
    changed.iloc[0, changed.columns.get_loc(column)] = replacement
    with pytest.raises(RuntimeError, match="independent exact closure"):
        module._validate_result(
            values["mv_hv_network_authority"], replace(result, states=changed)
        )


def test_validator_rejects_diagnostics_tampering() -> None:
    values = _inputs()
    result = _resolve(values)
    tampered = replace(
        result,
        diagnostics=replace(result.diagnostics, measured_power_state_present_count=99),
    )
    with pytest.raises(RuntimeError, match="diagnostics"):
        module._validate_result(values["mv_hv_network_authority"], tampered)


def test_public_schema_order_and_dtypes_are_explicit() -> None:
    result = _resolve()
    assert tuple(result.states.columns) == module._COLUMNS
    assert len(module._COLUMNS) == len(set(module._COLUMNS))
    assert list(result.states.index.names) == ["timestamp", "revenue_meter_id"]
    assert str(result.states["network_basis_resolved"].dtype) == "bool"
    assert str(result.states["measured_active_power_w"].dtype) == "float64"
    assert str(result.states["measured_active_power_is_zero"].dtype) == "boolean"
    assert str(result.states["measurement_time_semantics"].dtype) == "object"
    assert result.states.iloc[0]["revenue_meter_measurement_authority_contract"] == (
        REVENUE_METER_MEASUREMENT_AUTHORITY_CONTRACT_ID
    )


def test_source_has_no_operating_solution_or_benchmark_dependency() -> None:
    source = module.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    for forbidden in (
        "mv_hv_operating_solution",
        "TopologyMvHvOperatingSolutionResult",
        "expected_p",
        "expected_q",
        "actual_minus_expected",
        "p_residual",
        "q_residual",
    ):
        assert forbidden not in text
