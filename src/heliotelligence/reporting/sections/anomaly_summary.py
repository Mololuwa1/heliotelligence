"""Anomaly summary section — flag count, rate, and top-10 worst timestamps."""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from heliotelligence.reporting.report_data import ReportData

_BRAND_COLOUR = colors.HexColor("#1B4F8A")
_HEADER_BG = colors.HexColor("#EAF0F8")
_WARN_COLOUR = colors.HexColor("#FFF3CD")
_PLACEHOLDER = "No anomaly data available"


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
        Paragraph("Anomaly Detection Summary", styles["Heading2"]),
        Spacer(1, 0.3 * cm),
    ]

    anom = data.anomalies
    if not anom:
        flowables.append(Paragraph(_PLACEHOLDER, styles["Normal"]))
        return flowables

    # Summary stats table
    summary_rows = [
        ["Metric", "Value"],
        ["Flagged Intervals", _fmt(anom.get("flagged_count"), 0)],
        ["Total Daytime Intervals", _fmt(anom.get("total_count"), 0)],
        ["Flag Rate (%)", _fmt(anom.get("flag_rate_pct"), 2, "%")],
    ]

    t_summary = Table(summary_rows, colWidths=[9 * cm, 6 * cm])
    t_summary.setStyle(TableStyle([
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
    flowables.append(t_summary)

    # Top-10 worst flags table
    flags = anom.get("flags") or []
    if flags:
        flowables.append(Spacer(1, 0.4 * cm))
        flowables.append(Paragraph("Top Anomalous Intervals (worst by |residual|)", styles["Heading3"]))
        flowables.append(Spacer(1, 0.2 * cm))

        sorted_flags = sorted(flags, key=lambda f: abs(f.get("residual_kw") or 0), reverse=True)
        top10 = sorted_flags[:10]

        detail_rows = [["Timestamp (UTC)", "Actual (kW)", "Expected (kW)", "Residual (kW)", "σ"]]
        for f in top10:
            ts = str(f.get("time") or "—")[:19]
            detail_rows.append([
                ts,
                _fmt(f.get("actual_kw"), 2),
                _fmt(f.get("expected_kw"), 2),
                _fmt(f.get("residual_kw"), 2),
                _fmt(f.get("sigma"), 2),
            ])

        col_widths = [5.5 * cm, 3 * cm, 3 * cm, 3 * cm, 2 * cm]
        t_detail = Table(detail_rows, colWidths=col_widths)
        t_detail.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), _BRAND_COLOUR),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9F9F9")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flowables.append(t_detail)

    return flowables
