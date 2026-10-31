from __future__ import annotations

import ast
import inspect
import math
from dataclasses import fields, replace
from typing import Any

import pandas as pd
import pytest

from heliotelligence.physics import inverter_envelope_lookup, inverter_lookup
from heliotelligence.physics import revenue_meter_interval_uncertainty_interpretation as m
from tests.unit.test_physics import test_revenue_meter_combined_interval_uncertainty as support


@pytest.fixture(autouse=True)
def database(monkeypatch: Any) -> None:
    db = support.support.interval_support.support.conversion_support._database
    monkeypatch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
    monkeypatch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)


@pytest.fixture(scope="module")
def seed() -> Any:
    with pytest.MonkeyPatch.context() as patch:
        db = support.support.interval_support.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)
        return support.support.interval_support._parents()


def compose(parent: Any) -> Any:
    frame = m._frame(parent, [m._record(row) for _, row in parent.states.iterrows()])
    result = m.RevenueMeterIntervalUncertaintyInterpretationResult(frame, m._diagnostics(frame))
    m._validate_result(parent, result)
    return result


def case(
    seed: Any,
    *,
    r: float = 10,
    q: float = 0,
    gap: Any = 3600,
    ma: Any = None,
    ea: Any = None,
    duration: float = 3600,
) -> Any:
    """Canonical S14B equations on controlled inputs; native public replay is separate."""
    b = support.support.interval_support
    physical, benchmark = b._bounded(
        seed,
        [(duration, 100, 100, True), (0, 100, 100, True)],
        measured_p=100 + r,
        measured_q=100 + q,
        duration=duration,
        maximum_gap=gap,
    )
    support.support.m.s14b._validate_result(
        physical,
        benchmark,
        revenue_meter_interval_support_policy_by_meter_id=b._policy_mapping(gap),
    )
    ma = support.measured_authority() if ma is None else ma
    ea = (
        support.model_authority(
            active_power_relative_error_bound_fraction=None, active_power_absolute_error_bound_w=15
        )
        if ea is None
        else ea
    )
    mmap, emap = ({} if a is False else {"meter": a} for a in (ma, ea))
    owner = support.m.measurement
    frame = owner._frame(
        physical[2].states,
        [
            owner._record(t, row, mmap.get(meter))
            for (t, meter), row in physical[2].states.iterrows()
        ],
    )
    measured = owner.RevenueMeterMeasurementUncertaintyResult(
        frame, owner._diagnostics(physical[0], frame)
    )
    owner._validate_result(physical[0], physical[2], measured, mmap)
    point_owner = support.support.m.pointwise
    frame = point_owner._frame(
        physical[1].revenue_meter_states,
        [
            point_owner._record(t, row, emap.get(meter))
            for (t, meter), row in physical[1].revenue_meter_states.iterrows()
        ],
    )
    point = point_owner.RevenueMeterExpectedModelUncertaintyResult(
        frame, point_owner._diagnostics(physical[0], frame)
    )
    point_owner._validate_result(physical[0], physical[1], point, emap)
    interval_owner = support.m.model
    frame = interval_owner._frame(
        benchmark,
        [
            interval_owner._record(meter, row, point)
            for (_, meter), row in benchmark.states.iterrows()
        ],
    )
    snapshot = interval_owner._support_snapshot(benchmark, point)
    model = interval_owner.RevenueMeterExpectedModelIntervalUncertaintyResult(
        frame, snapshot, interval_owner._diagnostics(frame, snapshot)
    )
    interval_owner._validate_result(benchmark, point, model)
    support.m._align(measured, model)
    frame = support.m._frame(
        model,
        [
            support.m._record(measured.states.iloc[i], row)
            for i, (_, row) in enumerate(model.states.iterrows())
        ],
    )
    snapshot = support.m._measurement_snapshot(measured)
    parent = support.m.RevenueMeterCombinedIntervalUncertaintyResult(
        frame, snapshot, support.m._diagnostics(frame, snapshot)
    )
    support.m._validate_result(measured, model, parent)
    return parent, compose(parent)


@pytest.fixture(scope="module")
def simple(seed: Any) -> Any:
    return case(seed)


@pytest.mark.parametrize(
    "r,relation,excess", [(10, 0, 0), (20, 1, 0), (-20, 1, 0), (25, 2, 5), (-25, 3, 5)]
)
def test_canonical_eligible_residual_examples(
    seed: Any, r: float, relation: int, excess: float
) -> None:
    parent, result = case(seed, r=r, q=r / 2)
    row = result.states.iloc[0]
    assert row.benchmark_eligible
    assert row.active_power_residual_measured_minus_expected_w == r
    assert row.active_energy_residual_measured_minus_expected_wh == r
    for prefix, unit, _residual, bound in m._QUANTITIES:
        expected_excess = excess if prefix.startswith("active") else excess / 2
        assert row[f"{prefix}_uncertainty_envelope_relation"] == m._RELATIONS[relation]
        assert (
            row[f"{prefix}_residual_excess_beyond_combined_uncertainty_{unit}"] == expected_excess
        )
        assert row[f"{prefix}_combined_uncertainty_envelope_lower_{unit}"] == -row[bound]
        assert row[f"{prefix}_combined_uncertainty_envelope_upper_{unit}"] == row[bound]
    assert row.interval_uncertainty_interpretation_state == m._STATES[5]
    pd.testing.assert_frame_equal(
        result.states[parent.states.columns], parent.states, check_exact=True
    )


@pytest.mark.parametrize("r,relation", [(0, 1), (1, 2), (-1, 3)])
def test_explicit_zero_bound(seed: Any, r: float, relation: int) -> None:
    parent, result = case(
        seed,
        r=r,
        q=r,
        ma=support.measured_authority(
            active_power_absolute_error_bound_w=0, reactive_power_absolute_error_bound_var=0
        ),
        ea=support.model_authority(
            active_power_relative_error_bound_fraction=None,
            active_power_absolute_error_bound_w=0,
            reactive_power_absolute_error_bound_var=0,
        ),
    )
    row = result.states.iloc[0]
    assert row.active_energy_combined_uncertainty_bound_wh == 0
    assert row.active_energy_uncertainty_envelope_relation == m._RELATIONS[relation]
    assert row.active_energy_residual_excess_beyond_combined_uncertainty_wh == abs(r)
    m._validate_result(parent, result)


@pytest.mark.parametrize(
    "r,index",
    [
        (math.nextafter(20, 0), 0),
        (20, 1),
        (math.nextafter(20, math.inf), 2),
        (math.nextafter(-20, 0), 0),
        (-20, 1),
        (math.nextafter(-20, -math.inf), 3),
    ],
)
def test_exact_relations_have_no_epsilon(r: float, index: int) -> None:
    value = m._quantity(r, 20)
    assert value is not None and value[0] == m._RELATIONS[index]


@pytest.mark.parametrize("gap", [None, 900])
def test_ineligible_gate_preserves_nan_residuals_and_nested_diagnostics(
    seed: Any, gap: Any
) -> None:
    parent, result = case(seed, gap=gap)
    row = result.states.iloc[0]
    assert row.active_combined_interval_uncertainty_resolved
    assert not row.benchmark_eligible
    assert math.isnan(row.active_energy_residual_measured_minus_expected_wh)
    assert row.interval_uncertainty_interpretation_state == m._STATES[0]
    for prefix, unit, _, _ in m._QUANTITIES:
        assert not row[f"{prefix}_uncertainty_interpretation_resolved"]
        assert row[f"{prefix}_uncertainty_envelope_relation"] == ""
        assert math.isnan(row[f"{prefix}_combined_uncertainty_envelope_lower_{unit}"])
    diag = result.diagnostics
    assert diag.benchmark_ineligible_count == 1
    assert diag.active_combined_uncertainty_unavailable_count == 0
    assert diag.reactive_combined_uncertainty_unavailable_count == 0
    assert all(count == 0 for _, counts in diag.quantity_relation_counts for _, count in counts)
    pd.testing.assert_frame_equal(
        result.states[parent.states.columns], parent.states, check_exact=True
    )


@pytest.mark.parametrize("channel", ["active", "reactive", "none"])
def test_channel_independence(seed: Any, channel: str) -> None:
    ma = (
        False
        if channel == "none"
        else support.measured_authority(
            **(
                {"reactive_power_absolute_error_bound_var": None}
                if channel == "active"
                else {"active_power_absolute_error_bound_w": None}
            )
        )
    )
    _, result = case(seed, ma=ma)
    row = result.states.iloc[0]
    assert row.benchmark_eligible
    assert bool(row.active_interval_uncertainty_interpretation_resolved) == (channel == "active")
    assert bool(row.reactive_interval_uncertainty_interpretation_resolved) == (
        channel == "reactive"
    )
    expected_state = (
        m._STATES[3]
        if channel == "active"
        else m._STATES[4]
        if channel == "reactive"
        else m._STATES[1]
    )
    assert row.interval_uncertainty_interpretation_state == expected_state
    if channel != "active":
        assert row.active_interval_uncertainty_interpretation_state == m._UNAVAILABLE


@pytest.mark.parametrize(
    "residual,bound",
    [
        (math.nan, 20),
        (math.inf, 20),
        (-math.inf, 20),
        (10, math.nan),
        (10, math.inf),
        (10, -1),
        (True, 20),
        (10, True),
        ("10", 20),
    ],
)
def test_malformed_values_are_not_clamped(residual: Any, bound: Any) -> None:
    assert m._quantity(residual, bound) is None


def test_largest_finite_values_do_not_overflow() -> None:
    largest = float.fromhex("0x1.fffffffffffffp+1023")
    assert m._quantity(-largest, largest) == (m._RELATIONS[1], -largest, largest, 0)
    assert m._quantity(largest, 0) == (m._RELATIONS[2], 0, 0, largest)


@pytest.mark.parametrize("field", [q[2] for q in m._QUANTITIES] + [q[3] for q in m._QUANTITIES])
def test_nonfinite_quantity_keeps_other_channel_and_independent_validator(
    simple: Any, field: str
) -> None:
    parent, _ = simple
    # Defensive core guard; a supplied malformed public parent is separately rejected.
    frame = parent.states.copy(deep=True)
    frame.loc[frame.index[0], field] = math.inf
    bad = replace(parent, states=frame)
    result = compose(bad)
    channel = "active" if field.startswith("active") else "reactive"
    row = result.states.iloc[0]
    assert not row[f"{channel}_interval_uncertainty_interpretation_resolved"]
    assert row[f"{channel}_interval_uncertainty_interpretation_state"] == m._STATES[2]
    assert row.interval_uncertainty_interpretation_state == (
        m._STATES[4] if channel == "active" else m._STATES[3]
    )
    assert getattr(result.diagnostics, f"{channel}_nonfinite_interpretation_count") == 1


def test_only_canonical_residual_fields_are_read_and_quantities_are_independent(
    simple: Any,
) -> None:
    row = simple[0].states.iloc[0]
    permitted = {
        "benchmark_eligible",
        *(f"{c}_combined_interval_uncertainty_resolved" for c, _, _ in m._CHANNELS),
        *(f for q in m._QUANTITIES for f in q[2:]),
    }

    class Guard(dict):
        def __getitem__(self, key: str) -> Any:
            assert key in permitted, f"attempted noncanonical residual reconstruction: {key}"
            return super().__getitem__(key)

    values = Guard({name: row[name] for name in permitted})
    values["active_power_residual_measured_minus_expected_w"] = 10
    values["active_energy_residual_measured_minus_expected_wh"] = 25
    record = m._record(values)
    assert record["active_interval_average_power_uncertainty_envelope_relation"] == m._RELATIONS[0]
    assert record["active_energy_uncertainty_envelope_relation"] == m._RELATIONS[2]
    values = Guard(benchmark_eligible=False)
    assert m._record(values)["interval_uncertainty_interpretation_state"] == m._STATES[0]


@pytest.mark.parametrize("field", m._EXTRA_COLUMNS)
def test_every_appended_field_tamper(simple: Any, field: str) -> None:
    parent, result = simple
    frame = result.states.copy(deep=True)
    frame.loc[frame.index[0], field] = (
        not bool(frame.iloc[0][field])
        if field in m._BOOL
        else 123.456
        if field in m._FLOAT
        else "forged"
    )
    with pytest.raises(ValueError, match="replay"):
        m._validate_result(parent, replace(result, states=frame))


@pytest.mark.parametrize(
    "field", [f.name for f in fields(m.RevenueMeterIntervalUncertaintyInterpretationDiagnostics)]
)
def test_every_diagnostic_tamper(simple: Any, field: str) -> None:
    parent, result = simple
    value = getattr(result.diagnostics, field)
    changed = (
        "forged"
        if isinstance(value, str)
        else (("forged", 1),)
        if isinstance(value, tuple)
        else value + 1
    )
    with pytest.raises(ValueError):
        m._validate_result(
            parent, replace(result, diagnostics=replace(result.diagnostics, **{field: changed}))
        )


@pytest.mark.parametrize("position", range(4))
def test_each_quantity_relation_partition_tamper(simple: Any, position: int) -> None:
    parent, result = simple
    counts = list(result.diagnostics.quantity_relation_counts)
    name, relations = counts[position]
    values = list(relations)
    values[0] = (values[0][0], values[0][1] + 1)
    counts[position] = (name, tuple(values))
    with pytest.raises(ValueError):
        m._validate_result(
            parent,
            replace(
                result,
                diagnostics=replace(result.diagnostics, quantity_relation_counts=tuple(counts)),
            ),
        )


@pytest.mark.parametrize(
    "kind",
    ["eligible", "ineligible", "partial", "unavailable", "nonfinite", "both_nonfinite", "empty"],
)
def test_independent_validator_without_production_helpers(
    seed: Any, monkeypatch: Any, kind: str
) -> None:
    kwargs: dict[str, Any] = {"gap": None} if kind == "ineligible" else {}
    if kind == "partial":
        kwargs["ma"] = support.measured_authority(reactive_power_absolute_error_bound_var=None)
    elif kind == "unavailable":
        kwargs["ma"] = False
    parent, result = case(seed, **kwargs)
    if kind in ("nonfinite", "both_nonfinite"):
        frame = parent.states.copy(deep=True)
        frame.loc[frame.index[0], "active_energy_residual_measured_minus_expected_wh"] = math.nan
        if kind == "both_nonfinite":
            frame.loc[frame.index[0], "reactive_energy_residual_measured_minus_expected_varh"] = (
                math.inf
            )
        parent = replace(parent, states=frame)
        result = compose(parent)
        if kind == "both_nonfinite":
            assert result.states.iloc[0].interval_uncertainty_interpretation_state == m._STATES[2]
    elif kind == "empty":
        parent = replace(parent, states=parent.states.iloc[:0])
        result = compose(parent)
        assert result.states.empty
        assert all(result.states[name].dtype == bool for name in m._BOOL)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production interpretation helper invoked")

    for name in (
        "_parent",
        "_quantity",
        "_channel",
        "_record",
        "_frame",
        "_diagnostics",
        "resolve_revenue_meter_interval_uncertainty_interpretation",
    ):
        monkeypatch.setattr(m, name, fail)
    m._validate_result(parent, result)


@pytest.fixture(scope="module")
def native() -> Any:
    with pytest.MonkeyPatch.context() as patch:
        db = support.support.interval_support.support.conversion_support._database
        patch.setattr(inverter_lookup, "_load_cec_inverter_database", db)
        patch.setattr(inverter_envelope_lookup, "_load_cec_inverter_database", db)
        raw = support.support._stationary_raw_context()
        policies = support.support.interval_support._policy_mapping(3600)
        values, ea, _ = support.support.real_parents(raw, policies=policies)
        ma = {"meter": support.measured_authority()}
        values["revenue_meter_measurement_uncertainty"] = (
            support.m.measurement.resolve_topology_revenue_meter_measurement_uncertainty(
                **values, revenue_meter_measurement_uncertainty_by_meter_id=ma
            )
        )
        values["revenue_meter_expected_model_interval_uncertainty"] = (
            support.m.model.resolve_revenue_meter_expected_model_interval_uncertainty(
                **values,
                revenue_meter_expected_model_uncertainty_by_meter_id=ea,
                revenue_meter_interval_support_policy_by_meter_id=policies,
            )
        )
        maps = dict(
            revenue_meter_measurement_uncertainty_by_meter_id=ma,
            revenue_meter_expected_model_uncertainty_by_meter_id=ea,
            revenue_meter_interval_support_policy_by_meter_id=policies,
        )
        values["revenue_meter_combined_interval_uncertainty"] = (
            m.combined.resolve_revenue_meter_combined_interval_uncertainty(**values, **maps)
        )
        result = m.resolve_revenue_meter_interval_uncertainty_interpretation(**values, **maps)
        return values, maps, result


def test_native_public_chain_and_validator_independence(native: Any, monkeypatch: Any) -> None:
    values, maps, result = native
    parent = values["revenue_meter_combined_interval_uncertainty"]
    row = result.states.iloc[0]
    assert row.benchmark_eligible
    assert row.active_interval_uncertainty_interpretation_resolved
    pd.testing.assert_frame_equal(
        result.states[parent.states.columns], parent.states, check_exact=True
    )

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("production helper invoked")

    for name in (
        "_parent",
        "_quantity",
        "_channel",
        "_record",
        "_frame",
        "_diagnostics",
        "resolve_revenue_meter_interval_uncertainty_interpretation",
    ):
        monkeypatch.setattr(m, name, fail)
    m.validate_revenue_meter_interval_uncertainty_interpretation(result, **values, **maps)


@pytest.mark.parametrize(
    "field",
    [
        "benchmark_eligible",
        "active_power_residual_measured_minus_expected_w",
        "active_energy_residual_measured_minus_expected_wh",
        "reactive_power_residual_measured_minus_expected_var",
        "reactive_energy_residual_measured_minus_expected_varh",
        "active_energy_combined_uncertainty_bound_wh",
        "measurement_parameter_source",
        "combined_interval_uncertainty_state",
        "expected_interval_sample_timestamps",
        "measurement_snapshot",
        "diagnostics",
    ],
)
def test_full_supplied_parent_exact_replay(native: Any, monkeypatch: Any, field: str) -> None:
    values, maps, result = native
    canonical = values["revenue_meter_combined_interval_uncertainty"]

    # Isolate exact replay of the genuine native fixture; full public reconstruction
    # from original inputs is exercised above without this stub.
    def reconstructed(**kwargs: Any) -> Any:
        for name, original in maps.items():
            assert kwargs[name] is original
        return canonical

    monkeypatch.setattr(
        m.combined, "resolve_revenue_meter_combined_interval_uncertainty", reconstructed
    )
    if field == "measurement_snapshot":
        frame = canonical.measurement_uncertainty_states.copy(deep=True)
        frame.loc[frame.index[0], "parameter_source"] = "forged"
        bad = replace(canonical, measurement_uncertainty_states=frame)
    elif field == "diagnostics":
        bad = replace(canonical, diagnostics=replace(canonical.diagnostics, interval_row_count=99))
    else:
        frame = canonical.states.copy(deep=True)
        if pd.api.types.is_bool_dtype(frame[field].dtype):
            change: Any = not bool(frame.iloc[0][field])
        elif pd.api.types.is_numeric_dtype(frame[field].dtype):
            change = 123.456
        else:
            change = "forged"
        frame.loc[frame.index[0], field] = change
        bad = replace(canonical, states=frame)
    supplied = {**values, "revenue_meter_combined_interval_uncertainty": bad}
    with pytest.raises(ValueError, match="replay"):
        m.resolve_revenue_meter_interval_uncertainty_interpretation(**supplied, **maps)
    with pytest.raises(ValueError, match="replay"):
        m.validate_revenue_meter_interval_uncertainty_interpretation(result, **supplied, **maps)


def test_contracts_and_dependency_ownership() -> None:
    assert m.REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_CONTRACT_ID == (
        "admitted_combined_interval_uncertainty_and_eligible_s14b_residual_to_"
        "revenue_meter_interval_uncertainty_interpretation_state_v1"
    )
    assert (
        m.REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_MODEL_ID
        == "deterministic_zero_centered_combined_uncertainty_envelope_residual_comparison_v1"
    )
    assert m.REVENUE_METER_INTERVAL_UNCERTAINTY_INTERPRETATION_SCOPE == (
        "eligible_s14b_interval_residual_uncertainty_envelope_interpretation_"
        "before_causal_or_commercial_attribution"
    )
    assert m.INTERPRETATION_SEMANTICS == (
        "deterministic_residual_vs_symmetric_combined_maximum_bound_"
        "no_probability_or_statistical_significance"
    )
    assert m.OUTSIDE_ENVELOPE_MEANING == (
        "outside_envelope_means_absolute_canonical_residual_exceeds_"
        "admitted_combined_maximum_bound_only"
    )
    assert m.COVERAGE_LIMITATION == (
        "uncertainty_envelope_relation_only_not_causality_fault_classification_"
        "loss_attribution_or_commercial_impact"
    )
    tree = ast.parse(inspect.getsource(m))
    imports = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("heliotelligence")
    ]
    assert len(imports) == 1
    assert [alias.name for n in imports for alias in n.names] == [
        "revenue_meter_combined_interval_uncertainty"
    ]
    assert "isclose" not in inspect.getsource(m)
    assert not any("significant" in name for name in (*m._RELATIONS, *m._STATES))


@pytest.mark.parametrize("residual,bound", [(10**400, 20), (10, 10**400)])
def test_unrepresentable_numeric_guard(residual: Any, bound: Any) -> None:
    assert m._quantity(residual, bound) is None
