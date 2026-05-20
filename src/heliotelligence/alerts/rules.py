"""Alert rule definitions.

Each rule is a pure function:
    rule(data: dict) -> AlertResult | None

`data` is the combined metrics dict passed by the evaluator (keys mirror
the benchmarking / analysis return dicts).  Returns None when the condition
is healthy (no alert to fire).
"""

from __future__ import annotations

from heliotelligence.alerts.models import AlertResult, Severity

# ── Thresholds ──────────────────────────────────────────────────────────────
_PR_LOW_THRESHOLD = 0.75
_AVAILABILITY_LOW_THRESHOLD = 90.0  # %
_ANOMALY_RATE_HIGH_THRESHOLD = 10.0  # %
_STRING_DEVIATION_THRESHOLD = 2.0   # σ — mirrors analysis default


# ── Rules ────────────────────────────────────────────────────────────────────

def pr_low(data: dict) -> AlertResult | None:
    pr_data = data.get("performance_ratio") or {}
    pr = pr_data.get("pr")
    if pr is None:
        return None
    if pr < _PR_LOW_THRESHOLD:
        return AlertResult(
            rule_name="pr_low",
            severity=Severity.CRITICAL,
            message=(
                f"Performance Ratio {pr:.4f} is below threshold "
                f"{_PR_LOW_THRESHOLD:.2f}"
            ),
            metric_value=pr,
            threshold=_PR_LOW_THRESHOLD,
        )
    return None


def availability_low(data: dict) -> AlertResult | None:
    avail_data = data.get("availability") or {}
    avail_pct = avail_data.get("availability_pct")
    if avail_pct is None:
        return None
    if avail_pct < _AVAILABILITY_LOW_THRESHOLD:
        return AlertResult(
            rule_name="availability_low",
            severity=Severity.CRITICAL,
            message=(
                f"Plant availability {avail_pct:.1f}% is below threshold "
                f"{_AVAILABILITY_LOW_THRESHOLD:.0f}%"
            ),
            metric_value=avail_pct,
            threshold=_AVAILABILITY_LOW_THRESHOLD,
        )
    return None


def inverter_offline(data: dict) -> AlertResult | None:
    ih = data.get("inverter_health") or {}
    events = ih.get("fault_events") or []
    offline_events = [e for e in events if e.get("fault_type") == "offline"]
    if not offline_events:
        return None
    inverter_ids = sorted({str(e.get("inverter_id", "?")) for e in offline_events})
    return AlertResult(
        rule_name="inverter_offline",
        severity=Severity.CRITICAL,
        message=(
            f"{len(offline_events)} offline fault event(s) detected on "
            f"inverter(s): {', '.join(inverter_ids)}"
        ),
        metric_value=float(len(offline_events)),
        threshold=0.0,
    )


def string_underperforming(data: dict) -> AlertResult | None:
    sh = data.get("string_health") or {}
    flagged = sh.get("flagged_strings") or []
    if not flagged:
        return None
    string_ids = sorted({str(f.get("string_id", "?")) for f in flagged})
    return AlertResult(
        rule_name="string_underperforming",
        severity=Severity.WARNING,
        message=(
            f"{len(flagged)} underperforming string(s) detected "
            f"(>{_STRING_DEVIATION_THRESHOLD:.1f}σ below inverter mean): "
            f"{', '.join(string_ids[:5])}"
            + ("…" if len(string_ids) > 5 else "")
        ),
        metric_value=float(len(flagged)),
        threshold=0.0,
    )


def anomaly_rate_high(data: dict) -> AlertResult | None:
    anom = data.get("anomalies") or {}
    rate = anom.get("flag_rate_pct")
    if rate is None:
        return None
    if rate > _ANOMALY_RATE_HIGH_THRESHOLD:
        return AlertResult(
            rule_name="anomaly_rate_high",
            severity=Severity.WARNING,
            message=(
                f"Anomaly flag rate {rate:.2f}% exceeds threshold "
                f"{_ANOMALY_RATE_HIGH_THRESHOLD:.0f}%"
            ),
            metric_value=rate,
            threshold=_ANOMALY_RATE_HIGH_THRESHOLD,
        )
    return None


# Ordered list of all rules — evaluator iterates this
ALL_RULES = [
    pr_low,
    availability_low,
    inverter_offline,
    string_underperforming,
    anomaly_rate_high,
]
