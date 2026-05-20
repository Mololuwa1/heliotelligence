"""Degradation trend section — daily PR line chart with regression line."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from heliotelligence.reporting.report_data import ReportData

_PLACEHOLDER = "No degradation data available"
_BRAND_COLOUR = colors.HexColor("#1B4F8A")


def _build_chart_image(degradation: dict) -> Image | None:
    try:
        from reportlab.graphics.shapes import Drawing, Line, String, PolyLine
        from reportlab.graphics import renderPDF

        daily_pr = degradation.get("daily_pr_series") or {}
        if not daily_pr or len(daily_pr) < 2:
            return None

        dates = sorted(daily_pr.keys())
        pr_values = [daily_pr[d] for d in dates]

        W, H = 420, 200
        margin_l, margin_r, margin_t, margin_b = 50, 20, 20, 40

        plot_w = W - margin_l - margin_r
        plot_h = H - margin_t - margin_b

        pr_min = max(0.0, min(pr_values) - 0.05)
        pr_max = min(1.0, max(pr_values) + 0.05)
        pr_range = pr_max - pr_min or 0.1

        n = len(pr_values)

        def x_pos(i: int) -> float:
            return margin_l + (i / max(n - 1, 1)) * plot_w

        def y_pos(v: float) -> float:
            return margin_b + ((v - pr_min) / pr_range) * plot_h

        d = Drawing(W, H)

        # Title
        d.add(String(W / 2, H - 12, "Daily Performance Ratio Trend",
                     fontSize=10, fillColor=colors.HexColor("#333333"),
                     textAnchor="middle"))

        # Axes
        d.add(Line(margin_l, margin_b, margin_l, margin_b + plot_h,
                   strokeColor=colors.HexColor("#AAAAAA"), strokeWidth=0.5))
        d.add(Line(margin_l, margin_b, margin_l + plot_w, margin_b,
                   strokeColor=colors.HexColor("#AAAAAA"), strokeWidth=0.5))

        # Y-axis labels
        for tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
            if pr_min <= tick <= pr_max:
                y = y_pos(tick)
                d.add(String(margin_l - 4, y - 3, f"{tick:.2f}",
                             fontSize=7, fillColor=colors.HexColor("#666666"),
                             textAnchor="end"))
                d.add(Line(margin_l, y, margin_l + plot_w, y,
                           strokeColor=colors.HexColor("#EEEEEE"), strokeWidth=0.3))

        # X-axis: first / middle / last date labels
        label_indices = [0, n // 2, n - 1] if n >= 3 else list(range(n))
        for i in label_indices:
            x = x_pos(i)
            label = str(dates[i])[:10]
            d.add(String(x, margin_b - 12, label,
                         fontSize=6, fillColor=colors.HexColor("#666666"),
                         textAnchor="middle"))

        # PR line (actual)
        points = []
        for i, v in enumerate(pr_values):
            points.extend([x_pos(i), y_pos(v)])
        d.add(PolyLine(points, strokeColor=colors.HexColor("#4E79A7"),
                       strokeWidth=1.2, fillColor=None))

        # Regression line overlay
        rate = degradation.get("rate_pct_per_year")
        if rate is not None and n >= 2:
            # Reconstruct regression from first/last points via rate
            # slope in PR/day = rate_pct_per_year / (100 * 365)
            slope_per_day = rate / (100.0 * 365.0)
            pr_first = degradation.get("first_pr")
            if pr_first is not None:
                reg_start = pr_first
                reg_end = pr_first + slope_per_day * (n - 1)
                x0, y0 = x_pos(0), y_pos(max(pr_min, min(pr_max, reg_start)))
                x1, y1 = x_pos(n - 1), y_pos(max(pr_min, min(pr_max, reg_end)))
                d.add(Line(x0, y0, x1, y1,
                           strokeColor=colors.HexColor("#E15759"),
                           strokeWidth=1.0,
                           strokeDashArray=[4, 3]))

        # Legend
        d.add(Line(W - 120, H - 14, W - 105, H - 14,
                   strokeColor=colors.HexColor("#4E79A7"), strokeWidth=1.2))
        d.add(String(W - 102, H - 17, "Daily PR",
                     fontSize=7, fillColor=colors.HexColor("#444444"),
                     textAnchor="start"))
        d.add(Line(W - 60, H - 14, W - 45, H - 14,
                   strokeColor=colors.HexColor("#E15759"), strokeWidth=1.0,
                   strokeDashArray=[4, 3]))
        d.add(String(W - 42, H - 17, "Trend",
                     fontSize=7, fillColor=colors.HexColor("#444444"),
                     textAnchor="start"))

        buf = io.BytesIO()
        renderPDF.drawToFile(d, buf)
        buf.seek(0)
        return Image(buf, width=14 * cm, height=H / 420 * 14 * cm)

    except Exception:
        return None


def build(data: ReportData) -> list:
    styles = getSampleStyleSheet()

    flowables: list = [
        Paragraph("Degradation Trend", styles["Heading2"]),
        Spacer(1, 0.3 * cm),
    ]

    deg = data.degradation
    if not deg:
        flowables.append(Paragraph(_PLACEHOLDER, styles["Normal"]))
        return flowables

    img = _build_chart_image(deg)
    if img:
        flowables.append(img)
        flowables.append(Spacer(1, 0.3 * cm))

    def _fmt(v, decimals: int = 3, suffix: str = "") -> str:
        if v is None:
            return "—"
        try:
            return f"{float(v):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            return str(v)

    rows = [
        ["Metric", "Value"],
        ["Degradation Rate (%/year)", _fmt(deg.get("rate_pct_per_year"), 3, "%/yr")],
        ["R²", _fmt(deg.get("r_squared"), 4)],
        ["Window (days)", _fmt(deg.get("window_days"), 0)],
        ["Confidence", str(deg.get("confidence") or "—")],
        ["First PR", _fmt(deg.get("first_pr"), 4)],
        ["Last PR", _fmt(deg.get("last_pr"), 4)],
    ]

    t = Table(rows, colWidths=[9 * cm, 6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F8")),
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
