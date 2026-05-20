"""Loss waterfall section — horizontal bar chart of loss buckets."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from heliotelligence.reporting.report_data import ReportData

_PLACEHOLDER = "No loss data available"

_BUCKET_LABELS = [
    ("optical_pct", "Optical (soiling + LID)"),
    ("temperature_pct", "Temperature"),
    ("dc_losses_pct", "DC wiring + mismatch"),
    ("inverter_pct", "Inverter conversion"),
    ("clipping_pct", "Clipping / curtailment"),
    ("availability_pct", "Availability"),
    ("unaccounted_pct", "Unaccounted"),
]

_BAR_COLOURS = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2",
    "#59A14F", "#EDC948", "#B07AA1",
]


def _build_chart_image(losses: dict) -> Image | None:
    """Build a horizontal bar chart using reportlab's graphics (no matplotlib)."""
    try:
        from reportlab.graphics.shapes import Drawing, Rect, String, Line
        from reportlab.graphics import renderPDF

        labels = []
        values = []
        for key, label in _BUCKET_LABELS:
            v = losses.get(key)
            if v is not None:
                labels.append(label)
                values.append(float(v))

        if not labels:
            return None

        W, H = 400, max(160, len(labels) * 28 + 40)
        bar_max_w = 220
        label_w = 160
        margin_top = 30
        bar_h = 16
        row_h = 28

        max_val = max(abs(v) for v in values) if values else 1.0
        if max_val == 0:
            max_val = 1.0

        d = Drawing(W, H)

        # Title
        d.add(String(W / 2, H - 15, "Loss Waterfall (% of E_exp_stc)",
                     fontSize=10, fillColor=colors.HexColor("#333333"),
                     textAnchor="middle"))

        for i, (label, val) in enumerate(zip(labels, values)):
            y = H - margin_top - (i + 1) * row_h
            bar_w = abs(val) / max_val * bar_max_w

            colour = colors.HexColor(_BAR_COLOURS[i % len(_BAR_COLOURS)])
            d.add(Rect(label_w, y, bar_w, bar_h,
                       fillColor=colour, strokeColor=None))

            d.add(String(label_w - 4, y + 3, label,
                         fontSize=8, fillColor=colors.HexColor("#444444"),
                         textAnchor="end"))

            val_str = f"{val:+.2f}%"
            d.add(String(label_w + bar_w + 4, y + 3, val_str,
                         fontSize=8, fillColor=colors.HexColor("#444444"),
                         textAnchor="start"))

        buf = io.BytesIO()
        renderPDF.drawToFile(d, buf)
        buf.seek(0)
        return Image(buf, width=12 * cm, height=H / 400 * 12 * cm)

    except Exception:
        return None


def build(data: ReportData) -> list:
    styles = getSampleStyleSheet()

    flowables: list = [
        Paragraph("Loss Waterfall", styles["Heading2"]),
        Spacer(1, 0.3 * cm),
    ]

    losses = data.losses
    if not losses:
        flowables.append(Paragraph(_PLACEHOLDER, styles["Normal"]))
        return flowables

    img = _build_chart_image(losses)
    if img:
        flowables.append(img)
    else:
        # Fallback: text table
        from reportlab.platypus import Table, TableStyle
        rows = [["Loss Component", "% of E_exp_stc"]]
        for key, label in _BUCKET_LABELS:
            v = losses.get(key)
            rows.append([label, f"{v:.3f}%" if v is not None else "—"])
        t = Table(rows, colWidths=[9 * cm, 5 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F8")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        flowables.append(t)

    return flowables
