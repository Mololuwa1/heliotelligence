"""Alert dataclass and severity enum for the alerting engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class AlertResult:
    """In-memory alert produced by a rule evaluation."""

    rule_name: str
    severity: Severity
    message: str
    metric_value: float | None = None
    threshold: float | None = None
    fired_at: datetime | None = None
