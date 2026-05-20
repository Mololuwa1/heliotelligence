"""Tests for alert rule firing logic."""

from __future__ import annotations

import pytest

from heliotelligence.alerts.models import Severity
from heliotelligence.alerts.rules import (
    pr_low,
    availability_low,
    inverter_offline,
    string_underperforming,
    anomaly_rate_high,
    ALL_RULES,
)


# ── pr_low ───────────────────────────────────────────────────────────────────

def test_pr_low_fires_when_below_threshold():
    data = {"performance_ratio": {"pr": 0.70}}
    result = pr_low(data)
    assert result is not None
    assert result.rule_name == "pr_low"
    assert result.severity == Severity.CRITICAL
    assert result.metric_value == pytest.approx(0.70)
    assert result.threshold == pytest.approx(0.75)


def test_pr_low_does_not_fire_when_above_threshold():
    data = {"performance_ratio": {"pr": 0.80}}
    assert pr_low(data) is None


def test_pr_low_does_not_fire_at_exact_threshold():
    data = {"performance_ratio": {"pr": 0.75}}
    assert pr_low(data) is None


def test_pr_low_returns_none_when_pr_missing():
    assert pr_low({}) is None
    assert pr_low({"performance_ratio": {}}) is None
    assert pr_low({"performance_ratio": None}) is None


# ── availability_low ─────────────────────────────────────────────────────────

def test_availability_low_fires_when_below_threshold():
    data = {"availability": {"availability_pct": 85.0}}
    result = availability_low(data)
    assert result is not None
    assert result.rule_name == "availability_low"
    assert result.severity == Severity.CRITICAL
    assert result.metric_value == pytest.approx(85.0)
    assert result.threshold == pytest.approx(90.0)


def test_availability_low_does_not_fire_when_healthy():
    data = {"availability": {"availability_pct": 99.5}}
    assert availability_low(data) is None


def test_availability_low_returns_none_when_data_missing():
    assert availability_low({}) is None
    assert availability_low({"availability": None}) is None


# ── inverter_offline ─────────────────────────────────────────────────────────

def test_inverter_offline_fires_when_offline_events_present():
    data = {
        "inverter_health": {
            "fault_events": [
                {"inverter_id": "INV-01", "fault_type": "offline", "duration_hours": 3.0},
            ]
        }
    }
    result = inverter_offline(data)
    assert result is not None
    assert result.rule_name == "inverter_offline"
    assert result.severity == Severity.CRITICAL
    assert "INV-01" in result.message


def test_inverter_offline_does_not_fire_for_comms_fault_only():
    data = {
        "inverter_health": {
            "fault_events": [
                {"inverter_id": "INV-02", "fault_type": "comms_fault", "duration_hours": 1.0},
            ]
        }
    }
    assert inverter_offline(data) is None


def test_inverter_offline_does_not_fire_when_no_events():
    data = {"inverter_health": {"fault_events": []}}
    assert inverter_offline(data) is None


def test_inverter_offline_returns_none_when_data_missing():
    assert inverter_offline({}) is None
    assert inverter_offline({"inverter_health": None}) is None


# ── string_underperforming ───────────────────────────────────────────────────

def test_string_underperforming_fires_when_flagged_strings_present():
    data = {
        "string_health": {
            "flagged_strings": [
                {"inverter_id": "INV-01", "string_id": "STR-03", "deviation_sigma": 3.1},
            ]
        }
    }
    result = string_underperforming(data)
    assert result is not None
    assert result.rule_name == "string_underperforming"
    assert result.severity == Severity.WARNING
    assert "STR-03" in result.message


def test_string_underperforming_does_not_fire_when_no_flags():
    data = {"string_health": {"flagged_strings": []}}
    assert string_underperforming(data) is None


def test_string_underperforming_returns_none_when_data_missing():
    assert string_underperforming({}) is None
    assert string_underperforming({"string_health": None}) is None


# ── anomaly_rate_high ─────────────────────────────────────────────────────────

def test_anomaly_rate_high_fires_when_above_threshold():
    data = {"anomalies": {"flag_rate_pct": 15.0}}
    result = anomaly_rate_high(data)
    assert result is not None
    assert result.rule_name == "anomaly_rate_high"
    assert result.severity == Severity.WARNING
    assert result.metric_value == pytest.approx(15.0)
    assert result.threshold == pytest.approx(10.0)


def test_anomaly_rate_high_does_not_fire_when_below_threshold():
    data = {"anomalies": {"flag_rate_pct": 5.0}}
    assert anomaly_rate_high(data) is None


def test_anomaly_rate_high_does_not_fire_at_exact_threshold():
    data = {"anomalies": {"flag_rate_pct": 10.0}}
    assert anomaly_rate_high(data) is None


def test_anomaly_rate_high_returns_none_when_data_missing():
    assert anomaly_rate_high({}) is None
    assert anomaly_rate_high({"anomalies": None}) is None


# ── ALL_RULES ────────────────────────────────────────────────────────────────

def test_all_rules_has_five_entries():
    assert len(ALL_RULES) == 5


def test_all_rules_returns_none_for_healthy_site():
    healthy_data = {
        "performance_ratio": {"pr": 0.85},
        "availability": {"availability_pct": 99.9},
        "inverter_health": {"fault_events": []},
        "string_health": {"flagged_strings": []},
        "anomalies": {"flag_rate_pct": 1.0},
    }
    for rule_fn in ALL_RULES:
        assert rule_fn(healthy_data) is None, f"Rule {rule_fn.__name__} should not fire on healthy data"
