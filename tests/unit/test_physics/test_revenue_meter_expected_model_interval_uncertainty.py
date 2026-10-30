from __future__ import annotations

import ast
import inspect
import math
import typing
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import revenue_meter_expected_model_interval_uncertainty as m
from tests.unit.test_physics import test_revenue_meter_expected_model_uncertainty as point_support
from tests.unit.test_physics import test_revenue_meter_interval_benchmark as interval_support


@pytest.fixture(autouse=True)
def fake_cec_database(monkeypatch: Any) -> None:
    db = interval_support.support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)


@pytest.fixture(scope="module")
def seed() -> Any:
    with pytest.MonkeyPatch.context() as patch:
        db = interval_support.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)
        return interval_support._parents()


def unit_case(
    seed: Any,
    samples: Any = None,
    *,
    a: Any = None,
    duration: float = 3600,
    maximum_gap: float | None = None,
    temporal: str = "interval_average_ending_at_timestamp",
) -> Any:
    """Controlled mathematics only; these parents are never passed as raw public inputs."""
    samples = samples if samples is not None else [(3600, 50, 20, True), (0, 150, 80, True)]
    parents, benchmark = interval_support._bounded(
        seed, samples, duration=duration, temporal=temporal, maximum_gap=maximum_gap
    )
    policies = interval_support._policy_mapping(maximum_gap)
    m.s14b._validate_result(
        parents, benchmark, revenue_meter_interval_support_policy_by_meter_id=policies
    )
    a = (
        a
        if a is not None
        else point_support.authority(
            active_power_relative_error_bound_fraction=0.1,
            active_power_absolute_error_bound_w=5,
            reactive_power_relative_error_bound_fraction=0.1,
            reactive_power_absolute_error_bound_var=5,
        )
    )
    mapping = {} if a is False else {"meter": a}
    records = [
        m.pointwise._record(t, row, mapping.get(meter))
        for (t, meter), row in parents[1].revenue_meter_states.iterrows()
    ]
    states = m.pointwise._frame(parents[1].revenue_meter_states, records)
    point = m.pointwise.RevenueMeterExpectedModelUncertaintyResult(
        states, m.pointwise._diagnostics(parents[0], states)
    )
    m.pointwise._validate_result(parents[0], parents[1], point, mapping)
    out = [m._record(meter, row, point) for (_, meter), row in benchmark.states.iterrows()]
    frame = m._frame(benchmark, out)
    snapshot = m._support_snapshot(benchmark, point)
    result = m.RevenueMeterExpectedModelIntervalUncertaintyResult(
        frame, snapshot, m._diagnostics(frame, snapshot)
    )
    m._validate_result(benchmark, point, result)
    return benchmark, point, result


@pytest.fixture(scope="module")
def simple(seed: Any) -> Any:
    return unit_case(seed)


def test_two_point_example_and_original_frames_unchanged(simple: Any) -> None:
    benchmark, point, result = simple
    row = result.states.iloc[0]
    assert row.active_energy_expected_model_uncertainty_bound_wh == 15
    assert row.active_interval_average_power_expected_model_uncertainty_bound_w == 15
    assert row.expected_active_energy_lower_bound_wh == 85
    assert row.expected_active_energy_upper_bound_wh == 115
    assert row.expected_interval_average_active_power_lower_bound_w == 85
    assert row.expected_interval_average_active_power_upper_bound_w == 115
    assert row.reactive_energy_expected_model_uncertainty_bound_varh == 10
    pd.testing.assert_frame_equal(result.states[benchmark.states.columns], benchmark.states)
    pd.testing.assert_frame_equal(result.pointwise_support_states, point.states)
    assert row.expected_model_interval_uncertainty_state == m._STATES[5]


@pytest.mark.parametrize("gap,eligible", [(None, False), (900, False), (3600, True)])
def test_support_policy_is_orthogonal_to_propagation(seed: Any, gap: Any, eligible: bool) -> None:
    original, _, result = unit_case(seed, maximum_gap=gap)
    row = result.states.iloc[0]
    assert row.expected_interval_reconstruction_resolved
    assert bool(row.expected_interval_support_eligible) == eligible
    assert bool(row.benchmark_eligible) == eligible
    assert row.active_expected_model_interval_uncertainty_resolved
    assert row.active_energy_expected_model_uncertainty_bound_wh == 15
    if not eligible:
        assert math.isnan(row.active_energy_residual_measured_minus_expected_wh)
    pd.testing.assert_frame_equal(result.states[original.states.columns], original.states)
    assert result.diagnostics.support_policy_ineligible_count == int(not eligible)


def test_irregular_spacing_and_tight_worst_case(seed: Any) -> None:
    a = point_support.authority(
        active_power_relative_error_bound_fraction=1,
        active_power_absolute_error_bound_w=0,
        reactive_power_relative_error_bound_fraction=1,
        reactive_power_absolute_error_bound_var=0,
    )
    _, point, result = unit_case(
        seed, [(3600, 0, 0, True), (3000, 60, -30, True), (0, 120, -60, True)], a=a
    )
    row = result.states.iloc[0]
    assert row.active_energy_expected_model_uncertainty_bound_wh == 80
    assert row.active_interval_average_power_expected_model_uncertainty_bound_w == 80
    assert row.reactive_energy_expected_model_uncertainty_bound_varh == 40
    assert row.expected_reactive_energy_lower_bound_varh == -80
    assert row.expected_reactive_energy_upper_bound_varh == 0
    times = row.expected_interval_sample_timestamps
    central = [
        float(point.states.loc[(t, "meter"), "expected_p_at_revenue_meter_w"]) for t in times
    ]
    bounds = [
        float(point.states.loc[(t, "meter"), "active_power_expected_model_uncertainty_bound_w"])
        for t in times
    ]

    def functional(values: Any) -> float:
        return math.fsum(
            (values[i] / 2 + values[i + 1] / 2) * ((times[i + 1] - times[i]).value / 1e9 / 3600)
            for i in range(len(times) - 1)
        )

    nominal = functional(central)
    assert functional(
        [v + b for v, b in zip(central, bounds, strict=True)]
    ) - nominal == pytest.approx(80)
    assert functional(
        [v - b for v, b in zip(central, bounds, strict=True)]
    ) - nominal == pytest.approx(-80)


@pytest.mark.parametrize("sign", [1, -1])
def test_zero_bound_and_signed_centers(seed: Any, sign: int) -> None:
    a = point_support.authority(**dict.fromkeys(m.pointwise._AUTHORITY_NUMBERS, 0))
    original, _, result = unit_case(
        seed, [(3600, 50 * sign, 20 * sign, True), (0, 150 * sign, 80 * sign, True)], a=a
    )
    row = result.states.iloc[0]
    assert row.active_energy_expected_model_uncertainty_bound_wh == 0
    assert (
        row.expected_active_energy_lower_bound_wh
        == row.expected_active_energy_upper_bound_wh
        == 100 * sign
    )
    assert row.expected_interval_average_active_power_lower_bound_w == 100 * sign
    pd.testing.assert_frame_equal(result.states[original.states.columns], original.states)


@pytest.mark.parametrize("mode", ["active", "reactive", "missing", "partial_time"])
def test_channel_independence_and_exact_unresolved_support(seed: Any, mode: str) -> None:
    changes = {}
    if mode == "active":
        changes.update(
            reactive_power_relative_error_bound_fraction=None,
            reactive_power_absolute_error_bound_var=None,
        )
    elif mode == "reactive":
        changes.update(
            active_power_relative_error_bound_fraction=None,
            active_power_absolute_error_bound_w=None,
        )
    elif mode == "partial_time":
        end = seed[2].states.index[0][0]
        changes["valid_from_timestamp"] = end - pd.Timedelta(seconds=3599)
    a = False if mode == "missing" else point_support.authority(**changes)
    _, _, result = unit_case(seed, a=a)
    row = result.states.iloc[0]
    assert bool(row.active_expected_model_interval_uncertainty_resolved) == (mode == "active")
    assert bool(row.reactive_expected_model_interval_uncertainty_resolved) == (mode == "reactive")
    times = row.expected_interval_sample_timestamps
    if mode == "partial_time":
        assert row.unresolved_active_pointwise_expected_model_support_timestamps == (times[0],)
        assert result.diagnostics.active_support_incomplete_count == 1
    if mode == "active":
        assert row.unresolved_reactive_pointwise_expected_model_support_timestamps == times
        assert row.expected_model_interval_uncertainty_state == m._STATES[3]
    if mode == "reactive":
        assert row.expected_model_interval_uncertainty_state == m._STATES[4]


@pytest.mark.parametrize(
    "kind", ["snapshot", "missing_start", "unrepresentable", "unresolved_sample", "nonfinite"]
)
def test_reconstruction_failure_not_classified_as_pointwise_gap(seed: Any, kind: str) -> None:
    options = {}
    samples = [(3600, 50, 10, True), (0, 50, 10, True)]
    if kind == "snapshot":
        options["temporal"] = "instantaneous_snapshot"
    elif kind == "missing_start":
        samples = [(0, 50, 10, True)]
    elif kind == "unrepresentable":
        options["duration"] = 1e-10
    elif kind == "unresolved_sample":
        samples = [(3600, 50, 10, False), (0, 50, 10, True)]
    else:
        samples = [(7200, 1e308, 0, True), (0, 1e308, 0, True)]
        options["duration"] = 7200
    _, _, result = unit_case(seed, samples, **options)
    assert not result.states.iloc[0].expected_interval_reconstruction_resolved
    assert result.states.iloc[0].expected_model_interval_uncertainty_state == m._STATES[0]
    assert result.diagnostics.active_support_incomplete_count == 0
    assert result.diagnostics.reactive_support_incomplete_count == 0
    assert not result.states.iloc[0].pointwise_expected_model_support_assessed


def test_exact_subsecond_and_dst_elapsed_math() -> None:
    end = pd.Timestamp("2026-01-01", tz="UTC")
    times = (end - pd.Timedelta(1000000002, unit="ns"), end - pd.Timedelta(1, unit="ns"), end)
    answer = m._propagate(times, (0, 1, 0), 1.000000002, 0, 0)
    assert answer is not None
    assert answer[0] == pytest.approx(0.5 * 1.000000002 / 3600, abs=1e-19, rel=0)
    assert answer[3] == pytest.approx(0.5, abs=1e-15, rel=0)
    start = pd.Timestamp("2026-10-25T00:30:00Z").tz_convert("Europe/London")
    finish = pd.Timestamp("2026-10-25T01:30:00Z").tz_convert("Europe/London")
    assert start.hour == finish.hour == 1
    assert m._propagate((start, finish), (10, 20), 3600, 100, 100) == (15, 85, 115, 15, 85, 115)


def test_safe_half_plus_half_and_arithmetic_failures(seed: Any) -> None:
    end = pd.Timestamp("2026-01-01", tz="UTC")
    start = end - pd.Timedelta(hours=1)
    answer = m._propagate((start, end), (1e308, 1e308), 3600, 0, 0)
    assert answer is not None and answer[0] == 1e308
    cases = [
        ((start, end), (math.inf, 1), 3600, 0, 0),
        ((start, end), (-1, 1), 3600, 0, 0),
        ((end, start), (1, 1), 3600, 0, 0),
        ((start, end), (1, 1), 0, 0, 0),
        ((start, end), (1, 1), 1e-320, 0, 0),
        ((start, end), (1e308, 1e308), 3600, 1e308, 1e308),
        ((pd.Timestamp.min, pd.Timestamp.max), (1, 1), 3600, 0, 0),
        (
            (end - pd.Timedelta(hours=4), end - pd.Timedelta(hours=2), end),
            (8e307,) * 3,
            14400,
            0,
            0,
        ),
    ]
    for args in cases:
        assert m._propagate(*args) is None
    a = point_support.authority(
        active_power_relative_error_bound_fraction=None,
        active_power_absolute_error_bound_w=1e308,
        reactive_power_relative_error_bound_fraction=None,
        reactive_power_absolute_error_bound_var=0,
    )
    _, _, result = unit_case(seed, [(7200, 0, 0, True), (0, 0, 0, True)], duration=7200, a=a)
    row = result.states.iloc[0]
    assert row.active_pointwise_expected_model_uncertainty_support_complete
    assert not row.active_expected_model_interval_uncertainty_resolved
    assert row.reactive_expected_model_interval_uncertainty_resolved
    assert row.active_expected_model_interval_uncertainty_state == m._STATES[2]
    assert math.isnan(row.active_energy_expected_model_uncertainty_bound_wh)


@pytest.mark.parametrize("field", m._EXTRA_COLUMNS)
def test_every_appended_field_tamper(simple: Any, field: str) -> None:
    benchmark, point, result = simple
    frame = result.states.copy(deep=True)
    old = frame.iloc[0][field]
    value = (
        not bool(old)
        if field in m._BOOL
        else 99
        if field in m._INT
        else 123.456
        if field in m._FLOAT
        else (pd.Timestamp("2000", tz="UTC"),)
        if field in m._TUPLE
        else "forged"
    )
    frame.loc[frame.index[0], field] = value
    with pytest.raises(ValueError):
        m._validate_result(benchmark, point, replace(result, states=frame))


@pytest.mark.parametrize(
    "field", [f.name for f in fields(m.RevenueMeterExpectedModelIntervalUncertaintyDiagnostics)]
)
def test_every_diagnostic_tamper(simple: Any, field: str) -> None:
    benchmark, point, result = simple
    old = getattr(result.diagnostics, field)
    value = "forged" if field == "model" else () if field == "state_counts" else old + 1
    with pytest.raises(ValueError):
        m._validate_result(
            benchmark,
            point,
            replace(result, diagnostics=replace(result.diagnostics, **{field: value})),
        )


def test_every_support_provenance_column_and_row_identity_tamper(simple: Any) -> None:
    benchmark, point, result = simple
    for field in result.pointwise_support_states.columns:
        frame = result.pointwise_support_states.copy(deep=True)
        old = frame.iloc[0][field]
        value = (
            not bool(old)
            if pd.api.types.is_bool_dtype(frame[field])
            else int(old) + 1
            if pd.api.types.is_integer_dtype(frame[field])
            else 123.456
            if pd.api.types.is_numeric_dtype(frame[field])
            else "forged"
        )
        frame.loc[frame.index[0], field] = value
        with pytest.raises(ValueError):
            m._validate_result(benchmark, point, replace(result, pointwise_support_states=frame))
    for frame in (
        result.pointwise_support_states.iloc[:0],
        result.pointwise_support_states.iloc[::-1],
    ):
        with pytest.raises(ValueError):
            m._validate_result(benchmark, point, replace(result, pointwise_support_states=frame))


def test_input_frames_not_mutated(seed: Any) -> None:
    benchmark, point, result = unit_case(seed)
    b = benchmark.states.copy(deep=True)
    p = point.states.copy(deep=True)
    result.states.loc[result.states.index[0], "expected_active_energy_wh"] = 999
    result.pointwise_support_states.loc[
        result.pointwise_support_states.index[0], "active_power_expected_model_uncertainty_bound_w"
    ] = 999
    pd.testing.assert_frame_equal(benchmark.states, b)
    pd.testing.assert_frame_equal(point.states, p)


@pytest.mark.parametrize("mode", ["both", "active", "reactive", "missing", "gap", "upstream"])
def test_independent_core_with_all_production_helpers_disabled(
    monkeypatch: Any, seed: Any, mode: str
) -> None:
    a = point_support.authority()
    if mode == "active":
        a = replace(
            a,
            reactive_power_relative_error_bound_fraction=None,
            reactive_power_absolute_error_bound_var=None,
        )
    if mode == "reactive":
        a = replace(
            a,
            active_power_relative_error_bound_fraction=None,
            active_power_absolute_error_bound_w=None,
        )
    if mode == "missing":
        a = False
    benchmark, point, result = unit_case(
        seed,
        a=a,
        maximum_gap=900 if mode == "gap" else None,
        temporal="instantaneous_snapshot"
        if mode == "upstream"
        else "interval_average_ending_at_timestamp",
    )

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("production interval uncertainty helper invoked")

    for name in (
        "_parents",
        "_support",
        "_propagate",
        "_channel",
        "_record",
        "_frame",
        "_support_snapshot",
        "_diagnostics",
        "resolve_revenue_meter_expected_model_interval_uncertainty",
    ):
        monkeypatch.setattr(m, name, fail)
    m._validate_result(benchmark, point, result)


def _repeat_frame(frame: Any, times: Any) -> Any:
    if isinstance(frame, pd.DataFrame) and "timestamp" in frame.columns:
        return pd.concat([frame.assign(timestamp=t) for t in times], ignore_index=True)
    if isinstance(frame.index, pd.DatetimeIndex):
        blocks = []
        for timestamp in times:
            block = frame.copy(deep=True)
            block.index = pd.DatetimeIndex([timestamp] * len(block), name=frame.index.name)
            blocks.append(block)
        return pd.concat(blocks).sort_index()
    if isinstance(frame.index, pd.MultiIndex) and "timestamp" in frame.index.names:
        position = frame.index.names.index("timestamp")
        blocks = []
        for timestamp in times:
            block = frame.copy(deep=True)
            keys = []
            for key in block.index:
                updated = list(key)
                updated[position] = timestamp
                keys.append(tuple(updated))
            block.index = pd.MultiIndex.from_tuples(keys, names=frame.index.names)
            blocks.append(block)
        return pd.concat(blocks).sort_index()
    return frame


def _stationary_raw_context() -> Any:
    """Declare stationary raw S8 inputs/evidence at two times; rebuild all native stages.

    Target S14B and pointwise parents are never shifted or edited. Their public
    resolvers reconstruct them from this complete explicitly timestamped context.
    """
    values = interval_support._s14a_values(
        temporal="interval_average_ending_at_timestamp", interval=3600
    )
    end = next(iter(values["revenue_meter_measured_power_by_key"]))[0]
    times = (end - pd.Timedelta(hours=1), end)
    original = dict(values)
    for key, value in original.items():
        if key == "revenue_meter_measured_power_by_key":
            continue  # One actual measurement interval.
        if isinstance(value, (pd.DataFrame, pd.Series)):
            values[key] = _repeat_frame(value, times)
        elif (
            isinstance(value, (MappingProxyType, dict))
            and value
            and all(isinstance(k, tuple) and isinstance(k[0], pd.Timestamp) for k in value)
        ):
            values[key] = {(t, *k[1:]): state for t in times for k, state in value.items()}
    raw = values["topology_string_iv"]
    states = _repeat_frame(raw.states, times)
    resolved = int(states.string_iv_resolved.sum())
    diagnostics = replace(
        raw.diagnostics,
        timestamp_count=len(times),
        state_row_count=len(states),
        resolved_string_iv_state_count=resolved,
        unresolved_string_iv_state_count=len(states) - resolved,
        zero_string_iv_state_count=int(states.string_iv_state.eq("resolved_zero_string_iv").sum()),
        scaled_string_iv_state_count=int(states.string_iv_state.eq("resolved_string_iv").sum()),
        power_only_iv_unavailable_count=int(
            states.string_iv_state.eq("unresolved_tier5_voltage_dependent_iv_unavailable").sum()
        ),
        iv_curve_row_count=resolved * raw.diagnostics.voltage_points,
    )
    curves = {
        key: _repeat_frame(frame, times) for key, frame in raw.string_iv_curves_by_string_id.items()
    }
    values["topology_string_iv"] = replace(
        raw,
        states=states,
        string_iv_curves_by_string_id=MappingProxyType(curves),
        diagnostics=diagnostics,
    )
    for key, prototype in original.items():
        if (
            key == "topology_string_iv"
            or not is_dataclass(prototype)
            or not type(prototype).__name__.endswith("Result")
        ):
            continue
        owner = inspect.getmodule(type(prototype))
        candidates = []
        for name, fn in inspect.getmembers(owner, inspect.isfunction):
            if name.startswith("_") or fn.__module__ != owner.__name__:
                continue
            if typing.get_type_hints(fn).get("return") is not type(prototype):
                continue
            parameters = inspect.signature(fn).parameters
            required = {
                name
                for name, p in parameters.items()
                if p.default is inspect.Parameter.empty
                and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            }
            if required.issubset(values):
                candidates.append(fn)
        assert len(candidates) == 1, (key, candidates)
        fn = candidates[0]
        parameters = inspect.signature(fn).parameters
        kwargs = (
            values
            if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
            else {name: values[name] for name in parameters if name in values}
        )
        values[key] = fn(**kwargs)
    return values


@pytest.fixture(scope="module")
def real_context() -> Any:
    with pytest.MonkeyPatch.context() as patch:
        db = interval_support.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)
        return _stationary_raw_context()


def real_parents(values: Any, *, policies: Any = None, authorities: Any = None) -> Any:
    authorities = (
        authorities
        if authorities is not None
        else {
            "meter": point_support.authority(
                active_power_relative_error_bound_fraction=None,
                active_power_absolute_error_bound_w=10,
                reactive_power_relative_error_bound_fraction=None,
                reactive_power_absolute_error_bound_var=20,
            )
        }
    )
    values = dict(values)
    values["revenue_meter_interval_benchmark"] = (
        m.s14b.calculate_topology_revenue_meter_interval_benchmark(
            **values, revenue_meter_interval_support_policy_by_meter_id=policies
        )
    )
    values["revenue_meter_expected_model_uncertainty"] = (
        m.pointwise.resolve_topology_revenue_meter_expected_model_uncertainty(
            **values, revenue_meter_expected_model_uncertainty_by_meter_id=authorities
        )
    )
    return values, authorities, policies


def test_real_public_chain_missing_policy_and_validator_independence(
    real_context: Any, monkeypatch: Any
) -> None:
    values, authorities, policies = real_parents(real_context)
    result = m.resolve_revenue_meter_expected_model_interval_uncertainty(
        **values,
        revenue_meter_expected_model_uncertainty_by_meter_id=authorities,
        revenue_meter_interval_support_policy_by_meter_id=policies,
    )
    row = result.states.iloc[0]
    assert row.expected_interval_reconstruction_resolved
    assert not row.expected_interval_support_eligible and not row.benchmark_eligible
    assert row.active_energy_expected_model_uncertainty_bound_wh == 10
    assert row.reactive_energy_expected_model_uncertainty_bound_varh == 20
    assert len(result.pointwise_support_states) == 2

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("production interval helper invoked")

    for name in (
        "_parents",
        "_support",
        "_propagate",
        "_channel",
        "_record",
        "_frame",
        "_support_snapshot",
        "_diagnostics",
        "resolve_revenue_meter_expected_model_interval_uncertainty",
    ):
        monkeypatch.setattr(m, name, fail)
    m.validate_revenue_meter_expected_model_interval_uncertainty(
        result,
        **values,
        revenue_meter_expected_model_uncertainty_by_meter_id=authorities,
        revenue_meter_interval_support_policy_by_meter_id=policies,
    )


@pytest.mark.parametrize(
    "parent", ["revenue_meter_interval_benchmark", "revenue_meter_expected_model_uncertainty"]
)
def test_public_exact_parent_replay(real_context: Any, parent: str) -> None:
    values, authorities, policies = real_parents(real_context)
    original = values[parent]
    changed = original.states.copy(deep=True)
    if parent == "revenue_meter_interval_benchmark":
        changed.loc[changed.index[0], "expected_interval_sample_timestamps"] = (
            pd.Timestamp("2000", tz="UTC"),
        )
    else:
        changed = changed.iloc[:0]
    values[parent] = replace(original, states=changed)
    with pytest.raises(ValueError, match="replay"):
        m.resolve_revenue_meter_expected_model_interval_uncertainty(
            **values,
            revenue_meter_expected_model_uncertainty_by_meter_id=authorities,
            revenue_meter_interval_support_policy_by_meter_id=policies,
        )


def test_contracts_and_no_forbidden_dependencies() -> None:
    assert m.REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_CONTRACT_ID == (
        "admitted_s14b_and_pointwise_expected_model_uncertainty_to_exact_interval_expected_model_uncertainty_state_v1"
    )
    assert m.REVENUE_METER_EXPECTED_MODEL_INTERVAL_UNCERTAINTY_MODEL_ID == (
        "deterministic_worst_case_trapezoidal_propagation_of_pointwise_symmetric_expected_model_bounds_v1"
    )
    source = Path(m.__file__).read_text()
    tree = ast.parse(source)
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(
        name
        and any(
            x in name
            for x in (
                "measurement_uncertainty",
                "loss_attribution",
                "engine.pipeline",
                "expected_energy_source",
            )
        )
        for name in imports
    )
    assert not any(
        isinstance(n, ast.ClassDef) and n.name.endswith("Authority") for n in ast.walk(tree)
    )
    assert "relative_error_bound_fraction" not in source
    assert "total_seconds" not in source


def test_empty_intervals_keep_typed_schema_and_empty_support_snapshot(simple: Any) -> None:
    benchmark, point, _ = simple
    empty = m.s14b._frame((), [])
    b = replace(benchmark, states=empty)
    frame = m._frame(b, [])
    snapshot = m._support_snapshot(b, point)
    result = m.RevenueMeterExpectedModelIntervalUncertaintyResult(
        frame, snapshot, m._diagnostics(frame, snapshot)
    )
    m._validate_result(b, point, result)
    assert result.states.empty and result.pointwise_support_states.empty
    assert result.diagnostics.interval_row_count == 0
    for field in m._BOOL:
        assert str(frame[field].dtype) == "bool"
    for field in m._INT:
        assert str(frame[field].dtype) == "int64"
    for field in m._FLOAT:
        assert str(frame[field].dtype) == "float64"


def test_support_tuple_equivalent_timezone_representation_is_tampering(simple: Any) -> None:
    benchmark, _, _ = simple
    changed = benchmark.states.copy(deep=True)
    index = changed.index[0]
    changed.at[index, "expected_interval_sample_timestamps"] = tuple(
        t.tz_convert("Europe/Paris")
        for t in changed.at[index, "expected_interval_sample_timestamps"]
    )
    with pytest.raises(ValueError, match="replay"):
        m._replay("S14B", replace(benchmark, states=changed), benchmark)


def test_propagation_semantics_are_fixed_public_literals() -> None:
    assert m.PROPAGATION_SEMANTICS == (
        "deterministic_worst_case_positive_trapezoidal_weight_propagation_no_probability_or_covariance"
    )
    assert m.WEIGHT_BASIS == (
        "sum_of_nonnegative_s14b_trapezoidal_weights_times_pointwise_symmetric_bound_magnitudes"
    )
    assert m.COVERAGE_LIMITATION == (
        "uncertainty_of_s14b_discrete_reconstructed_expected_path_not_support_gap_or_continuous_physical_truth"
    )
