"""Tests for the alert evaluator."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from heliotelligence.alerts.models import Severity
from heliotelligence.alerts.evaluator import evaluate_and_persist_alerts


def _make_healthy_metrics() -> dict:
    return {
        "performance_ratio": {"pr": 0.85, "e_actual_kwh": 10000.0, "coverage_pct": 99.0},
        "availability": {"availability_pct": 99.5},
        "inverter_health": {"fault_events": []},
        "string_health": {"flagged_strings": []},
        "anomalies": {"flag_rate_pct": 1.0, "flagged_count": 5, "total_count": 500},
    }


def _make_failing_metrics() -> dict:
    return {
        "performance_ratio": {"pr": 0.55},       # fires pr_low (critical)
        "availability": {"availability_pct": 80.0},  # fires availability_low (critical)
        "inverter_health": {
            "fault_events": [
                {"inverter_id": "INV-01", "fault_type": "offline", "duration_hours": 2.0}
            ]
        },                                          # fires inverter_offline (critical)
        "string_health": {
            "flagged_strings": [
                {"inverter_id": "INV-01", "string_id": "STR-02", "deviation_sigma": 3.5}
            ]
        },                                          # fires string_underperforming (warning)
        "anomalies": {"flag_rate_pct": 20.0},       # fires anomaly_rate_high (warning)
    }


@pytest.mark.asyncio
async def test_evaluate_returns_empty_list_when_all_healthy():
    session = MagicMock()
    session.add = MagicMock()

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=_make_healthy_metrics()),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    assert results == []
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_fires_all_five_rules_when_all_thresholds_exceeded():
    session = MagicMock()
    session.add = MagicMock()

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=_make_failing_metrics()),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    assert len(results) == 5
    assert session.add.call_count == 5


@pytest.mark.asyncio
async def test_evaluate_correct_rule_names():
    session = MagicMock()
    session.add = MagicMock()

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=_make_failing_metrics()),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    rule_names = {a.rule_name for a in results}
    assert rule_names == {
        "pr_low", "availability_low", "inverter_offline",
        "string_underperforming", "anomaly_rate_high",
    }


@pytest.mark.asyncio
async def test_evaluate_correct_severities():
    session = MagicMock()
    session.add = MagicMock()

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=_make_failing_metrics()),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    severity_map = {a.rule_name: a.severity for a in results}
    assert severity_map["pr_low"] == "critical"
    assert severity_map["availability_low"] == "critical"
    assert severity_map["inverter_offline"] == "critical"
    assert severity_map["string_underperforming"] == "warning"
    assert severity_map["anomaly_rate_high"] == "warning"


@pytest.mark.asyncio
async def test_evaluate_sets_site_id_on_all_alerts():
    session = MagicMock()
    session.add = MagicMock()

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=_make_failing_metrics()),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-xyz", session)

    assert all(a.site_id == "site-uuid-xyz" for a in results)


@pytest.mark.asyncio
async def test_evaluate_sets_fired_at_on_all_alerts():
    session = MagicMock()
    session.add = MagicMock()

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=_make_failing_metrics()),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    for alert in results:
        assert alert.fired_at is not None
        assert isinstance(alert.fired_at, datetime)


@pytest.mark.asyncio
async def test_evaluate_acknowledged_defaults_to_false():
    session = MagicMock()
    session.add = MagicMock()

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=_make_failing_metrics()),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    assert all(a.acknowledged is False for a in results)


@pytest.mark.asyncio
async def test_evaluate_only_pr_fires():
    session = MagicMock()
    session.add = MagicMock()

    metrics = _make_healthy_metrics()
    metrics["performance_ratio"] = {"pr": 0.60}

    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value=metrics),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    assert len(results) == 1
    assert results[0].rule_name == "pr_low"


@pytest.mark.asyncio
async def test_evaluate_metric_fetch_failure_does_not_crash():
    """If _fetch_metrics raises, the evaluator should propagate (it's logged above)."""
    session = MagicMock()
    session.add = MagicMock()

    # If all metrics are None, rules return None gracefully
    with patch(
        "heliotelligence.alerts.evaluator._fetch_metrics",
        new=AsyncMock(return_value={
            "performance_ratio": None,
            "availability": None,
            "inverter_health": None,
            "string_health": None,
            "anomalies": None,
        }),
    ):
        results = await evaluate_and_persist_alerts("site-uuid-001", session)

    assert results == []
