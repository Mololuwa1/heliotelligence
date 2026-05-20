"""Performance summary section — PR and energy table."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from heliotelligence.reporting.report_data import ReportData

_BRAND_COLOUR = colors.HexColor("#1B4F8A")
_HEADER_BG = colors.HexColor("#EAF0F8")
_PLACEHOLDER = "No data available"


def _fmt(v, decimals: int = 3, suffix: str = "") -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def build(data: ReportData) -> list:
    styles = getSampleStyleSheet()
    h2 = styles["Heading2"]
    normal = styles["Normal"]

    flowables: list = [
        Paragraph("Performance Summary", h2),
        Spacer(1, 0.3 * cm),
    ]

    pr_data = data.performance_ratio
    if not pr_data:
        flowables.append(Paragraph(_PLACEHOLDER, normal))
        return flowables

    pr_val = pr_data.get("pr")
    pr_str = _fmt(pr_val, 4) if pr_val is not None else "—"

    rows = [
        ["Metric", "Value"],
        ["Performance Ratio (PR)", pr_str],
        ["E_actual (kWh)", _fmt(pr_data.get("e_actual_kwh"), 1)],
        ["E_expected (kWh)", _fmt(pr_data.get("e_expected_kwh"), 1)],
        ["Coverage (%)", _fmt(pr_data.get("coverage_pct"), 1, "%")],
    ]

    # Availability
    avail = data.availability
    if avail:
        rows.append([
            "Plant Availability (%)",
            _fmt(avail.get("availability_pct"), 1, "%"),
        ])

    t = Table(rows, colWidths=[9 * cm, 6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _BRAND_COLOUR),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9F9F9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    flowables.append(t)
    return flowables
