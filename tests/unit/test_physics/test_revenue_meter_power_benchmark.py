from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import revenue_meter_power_benchmark as module
from heliotelligence.physics.mv_hv_operating_solution import (
    calculate_topology_mv_hv_operating_solution,
)
from heliotelligence.physics.revenue_meter_measurement_authority import (
    RevenueMeterMeasuredPowerState,
    resolve_topology_revenue_meter_measurement_authority,
)
from heliotelligence.physics.revenue_meter_power_benchmark import (
    calculate_topology_revenue_meter_power_benchmark,
)
from tests.unit.test_physics import test_inverter_dispatch_feasibility as support
from tests.unit.test_physics.test_mv_hv_operating_solution import _values as _s13c_values


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


def _measurement(
    p: float,
    q: float,
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


def _values(
    *,
    measured_p: float | None = None,
    measured_q: float | None = None,
    measured_p_offset: float | None = None,
    temporal: str = "instantaneous_snapshot",
    interval: float | None = None,
    evidence_timestamp: pd.Timestamp | None = None,
    no_measurement: bool = False,
    **operating: Any,
) -> dict[str, Any]:
    values = _s13c_values(**operating)
    s13c = calculate_topology_mv_hv_operating_solution(**values)
    values["mv_hv_operating_solution"] = s13c
    timestamp = s13c.revenue_meter_states.index.get_level_values("timestamp")[0]
    row = s13c.revenue_meter_states.iloc[0]
    expected_p = float(row["expected_p_at_revenue_meter_w"])
    p = expected_p if measured_p is None else measured_p
    if measured_p_offset is not None:
        p = expected_p + measured_p_offset
    q = float(row["expected_q_at_revenue_meter_var"]) if measured_q is None else measured_q
    evidence = (
        {}
        if no_measurement
        else {
            (evidence_timestamp or timestamp, "meter"): _measurement(
                p, q, temporal=temporal, interval=interval
            )
        }
    )
    values["revenue_meter_measured_power_by_key"] = evidence
    values["revenue_meter_measurement_authority"] = module._call(
        resolve_topology_revenue_meter_measurement_authority, values
    )
    return values


def _run(**kwargs: Any) -> Any:
    return calculate_topology_revenue_meter_power_benchmark(**_values(**kwargs))


@pytest.mark.parametrize(
    ("measured_p_offset", "measured_q", "expected_dp"),
    [
        (0.0, 20.0, 0.0),
        (20.0, 20.0, 20.0),
        (-20.0, 20.0, -20.0),
        (-1_000.0, 20.0, -1_000.0),
    ],
)
def test_snapshot_residual_is_signed_measured_minus_expected(
    measured_p_offset: float, measured_q: float, expected_dp: float
) -> None:
    result = _run(
        p=100.0,
        q=20.0,
        measured_p_offset=measured_p_offset,
        measured_q=measured_q,
    )
    row = result.states.iloc[0]
    dq = measured_q - float(row["expected_reactive_power_var"])
    assert row["benchmark_eligible"]
    assert bool(row["temporal_basis_compatible"])
    assert row["active_power_residual_measured_minus_expected_w"] == pytest.approx(expected_dp)
    assert row["reactive_power_residual_measured_minus_expected_var"] == pytest.approx(dq)
    assert row["power_residual_vector_magnitude_va"] == pytest.approx(math.hypot(expected_dp, dq))
    assert row["revenue_meter_power_benchmark_state"] == (
        "resolved_instantaneous_revenue_meter_power_benchmark"
    )


def test_modeled_only_timestamp_preserves_expected_evidence() -> None:
    row = _run(no_measurement=True).states.iloc[0]
    assert row["expected_power_resolved"]
    assert math.isfinite(row["expected_active_power_w"])
    assert not row["measured_parent_row_present"]
    assert pd.isna(row["temporal_basis_compatible"])
    assert pd.isna(row["active_power_residual_measured_minus_expected_w"])
    assert row["revenue_meter_power_benchmark_state"] == (
        "unresolved_missing_measured_revenue_meter_power_state"
    )


def test_measured_only_timestamp_is_preserved_without_nearest_matching() -> None:
    base = _s13c_values()
    s13c = calculate_topology_mv_hv_operating_solution(**base)
    timestamp = s13c.revenue_meter_states.index.get_level_values("timestamp")[0]
    result = _run(evidence_timestamp=timestamp + pd.Timedelta(seconds=1), measured_p=50.0)
    assert len(result.states) == 2
    earlier, later = result.states.iloc[0], result.states.iloc[1]
    assert earlier["expected_power_resolved"] and not earlier["measured_parent_row_present"]
    assert later["measured_power_authority_resolved"] and not later["expected_parent_row_present"]
    assert math.isfinite(later["measured_active_power_w"])
    assert pd.isna(later["active_power_residual_measured_minus_expected_w"])


def test_unresolved_expected_parent_preserves_valid_measurement() -> None:
    row = _run(boundary_voltage=9_000.0, measured_p=75.0, measured_q=-5.0).states.iloc[0]
    assert row["expected_parent_row_present"]
    assert not row["expected_power_resolved"]
    assert row["measured_power_authority_resolved"]
    assert row["measured_active_power_w"] == 75.0
    assert pd.isna(row["active_power_residual_measured_minus_expected_w"])
    assert row["revenue_meter_power_benchmark_state"] == (
        "unresolved_expected_revenue_meter_operating_solution"
    )


def test_interval_average_preserves_both_parents_but_has_no_residual() -> None:
    row = _run(
        measured_p=120.0,
        measured_q=-10.0,
        temporal="interval_average_ending_at_timestamp",
        interval=300.0,
    ).states.iloc[0]
    assert math.isfinite(row["expected_active_power_w"])
    assert row["measured_active_power_w"] == 120.0
    assert not bool(row["temporal_basis_compatible"])
    assert not row["benchmark_eligible"]
    assert pd.isna(row["power_residual_vector_magnitude_va"])
    assert row["revenue_meter_power_benchmark_state"] == (
        "unresolved_interval_average_measurement_requires_temporal_aggregation"
    )


def _numerical_boundary_result(
    parents: tuple[Any, Any, Any],
    expected_p: float,
    expected_q: float,
    measured_p: float,
    measured_q: float,
) -> tuple[tuple[Any, Any, Any], Any]:
    s13a, s13c, s13d = parents
    expected = s13c.revenue_meter_states.copy(deep=True)
    measured = s13d.states.copy(deep=True)
    expected.loc[:, "expected_p_at_revenue_meter_w"] = expected_p
    expected.loc[:, "expected_q_at_revenue_meter_var"] = expected_q
    measured.loc[:, "measured_active_power_w"] = measured_p
    measured.loc[:, "measured_reactive_power_var"] = measured_q
    bounded_parents = (
        s13a,
        replace(s13c, revenue_meter_states=expected),
        replace(s13d, states=measured),
    )
    timestamp, meter_id = expected.index[0]
    keys = ((timestamp, meter_id),)
    record = module._record(*bounded_parents, timestamp, meter_id)
    frame = module._frame(keys, [record])
    result = module.TopologyRevenueMeterInstantaneousBenchmarkResult(
        frame,
        module._diagnostics((meter_id,), (timestamp,), frame),
    )
    return bounded_parents, result


def test_nonfinite_residual_boundaries_are_controlled_and_finite_case_resolves() -> None:
    parents = module._parents(_values())
    cases = (
        ("subtraction", -1.0e308, 0.0, 1.0e308, 0.0, False),
        ("magnitude", 0.0, 0.0, 1.3e308, 1.3e308, False),
        ("large-finite", -1.0e307, 0.0, 1.0e307, 1.0e307, True),
    )
    for _label, ep, eq, mp, mq, should_resolve in cases:
        bounded_parents, result = _numerical_boundary_result(parents, ep, eq, mp, mq)
        row = result.states.iloc[0]
        assert bool(row["temporal_basis_compatible"])
        assert bool(row["benchmark_eligible"]) is should_resolve
        if should_resolve:
            assert row["active_power_residual_measured_minus_expected_w"] == 2.0e307
            assert math.isfinite(row["power_residual_vector_magnitude_va"])
            assert row["revenue_meter_power_benchmark_state"] == (
                "resolved_instantaneous_revenue_meter_power_benchmark"
            )
        else:
            assert row["revenue_meter_power_benchmark_state"] == (
                "unresolved_nonfinite_revenue_meter_power_residual"
            )
            for column in (
                "active_power_residual_measured_minus_expected_w",
                "reactive_power_residual_measured_minus_expected_var",
                "absolute_active_power_residual_w",
                "absolute_reactive_power_residual_var",
                "power_residual_vector_magnitude_va",
            ):
                assert pd.isna(row[column])
            assert row["expected_power_resolved"]
            assert row["measured_power_authority_resolved"]
            module._validate_result(bounded_parents, result)


def test_nonfinite_residual_publication_tampering_is_rejected() -> None:
    parents = module._parents(_values())
    bounded_parents, result = _numerical_boundary_result(parents, -1.0e308, 0.0, 1.0e308, 0.0)
    for value in (math.inf, 1.0):
        changed = result.states.copy(deep=True)
        changed.iloc[
            0,
            changed.columns.get_loc("active_power_residual_measured_minus_expected_w"),
        ] = value
        with pytest.raises(RuntimeError, match="independent exact closure"):
            module._validate_result(bounded_parents, replace(result, states=changed))


def test_zero_expected_power_supports_raw_residual_without_percentage() -> None:
    row = _run(
        p=0.0,
        q=0.0,
        energised=False,
        boundary_voltage=11_000.0,
        measured_p=10.0,
        measured_q=-3.0,
    ).states.iloc[0]
    assert row["expected_active_power_w"] == pytest.approx(0.0)
    assert row["active_power_residual_measured_minus_expected_w"] == pytest.approx(10.0)
    assert row["reactive_power_residual_measured_minus_expected_var"] == pytest.approx(-3.0)
    assert not any("percent" in column or "ratio" in column for column in module._COLUMNS)


def test_internal_and_grid_colocated_meter_contexts_are_preserved() -> None:
    internal = _run(meter_node="tx-node").states.iloc[0]
    colocated = _run().states.iloc[0]
    assert not internal["revenue_meter_colocated_with_grid_boundary"]
    assert internal["benchmark_eligible"]
    assert colocated["revenue_meter_colocated_with_grid_boundary"]
    assert colocated["colocated_grid_boundary_id"] == "grid"


def test_incompatible_timestamp_timezones_are_rejected() -> None:
    values = _values()
    state = next(iter(values["revenue_meter_measured_power_by_key"].values()))
    values["revenue_meter_measured_power_by_key"] = {
        (pd.Timestamp("2026-01-01 00:00:00"), "meter"): state
    }
    values["revenue_meter_measurement_authority"] = module._call(
        resolve_topology_revenue_meter_measurement_authority, values
    )
    with pytest.raises(ValueError, match="timezone"):
        calculate_topology_revenue_meter_power_benchmark(**values)


def test_empty_frame_schema_and_dtypes_are_stable() -> None:
    frame = module._frame((), [])
    assert tuple(frame.columns) == module._COLUMNS
    assert frame.index.names == ["timestamp", "revenue_meter_id"]
    assert frame.empty
    assert frame["benchmark_eligible"].dtype == "bool"
    assert frame["temporal_basis_compatible"].dtype == "boolean"
    assert frame["expected_active_power_w"].dtype == "float64"
    assert frame["revenue_meter_power_benchmark_state"].dtype == "object"


@pytest.mark.parametrize("parent", ["s13a", "s13c", "s13d"])
def test_strong_parent_replay_rejects_tampering(parent: str) -> None:
    values = _values()
    if parent == "s13a":
        supplied = values["mv_hv_network_authority"]
        changed = supplied.transformer_states.copy(deep=True)
        changed.iloc[0, 0] = not changed.iloc[0, 0]
        values["mv_hv_network_authority"] = replace(supplied, transformer_states=changed)
    elif parent == "s13c":
        supplied = values["mv_hv_operating_solution"]
        changed = supplied.revenue_meter_states.copy(deep=True)
        changed.iloc[0, changed.columns.get_loc("expected_p_at_revenue_meter_w")] += 1.0
        values["mv_hv_operating_solution"] = replace(supplied, revenue_meter_states=changed)
    else:
        supplied = values["revenue_meter_measurement_authority"]
        changed = supplied.states.copy(deep=True)
        changed.iloc[0, changed.columns.get_loc("measured_active_power_w")] += 1.0
        values["revenue_meter_measurement_authority"] = replace(supplied, states=changed)
    with pytest.raises(ValueError, match="canonical replay"):
        calculate_topology_revenue_meter_power_benchmark(**values)


def test_independent_validator_rejects_representative_result_tampering() -> None:
    values = _values(measured_p=123.0, measured_q=-7.0)
    parents = module._parents(values)
    result = calculate_topology_revenue_meter_power_benchmark(**values)
    tampering = {
        "revenue_meter_node_id": "wrong",
        "active_power_sign_convention": "wrong",
        "expected_power_resolved": False,
        "expected_active_power_w": 9.0,
        "expected_revenue_meter_state": "wrong",
        "measured_power_state_present": False,
        "measured_active_power_w": 8.0,
        "measurement_time_semantics": "wrong",
        "temporal_basis_compatible": False,
        "benchmark_eligible": False,
        "active_power_residual_measured_minus_expected_w": 7.0,
        "reactive_power_residual_measured_minus_expected_var": 6.0,
        "power_residual_vector_magnitude_va": 5.0,
        "revenue_meter_power_benchmark_state": "wrong",
        "revenue_meter_power_benchmark_contract": "wrong",
        "revenue_meter_power_benchmark_model": "wrong",
    }
    for column, value in tampering.items():
        changed = result.states.copy(deep=True)
        changed.iloc[0, changed.columns.get_loc(column)] = value
        with pytest.raises(RuntimeError, match="independent exact closure"):
            module._validate_result(parents, replace(result, states=changed))
    altered = replace(result.diagnostics, benchmark_eligible_count=0)
    with pytest.raises(RuntimeError, match="diagnostics"):
        module._validate_result(parents, replace(result, diagnostics=altered))


def test_validator_is_independent_of_production_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _values()
    parents = module._parents(values)
    result = calculate_topology_revenue_meter_power_benchmark(**values)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production builder called")

    monkeypatch.setattr(module, "_record", fail)
    monkeypatch.setattr(module, "_frame", fail)
    monkeypatch.setattr(module, "_diagnostics", fail)
    module._validate_result(parents, result)


def test_schema_order_and_source_exclusions_are_explicit() -> None:
    result = _run()
    assert tuple(result.states.columns) == module._COLUMNS
    assert len(module._COLUMNS) == len(set(module._COLUMNS))
    source = Path(module.__file__).read_text()
    assert "residual_pct" not in source
    assert "efficiency_pct" not in source
    assert "calculate_topology_mv_hv_operating_solution" in source
    assert "expected_p_at_revenue_meter_w" in source


def test_downstream_s12m_fallback_resolves_instantaneous_meter_benchmark() -> None:
    values = _values(fallback=True, measured_p_offset=17.0)
    s12m = values["transformer_advanced_operating_solution"].states.iloc[0]
    assert s12m["terminal_solution_fidelity"] == "coupled_s12g_load_loss_fallback"
    assert values["mv_hv_operating_solution"].revenue_meter_states.iloc[0][
        "mv_hv_operating_solution_resolved"
    ]
    result = calculate_topology_revenue_meter_power_benchmark(**values)
    row = result.states.iloc[0]
    assert row["revenue_meter_power_benchmark_state"] == (
        "resolved_instantaneous_revenue_meter_power_benchmark"
    )
    assert row["active_power_residual_measured_minus_expected_w"] == pytest.approx(17.0)
    assert row["active_power_residual_measured_minus_expected_w"] == pytest.approx(
        row["measured_active_power_w"] - row["expected_active_power_w"]
    )
