"""Inverter health summary section — fault event table."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from heliotelligence.reporting.report_data import ReportData

_BRAND_COLOUR = colors.HexColor("#1B4F8A")
_HEADER_BG = colors.HexColor("#EAF0F8")
_OFFLINE_BG = colors.HexColor("#FDECEA")
_COMMS_BG = colors.HexColor("#FFF3CD")
_PLACEHOLDER = "No inverter health data available"

_FAULT_COLOURS = {
    "offline": _OFFLINE_BG,
    "comms_fault": _COMMS_BG,
}


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
        Paragraph("Inverter Health Summary", styles["Heading2"]),
        Spacer(1, 0.3 * cm),
    ]

    ih = data.inverter_health
    if not ih:
        flowables.append(Paragraph(_PLACEHOLDER, styles["Normal"]))
        return flowables

    inv_count = ih.get("inverter_count") or 0
    fault_count = ih.get("fault_event_count") or 0
    events = ih.get("fault_events") or []

    overview = [
        ["Metric", "Value"],
        ["Inverters Monitored", str(inv_count)],
        ["Fault Events Detected", str(fault_count)],
    ]

    t_overview = Table(overview, colWidths=[9 * cm, 6 * cm])
    t_overview.setStyle(TableStyle([
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
    flowables.append(t_overview)

    if not events:
        flowables.append(Spacer(1, 0.3 * cm))
        flowables.append(Paragraph("No fault events detected in this window.", styles["Normal"]))
        return flowables

    flowables.append(Spacer(1, 0.4 * cm))
    flowables.append(Paragraph("Fault Events", styles["Heading3"]))
    flowables.append(Spacer(1, 0.2 * cm))

    detail_rows = [["Inverter ID", "Type", "Start (UTC)", "End (UTC)", "Duration (h)"]]
    row_styles: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _BRAND_COLOUR),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]

    sorted_events = sorted(events, key=lambda e: str(e.get("start_time") or ""))
    for row_idx, e in enumerate(sorted_events, start=1):
        fault_type = str(e.get("fault_type") or "unknown")
        start_ts = str(e.get("start_time") or "—")[:19]
        end_ts = str(e.get("end_time") or "—")[:19]
        detail_rows.append([
            str(e.get("inverter_id") or "—"),
            fault_type,
            start_ts,
            end_ts,
            _fmt(e.get("duration_hours"), 1, "h"),
        ])
        bg = _FAULT_COLOURS.get(fault_type, colors.white)
        row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))

    col_widths = [4.5 * cm, 3 * cm, 4 * cm, 4 * cm, 3 * cm]
    t_detail = Table(detail_rows, colWidths=col_widths)
    t_detail.setStyle(TableStyle(row_styles))
    flowables.append(t_detail)

    return flowables
