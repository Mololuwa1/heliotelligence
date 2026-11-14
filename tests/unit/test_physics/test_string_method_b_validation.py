"""Comparison is explicit validation, never production fidelity dispatch."""

import math
from dataclasses import MISSING, fields, replace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import string_method_b_validation as v
from heliotelligence.physics.string_method_a import execute_string_method_a
from tests.unit.test_physics.test_string_method_b import run
from tests.unit.test_physics.test_string_operating_classes import inputs, update_electrical
from tests.unit.test_physics.test_string_section_electrical_state_authority import STAMP


def pair(
    dark: bool = False, grid: tuple[float, ...] = (0.0, 1.0, 3.0, 8.0, 12.0)
) -> tuple[Any, Any]:
    x = inputs()
    if dark:
        update_electrical(
            x,
            {
                k: replace(s, operating_state=replace(s.operating_state, photocurrent_a=0.0))
                for k, s in x[5].bindings_by_section.items()
            },
        )
    a = execute_string_method_a(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], grid, STAMP)
    return a, run(x)


def test_known_nonzero_approximation_error_and_snapshot_closure() -> None:
    a, b = pair()
    r = v.compare_string_methods(a, b)
    assert r.comparison_complete and r.compared_string_count == 3
    assert r.reference_unavailable_string_count == 0
    assert all(row.comparison_resolved for row in r.rows)
    assert any(
        row.absolute_power_error_w is not None and row.absolute_power_error_w > 0 for row in r.rows
    )
    assert r.method_a_power_w == math.fsum(
        row.method_a_power_w for row in r.rows if row.method_a_power_w is not None
    )
    assert r.method_b_power_w == math.fsum(
        row.method_b_power_w for row in r.rows if row.method_b_power_w is not None
    )
    assert r.power_error_w == r.method_b_power_w - r.method_a_power_w
    for row in r.rows:
        selected = a.advanced_string_candidates.candidates
        selected = selected[
            (selected.string_id == row.string_id) & selected.is_selected_global
        ].iloc[0]
        assert row.method_a_power_w == selected.power_w
        assert row.power_error_w is not None and row.method_a_power_w is not None
        assert row.relative_power_error_fraction == abs(row.power_error_w) / row.method_a_power_w


def test_exact_dark_match_and_zero_reference_undefined() -> None:
    a, b = pair(True)
    r = v.compare_string_methods(a, b)
    assert r.relative_power_error_fraction == 0 and all(
        row.selected_point_exact_match for row in r.rows
    )
    changed = b.candidates.copy(deep=True)
    changed["power_w"] = 1.0
    changed["voltage_v"] = 1.0
    changed["current_a"] = 1.0
    synthetic = replace(b, candidates=changed)
    r = v.compare_string_methods(a, synthetic)
    assert r.relative_power_error_fraction is None and not r.comparison_complete
    assert all(
        row.comparison_state == "unresolved_zero_reference_positive_method_b" for row in r.rows
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("observation_timestamp", STAMP + pd.Timedelta(seconds=1)),
        ("geometry_revision", "old"),
        ("optical_snapshot_reference", "other"),
    ],
)
def test_different_observation_rejected(field: str, value: Any) -> None:
    a, b = pair()
    with pytest.raises(ValueError):
        v.compare_string_methods(a, replace(b, **{field: value}))


def test_incomplete_method_a_reference_cannot_certify() -> None:
    a, b = pair(grid=(0.0, 1.0))
    r = v.compare_string_methods(a, b)
    assert not r.comparison_complete and r.reference_unavailable_string_count == 3
    assert all(
        row.comparison_state == "unavailable_incomplete_method_a_reference" for row in r.rows
    )
    result = v.aggregate_method_b_validation((r,), {STAMP: 1.0}, policy(1.0))
    assert result.policy_state == "unresolved_incomplete_reference"


def policy(limit: float) -> v.MethodBValidationPolicy:
    return v.MethodBValidationPolicy(
        limit, limit, limit, "explicit test study", "unknown", "test", "synthetic only"
    )


def test_explicit_duration_energy_closure_and_policy() -> None:
    a, b = pair()
    r = v.compare_string_methods(a, b)
    loose = v.aggregate_method_b_validation((r,), {STAMP: 2.0}, policy(100.0))
    strict = v.aggregate_method_b_validation((r,), {STAMP: 2.0}, policy(0.0))
    assert loose.method_a_energy_wh == r.method_a_power_w * 2
    assert loose.method_b_energy_wh == r.method_b_power_w * 2
    assert loose.energy_error_wh == loose.method_b_energy_wh - loose.method_a_energy_wh
    assert loose.policy_state == "resolved_within_policy"
    assert strict.policy_state == "resolved_outside_policy"
    assert (
        loose.comparison_complete and loose.timestamp_count == loose.complete_timestamp_count == 1
    )
    assert all(
        f.default is MISSING and f.default_factory is MISSING
        for f in fields(v.MethodBValidationPolicy)
    )


@pytest.mark.parametrize("duration", [None, 0.0, -1.0, True, float("nan"), float("inf")])
def test_duration_required_positive_finite(duration: Any) -> None:
    a, b = pair(True)
    r = v.compare_string_methods(a, b)
    with pytest.raises(ValueError):
        v.aggregate_method_b_validation((r,), {} if duration is None else {STAMP: duration})


def test_timezone_key_must_match_exactly() -> None:
    a, b = pair(True)
    r = v.compare_string_methods(a, b)
    with pytest.raises(ValueError):
        v.aggregate_method_b_validation((r,), {STAMP.tz_convert("Europe/London"): 1.0})


@pytest.mark.parametrize("limit", [-1.0, True, float("nan"), float("inf")])
def test_invalid_policy_rejected(limit: Any) -> None:
    with pytest.raises(ValueError):
        policy(limit)


def test_multiple_snapshots_stable_accumulation() -> None:
    a, b = pair(True)
    first = v.compare_string_methods(a, b)
    # Frozen observation comparison copies are used for duration aggregation;
    # no interval is inferred from their timestamps.
    second = replace(first, observation_timestamp=STAMP + pd.Timedelta(hours=2))
    times = {first.observation_timestamp: 0.5, second.observation_timestamp: 1.25}
    r = v.aggregate_method_b_validation((second, first), times)
    assert r.timestamp_count == 2 and r.comparison_complete
    assert r == v.aggregate_method_b_validation((first, second), times)
    assert r.relative_energy_error_fraction == 0


def test_underlying_electrical_context_must_match() -> None:
    a, b = pair()
    key = next(iter(b.section_electrical_state_authority.bindings_by_section))
    binding = b.section_electrical_state_authority.bindings_by_section[key]
    object.__setattr__(
        binding.operating_state, "photocurrent_a", binding.operating_state.photocurrent_a + 1.0
    )
    with pytest.raises(ValueError):
        v.compare_string_methods(a, b)


def test_positive_selected_point_match_and_nonzero_energy_accumulation() -> None:
    a, b = pair()
    candidates = a.advanced_string_candidates.candidates.copy(deep=True)
    for sid, rows in b.candidates.groupby("string_id"):
        selected = rows.loc[rows.is_selected_method_b].iloc[0]
        mask = candidates.string_id.eq(sid) & candidates.is_selected_global
        candidates.loc[mask, ["power_w", "voltage_v", "current_a"]] = [
            selected.power_w,
            selected.voltage_v,
            selected.current_a,
        ]
    # Metric fixture: preserve the A-owner selection flags while matching its
    # published selected point to B; comparison must not reselect another peak.
    matched = replace(
        a, advanced_string_candidates=replace(a.advanced_string_candidates, candidates=candidates)
    )
    first = v.compare_string_methods(matched, b)
    assert first.method_a_power_w > 0 and all(r.selected_point_exact_match for r in first.rows)
    second = replace(first, observation_timestamp=STAMP + pd.Timedelta(hours=2))
    durations = {STAMP: 0.5, second.observation_timestamp: 1.25}
    result = v.aggregate_method_b_validation((second, first), durations, policy(0.0))
    assert result.method_a_energy_wh == math.fsum(
        (first.method_a_power_w * 0.5, second.method_a_power_w * 1.25)
    )
    assert result.energy_error_wh == 0 and result.policy_state == "resolved_within_policy"


def test_partial_reference_subset_is_not_full_site_validation() -> None:
    x = inputs()
    bindings = dict(x[5].bindings_by_section)
    key = list(bindings)[3]
    bindings[key] = replace(
        bindings[key], operating_state=replace(bindings[key].operating_state, photocurrent_a=20.0)
    )
    update_electrical(x, bindings)
    a = execute_string_method_a(
        x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], (0.0, 1.0, 3.0, 8.0, 12.0), STAMP
    )
    r = v.compare_string_methods(a, run(x))
    assert r.compared_string_ids == ("string-z", "string-b")
    assert r.reference_unavailable_string_count == 1 and not r.comparison_complete
    assert (
        v.aggregate_method_b_validation((r,), {STAMP: 1.0}, policy(100.0)).policy_state
        == "unresolved_incomplete_reference"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("parameter_source", ""),
        ("confidence", "certain"),
        ("method_reference", " padded"),
        ("applicability_description", " "),
    ],
)
def test_invalid_policy_provenance_rejected(field: str, value: str) -> None:
    changes: dict[str, Any] = {field: value}
    with pytest.raises(ValueError):
        replace(policy(1.0), **changes)


def test_policy_confidence_does_not_change_metrics_or_selection() -> None:
    a, b = pair(True)
    r = v.compare_string_methods(a, b)
    low = v.aggregate_method_b_validation(
        (r,), {STAMP: 1.0}, replace(policy(0.0), confidence="low")
    )
    high = v.aggregate_method_b_validation(
        (r,), {STAMP: 1.0}, replace(policy(0.0), confidence="high")
    )
    assert low.method_a_energy_wh == high.method_a_energy_wh
    assert low.policy_state == high.policy_state == "resolved_within_policy"
    assert not hasattr(low, "activate_method_b") and not hasattr(low, "production_method")


def test_energy_error_is_not_annual_mismatch_percentage_points() -> None:
    assert v.__doc__ is not None and "NOT" in v.__doc__ and "percentage-point" in v.__doc__
    names = {f.name for f in fields(v.MethodBEnergyValidation)}
    assert "relative_energy_error_fraction" in names
    assert not any("mismatch_loss" in name for name in names)


def test_unrepresentable_relative_error_fails_closed() -> None:
    with pytest.raises(ValueError, match="relative error"):
        v._relative(1e-308, 1e308)


@pytest.mark.parametrize("field", ["geometry_revision", "optical_snapshot_reference"])
def test_aggregate_rejects_forged_complete_observation_metadata(field: str) -> None:
    a, b = pair(True)
    r = v.compare_string_methods(a, b)
    object.__setattr__(r, field, None)
    with pytest.raises(ValueError):
        v.aggregate_method_b_validation((r,), {STAMP: 1.0}, policy(0.0))


def test_aggregate_rejects_forged_error_metric() -> None:
    a, b = pair(True)
    r = v.compare_string_methods(a, b)
    object.__setattr__(r.rows[0], "relative_power_error_fraction", 1.0)
    with pytest.raises(ValueError):
        v.aggregate_method_b_validation((r,), {STAMP: 1.0}, policy(100.0))
