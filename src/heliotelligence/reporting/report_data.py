"""ReportData dataclass — aggregates all section inputs for PDF rendering.

All fields are optional (default None) so the renderer never crashes when
a section has no data.  Populate only the fields you want in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ReportData:
    """Container for all data needed to render a full site report PDF.

    Fields mirror the return dicts of the corresponding calculate_*/analyse_*
    functions.  None means the section will show a 'No data available'
    placeholder rather than raising.
    """

    # --- Identity -------------------------------------------------------
    site_id: str = ""
    site_name: str = ""
    report_start: datetime | None = None
    report_end: datetime | None = None
    generated_at: datetime | None = None

    # --- Benchmarking ---------------------------------------------------
    performance_ratio: dict[str, Any] | None = None   # from calculate_pr
    losses: dict[str, Any] | None = None               # from calculate_losses
    availability: dict[str, Any] | None = None         # from calculate_availability
    yield_metrics: dict[str, Any] | None = None        # from calculate_yield

    # --- Analysis -------------------------------------------------------
    degradation: dict[str, Any] | None = None          # from calculate_degradation
    anomalies: dict[str, Any] | None = None            # from detect_anomalies
    string_health: dict[str, Any] | None = None        # from analyse_string_health
    inverter_health: dict[str, Any] | None = None      # from analyse_inverter_health

    # --- Optional metadata ----------------------------------------------
    sections: list[str] = field(default_factory=lambda: list(_DEFAULT_SECTIONS))


_DEFAULT_SECTIONS: list[str] = [
    "performance_summary",
    "loss_waterfall",
    "yield_summary",
    "degradation_trend",
    "anomaly_summary",
    "string_health_summary",
    "inverter_health_summary",
]
