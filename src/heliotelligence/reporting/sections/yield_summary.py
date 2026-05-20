"""Yield summary section — specific yield and capacity factor."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from heliotelligence.reporting.report_data import ReportData

_BRAND_COLOUR = colors.HexColor("#1B4F8A")
_HEADER_BG = colors.HexColor("#EAF0F8")
_PLACEHOLDER = "No yield data available"


def _fmt(v, decimals: int = 2, suffix: str = "") -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def build(data: ReportData) -> list:
    styles = getSampleStyleSheet()

    flowables: list = [
        Paragraph("Yield Metrics", styles["Heading2"]),
        Spacer(1, 0.3 * cm),
    ]

    ym = data.yield_metrics
    if not ym:
        flowables.append(Paragraph(_PLACEHOLDER, styles["Normal"]))
        return flowables

    rows = [
        ["Metric", "Value"],
        ["E_actual (kWh)", _fmt(ym.get("e_actual_kwh"), 1)],
        ["Specific Yield (kWh/kWp)", _fmt(ym.get("specific_yield_kwh_kwp"), 2)],
        ["Capacity Factor (%)", _fmt(ym.get("capacity_factor_pct"), 2, "%")],
        ["Window (hours)", _fmt(ym.get("hours_in_window"), 1)],
    ]

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
