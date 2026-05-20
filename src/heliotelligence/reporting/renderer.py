"""PDF report renderer — orchestrates all sections into a single PDF bytes object."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Spacer, PageBreak
from reportlab.platypus.frames import Frame
from reportlab.platypus.doctemplate import PageTemplate

from heliotelligence.reporting.report_data import ReportData
from heliotelligence.reporting.sections import (
    cover,
    performance_summary,
    loss_waterfall,
    yield_summary,
    degradation_trend,
    anomaly_summary,
    string_health_summary,
    inverter_health_summary,
)

_BRAND_COLOUR = colors.HexColor("#1B4F8A")

_SECTION_BUILDERS = {
    "performance_summary": performance_summary.build,
    "loss_waterfall": loss_waterfall.build,
    "yield_summary": yield_summary.build,
    "degradation_trend": degradation_trend.build,
    "anomaly_summary": anomaly_summary.build,
    "string_health_summary": string_health_summary.build,
    "inverter_health_summary": inverter_health_summary.build,
}


def _make_footer(canvas, doc):
    """Draw page number footer on every page except the cover."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    page_num = canvas.getPageNumber()
    if page_num > 1:
        canvas.drawCentredString(
            A4[0] / 2,
            1.0 * cm,
            f"Heliotelligence — Page {page_num}",
        )
    canvas.restoreState()


def render(data: ReportData) -> bytes:
    """Render a complete PDF report and return as bytes.

    Never raises on missing/None data — each section falls back gracefully.
    """
    if data.generated_at is None:
        data.generated_at = datetime.now(timezone.utc)

    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title=f"Heliotelligence Report — {data.site_name or data.site_id}",
        author="Heliotelligence",
    )

    story = []

    # Cover page
    try:
        story.extend(cover.build(data))
    except Exception:
        pass

    story.append(PageBreak())

    # Content sections
    sections_to_render = data.sections or list(_SECTION_BUILDERS.keys())

    for section_name in sections_to_render:
        builder = _SECTION_BUILDERS.get(section_name)
        if builder is None:
            continue
        try:
            flowables = builder(data)
            if flowables:
                story.extend(flowables)
                story.append(Spacer(1, 0.6 * cm))
        except Exception:
            # Never let a section crash the whole report
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph
            styles = getSampleStyleSheet()
            story.append(
                Paragraph(
                    f"[Section '{section_name}' could not be rendered]",
                    styles["Normal"],
                )
            )

    doc.build(story, onFirstPage=_make_footer, onLaterPages=_make_footer)

    return buf.getvalue()
