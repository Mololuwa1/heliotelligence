from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import revenue_meter_interval_benchmark as module
from heliotelligence.physics.revenue_meter_interval_benchmark import (
    calculate_topology_revenue_meter_interval_benchmark,
)
from tests.unit.test_physics import test_inverter_dispatch_feasibility as support
from tests.unit.test_physics.test_revenue_meter_power_benchmark import _values as _s14a_values


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


def _parents() -> tuple[Any, Any, Any]:
    return module._parents(
        _s14a_values(
            temporal="interval_average_ending_at_timestamp",
            interval=3600.0,
            measured_p=50.0,
            measured_q=10.0,
        )
    )


def _bounded(
    parents: tuple[Any, Any, Any],
    samples: list[tuple[float, float, float, bool]],
    *,
    duration: float = 3600.0,
    measured_p: float = 50.0,
    measured_q: float = 10.0,
    temporal: str = "interval_average_ending_at_timestamp",
) -> tuple[tuple[Any, Any, Any], Any]:
    s13a, s13c, s13d = parents
    end = s13d.states.index.get_level_values("timestamp")[0]
    template = s13c.revenue_meter_states.iloc[0]
    rows: list[pd.Series[Any]] = []
    keys: list[tuple[pd.Timestamp, str]] = []
    for seconds_before_end, p, q, resolved in samples:
        row = template.copy(deep=True)
        row["expected_p_at_revenue_meter_w"] = p
        row["expected_q_at_revenue_meter_var"] = q
        row["expected_s_at_revenue_meter_magnitude_va"] = math.hypot(p, q)
        row["mv_hv_operating_solution_resolved"] = resolved
        row["revenue_meter_expected_state"] = (
            "resolved_expected_revenue_meter_boundary_power"
            if resolved
            else "unresolved_upstream_mv_hv_operating_solution"
        )
        rows.append(row)
        keys.append((end - pd.Timedelta(seconds=seconds_before_end), "meter"))
    expected = pd.DataFrame(rows)
    expected.index = pd.MultiIndex.from_tuples(keys, names=["timestamp", "revenue_meter_id"])
    expected = expected.sort_index()
    measured = s13d.states.copy(deep=True)
    measured.loc[:, "measured_active_power_w"] = measured_p
    measured.loc[:, "measured_reactive_power_var"] = measured_q
    measured.loc[:, "measured_apparent_power_magnitude_va"] = math.hypot(measured_p, measured_q)
    measured.loc[:, "measurement_time_semantics"] = temporal
    measured.loc[:, "averaging_interval_seconds"] = (
        duration if temporal == "interval_average_ending_at_timestamp" else math.nan
    )
    bounded_parents = (
        s13a,
        replace(s13c, revenue_meter_states=expected),
        replace(s13d, states=measured),
    )
    record = module._record(*bounded_parents, end, "meter")
    frame = module._frame(((end, "meter"),), [record])
    result = module.TopologyRevenueMeterIntervalBenchmarkResult(
        frame,
        module._diagnostics(("meter",), (end,), frame),
    )
    return bounded_parents, result


def test_constant_linear_irregular_and_signed_interval_equations() -> None:
    parents = _parents()
    cases = (
        ([(3600.0, 50.0, 10.0, True), (0.0, 50.0, 10.0, True)], 50.0, 10.0),
        ([(3600.0, 0.0, -20.0, True), (0.0, 100.0, 20.0, True)], 50.0, 0.0),
        (
            [
                (3600.0, 0.0, -30.0, True),
                (2700.0, 40.0, -10.0, True),
                (0.0, 100.0, 20.0, True),
            ],
            57.5,
            -1.25,
        ),
        ([(3600.0, -100.0, 0.0, True), (0.0, -20.0, 0.0, True)], -60.0, 0.0),
        ([(3600.0, -100.0, 0.0, True), (0.0, 100.0, 0.0, True)], 0.0, 0.0),
    )
    for samples, expected_p, expected_q in cases:
        bounded, result = _bounded(
            parents, samples, measured_p=expected_p + 5.0, measured_q=expected_q - 2.0
        )
        row = result.states.iloc[0]
        assert row["benchmark_eligible"]
        assert row["expected_interval_average_active_power_w"] == pytest.approx(expected_p)
        assert row["expected_interval_average_reactive_power_var"] == pytest.approx(expected_q)
        assert row["expected_active_energy_wh"] == pytest.approx(expected_p)
        assert row["expected_reactive_energy_varh"] == pytest.approx(expected_q)
        assert row["measured_active_energy_wh"] == pytest.approx(expected_p + 5.0)
        assert row["active_power_residual_measured_minus_expected_w"] == pytest.approx(5.0)
        assert row["reactive_power_residual_measured_minus_expected_var"] == pytest.approx(-2.0)
        assert row["active_energy_residual_measured_minus_expected_wh"] == pytest.approx(5.0)
        assert row["reactive_energy_residual_measured_minus_expected_varh"] == pytest.approx(-2.0)
        module._validate_result(bounded, result)


def test_irregular_spacing_uses_all_samples_and_reports_unclassified_max_gap() -> None:
    parents = _parents()
    bounded, result = _bounded(
        parents,
        [
            (3600.0, 0.0, 0.0, True),
            (3000.0, 60.0, 0.0, True),
            (0.0, 120.0, 0.0, True),
        ],
        measured_p=90.0,
        measured_q=0.0,
    )
    row = result.states.iloc[0]
    assert row["expected_interval_sample_count"] == 3
    assert row["expected_interval_segment_count"] == 2
    assert row["maximum_expected_sample_gap_seconds"] == 3000.0
    assert row["expected_interval_average_active_power_w"] == pytest.approx(80.0)
    module._validate_result(bounded, result)


def test_snapshot_missing_boundaries_and_unresolved_samples_have_exact_states() -> None:
    parents = _parents()
    cases = (
        (
            [(0.0, 50.0, 10.0, True)],
            "instantaneous_snapshot",
            "unresolved_instantaneous_measurement_owned_by_s14a",
        ),
        (
            [(3599.0, 50.0, 10.0, True), (0.0, 50.0, 10.0, True)],
            "interval_average_ending_at_timestamp",
            "unresolved_missing_expected_interval_boundary_state",
        ),
        (
            [(3600.0, 50.0, 10.0, True), (1800.0, 50.0, 10.0, False), (0.0, 50.0, 10.0, True)],
            "interval_average_ending_at_timestamp",
            "unresolved_expected_interval_operating_solution",
        ),
    )
    for samples, temporal, state in cases:
        bounded, result = _bounded(parents, samples, temporal=temporal)
        row = result.states.iloc[0]
        assert not row["benchmark_eligible"]
        assert row["revenue_meter_interval_benchmark_state"] == state
        assert pd.isna(row["expected_active_energy_wh"])
        module._validate_result(bounded, result)


def test_exact_subsecond_and_nonrepresentable_interval_boundaries() -> None:
    parents = _parents()
    bounded, result = _bounded(
        parents,
        [(0.1, 10.0, 0.0, True), (0.0, 10.0, 0.0, True)],
        duration=0.1,
        measured_p=10.0,
        measured_q=0.0,
    )
    assert result.states.iloc[0]["benchmark_eligible"]
    module._validate_result(bounded, result)
    bounded, result = _bounded(
        parents,
        [(0.0, 10.0, 0.0, True)],
        duration=1.0 / 3.0,
    )
    row = result.states.iloc[0]
    assert not row["interval_boundary_exactly_representable"]
    assert row["revenue_meter_interval_benchmark_state"] == (
        "unresolved_interval_boundary_not_exactly_representable"
    )
    module._validate_result(bounded, result)


def test_nonfinite_integration_measured_energy_and_residual_are_controlled() -> None:
    parents = _parents()
    cases = (
        ([(7200.0, 1.7e308, 0.0, True), (0.0, 1.7e308, 0.0, True)], 0.0, 7200.0),
        ([(7200.0, 0.0, 0.0, True), (0.0, 0.0, 0.0, True)], 1.0e308, 7200.0),
        (
            [(3600.0, -1.0e308, 0.0, True), (0.0, -1.0e308, 0.0, True)],
            1.0e308,
            3600.0,
        ),
    )
    for samples, measured_p, duration in cases:
        bounded, result = _bounded(
            parents,
            samples,
            duration=duration,
            measured_p=measured_p,
            measured_q=0.0,
        )
        row = result.states.iloc[0]
        assert not row["benchmark_eligible"]
        assert row["revenue_meter_interval_benchmark_state"] == (
            "unresolved_nonfinite_interval_benchmark_arithmetic"
        )
        for column in (
            "expected_active_energy_wh",
            "measured_active_energy_wh",
            "active_power_residual_measured_minus_expected_w",
            "active_energy_residual_measured_minus_expected_wh",
        ):
            assert pd.isna(row[column])
        module._validate_result(bounded, result)


def test_public_resolution_preserves_interval_measurement_when_start_is_missing() -> None:
    values = _s14a_values(
        temporal="interval_average_ending_at_timestamp",
        interval=3600.0,
        measured_p=50.0,
        measured_q=10.0,
    )
    result = calculate_topology_revenue_meter_interval_benchmark(**values)
    row = result.states.iloc[0]
    assert row["measured_power_authority_resolved"]
    assert row["measured_interval_average_active_power_w"] == 50.0
    assert row["revenue_meter_interval_benchmark_state"] == (
        "unresolved_missing_expected_interval_boundary_state"
    )
    assert pd.isna(row["expected_active_energy_wh"])


def test_public_resolution_preserves_measurement_with_zero_s13c_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _s14a_values(
        temporal="interval_average_ending_at_timestamp",
        interval=3600.0,
        measured_p=50.0,
        measured_q=10.0,
    )
    s13a, s13c, s13d = module._parents(values)
    empty_expected = s13c.revenue_meter_states.iloc[0:0].copy(deep=True)
    empty_s13c = replace(s13c, revenue_meter_states=empty_expected)
    monkeypatch.setattr(module, "_parents", lambda _values: (s13a, empty_s13c, s13d))

    result = calculate_topology_revenue_meter_interval_benchmark(**values)
    assert len(result.states) == 1
    row = result.states.iloc[0]
    assert row["measured_parent_row_present"]
    assert row["measured_power_state_present"]
    assert row["measured_power_authority_resolved"]
    assert row["measured_interval_average_active_power_w"] == 50.0
    assert row["measured_interval_average_reactive_power_var"] == 10.0
    assert row["interval_boundary_exactly_representable"]
    assert row["interval_start_timestamp"] == result.states.index[0][0] - pd.Timedelta(hours=1)
    assert not row["expected_interval_start_row_present"]
    assert not row["expected_interval_end_row_present"]
    assert row["expected_interval_sample_count"] == 0
    assert row["expected_interval_resolved_sample_count"] == 0
    assert row["expected_interval_unresolved_sample_count"] == 0
    assert row["expected_interval_sample_timestamps"] == ()
    assert row["unresolved_expected_sample_timestamps"] == ()
    assert row["expected_interval_segment_count"] == 0
    assert pd.isna(row["maximum_expected_sample_gap_seconds"])
    assert not row["expected_interval_all_samples_resolved"]
    assert not row["benchmark_eligible"]
    assert row["revenue_meter_interval_benchmark_state"] == (
        "unresolved_missing_expected_interval_boundary_state"
    )
    for column in (
        "expected_active_energy_wh",
        "expected_reactive_energy_varh",
        "measured_active_energy_wh",
        "measured_reactive_energy_varh",
        "active_power_residual_measured_minus_expected_w",
        "reactive_power_residual_measured_minus_expected_var",
        "active_energy_residual_measured_minus_expected_wh",
        "reactive_energy_residual_measured_minus_expected_varh",
    ):
        assert pd.isna(row[column])
    module._validate_result((s13a, empty_s13c, s13d), result)


def test_half_hour_power_and_energy_residual_representations_close() -> None:
    parents = _parents()
    bounded, result = _bounded(
        parents,
        [(1800.0, 20.0, -10.0, True), (0.0, 60.0, 30.0, True)],
        duration=1800.0,
        measured_p=50.0,
        measured_q=5.0,
    )
    row = result.states.iloc[0]
    hours = 0.5
    assert row["benchmark_eligible"]
    assert row["active_energy_residual_measured_minus_expected_wh"] == pytest.approx(
        row["active_power_residual_measured_minus_expected_w"] * hours
    )
    assert row["reactive_energy_residual_measured_minus_expected_varh"] == pytest.approx(
        row["reactive_power_residual_measured_minus_expected_var"] * hours
    )
    module._validate_result(bounded, result)


def test_strong_parent_replay_rejects_each_parent() -> None:
    for parent_name in (
        "mv_hv_network_authority",
        "mv_hv_operating_solution",
        "revenue_meter_measurement_authority",
    ):
        values = _s14a_values(
            temporal="interval_average_ending_at_timestamp",
            interval=3600.0,
            measured_p=50.0,
            measured_q=10.0,
        )
        supplied = values[parent_name]
        if parent_name == "mv_hv_network_authority":
            changed = supplied.transformer_states.copy(deep=True)
            changed.iloc[0, 0] = not changed.iloc[0, 0]
            values[parent_name] = replace(supplied, transformer_states=changed)
        elif parent_name == "mv_hv_operating_solution":
            changed = supplied.revenue_meter_states.copy(deep=True)
            changed.iloc[0, changed.columns.get_loc("expected_p_at_revenue_meter_w")] += 1.0
            values[parent_name] = replace(supplied, revenue_meter_states=changed)
        else:
            changed = supplied.states.copy(deep=True)
            changed.iloc[0, changed.columns.get_loc("averaging_interval_seconds")] += 1.0
            values[parent_name] = replace(supplied, states=changed)
        with pytest.raises(ValueError, match="canonical replay"):
            calculate_topology_revenue_meter_interval_benchmark(**values)


def test_independent_validator_rejects_tampering_and_ignores_production_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parents = _parents()
    bounded, result = _bounded(
        parents,
        [(3600.0, 0.0, 0.0, True), (0.0, 100.0, 20.0, True)],
        measured_p=60.0,
        measured_q=5.0,
    )
    for column, value in {
        "revenue_meter_node_id": "wrong",
        "averaging_interval_seconds": 10.0,
        "interval_start_timestamp": pd.Timestamp("2000-01-01T00:00:00Z"),
        "expected_interval_sample_count": 99,
        "expected_interval_sample_timestamps": (),
        "maximum_expected_sample_gap_seconds": 1.0,
        "expected_interval_average_active_power_w": 1.0,
        "expected_active_energy_wh": 2.0,
        "measured_active_energy_wh": 3.0,
        "active_power_residual_measured_minus_expected_w": 4.0,
        "active_energy_residual_measured_minus_expected_wh": 5.0,
        "benchmark_eligible": False,
        "revenue_meter_interval_benchmark_state": "wrong",
        "revenue_meter_interval_benchmark_contract": "wrong",
    }.items():
        changed = result.states.copy(deep=True)
        changed.at[changed.index[0], column] = value
        with pytest.raises(RuntimeError, match="independent exact closure"):
            module._validate_result(bounded, replace(result, states=changed))
    with pytest.raises(RuntimeError, match="diagnostics"):
        module._validate_result(
            bounded,
            replace(
                result,
                diagnostics=replace(result.diagnostics, benchmark_eligible_count=0),
            ),
        )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production helper called")

    for name in ("_interval_start", "_integrate", "_record", "_frame", "_diagnostics"):
        monkeypatch.setattr(module, name, fail)
    module._validate_result(bounded, result)


def test_empty_schema_dtypes_and_source_exclusions() -> None:
    frame = module._frame((), [])
    assert tuple(frame.columns) == module._COLUMNS
    assert frame.index.names == ["timestamp", "revenue_meter_id"]
    assert frame.empty
    assert frame["benchmark_eligible"].dtype == "bool"
    assert frame["expected_interval_sample_count"].dtype == "int64"
    assert frame["expected_active_energy_wh"].dtype == "float64"
    assert frame["revenue_meter_interval_benchmark_state"].dtype == "object"
    source = Path(module.__file__).read_text()
    assert "revenue_meter_power_benchmark" not in source
    assert "percentage" not in source
    assert "nearest" in module.TIMESTAMP_ALIGNMENT_SEMANTICS


def test_downstream_fallback_support_integrates_without_special_adjustment() -> None:
    values = _s14a_values(
        fallback=True,
        temporal="interval_average_ending_at_timestamp",
        interval=1800.0,
    )
    assert values["transformer_advanced_operating_solution"].states.iloc[0][
        "load_loss_fallback_applied"
    ]
    parents = module._parents(values)
    expected = parents[1].revenue_meter_states.iloc[0]
    p, q = (
        float(expected["expected_p_at_revenue_meter_w"]),
        float(expected["expected_q_at_revenue_meter_var"]),
    )
    # Stationary boundary support is taken from the real canonical fallback solve.
    bounded, result = _bounded(
        parents,
        [(1800.0, p, q, True), (900.0, p, q, True), (0.0, p, q, True)],
        duration=1800.0,
        measured_p=p + 10.0,
        measured_q=q,
    )
    module._validate_result(bounded, result)
    row = result.states.iloc[0]
    end = row.name[0]
    assert row["expected_interval_sample_timestamps"] == (
        end - pd.Timedelta(minutes=30),
        end - pd.Timedelta(minutes=15),
        end,
    )
    assert row["revenue_meter_interval_benchmark_state"] == (
        "resolved_interval_average_revenue_meter_energy_benchmark"
    )
    assert row["expected_active_energy_wh"] == pytest.approx(p * 0.5)
    assert row["measured_active_energy_wh"] == pytest.approx((p + 10.0) * 0.5)
    assert row["active_energy_residual_measured_minus_expected_wh"] == pytest.approx(5.0)
