"""Cover page section."""

from __future__ import annotations

from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from heliotelligence.reporting.report_data import ReportData

_BRAND_COLOUR = colors.HexColor("#1B4F8A")
_LIGHT_GREY = colors.HexColor("#F5F5F5")


def build(data: ReportData) -> list:
    """Return a list of reportlab flowables for the cover page."""
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontSize=28,
        textColor=_BRAND_COLOUR,
        alignment=TA_CENTER,
        spaceAfter=0.4 * cm,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=14,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=0.2 * cm,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )

    site_name = data.site_name or data.site_id or "Unknown Site"

    def _fmt(dt: datetime | None) -> str:
        return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "—"

    period = (
        f"{_fmt(data.report_start)}  →  {_fmt(data.report_end)}"
        if data.report_start or data.report_end
        else "—"
    )

    flowables = [
        Spacer(1, 3 * cm),
        Paragraph("Heliotelligence", title_style),
        Paragraph("Solar Performance Report", subtitle_style),
        Spacer(1, 1 * cm),
        Paragraph(site_name, ParagraphStyle(
            "SiteName",
            parent=styles["Heading1"],
            fontSize=20,
            textColor=_BRAND_COLOUR,
            alignment=TA_CENTER,
        )),
        Spacer(1, 0.6 * cm),
        Paragraph(f"Report period: {period}", label_style),
        Paragraph(f"Generated: {_fmt(data.generated_at)}", label_style),
        Spacer(1, 1.5 * cm),
    ]

    # Divider line
    divider = Table(
        [[""]],
        colWidths=[14 * cm],
        style=TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1.5, _BRAND_COLOUR),
        ]),
    )
    flowables.append(divider)

    return flowables
