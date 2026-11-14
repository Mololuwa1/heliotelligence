"""Complete candidates of piecewise-linear I(V), not continuous Bishop extrema."""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from heliotelligence.physics import electrical as e


def curve(v: list[float], i: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        dict(
            timestamp=[pd.Timestamp("2024-06-21T12:00:00Z")] * len(v),
            curve_point=np.arange(len(v)),
            voltage_v=v,
            current_a=i,
            power_w=np.asarray(v) * np.asarray(i),
        )
    )


def test_interior_stationary_point_not_in_input_samples() -> None:
    f = curve([0.0, 4.0], [4.0, 0.0])
    result = e.calculate_common_voltage_mppt_candidates([f])
    assert result.voltage_v.tolist() == [0.0, 2.0, 4.0]
    assert result.candidate_type.tolist() == [
        "zero_domain_endpoint",
        "interior_stationary_point",
        "breakpoint",
    ]
    assert result.is_local_maximum.tolist() == [False, True, False]
    assert result[result.is_selected_global].power_w.tolist() == [4.0]
    selected = e.calculate_common_voltage_mppt([f]).iloc[0]
    assert (selected.v_common_mppt_v, selected.i_common_mppt_a, selected.p_common_mppt_w) == (
        2.0,
        2.0,
        4.0,
    )
    assert result.contract.eq(e.COMMON_VOLTAGE_CANDIDATE_CONTRACT_ID).all()
    assert result.model.eq(e.COMMON_VOLTAGE_CANDIDATE_MODEL_ID).all()
    assert result.scope.eq(e.COMMON_VOLTAGE_CANDIDATE_SCOPE).all()
    assert result.coverage_scope.eq(e.COMMON_VOLTAGE_CANDIDATE_COVERAGE_SCOPE).all()


def test_kink_multiple_local_maxima_exact_tie_lowest_voltage() -> None:
    f = curve([0.0, 1.0, 1.5, 4.0, 5.0], [8.0, 8.0, 2.0, 2.0, 0.0])
    result = e.calculate_common_voltage_mppt_candidates([f])
    assert result[result.is_local_maximum].voltage_v.tolist() == [1.0, 4.0]
    assert result[result.is_selected_global].voltage_v.tolist() == [1.0]
    assert result[result.is_selected_global].power_w.tolist() == [8.0]
    assert result.candidate_index.tolist() == list(range(len(result)))


def test_shared_distinct_breakpoints_interior_aggregate_and_overlap() -> None:
    first = curve([0.0, 4.0], [4.0, 0.0])
    second = curve([0.0, 1.0, 3.0], [4.0, 3.0, 1.0])
    result = e.calculate_common_voltage_mppt_candidates([first, second])
    assert result.voltage_v.max() == 3.0
    row = result[result.is_selected_global].iloc[0]
    assert row.voltage_v == 2.0 and row.current_a == 4.0 and row.power_w == 8.0
    assert row.string_currents_a == (2.0, 2.0)
    other = e.calculate_common_voltage_mppt_candidates([second, first])
    pd.testing.assert_frame_equal(
        result.drop(columns="string_currents_a"),
        other.drop(columns="string_currents_a"),
        check_exact=True,
    )


def test_positive_or_zero_slope_has_no_stationary_candidates() -> None:
    for f in (curve([0.0, 2.0, 4.0], [1.0, 2.0, 3.0]), curve([0.0, 2.0, 4.0], [2.0, 2.0, 2.0])):
        result = e.calculate_common_voltage_mppt_candidates([f])
        assert "interior_stationary_point" not in set(result.candidate_type)
        assert result[result.is_selected_global].voltage_v.tolist() == [4.0]


def test_consistent_independent_counterfactual() -> None:
    a = curve([0.0, 4.0], [4.0, 0.0])
    b = curve([0.0, 2.0], [2.0, 0.0])
    result = e.calculate_physical_mismatch([a, b]).iloc[0]
    assert result.p_independent_mp_w == 5.0
    assert result.p_common_mppt_w == 4.5
    assert result.p_mismatch_w == 0.5
    assert result.mismatch_pct == 10.0
    assert result.p_common_mppt_w <= result.p_independent_mp_w


def test_multiple_aggregate_peaks_and_unchanged_sampled_maximum() -> None:
    f = curve([0.0, 1.0, 1.5, 4.0, 5.0], [8.0, 8.0, 2.0, 2.0, 0.0])
    result = e.calculate_common_voltage_mppt_candidates([f, f])
    assert result[result.is_local_maximum].voltage_v.tolist() == [1.0, 4.0]
    assert result[result.is_selected_global].power_w.tolist() == [16.0]
    selected = e.calculate_common_voltage_mppt([curve([0.0, 1.0, 2.0], [2.0, 2.0, 0.0])]).iloc[0]
    assert selected.p_common_mppt_w == 2.0 and selected.v_common_mppt_v == 1.0


def test_zero_and_mixed_rules_preserved() -> None:
    zero = curve([0.0, 0.0], [0.0, 0.0])
    candidates = e.calculate_common_voltage_mppt_candidates([zero, zero])
    assert len(candidates) == 1 and candidates.iloc[0].is_selected_global
    assert candidates.iloc[0].candidate_type == "zero_domain_endpoint"
    assert candidates.iloc[0].power_w == 0.0
    with pytest.raises(ValueError, match="blocking"):
        e.calculate_common_voltage_mppt_candidates([zero, curve([0.0, 1.0], [1.0, 0.0])])


@pytest.mark.parametrize(
    "bad",
    [
        curve([0.0, 1.0], [1.0, np.nan]),
        curve([0.0, 0.0], [1.0, 1.0]),
        curve([1.0, 2.0], [1.0, 0.0]),
        curve([0.0, 1.0], [-1.0, 0.0]),
    ],
)
def test_bad_curves_fail(bad: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        e.calculate_common_voltage_mppt_candidates([bad])


def test_timestamps_input_detachment_and_exact_flat_maxima() -> None:
    f = curve([0.0, 1.0], [0.0, 0.0])
    before = f.copy(deep=True)
    result = e.calculate_common_voltage_mppt_candidates([f])
    assert result.is_local_maximum.tolist() == [True, True]
    assert result[result.is_selected_global].voltage_v.tolist() == [0.0]
    assert result.timestamp.iloc[0] == f.timestamp.iloc[0]
    pd.testing.assert_frame_equal(f, before)


def test_unequal_multi_peak_global_is_not_first_local_peak() -> None:
    f = curve([0.0, 1.0, 1.5, 4.0, 5.0], [8.0, 8.0, 2.5, 2.5, 0.0])
    result = e.calculate_common_voltage_mppt_candidates([f, f])
    assert result[result.is_local_maximum].voltage_v.tolist() == [1.0, 4.0]
    assert result[result.is_selected_global].voltage_v.tolist() == [4.0]
    assert result[result.is_selected_global].power_w.tolist() == [20.0]


def test_unrepresentable_interval_fails_closed() -> None:
    with pytest.raises(ValueError, match="interval slope"):
        e.calculate_common_voltage_mppt_candidates([curve([0.0, 1e-308], [1e308, 0.0])])


def test_underflowed_nonconstant_interval_fails_closed() -> None:
    # All samples are finite, but a float64 interval slope is unrepresentable.
    # Never claim a zero global maximum by silently treating that slope as flat.
    with pytest.raises(ValueError, match="interval slope"):
        e.calculate_common_voltage_mppt_candidates([curve([0.0, 1e308], [1e-308, 0.0])])


def test_unrepresentable_stationary_arithmetic_fails_closed() -> None:
    # Finite samples and slope do not guarantee representable peak arithmetic.
    # Never silently discard an overflowed stationary point.
    with pytest.raises(ValueError, match="stationary"):
        e.calculate_common_voltage_mppt_candidates([curve([0.0, 1.7e308], [4.5, 0.59])])
