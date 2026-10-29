from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, fields, replace
from typing import Any

import pandas as pd
import pytest

from heliotelligence.physics import revenue_meter_measurement_uncertainty as m
from tests.unit.test_physics import test_revenue_meter_measurement_authority as parent

T = parent.T1


def authority(**changes: Any) -> m.RevenueMeterMeasurementUncertaintyAuthority:
    values = dict(
        active_power_relative_error_bound_fraction=0.01,
        active_power_absolute_error_bound_w=5.0,
        reactive_power_relative_error_bound_fraction=None,
        reactive_power_absolute_error_bound_var=None,
        uncertainty_interpretation=m.UNCERTAINTY_INTERPRETATION,
        combination_basis=m.COMBINATION_BASIS,
        measurement_chain_scope=m.MEASUREMENT_CHAIN_SCOPE,
        measurement_time_scope="instantaneous_and_interval_average",
        evidence_kind="engineering_uncertainty_budget",
        parameter_source="explicit complete chain budget",
        confidence="medium",
        method_reference="bounded sum of supplied terms",
        applicability_description="declared meter and timestamp scope",
    )
    values.update(changes)
    return m.RevenueMeterMeasurementUncertaintyAuthority(**values)


def inputs(evidence: Any = None) -> dict[str, Any]:
    values = parent._inputs(evidence)
    values["revenue_meter_measurement_authority"] = parent._resolve(values)
    return values


def resolve(values: Any = None, mapping: Any = None) -> Any:
    return m.resolve_topology_revenue_meter_measurement_uncertainty(
        **(inputs() if values is None else values),
        revenue_meter_measurement_uncertainty_by_meter_id=mapping,
    )


@pytest.mark.parametrize("p,bound", [(1000, 15), (-1000, 15), (0, 5)])
def test_signed_measurement_bound_and_parent_immutability(p: float, bound: float) -> None:
    values = inputs({(T, "meter"): parent._measurement(p, -200)})
    original = values["revenue_meter_measurement_authority"].states.copy(deep=True)
    result = resolve(values, {"meter": authority()})
    row = result.states.iloc[0]
    assert row.active_power_measurement_uncertainty_bound_w == bound
    assert row.measured_active_power_lower_bound_w == p - bound
    assert row.measured_active_power_upper_bound_w == p + bound
    assert row.active_power_relative_uncertainty_component_w == abs(p) * 0.01
    assert math.isnan(row.active_energy_measurement_uncertainty_bound_wh)
    assert not row.reactive_power_measurement_uncertainty_resolved
    pd.testing.assert_frame_equal(result.states[original.columns], original)
    pd.testing.assert_frame_equal(values["revenue_meter_measurement_authority"].states, original)


@pytest.mark.parametrize("channel", ["active", "reactive", "both"])
@pytest.mark.parametrize(
    "relative,absolute", [(0, None), (None, 0), (0.02, None), (None, 7), (0.02, 7)]
)
def test_independent_channels_and_explicit_zero(channel: str, relative: Any, absolute: Any) -> None:
    args = {key: None for key in m._AUTHORITY_NUMBERS}
    for name, unit in (("active", "w"), ("reactive", "var")):
        if channel in (name, "both"):
            args[f"{name}_power_relative_error_bound_fraction"] = relative
            args[f"{name}_power_absolute_error_bound_{unit}"] = absolute
    result = resolve(mapping={"meter": authority(**args)})
    row = result.states.iloc[0]
    for name, unit, measured in (("active", "w", 1000), ("reactive", "var", 200)):
        selected = channel in (name, "both")
        assert bool(row[f"{name}_power_measurement_uncertainty_resolved"]) == selected
        if selected:
            expected = measured * (relative or 0) + (absolute or 0)
            assert row[f"{name}_power_measurement_uncertainty_bound_{unit}"] == expected
        else:
            assert math.isnan(row[f"{name}_power_measurement_uncertainty_bound_{unit}"])


@pytest.mark.parametrize("field", m._AUTHORITY_NUMBERS)
@pytest.mark.parametrize("value", [-1, math.nan, math.inf, -math.inf, True, "0.01"])
def test_invalid_numbers(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        authority(**{field: value})


@pytest.mark.parametrize("field", (*m._PROVENANCE, *m._AUTHORITY_SEMANTICS, *m._OPTIONAL_METADATA))
@pytest.mark.parametrize("value", ["", " padded", "padded ", 123])
def test_strict_text(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        authority(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "confidence",
        "evidence_kind",
        "measurement_time_scope",
        "combination_basis",
        "measurement_chain_scope",
        "uncertainty_interpretation",
    ],
)
def test_unknown_enums(field: str) -> None:
    with pytest.raises(ValueError):
        authority(**{field: "unknown unsupported value"})


def test_all_absent_frozen_and_forged() -> None:
    with pytest.raises(ValueError):
        authority(**dict.fromkeys(m._AUTHORITY_NUMBERS))
    a = authority()
    with pytest.raises(FrozenInstanceError):
        a.confidence = "high"
    object.__setattr__(a, "active_power_absolute_error_bound_w", -5)
    with pytest.raises(ValueError):
        resolve(mapping={"meter": a})


@pytest.mark.parametrize("scope", sorted(m._TIME_SCOPES))
@pytest.mark.parametrize("interval", [None, 1800.0])
def test_temporal_scope_and_energy(scope: str, interval: Any) -> None:
    temporal = (
        "instantaneous_snapshot" if interval is None else "interval_average_ending_at_timestamp"
    )
    values = inputs({(T, "meter"): parent._measurement(temporal=temporal, interval=interval)})
    a = authority(
        active_power_relative_error_bound_fraction=0.02,
        active_power_absolute_error_bound_w=None,
        measurement_time_scope=scope,
    )
    row = resolve(values, {"meter": a}).states.iloc[0]
    applicable = scope == "instantaneous_and_interval_average" or scope == (
        "instantaneous_snapshot_only" if interval is None else "interval_average_only"
    )
    assert bool(row.active_power_measurement_uncertainty_resolved) == applicable
    if applicable and interval is not None:
        assert row.active_energy_measurement_uncertainty_bound_wh == 10
        assert row.measured_active_energy_lower_bound_wh == 490
        assert row.measured_active_energy_upper_bound_wh == 510
    else:
        assert math.isnan(row.active_energy_measurement_uncertainty_bound_wh)


@pytest.mark.parametrize(
    "offset,expected", [(-1, False), (0, True), (5, True), (10, True), (11, False)]
)
def test_inclusive_validity(offset: int, expected: bool) -> None:
    timestamp = T + pd.Timedelta(seconds=offset)
    values = inputs({(timestamp, "meter"): parent._measurement()})
    a = authority(valid_from_timestamp=T, valid_to_timestamp=T + pd.Timedelta(seconds=10))
    row = resolve(values, {"meter": a}).states.iloc[0]
    assert bool(row.active_power_measurement_uncertainty_resolved) == expected
    assert row.valid_from_timestamp == T


@pytest.mark.parametrize(
    "kwargs",
    [
        {"valid_from_timestamp": pd.NaT},
        {"valid_to_timestamp": "2026-01-01"},
        {"valid_from_timestamp": T, "valid_to_timestamp": T - pd.Timedelta(seconds=1)},
        {"valid_from_timestamp": T, "valid_to_timestamp": T.tz_localize(None)},
    ],
)
def test_invalid_validity(kwargs: Any) -> None:
    with pytest.raises(ValueError):
        authority(**kwargs)


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (T, None, True),
        (None, T, True),
        (None, None, True),
        (T.tz_convert("Europe/Paris"), None, True),
        (T.tz_localize(None), None, False),
    ],
)
def test_open_validity_and_timezone(start: Any, end: Any, expected: bool) -> None:
    row = resolve(
        mapping={"meter": authority(valid_from_timestamp=start, valid_to_timestamp=end)}
    ).states.iloc[0]
    assert bool(row.active_power_measurement_uncertainty_resolved) == expected
    if start is not None:
        assert str(row.valid_from_timestamp.tz) == str(start.tz)


def test_missing_authority_empty_result_and_missing_measurement_partitions() -> None:
    result = resolve()
    assert result.states.iloc[0].measurement_uncertainty_state == m._STATES[1]
    assert result.diagnostics.uncertainty_authority_missing_count == 1
    empty = resolve(inputs({}), {})
    assert empty.states.empty
    values = parent._two_meter_inputs()
    values["revenue_meter_measurement_authority"] = parent._resolve(values)
    result = resolve(values, {"meter-a": authority()})
    assert result.diagnostics.row_count == 4
    assert result.diagnostics.measured_power_state_missing_count == 2
    assert result.diagnostics.uncertainty_authority_present_count == 1
    assert result.diagnostics.uncertainty_authority_missing_count == 1
    assert sum(count for _, count in result.diagnostics.state_counts) == 4


@pytest.mark.parametrize(
    "mapping", [{"unknown": None}, {1: None}, {"meter": object()}, [], "meter"]
)
def test_mapping_rejection(mapping: Any) -> None:
    with pytest.raises(ValueError):
        resolve(mapping=mapping)


def test_explicit_reuse_order_and_partial_coverage() -> None:
    values = parent._two_meter_inputs()
    values["revenue_meter_measurement_authority"] = parent._resolve(values)
    a = authority()
    first = resolve(values, {"meter-a": a, "meter-b": a})
    second = resolve(values, {"meter-b": a, "meter-a": a})
    pd.testing.assert_frame_equal(first.states, second.states)
    assert first.diagnostics == second.diagnostics
    assert first.diagnostics.active_power_uncertainty_resolved_count == 2


def test_descriptive_metadata_and_confidence_do_not_change_numbers() -> None:
    base = resolve(mapping={"meter": authority()})
    a = authority(
        confidence="unknown",
        **dict.fromkeys(m._OPTIONAL_METADATA, "different text, not a numerical specification"),
    )
    changed = resolve(mapping={"meter": a})
    pd.testing.assert_frame_equal(base.states[list(m._FLOAT)], changed.states[list(m._FLOAT)])
    assert changed.states.iloc[0].confidence == "high"  # S13D metadata remains intact.
    assert changed.states.iloc[0].uncertainty_confidence == "unknown"


@pytest.mark.parametrize(
    "parent_name", ["mv_hv_network_authority", "revenue_meter_measurement_authority"]
)
def test_parent_frame_tampering_rejected(parent_name: str) -> None:
    values = inputs()
    result = values[parent_name]
    frame = result.transformer_states if parent_name == "mv_hv_network_authority" else result.states
    frame.iloc[0, 0] = not bool(frame.iloc[0, 0])
    with pytest.raises(ValueError):
        resolve(values, {"meter": authority()})


def test_validator_independent_of_production_helpers(monkeypatch: Any) -> None:
    values = inputs()
    mapping = {"meter": authority()}
    result = resolve(values, mapping)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("production helper invoked")

    for name in (
        "_parents",
        "_admit_authorities",
        "_channel",
        "_record",
        "_frame",
        "_diagnostics",
        "resolve_topology_revenue_meter_measurement_uncertainty",
    ):
        monkeypatch.setattr(m, name, fail)
    m.validate_revenue_meter_measurement_uncertainty(
        result, **values, revenue_meter_measurement_uncertainty_by_meter_id=mapping
    )


@pytest.mark.parametrize("field", m._EXTRA_COLUMNS)
def test_each_material_output_tamper_rejected(field: str) -> None:
    values = inputs()
    mapping = {"meter": authority()}
    result = resolve(values, mapping)
    bad = result.states.copy(deep=True)
    current = bad.iloc[0][field]
    replacement = (
        not bool(current) if field in m._BOOL else 123.456 if field in m._FLOAT else "forged"
    )
    bad.loc[bad.index[0], field] = replacement
    with pytest.raises(ValueError):
        m.validate_revenue_meter_measurement_uncertainty(
            replace(result, states=bad),
            **values,
            revenue_meter_measurement_uncertainty_by_meter_id=mapping,
        )


@pytest.mark.parametrize(
    "field", [f.name for f in fields(m.RevenueMeterMeasurementUncertaintyDiagnostics)]
)
def test_each_diagnostic_tamper_rejected(field: str) -> None:
    values = inputs()
    mapping = {"meter": authority()}
    result = resolve(values, mapping)
    old = getattr(result.diagnostics, field)
    bad = "forged" if field == "model" else () if field == "state_counts" else old + 1
    with pytest.raises(ValueError):
        m.validate_revenue_meter_measurement_uncertainty(
            replace(result, diagnostics=replace(result.diagnostics, **{field: bad})),
            **values,
            revenue_meter_measurement_uncertainty_by_meter_id=mapping,
        )


@pytest.mark.parametrize("field", m._AUTHORITY_NUMBERS)
def test_explicit_fraction_not_capped_or_inferred(field: str) -> None:
    # The authority admits a bound, not a probability; no hidden fraction ceiling.
    assert getattr(authority(**{field: 2.0}), field) == 2.0


def test_network_basis_absence_does_not_destroy_admitted_measurement() -> None:
    values = parent._s13a_inputs()
    values["mv_hv_network_basis"] = None
    values["mv_hv_network_authority"] = parent.resolve_topology_mv_hv_network_authority(**values)
    values["revenue_meter_measured_power_by_key"] = {(T, "meter"): parent._measurement()}
    values["revenue_meter_measurement_authority"] = parent._resolve(values)
    row = resolve(values, {"meter": authority()}).states.iloc[0]
    assert not row.network_basis_resolved
    assert row.active_power_measurement_uncertainty_resolved


def test_empty_meter_universe() -> None:
    values = parent._s13a_inputs()
    values["revenue_meter_boundary_by_id"] = {}
    values["mv_hv_network_authority"] = parent.resolve_topology_mv_hv_network_authority(**values)
    values["revenue_meter_measured_power_by_key"] = {}
    values["revenue_meter_measurement_authority"] = parent._resolve(values)
    result = resolve(values)
    assert result.states.empty
    assert result.diagnostics.revenue_meter_count == 0
    assert result.diagnostics.row_count == 0


def test_tampered_raw_measurement_authority_rejected() -> None:
    values = inputs()
    state = values["revenue_meter_measured_power_by_key"][(T, "meter")]
    object.__setattr__(state, "active_power_w", math.inf)
    with pytest.raises(ValueError):
        resolve(values, {"meter": authority()})


@pytest.mark.parametrize(
    "p_fraction,q_absolute,expected",
    [
        (1e308, None, "unresolved_nonfinite_measurement_uncertainty_arithmetic"),
        (1e308, 2, "resolved_reactive_power_measurement_uncertainty_only"),
    ],
)
def test_overflow_never_publishes_infinite_bounds(
    p_fraction: float, q_absolute: Any, expected: str
) -> None:
    a = authority(
        active_power_relative_error_bound_fraction=p_fraction,
        reactive_power_absolute_error_bound_var=q_absolute,
    )
    row = resolve(mapping={"meter": a}).states.iloc[0]
    assert row.measurement_uncertainty_state == expected
    assert not row.active_power_measurement_uncertainty_resolved
    assert math.isnan(row.active_power_measurement_uncertainty_bound_w)


def test_interval_energy_overflow_does_not_destroy_finite_power_bound() -> None:
    values = inputs(
        {
            (T, "meter"): parent._measurement(
                temporal="interval_average_ending_at_timestamp", interval=1e308
            )
        }
    )
    row = resolve(
        values, {"meter": authority(active_power_absolute_error_bound_w=1e10)}
    ).states.iloc[0]
    assert row.active_power_measurement_uncertainty_resolved
    assert not row.active_energy_measurement_uncertainty_resolved
    assert math.isnan(row.active_energy_measurement_uncertainty_bound_wh)


@pytest.mark.parametrize(
    "present,valid,scope", [(True, False, True), (True, True, False), (False, True, True)]
)
def test_earlier_failure_diagnostic_partitions(present: bool, valid: bool, scope: bool) -> None:
    a = authority(
        valid_from_timestamp=T if valid else T + pd.Timedelta(days=1),
        measurement_time_scope="instantaneous_snapshot_only" if scope else "interval_average_only",
    )
    result = resolve(mapping={"meter": a} if present else {})
    d = result.diagnostics
    assert d.uncertainty_authority_missing_count == int(not present)
    assert d.temporally_inapplicable_count == int(present and not valid)
    assert d.time_scope_inapplicable_count == int(present and valid and not scope)
    assert (
        d.active_power_uncertainty_resolved_count + d.active_power_uncertainty_unresolved_count
        == d.row_count
    )


@pytest.mark.parametrize("interval", [None, 1800.0])
def test_reactive_energy_and_negative_signed_bounds(interval: Any) -> None:
    values = inputs(
        {
            (T, "meter"): parent._measurement(
                -1000,
                -200,
                temporal="instantaneous_snapshot"
                if interval is None
                else "interval_average_ending_at_timestamp",
                interval=interval,
            )
        }
    )
    a = authority(
        reactive_power_relative_error_bound_fraction=0.01, reactive_power_absolute_error_bound_var=3
    )
    row = resolve(values, {"meter": a}).states.iloc[0]
    assert row.reactive_power_measurement_uncertainty_bound_var == 5
    assert row.measured_reactive_power_lower_bound_var == -205
    assert row.measured_reactive_power_upper_bound_var == -195
    if interval is not None:
        assert row.reactive_energy_measurement_uncertainty_bound_varh == 2.5
        assert row.measured_reactive_energy_lower_bound_varh == -102.5
        assert row.measured_reactive_energy_upper_bound_varh == -97.5


def test_contract_id_literals() -> None:
    assert m.REVENUE_METER_MEASUREMENT_UNCERTAINTY_AUTHORITY_CONTRACT_ID == (
        "explicit_revenue_meter_complete_measurement_chain_quantitative_uncertainty_authority_v1"
    )
    assert m.REVENUE_METER_MEASUREMENT_UNCERTAINTY_CONTRACT_ID == (
        "admitted_s13a_s13d_and_measurement_uncertainty_authority_to_timestamped_"
        "revenue_meter_measurement_uncertainty_state_v1"
    )
    assert m.REVENUE_METER_MEASUREMENT_UNCERTAINTY_MODEL_ID == (
        "explicit_complete_chain_symmetric_pq_measurement_uncertainty_bound_evaluation_v1"
    )


@pytest.mark.parametrize("field", ["valid_from_timestamp", "valid_to_timestamp"])
def test_equivalent_instant_different_zone_is_provenance_tampering(field: str) -> None:
    values = inputs()
    mapping = {"meter": authority(**{field: T})}
    result = resolve(values, mapping)
    bad = result.states.copy(deep=True)
    bad.loc[bad.index[0], field] = T.tz_convert("Europe/Paris")
    with pytest.raises(ValueError):
        m.validate_revenue_meter_measurement_uncertainty(
            replace(result, states=bad),
            **values,
            revenue_meter_measurement_uncertainty_by_meter_id=mapping,
        )


@pytest.mark.parametrize(
    "interval,channel,missing",
    [(1800.0, "both", False), (None, "reactive", False), (None, "both", True)],
)
def test_independent_validation_other_resolution_paths(
    monkeypatch: Any, interval: Any, channel: str, missing: bool
) -> None:
    temporal = (
        "instantaneous_snapshot" if interval is None else "interval_average_ending_at_timestamp"
    )
    values = inputs({(T, "meter"): parent._measurement(temporal=temporal, interval=interval)})
    mapping = (
        {}
        if missing
        else {
            "meter": authority(
                active_power_relative_error_bound_fraction=None if channel == "reactive" else 0.01,
                active_power_absolute_error_bound_w=None if channel == "reactive" else 5,
                reactive_power_absolute_error_bound_var=2,
            )
        }
    )
    result = resolve(values, mapping)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("production helper invoked")

    for name in ("_parents", "_admit_authorities", "_channel", "_record", "_frame", "_diagnostics"):
        monkeypatch.setattr(m, name, fail)
    m.validate_revenue_meter_measurement_uncertainty(
        result, **values, revenue_meter_measurement_uncertainty_by_meter_id=mapping
    )
