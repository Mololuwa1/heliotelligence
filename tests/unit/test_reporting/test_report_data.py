"""Tests for ReportData dataclass."""

from __future__ import annotations

from datetime import datetime, timezone

from heliotelligence.reporting.report_data import ReportData, _DEFAULT_SECTIONS


def test_default_all_metric_fields_are_none():
    data = ReportData()
    for field in [
        "performance_ratio", "losses", "availability", "yield_metrics",
        "degradation", "anomalies", "string_health", "inverter_health",
    ]:
        assert getattr(data, field) is None, f"{field} should default to None"


def test_default_sections_contains_all_seven():
    data = ReportData()
    assert len(data.sections) == 7
    assert "performance_summary" in data.sections
    assert "loss_waterfall" in data.sections
    assert "yield_summary" in data.sections
    assert "degradation_trend" in data.sections
    assert "anomaly_summary" in data.sections
    assert "string_health_summary" in data.sections
    assert "inverter_health_summary" in data.sections


def test_sections_constant_matches_default():
    assert _DEFAULT_SECTIONS == ReportData().sections


def test_assembly_from_dicts():
    pr = {"pr": 0.81, "e_actual_kwh": 10000.0}
    losses = {"optical_pct": -1.5}
    data = ReportData(
        site_id="abc",
        site_name="Farm A",
        report_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        report_end=datetime(2024, 2, 1, tzinfo=timezone.utc),
        generated_at=datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc),
        performance_ratio=pr,
        losses=losses,
    )
    assert data.site_id == "abc"
    assert data.performance_ratio["pr"] == 0.81
    assert data.losses["optical_pct"] == -1.5
    assert data.availability is None
    assert data.yield_metrics is None


def test_sections_list_is_independent_per_instance():
    """Two instances must not share the same list object."""
    d1 = ReportData()
    d2 = ReportData()
    assert d1.sections is not d2.sections
    d1.sections.append("extra")
    assert "extra" not in d2.sections


def test_missing_sections_default_none():
    """Explicitly confirm each unset metric field is None, not missing."""
    data = ReportData(site_id="x")
    assert data.degradation is None
    assert data.anomalies is None
    assert data.string_health is None
    assert data.inverter_health is None
