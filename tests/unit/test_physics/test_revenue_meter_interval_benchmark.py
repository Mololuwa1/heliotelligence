from __future__ import annotations

import math
from dataclasses import replace
from functools import cache
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
from tests.unit.test_physics.test_revenue_meter_interval_support_policy import policy
from tests.unit.test_physics.test_revenue_meter_power_benchmark import _values as _s14a_values


def _policy_mapping(maximum_gap: float | None = 3600.0) -> dict[str, Any]:
    """Explicit permissive test authority; never a production/default policy."""
    return {} if maximum_gap is None else {"meter": policy(maximum_gap)}


def _validate(parents: tuple[Any, ...], result: Any, *, policies: Any = None) -> None:
    module._validate_result(
        parents,
        result,
        revenue_meter_interval_support_policy_by_meter_id=_policy_mapping()
        if policies is None
        else policies,
    )


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", database)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", database)


@cache
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
    maximum_gap: float | None = 3600.0,
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
    record = module._record(*bounded_parents, end, "meter", _policy_mapping(maximum_gap))
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
        _validate(bounded, result)


def test_irregular_spacing_uses_all_samples_with_explicit_permissive_policy() -> None:
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
    _validate(bounded, result)


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
        _validate(bounded, result)


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
    _validate(bounded, result)
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
    _validate(bounded, result)


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
        _validate(bounded, result)


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
    _validate(bounded, result)


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
            _validate(bounded, replace(result, states=changed))
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate(
            bounded,
            replace(
                result,
                diagnostics=replace(result.diagnostics, benchmark_eligible_count=0),
            ),
        )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production helper called")

    for name in ("_interval_start", "_integrate", "_record", "_frame", "_diagnostics", "_policies"):
        monkeypatch.setattr(module, name, fail)
    _validate(bounded, result)


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
    _validate(bounded, result)
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


_RESIDUAL_COLUMNS = tuple(
    column
    for column in module._COLUMNS
    if "residual" in column and column != "residual_sign_semantics"
)


def test_missing_policy_preserves_reconstruction_but_not_benchmark_residuals() -> None:
    parents, result = _bounded(
        _parents(), [(3600, 50, 10, True), (0, 50, 10, True)], maximum_gap=None
    )
    row = result.states.iloc[0]
    assert row.expected_interval_reconstruction_resolved
    assert row.expected_interval_all_samples_resolved
    assert not row.expected_interval_support_policy_present
    assert not row.expected_interval_support_eligible
    assert not row.benchmark_eligible
    assert (
        row.revenue_meter_interval_benchmark_state
        == "unresolved_missing_expected_interval_support_policy"
    )
    assert row.expected_active_energy_wh == row.measured_active_energy_wh == 50
    assert row.expected_interval_average_active_power_w == 50
    assert row.maximum_expected_sample_gap_seconds == 3600
    assert row.maximum_expected_sample_gap_fraction_of_interval == 1
    assert pd.isna(row.maximum_expected_sample_gap_allowed_seconds)
    assert row.support_policy_parameter_source == row.support_policy_confidence == ""
    assert row[list(_RESIDUAL_COLUMNS)].isna().all()
    assert result.diagnostics.support_policy_missing_count == 1
    assert result.diagnostics.expected_interval_reconstruction_resolved_count == 1
    _validate(parents, result, policies={})


@pytest.mark.parametrize("allowed,eligible", [(2999.0, False), (3000.0, True), (3600.0, True)])
def test_irregular_gap_changes_eligibility_not_integration(allowed: float, eligible: bool) -> None:
    samples = [(3600, 0, 0, True), (3000, 60, 0, True), (0, 120, 0, True)]
    parents, result = _bounded(_parents(), samples, maximum_gap=allowed)
    row = result.states.iloc[0]
    assert (
        row.expected_interval_reconstruction_resolved and row.expected_interval_all_samples_resolved
    )
    assert row.expected_interval_average_active_power_w == pytest.approx(80)
    assert row.expected_active_energy_wh == pytest.approx(80)
    assert row.maximum_expected_sample_gap_fraction_of_interval == pytest.approx(5 / 6)
    assert row.expected_interval_support_gap_policy_satisfied == eligible
    assert row.expected_interval_support_eligible == row.benchmark_eligible == eligible
    if not eligible:
        assert (
            row.revenue_meter_interval_benchmark_state
            == "unresolved_expected_interval_support_gap_exceeds_policy"
        )
        assert row[list(_RESIDUAL_COLUMNS)].isna().all()
    assert result.diagnostics.support_policy_present_count == 1
    assert result.diagnostics.support_gap_policy_satisfied_count == int(eligible)
    assert result.diagnostics.support_gap_policy_failed_count == int(not eligible)
    _validate(parents, result, policies=_policy_mapping(allowed))


@pytest.mark.parametrize("sunset", [False, True], ids=["sunrise", "sunset"])
def test_analytic_daylight_edge_support_sensitivity_and_policy(sunset: bool) -> None:
    peak = 96.0
    exact_average = peak / 3
    results = []
    for divisions in [1, 4]:
        samples = []
        for index in range(divisions + 1):
            x = index / divisions
            p = peak * ((1 - x) ** 2 if sunset else x**2)
            samples.append((3600 * (1 - x), p, 0.0, True))
        parents, result = _bounded(
            _parents(), samples, maximum_gap=900, measured_p=exact_average, measured_q=0
        )
        row = result.states.iloc[0]
        assert row.expected_interval_reconstruction_resolved
        assert row.maximum_expected_sample_gap_seconds == 3600 / divisions
        assert row.benchmark_eligible == (divisions == 4)
        assert row.expected_interval_average_active_power_w == pytest.approx(
            48 if divisions == 1 else 33
        )
        assert row.expected_active_energy_wh == pytest.approx(48 if divisions == 1 else 33)
        if divisions == 1:
            assert row[list(_RESIDUAL_COLUMNS)].isna().all()
        _validate(parents, result, policies=_policy_mapping(900))
        results.append(abs(row.expected_interval_average_active_power_w - exact_average))
    assert results == pytest.approx([16, 1])
    assert results[1] < results[0]  # Analytic proxy only, not a real-site accuracy claim.


def test_constant_power_does_not_bypass_conservative_support_policy() -> None:
    parents, result = _bounded(
        _parents(), [(3600, 50, 10, True), (0, 50, 10, True)], maximum_gap=900
    )
    row = result.states.iloc[0]
    assert row.expected_interval_reconstruction_resolved
    assert row.expected_active_energy_wh == 50
    assert row.expected_interval_average_active_power_w == 50
    assert not row.benchmark_eligible
    assert row[list(_RESIDUAL_COLUMNS)].isna().all()
    _validate(parents, result, policies=_policy_mapping(900))


@pytest.mark.parametrize("allowed", [None, 900.0])
@pytest.mark.parametrize(
    "samples,temporal",
    [
        ([(0, 1, 0, True)], "instantaneous_snapshot"),
        ([(3599, 1, 0, True), (0, 1, 0, True)], "interval_average_ending_at_timestamp"),
        (
            [(3600, 1, 0, True), (1800, 1, 0, False), (0, 1, 0, True)],
            "interval_average_ending_at_timestamp",
        ),
    ],
)
def test_upstream_failures_are_not_support_policy_gaps(
    samples: Any, temporal: str, allowed: float | None
) -> None:
    parents, result = _bounded(_parents(), samples, maximum_gap=allowed, temporal=temporal)
    assert not result.states.iloc[0].expected_interval_reconstruction_resolved
    assert not result.states.iloc[0].expected_interval_support_eligible
    assert result.diagnostics.support_policy_present_count == 0
    assert result.diagnostics.support_policy_missing_count == 0
    assert result.diagnostics.support_gap_policy_satisfied_count == 0
    assert result.diagnostics.support_gap_policy_failed_count == 0
    _validate(parents, result, policies=_policy_mapping(allowed))


def _two_meter_parents() -> tuple[Any, Any, Any]:
    from types import MappingProxyType

    parents, _ = _bounded(_parents(), [(1800, 50, 10, True), (0, 50, 10, True)], duration=1800)
    a, c, d = parents
    boundaries = dict(a.revenue_meter_boundary_by_id)
    boundaries["meter-2"] = replace(boundaries["meter"], revenue_meter_id="meter-2")

    def duplicate(frame: pd.DataFrame) -> pd.DataFrame:
        other = frame.copy()
        other.index = pd.MultiIndex.from_tuples(
            [(t, "meter-2") for t, _ in frame.index], names=frame.index.names
        )
        return pd.concat([frame, other]).sort_index()

    return (
        replace(a, revenue_meter_boundary_by_id=MappingProxyType(boundaries)),
        replace(c, revenue_meter_states=duplicate(c.revenue_meter_states)),
        replace(d, states=duplicate(d.states)),
    )


def test_public_mapping_partial_coverage_reuse_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    parents = _two_meter_parents()
    monkeypatch.setattr(module, "_parents", lambda _values: parents)
    first = module.calculate_topology_revenue_meter_interval_benchmark(
        revenue_meter_interval_support_policy_by_meter_id={"meter": policy(1800)}
    )
    assert first.states.benchmark_eligible.tolist() == [True, False]
    assert (
        first.diagnostics.support_policy_present_count
        == first.diagnostics.support_policy_missing_count
        == 1
    )
    evidence = policy(1800)
    mapping = {"meter-2": evidence, "meter": evidence}
    reused = module.calculate_topology_revenue_meter_interval_benchmark(
        revenue_meter_interval_support_policy_by_meter_id=mapping
    )
    reordered = module.calculate_topology_revenue_meter_interval_benchmark(
        revenue_meter_interval_support_policy_by_meter_id=dict(reversed(list(mapping.items())))
    )
    assert reused.states.benchmark_eligible.all()
    pd.testing.assert_frame_equal(reused.states, reordered.states)
    assert reused.diagnostics == reordered.diagnostics
    differing = module.calculate_topology_revenue_meter_interval_benchmark(
        revenue_meter_interval_support_policy_by_meter_id={
            "meter": policy(900),
            "meter-2": policy(1800),
        }
    )
    assert differing.states.benchmark_eligible.tolist() == [False, True]
    assert differing.diagnostics.support_gap_policy_failed_count == 1


@pytest.mark.parametrize(
    "supplied", [{"unknown": policy()}, {1: policy()}, [], "policy", False, {"meter": object()}]
)
def test_public_rejects_invalid_policy_mapping(
    monkeypatch: pytest.MonkeyPatch, supplied: Any
) -> None:
    parents, _ = _bounded(_parents(), [(3600, 50, 10, True), (0, 50, 10, True)])
    monkeypatch.setattr(module, "_parents", lambda _values: parents)
    with pytest.raises(ValueError):
        module.calculate_topology_revenue_meter_interval_benchmark(
            revenue_meter_interval_support_policy_by_meter_id=supplied
        )


def test_omitted_policy_and_tampered_frozen_authority_public_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parents, _ = _bounded(_parents(), [(3600, 50, 10, True), (0, 50, 10, True)])
    monkeypatch.setattr(module, "_parents", lambda _values: parents)
    omitted = module.calculate_topology_revenue_meter_interval_benchmark()
    assert (
        omitted.states.iloc[0].revenue_meter_interval_benchmark_state
        == "unresolved_missing_expected_interval_support_policy"
    )
    forged = policy()
    object.__setattr__(forged, "maximum_expected_sample_gap_seconds", 0)
    with pytest.raises(ValueError):
        module.calculate_topology_revenue_meter_interval_benchmark(
            revenue_meter_interval_support_policy_by_meter_id={"meter": forged}
        )
    with pytest.raises(ValueError):
        module._validate_result(
            parents, omitted, revenue_meter_interval_support_policy_by_meter_id={"meter": forged}
        )


@pytest.mark.parametrize(
    "column,value",
    [
        ("expected_interval_reconstruction_resolved", False),
        ("expected_interval_support_policy_present", False),
        ("maximum_expected_sample_gap_allowed_seconds", 1),
        ("maximum_expected_sample_gap_fraction_of_interval", 0.3),
        ("expected_interval_support_gap_policy_satisfied", False),
        ("expected_interval_support_eligible", False),
        ("support_policy_scope", "wrong"),
        ("support_policy_evidence_kind", "wrong"),
        ("support_policy_parameter_source", "wrong"),
        ("support_policy_confidence", "low"),
        ("support_policy_method_reference", "wrong"),
        ("support_policy_applicability_description", "wrong"),
        ("revenue_meter_interval_support_policy_contract", "wrong"),
    ],
)
def test_new_policy_public_fields_tamper_rejected(column: str, value: Any) -> None:
    parents, result = _bounded(_parents(), [(3600, 50, 10, True), (0, 50, 10, True)])
    frame = result.states.copy()
    frame.at[frame.index[0], column] = value
    with pytest.raises(RuntimeError, match="independent exact closure"):
        _validate(parents, replace(result, states=frame))


@pytest.mark.parametrize("allowed", [None, 900.0, 3600.0])
def test_independent_validator_replays_each_policy_outcome(
    monkeypatch: pytest.MonkeyPatch, allowed: float | None
) -> None:
    parents, result = _bounded(
        _parents(), [(3600, 50, 10, True), (0, 50, 10, True)], maximum_gap=allowed
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("production support helper called")

    for name in [
        "_record",
        "_base_record",
        "_interval_start",
        "_integrate",
        "_frame",
        "_diagnostics",
        "_policies",
    ]:
        monkeypatch.setattr(module, name, forbidden)
    _validate(parents, result, policies=_policy_mapping(allowed))


def test_v2_identities_reconstruction_semantics_unchanged() -> None:
    assert module.REVENUE_METER_INTERVAL_BENCHMARK_CONTRACT_ID == (
        "admitted_s13a_s13c_s13d_and_support_policy_to_exact_interval_average_"
        "revenue_meter_energy_benchmark_v2"
    )
    assert module.REVENUE_METER_INTERVAL_BENCHMARK_MODEL_ID == (
        "piecewise_linear_s13c_expected_power_trapezoidal_interval_integration_"
        "with_explicit_maximum_support_gap_eligibility_v2"
    )
    assert (
        module.TEMPORAL_RECONSTRUCTION_SEMANTICS
        == "piecewise_linear_between_resolved_s13c_meter_samples_with_exact_interval_boundaries_v1"
    )
    assert (
        module.ENERGY_INTEGRATION_SEMANTICS
        == "trapezoidal_time_integral_of_piecewise_linear_expected_power_v1"
    )


@pytest.mark.parametrize(
    "field",
    [
        "expected_interval_reconstruction_resolved_count",
        "support_policy_present_count",
        "support_policy_missing_count",
        "support_gap_policy_satisfied_count",
        "support_gap_policy_failed_count",
    ],
)
def test_support_diagnostics_tamper_rejected(field: str) -> None:
    parents, result = _bounded(_parents(), [(3600, 50, 10, True), (0, 50, 10, True)])
    diagnostics = replace(result.diagnostics, **{field: getattr(result.diagnostics, field) + 1})
    with pytest.raises(RuntimeError, match="diagnostics"):
        _validate(parents, replace(result, diagnostics=diagnostics))
