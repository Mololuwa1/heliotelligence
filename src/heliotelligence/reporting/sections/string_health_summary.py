"""String health summary section — flagged strings per inverter."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from heliotelligence.reporting.report_data import ReportData

_BRAND_COLOUR = colors.HexColor("#1B4F8A")
_HEADER_BG = colors.HexColor("#EAF0F8")
_FLAG_BG = colors.HexColor("#FFF3CD")
_PLACEHOLDER = "No string health data available"


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
        Paragraph("String Health Summary", styles["Heading2"]),
        Spacer(1, 0.3 * cm),
    ]

    sh = data.string_health
    if not sh:
        flowables.append(Paragraph(_PLACEHOLDER, styles["Normal"]))
        return flowables

    # Overview stats
    inv_count = sh.get("inverter_count") or 0
    str_count = sh.get("string_count") or 0
    flagged = sh.get("flagged_strings") or []
    flagged_count = len(flagged)

    overview = [
        ["Metric", "Value"],
        ["Inverters Analysed", str(inv_count)],
        ["Strings Analysed", str(str_count)],
        ["Flagged Strings", str(flagged_count)],
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

    if not flagged:
        flowables.append(Spacer(1, 0.3 * cm))
        flowables.append(Paragraph("No underperforming strings detected.", styles["Normal"]))
        return flowables

    flowables.append(Spacer(1, 0.4 * cm))
    flowables.append(Paragraph("Flagged Strings", styles["Heading3"]))
    flowables.append(Spacer(1, 0.2 * cm))

    detail_rows = [["Inverter ID", "String ID", "Mean (A)", "Inv. Mean (A)", "Deviation (σ)"]]
    for f in sorted(flagged, key=lambda x: -(x.get("deviation_sigma") or 0)):
        detail_rows.append([
            str(f.get("inverter_id") or "—"),
            str(f.get("string_id") or "—"),
            _fmt(f.get("mean_current_a"), 2),
            _fmt(f.get("inverter_mean_a"), 2),
            _fmt(f.get("deviation_sigma"), 2, "σ"),
        ])

    col_widths = [4.5 * cm, 3.5 * cm, 2.5 * cm, 3 * cm, 3 * cm]
    t_detail = Table(detail_rows, colWidths=col_widths)
    t_detail.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _BRAND_COLOUR),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _FLAG_BG]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flowables.append(t_detail)

    return flowables
