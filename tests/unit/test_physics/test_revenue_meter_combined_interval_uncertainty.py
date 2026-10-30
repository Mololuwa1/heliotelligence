from __future__ import annotations

import ast
import inspect
import math
from dataclasses import fields, replace
from typing import Any

import pandas as pd
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import revenue_meter_combined_interval_uncertainty as m
from tests.unit.test_physics import (
    test_revenue_meter_expected_model_interval_uncertainty as support,
)
from tests.unit.test_physics import test_revenue_meter_measurement_uncertainty as ms


@pytest.fixture(autouse=True)
def database(monkeypatch: Any) -> None:
    db = support.interval_support.support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)


@pytest.fixture(scope="module")
def seed() -> Any:
    with pytest.MonkeyPatch.context() as patch:
        db = support.interval_support.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)
        return support.interval_support._parents()


def measured_authority(**kwargs: Any) -> Any:
    return ms.authority(
        **{
            "active_power_relative_error_bound_fraction": None,
            "active_power_absolute_error_bound_w": 5,
            "reactive_power_relative_error_bound_fraction": None,
            "reactive_power_absolute_error_bound_var": 4,
            **kwargs,
        }
    )


def model_authority(**kwargs: Any) -> Any:
    return support.point_support.authority(
        **{
            "active_power_relative_error_bound_fraction": 0.1,
            "active_power_absolute_error_bound_w": 5,
            "reactive_power_relative_error_bound_fraction": None,
            "reactive_power_absolute_error_bound_var": 6,
            **kwargs,
        }
    )


def case(
    seed: Any,
    *,
    ma: Any = None,
    ea: Any = None,
    duration: float = 3600,
    gap: Any = None,
    samples: Any = None,
    temporal: str = "interval_average_ending_at_timestamp",
) -> Any:
    """Controlled boundary mathematics; raw public parent replay tested separately."""
    samples = samples if samples is not None else [(duration, 50, 20, True), (0, 150, 80, True)]
    physical, benchmark = support.interval_support._bounded(
        seed, samples, duration=duration, temporal=temporal, maximum_gap=gap
    )
    support.m.s14b._validate_result(
        physical,
        benchmark,
        revenue_meter_interval_support_policy_by_meter_id=support.interval_support._policy_mapping(
            gap
        ),
    )
    ma = measured_authority() if ma is None else ma
    ea = model_authority() if ea is None else ea
    mmap, emap = ({} if a is False else {"meter": a} for a in (ma, ea))
    rows = [
        m.measurement._record(t, row, mmap.get(meter))
        for (t, meter), row in physical[2].states.iterrows()
    ]
    frame = m.measurement._frame(physical[2].states, rows)
    measured = m.measurement.RevenueMeterMeasurementUncertaintyResult(
        frame, m.measurement._diagnostics(physical[0], frame)
    )
    m.measurement._validate_result(physical[0], physical[2], measured, mmap)
    point_owner = support.m.pointwise
    rows = [
        point_owner._record(t, row, emap.get(meter))
        for (t, meter), row in physical[1].revenue_meter_states.iterrows()
    ]
    frame = point_owner._frame(physical[1].revenue_meter_states, rows)
    point = point_owner.RevenueMeterExpectedModelUncertaintyResult(
        frame, point_owner._diagnostics(physical[0], frame)
    )
    point_owner._validate_result(physical[0], physical[1], point, emap)
    rows = [m.model._record(meter, row, point) for (_, meter), row in benchmark.states.iterrows()]
    frame = m.model._frame(benchmark, rows)
    snapshot = m.model._support_snapshot(benchmark, point)
    expected = m.model.RevenueMeterExpectedModelIntervalUncertaintyResult(
        frame, snapshot, m.model._diagnostics(frame, snapshot)
    )
    m.model._validate_result(benchmark, point, expected)
    m._align(measured, expected)
    rows = [
        m._record(measured.states.iloc[i], row)
        for i, (_, row) in enumerate(expected.states.iterrows())
    ]
    frame = m._frame(expected, rows)
    snapshot = m._measurement_snapshot(measured)
    result = m.RevenueMeterCombinedIntervalUncertaintyResult(
        frame, snapshot, m._diagnostics(frame, snapshot)
    )
    m._validate_result(measured, expected, result)
    return measured, expected, result


@pytest.fixture(scope="module")
def simple(seed: Any) -> Any:
    return case(seed)


@pytest.mark.parametrize("duration", [3600, 1800])
def test_pq_examples_and_exact_parent_preservation(seed: Any, duration: float) -> None:
    measured, expected, result = case(seed, duration=duration)
    row = result.states.iloc[0]
    assert row.active_interval_average_power_combined_uncertainty_bound_w == 20
    assert row.active_energy_combined_uncertainty_bound_wh == 20 * duration / 3600
    assert row.reactive_interval_average_power_combined_uncertainty_bound_var == 10
    assert row.reactive_energy_combined_uncertainty_bound_varh == 10 * duration / 3600
    pd.testing.assert_frame_equal(
        result.states[expected.states.columns], expected.states, check_exact=True
    )
    pd.testing.assert_frame_equal(
        result.measurement_uncertainty_states, measured.states, check_exact=True
    )
    assert not any("residual" in name for name in m._EXTRA_COLUMNS)


def test_tightness() -> None:
    assert (+5) - (-15) == 20
    assert (-5) - (+15) == -20


@pytest.mark.parametrize("mv,ev", [(0, 15), (5, 0), (0, 0)])
def test_zero_contribution(seed: Any, mv: float, ev: float) -> None:
    _, _, result = case(
        seed,
        ma=measured_authority(active_power_absolute_error_bound_w=mv),
        ea=model_authority(
            active_power_relative_error_bound_fraction=None, active_power_absolute_error_bound_w=ev
        ),
    )
    row = result.states.iloc[0]
    assert row.active_combined_interval_uncertainty_resolved
    assert row.active_energy_combined_uncertainty_bound_wh == mv + ev


@pytest.mark.parametrize("gap,eligible", [(None, False), (900, False), (3600, True)])
def test_support_eligibility_orthogonal_no_regenerated_residual(
    seed: Any, gap: Any, eligible: bool
) -> None:
    _, expected, result = case(seed, gap=gap)
    row = result.states.iloc[0]
    assert row.active_combined_interval_uncertainty_resolved
    assert bool(row.benchmark_eligible) == eligible
    assert bool(row.expected_interval_support_eligible) == eligible
    pd.testing.assert_frame_equal(
        result.states[expected.states.columns], expected.states, check_exact=True
    )
    if not eligible:
        assert math.isnan(row.active_energy_residual_measured_minus_expected_wh)
    assert result.diagnostics.active_combined_unresolved_count == 0


@pytest.mark.parametrize(
    "mode",
    [
        "m_missing",
        "m_temporal",
        "m_scope",
        "e_missing",
        "e_partial",
        "reconstruction",
        "snapshot",
        "cross_channels",
        "active_only",
        "model_arithmetic",
        "combined_arithmetic",
    ],
)
def test_actual_unavailable_parent_reasons(seed: Any, mode: str) -> None:
    args: dict[str, Any] = {}
    end = seed[2].states.index.get_level_values("timestamp")[0]
    if mode == "m_missing":
        args["ma"] = False
    elif mode == "m_temporal":
        args["ma"] = measured_authority(valid_from_timestamp=end)
    elif mode == "m_scope":
        args["ma"] = measured_authority(measurement_time_scope="instantaneous_snapshot_only")
    elif mode == "e_missing":
        args["ea"] = False
    elif mode == "e_partial":
        args["ea"] = model_authority(valid_from_timestamp=end - pd.Timedelta(seconds=1))
    elif mode == "reconstruction":
        args["samples"] = [(3600, 50, 20, False), (0, 150, 80, True)]
    elif mode == "snapshot":
        args["temporal"] = "instantaneous_snapshot"
    elif mode in ("cross_channels", "active_only"):
        args["ma"] = measured_authority(reactive_power_absolute_error_bound_var=None)
        if mode == "cross_channels":
            args["ea"] = model_authority(
                active_power_relative_error_bound_fraction=None,
                active_power_absolute_error_bound_w=None,
            )
    else:
        args.update(
            duration=7200 if mode == "model_arithmetic" else 3600,
            samples=[(7200 if mode == "model_arithmetic" else 3600, 0, 0, True), (0, 0, 0, True)],
            ea=model_authority(
                active_power_relative_error_bound_fraction=None,
                active_power_absolute_error_bound_w=1e308,
            ),
        )
        if mode == "combined_arithmetic":
            args["ma"] = measured_authority(active_power_absolute_error_bound_w=1e308)
    measured, expected, result = case(seed, **args)
    row = result.states.iloc[0]
    if mode.startswith("m_"):
        assert (
            row.active_combined_interval_uncertainty_state
            == "unresolved_measurement_interval_uncertainty_unavailable"
        )
        assert not row.active_measurement_interval_uncertainty_available
    elif mode.startswith("e_") or mode in ("reconstruction", "model_arithmetic", "cross_channels"):
        assert (
            row.active_combined_interval_uncertainty_state
            == "unresolved_expected_model_interval_uncertainty_unavailable"
        )
    elif mode == "snapshot":
        assert (
            row.active_combined_interval_uncertainty_state
            == "unresolved_both_parent_interval_uncertainties_unavailable"
        )
    elif mode == "combined_arithmetic":
        assert row.active_combined_interval_uncertainty_state == m._STATES[1]
        assert math.isnan(row.active_energy_combined_uncertainty_bound_wh)
    else:
        assert row.combined_interval_uncertainty_state == m._STATES[2]
    pd.testing.assert_frame_equal(result.states[expected.states.columns], expected.states)
    pd.testing.assert_frame_equal(result.measurement_uncertainty_states, measured.states)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1, True, "5"])
def test_bad_required_bound_is_not_zero(bad: Any) -> None:
    assert m._combine((bad, 1, 1, 1)) is None


def test_combine_published_quantities_independently() -> None:
    assert m._combine((5, 15, 2, 3)) == (20, 5)
    assert m._combine((1e308, 1e308, 0, 0)) is None


@pytest.mark.parametrize("field", m._EXTRA_COLUMNS)
def test_every_appended_field_tamper(simple: Any, field: str) -> None:
    measured, expected, result = simple
    frame = result.states.copy(deep=True)
    frame.loc[frame.index[0], field] = (
        (not bool(frame.iloc[0][field]))
        if field in m._BOOL
        else 123.456
        if field in m._FLOAT
        else "forged"
    )
    with pytest.raises(ValueError, match="replay"):
        m._validate_result(measured, expected, replace(result, states=frame))


@pytest.mark.parametrize(
    "field", [f.name for f in fields(m.RevenueMeterCombinedIntervalUncertaintyDiagnostics)]
)
def test_every_diagnostic_tamper(simple: Any, field: str) -> None:
    measured, expected, result = simple
    value = getattr(result.diagnostics, field)
    replacement = (
        "forged"
        if isinstance(value, str)
        else (("forged", 1),)
        if isinstance(value, tuple)
        else value + 1
    )
    with pytest.raises(ValueError):
        m._validate_result(
            measured,
            expected,
            replace(result, diagnostics=replace(result.diagnostics, **{field: replacement})),
        )


def test_every_measurement_snapshot_field_and_identity_tamper(simple: Any) -> None:
    measured, expected, result = simple
    for field in result.measurement_uncertainty_states.columns:
        snapshot = result.measurement_uncertainty_states.copy(deep=True)
        if pd.api.types.is_bool_dtype(snapshot[field].dtype):
            value: Any = not bool(snapshot.iloc[0][field])
        elif pd.api.types.is_numeric_dtype(snapshot[field].dtype):
            value = 123 if pd.api.types.is_integer_dtype(snapshot[field].dtype) else 123.456
        else:
            value = "forged"
        snapshot.loc[snapshot.index[0], field] = value
        with pytest.raises(ValueError):
            m._validate_result(
                measured, expected, replace(result, measurement_uncertainty_states=snapshot)
            )
    with pytest.raises(ValueError):
        m._validate_result(
            measured,
            expected,
            replace(
                result,
                measurement_uncertainty_states=result.measurement_uncertainty_states.iloc[:0],
            ),
        )


@pytest.mark.parametrize(
    "field", (*m._SHARED, "measurement_parameter_source", "measurement_confidence")
)
def test_alignment_semantic_mismatch(simple: Any, field: str) -> None:
    measured, expected, result = simple
    frame = expected.states.copy(deep=True)
    if pd.api.types.is_bool_dtype(frame[field].dtype):
        value: Any = not bool(frame.iloc[0][field])
    elif pd.api.types.is_numeric_dtype(frame[field].dtype):
        value = 999
    else:
        value = "forged"
    frame.loc[frame.index[0], field] = value
    bad = replace(expected, states=frame)
    with pytest.raises(ValueError):
        m._align(measured, bad)
    with pytest.raises(ValueError):
        m._validate_result(measured, bad, result)


def test_timezone_representation_and_empty_universe(simple: Any) -> None:
    measured, expected, _ = simple
    frame = measured.states.copy(deep=True)
    times = frame.index.get_level_values("timestamp").tz_convert(
        "Europe/London"
        if str(frame.index.get_level_values("timestamp").tz) != "Europe/London"
        else "UTC"
    )
    frame.index = pd.MultiIndex.from_arrays(
        [times, frame.index.get_level_values("revenue_meter_id")], names=frame.index.names
    )
    with pytest.raises(ValueError):
        m._align(replace(measured, states=frame), expected)
    a, b = (
        replace(measured, states=measured.states.iloc[:0]),
        replace(expected, states=expected.states.iloc[:0]),
    )
    m._align(a, b)
    frame = m._frame(b, [])
    snapshot = m._measurement_snapshot(a)
    m._validate_result(
        a,
        b,
        m.RevenueMeterCombinedIntervalUncertaintyResult(
            frame, snapshot, m._diagnostics(frame, snapshot)
        ),
    )


def test_no_forbidden_dependencies_and_fixed_semantics() -> None:
    tree = ast.parse(inspect.getsource(m))
    imports = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("heliotelligence")
    ]
    assert len(imports) == 2
    assert {alias.name for n in imports for alias in n.names} == {
        "revenue_meter_measurement_uncertainty",
        "revenue_meter_expected_model_interval_uncertainty",
    }
    assert (
        m.COMBINATION_SEMANTICS
        == "deterministic_worst_case_difference_bound_sum_no_probability_independence_or_covariance"
    )
    assert m.COMBINATION_BASIS == (
        "sum_of_independently_admitted_symmetric_maximum_absolute_"
        "measurement_and_expected_model_bounds"
    )
    assert m.COVERAGE_LIMITATION == (
        "combined_uncertainty_magnitude_only_not_benchmark_eligibility_"
        "residual_reconstruction_or_significance"
    )


@pytest.fixture(scope="module")
def native() -> Any:
    with pytest.MonkeyPatch.context() as patch:
        db = support.interval_support.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)
        raw = support._stationary_raw_context()
        values, ea, policies = support.real_parents(
            raw,
            authorities={
                "meter": model_authority(
                    active_power_relative_error_bound_fraction=None,
                    active_power_absolute_error_bound_w=15,
                )
            },
        )
        ma = {"meter": measured_authority()}
        values["revenue_meter_expected_model_interval_uncertainty"] = (
            m.model.resolve_revenue_meter_expected_model_interval_uncertainty(
                **values,
                revenue_meter_expected_model_uncertainty_by_meter_id=ea,
                revenue_meter_interval_support_policy_by_meter_id=policies,
            )
        )
        values["revenue_meter_measurement_uncertainty"] = (
            m.measurement.resolve_topology_revenue_meter_measurement_uncertainty(
                **values, revenue_meter_measurement_uncertainty_by_meter_id=ma
            )
        )
        maps = dict(
            revenue_meter_measurement_uncertainty_by_meter_id=ma,
            revenue_meter_expected_model_uncertainty_by_meter_id=ea,
            revenue_meter_interval_support_policy_by_meter_id=policies,
        )
        result = m.resolve_revenue_meter_combined_interval_uncertainty(**values, **maps)
        return values, maps, result


def test_public_chain_and_validator_all_production_helpers_disabled(
    native: Any, monkeypatch: Any
) -> None:
    values, maps, result = native
    row = result.states.iloc[0]
    assert row.active_energy_combined_uncertainty_bound_wh == 20
    assert row.reactive_energy_combined_uncertainty_bound_varh == 10
    assert not row.benchmark_eligible
    assert math.isnan(row.active_energy_residual_measured_minus_expected_wh)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper invoked")

    for name in (
        "_parents",
        "_align",
        "_combine",
        "_record",
        "_frame",
        "_measurement_snapshot",
        "_diagnostics",
        "resolve_revenue_meter_combined_interval_uncertainty",
    ):
        monkeypatch.setattr(m, name, fail)
    m.validate_revenue_meter_combined_interval_uncertainty(result, **values, **maps)


@pytest.mark.parametrize(
    "parent",
    ["revenue_meter_measurement_uncertainty", "revenue_meter_expected_model_interval_uncertainty"],
)
def test_public_parent_tamper_rejected(native: Any, parent: str) -> None:
    values, maps, result = native
    bad = dict(values)
    frame = values[parent].states.copy(deep=True)
    frame.iloc[0, 0] = (
        "forged"
        if pd.api.types.is_object_dtype(frame.iloc[:, 0].dtype)
        else not bool(frame.iloc[0, 0])
    )
    bad[parent] = replace(values[parent], states=frame)
    with pytest.raises(ValueError, match="replay"):
        m.resolve_revenue_meter_combined_interval_uncertainty(**bad, **maps)
    with pytest.raises(ValueError, match="replay"):
        m.validate_revenue_meter_combined_interval_uncertainty(result, **bad, **maps)


@pytest.mark.parametrize("kind", ["partial", "overflow", "missing", "snapshot"])
def test_independent_core_reconstructs_branches_without_helpers(
    seed: Any, monkeypatch: Any, kind: str
) -> None:
    args: dict[str, Any] = {}
    if kind == "partial":
        args["ma"] = measured_authority(reactive_power_absolute_error_bound_var=None)
    elif kind == "missing":
        args["ea"] = False
    elif kind == "snapshot":
        args["temporal"] = "instantaneous_snapshot"
    else:
        args.update(
            samples=[(3600, 0, 0, True), (0, 0, 0, True)],
            ma=measured_authority(active_power_absolute_error_bound_w=1e308),
            ea=model_authority(
                active_power_relative_error_bound_fraction=None,
                active_power_absolute_error_bound_w=1e308,
            ),
        )
    measured, expected, result = case(seed, **args)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper invoked")

    for name in (
        "_parents",
        "_align",
        "_combine",
        "_record",
        "_frame",
        "_measurement_snapshot",
        "_diagnostics",
        "resolve_revenue_meter_combined_interval_uncertainty",
    ):
        monkeypatch.setattr(m, name, fail)
    m._validate_result(measured, expected, result)


def test_alignment_rejects_order_count_meter_and_timestamp_changes(simple: Any) -> None:
    measured, expected, _ = simple
    # Two valid, aligned identities isolate ordering from numeric calculations.
    start = measured.states.index[0][0]

    def twice(frame: Any) -> Any:
        duplicate = pd.concat([frame, frame], axis=0)
        duplicate.index = pd.MultiIndex.from_tuples(
            [(start, "meter"), (start + pd.Timedelta(hours=1), "meter")], names=frame.index.names
        )
        return duplicate

    a = replace(measured, states=twice(measured.states))
    b = replace(expected, states=twice(expected.states))
    m._align(a, b)
    for frame in (b.states.iloc[::-1], b.states.iloc[:1]):
        with pytest.raises(ValueError):
            m._align(a, replace(b, states=frame))
    for key in ((start, "unknown"), (start + pd.Timedelta(seconds=1), "meter")):
        frame = expected.states.copy(deep=True)
        frame.index = pd.MultiIndex.from_tuples([key], names=frame.index.names)
        with pytest.raises(ValueError):
            m._align(measured, replace(expected, states=frame))


def test_contract_identifiers_are_canonical() -> None:
    assert m.REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_CONTRACT_ID == (
        "admitted_measurement_and_expected_model_interval_uncertainty_to_combined_"
        "revenue_meter_interval_uncertainty_state_v1"
    )
    assert m.REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_MODEL_ID == (
        "deterministic_sum_of_symmetric_measurement_and_expected_model_interval_maximum_bounds_v1"
    )
    assert m.REVENUE_METER_COMBINED_INTERVAL_UNCERTAINTY_SCOPE == (
        "revenue_meter_interval_combined_measurement_expected_model_uncertainty_"
        "before_residual_interpretation"
    )
