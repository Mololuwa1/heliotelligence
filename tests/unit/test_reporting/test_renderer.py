"""Tests for the PDF renderer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from heliotelligence.reporting.report_data import ReportData
from heliotelligence.reporting.renderer import render


def _make_full_data() -> ReportData:
    return ReportData(
        site_id="test-site-uuid",
        site_name="Test Solar Farm",
        report_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        report_end=datetime(2024, 1, 31, tzinfo=timezone.utc),
        generated_at=datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc),
        performance_ratio={
            "pr": 0.812,
            "e_actual_kwh": 15000.0,
            "e_expected_kwh": 18480.0,
            "coverage_pct": 98.5,
        },
        losses={
            "optical_pct": -1.5,
            "temperature_pct": -3.2,
            "dc_losses_pct": -1.0,
            "inverter_pct": -1.8,
            "clipping_pct": -0.3,
            "availability_pct": -0.5,
            "unaccounted_pct": -1.2,
        },
        availability={"availability_pct": 99.1, "method": "weighted_equal_capacity"},
        yield_metrics={
            "e_actual_kwh": 15000.0,
            "specific_yield_kwh_kwp": 1250.0,
            "capacity_factor_pct": 14.27,
            "hours_in_window": 744.0,
        },
        degradation={
            "rate_pct_per_year": -0.45,
            "r_squared": 0.72,
            "window_days": 365,
            "confidence": "high",
            "first_pr": 0.83,
            "last_pr": 0.81,
            "daily_pr_series": {
                f"2024-01-{d:02d}": 0.82 - d * 0.001
                for d in range(1, 32)
            },
        },
        anomalies={
            "flagged_count": 12,
            "total_count": 480,
            "flag_rate_pct": 2.5,
            "flags": [
                {
                    "time": "2024-01-15T10:00:00",
                    "actual_kw": 450.0,
                    "expected_kw": 600.0,
                    "residual_kw": -150.0,
                    "sigma": 3.1,
                }
            ],
        },
        string_health={
            "inverter_count": 3,
            "string_count": 18,
            "flagged_strings": [
                {
                    "inverter_id": "INV-01",
                    "string_id": "STR-03",
                    "mean_current_a": 4.2,
                    "inverter_mean_a": 8.1,
                    "deviation_sigma": 2.8,
                }
            ],
        },
        inverter_health={
            "inverter_count": 3,
            "fault_event_count": 1,
            "fault_events": [
                {
                    "inverter_id": "INV-02",
                    "fault_type": "offline",
                    "start_time": "2024-01-20T02:00:00",
                    "end_time": "2024-01-20T04:30:00",
                    "duration_hours": 2.5,
                }
            ],
        },
    )


def test_render_returns_bytes():
    data = _make_full_data()
    result = render(data)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_render_is_pdf():
    data = _make_full_data()
    result = render(data)
    assert result[:4] == b"%PDF", "Output does not begin with %PDF header"


def test_render_all_none_data_does_not_crash():
    """Renderer must not raise when all metric fields are None."""
    data = ReportData(
        site_id="empty-site",
        site_name="Empty Site",
        report_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        report_end=datetime(2024, 1, 31, tzinfo=timezone.utc),
    )
    result = render(data)
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_render_partial_data_does_not_crash():
    """Renderer must not raise when only some metrics are populated."""
    data = ReportData(
        site_id="partial-site",
        site_name="Partial Site",
        performance_ratio={"pr": 0.75, "e_actual_kwh": None, "e_expected_kwh": None, "coverage_pct": None},
        losses=None,
        availability=None,
        yield_metrics=None,
        degradation=None,
        anomalies=None,
        string_health=None,
        inverter_health=None,
    )
    result = render(data)
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


def test_render_sets_generated_at_when_none():
    data = ReportData(site_id="x", site_name="x")
    assert data.generated_at is None
    render(data)
    assert data.generated_at is not None


def test_render_with_empty_sections_list():
    data = _make_full_data()
    data.sections = []
    result = render(data)
    assert result[:4] == b"%PDF"


def test_render_with_subset_of_sections():
    data = _make_full_data()
    data.sections = ["performance_summary", "yield_summary"]
    result = render(data)
    assert result[:4] == b"%PDF"
