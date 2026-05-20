"""Alert evaluator — runs all rules against current metrics and persists fired alerts.

Usage:
    results = await evaluate_and_persist_alerts(site_id, session)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from heliotelligence.alerts.models import AlertResult
from heliotelligence.alerts.rules import ALL_RULES
from heliotelligence.models.alerts import Alert

logger = logging.getLogger(__name__)


async def _fetch_metrics(site_id: str, session: AsyncSession) -> dict:
    """Fetch the latest benchmarking and analysis metrics for the site.

    Returns a merged dict with keys: performance_ratio, availability,
    inverter_health, string_health, anomalies.  Any fetch that fails
    returns None for that key — rules must tolerate None.
    """
    from datetime import timedelta
    from heliotelligence.benchmarking.performance_ratio import calculate_pr
    from heliotelligence.benchmarking.availability import calculate_availability
    from heliotelligence.analysis.inverter_health import analyse_inverter_health
    from heliotelligence.analysis.string_health import analyse_string_health
    from heliotelligence.analysis.anomaly import detect_anomalies

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)

    metrics: dict = {}

    for key, coro_factory in [
        ("performance_ratio", lambda: calculate_pr(site_id, start, now, session)),
        ("availability", lambda: calculate_availability(site_id, start, now, session)),
        ("inverter_health", lambda: analyse_inverter_health(site_id, start, now, session)),
        ("string_health", lambda: analyse_string_health(site_id, start, now, session)),
        ("anomalies", lambda: detect_anomalies(site_id, start, now, session)),
    ]:
        try:
            metrics[key] = await coro_factory()
        except Exception as exc:
            logger.debug("Could not fetch %s for %s: %s", key, site_id, exc)
            metrics[key] = None

    return metrics


async def evaluate_and_persist_alerts(
    site_id: str,
    session: AsyncSession,
) -> list[Alert]:
    """Evaluate all alert rules and persist any that fire.

    Returns the list of newly created Alert ORM objects (already added to
    the session but not yet committed — caller decides transaction boundary).
    """
    metrics = await _fetch_metrics(site_id, session)
    fired_at = datetime.now(timezone.utc)

    new_alerts: list[Alert] = []

    for rule_fn in ALL_RULES:
        try:
            result: AlertResult | None = rule_fn(metrics)
        except Exception as exc:
            logger.warning("Rule %s raised: %s", rule_fn.__name__, exc)
            continue

        if result is None:
            continue

        alert = Alert(
            site_id=site_id,
            fired_at=result.fired_at or fired_at,
            rule_name=result.rule_name,
            severity=result.severity.value,
            metric_value=result.metric_value,
            threshold=result.threshold,
            message=result.message,
            acknowledged=False,
            resolved_at=None,
        )
        session.add(alert)
        new_alerts.append(alert)
        logger.info(
            "Alert fired — site=%s rule=%s severity=%s",
            site_id, result.rule_name, result.severity.value,
        )

    return new_alerts
