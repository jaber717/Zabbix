"""PDF renderer (ReportLab). Consumes the shared report document only."""
from __future__ import annotations

import io

from reportlab import rl_config
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)
from xml.sax.saxutils import escape

from .model import NA, fmt_kpi, fmt_value

NAVY, GREY, LIGHT = colors.HexColor("#1f3a5f"), colors.HexColor("#5f6b76"), colors.HexColor("#f2f5f8")
STATUS_COLOR = {"ok": colors.HexColor("#2e8b57"), "warn": colors.HexColor("#d98c00"), "bad": colors.HexColor("#c0392b"),
                "info": colors.HexColor("#2f6db3"), "na": colors.HexColor("#8a949e")}
CELL_STATUS = {"UP": "ok", "RESOLVED": "ok", "HIGH": "ok", "Yes": None, "MEDIUM": "warn", "LOW": "bad", "NONE": "bad", "UNKNOWN": "warn",
               "DOWN": "bad", "OPEN": "bad", "Disaster": "bad", "High": "bad", "Average": "warn", "Warning": "warn", "Information": "info"}
PAGE = landscape(A4)
MARGIN = 14 * mm
USABLE = PAGE[0] - 2 * MARGIN


def _styles():
    s = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=s["Title"], fontName="Helvetica-Bold", fontSize=22, textColor=colors.white, alignment=0, leading=26),
        "sub": ParagraphStyle("s", parent=s["Normal"], fontSize=10, textColor=colors.HexColor("#dbe6f3"), leading=13),
        "h": ParagraphStyle("h", parent=s["Heading2"], fontName="Helvetica-Bold", fontSize=15, textColor=NAVY, spaceBefore=12, spaceAfter=4, keepWithNext=1),
        "h3": ParagraphStyle("h3", parent=s["Heading3"], fontName="Helvetica-Bold", fontSize=10, textColor=GREY, spaceBefore=6, spaceAfter=3, keepWithNext=1),
        "p": ParagraphStyle("p", parent=s["Normal"], fontSize=9, leading=12),
        "small": ParagraphStyle("sm", parent=s["Normal"], fontSize=7.5, textColor=GREY, leading=9.5),
        "cell": ParagraphStyle("c", parent=s["Normal"], fontSize=7.2, leading=8.8),
        "cellh": ParagraphStyle("ch", parent=s["Normal"], fontName="Helvetica-Bold", fontSize=7.2, leading=8.8, textColor=colors.white),
        "kl": ParagraphStyle("kl", parent=s["Normal"], fontSize=7.5, textColor=GREY, leading=9),
        "kv": ParagraphStyle("kv", parent=s["Normal"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=NAVY),
        "kn": ParagraphStyle("kn", parent=s["Normal"], fontSize=6.5, textColor=GREY, leading=8),
        "warn": ParagraphStyle("w", parent=s["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#6b4a00")),
    }


class NumberedCanvas(rl_canvas.Canvas):
    footer_text = ""

    def __init__(self, *a, **k):
        rl_canvas.Canvas.__init__(self, *a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(GREY)
            self.drawString(MARGIN, 8 * mm, self.footer_text)
            self.drawRightString(PAGE[0] - MARGIN, 8 * mm, "Page %d of %d" % (self._pageNumber, total))
            self.setStrokeColor(colors.HexColor("#d5dce1"))
            self.line(MARGIN, 11 * mm, PAGE[0] - MARGIN, 11 * mm)
            rl_canvas.Canvas.showPage(self)
        rl_canvas.Canvas.save(self)


def _kpi_grid(doc, st):
    cards = []
    for k in doc["kpis"]:
        color = STATUS_COLOR.get(k["status"], STATUS_COLOR["info"])
        cell = [Paragraph(escape(k["label"]), st["kl"]), Paragraph(escape(fmt_kpi(k)), st["kv"])]
        if k.get("note") or k.get("coverage") is not None:
            cell.append(Paragraph(escape(k.get("note") or ""), st["kn"]))
        cards.append((cell, color))
    per_row = 5
    rows, styles = [], [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    for r in range(0, len(cards), per_row):
        chunk = cards[r:r + per_row]
        rows.append([c[0] for c in chunk] + [""] * (per_row - len(chunk)))
        ri = len(rows) - 1
        for ci, (_, color) in enumerate(chunk):
            styles += [("BOX", (ci, ri), (ci, ri), 0.6, colors.HexColor("#d5dce1")), ("LINEABOVE", (ci, ri), (ci, ri), 3, color), ("BACKGROUND", (ci, ri), (ci, ri), LIGHT)]
    t = Table(rows, colWidths=[USABLE / per_row] * per_row)
    t.setStyle(TableStyle(styles))
    return t


def _col_widths(columns, rows):
    weights = []
    for c in columns:
        base = {"text": 14, "int": 6, "float1": 7, "float2": 7, "pct": 8, "bps": 10, "seconds": 9, "datetime": 12, "status": 9}[c["type"]]
        longest = max([len(str(r.get(c["key"]) if r.get(c["key"]) is not None else "")) for r in rows] + [len(c["label"]) * 0.75, 3])
        weights.append(min(max(base, min(longest, 40) * 0.9), 36) if c["type"] in ("text", "status") else base)
    total = float(sum(weights))
    return [USABLE * w / total for w in weights]


def _cell_color(c, v):
    cf = c.get("cf")
    if not cf or v is None:
        return None
    if cf["mode"] == "status":
        s = CELL_STATUS.get(str(v))
        return STATUS_COLOR.get(s) if s else None
    if cf["mode"] == "high":
        return STATUS_COLOR["bad"] if v >= cf["bad"] else (STATUS_COLOR["warn"] if v >= cf["warn"] else None)
    if cf["mode"] == "low":
        return STATUS_COLOR["bad"] if v < cf["bad"] else (STATUS_COLOR["warn"] if v < cf["warn"] else None)
    return None


def _table(t, st):
    cols, rows = t["columns"], t["rows"]
    out = [Paragraph(escape(t["title"]), st["h3"])]
    if not rows:
        out.append(Paragraph(escape(t["empty_text"]), st["small"]))
        return out
    shown = rows[:t["pdf_limit"]] if t["pdf_limit"] else rows
    data = [[Paragraph(escape(c["label"]), st["cellh"]) for c in cols]]
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dce1")),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for ri, r in enumerate(shown, start=1):
        line = []
        for ci, c in enumerate(cols):
            v = r.get(c["key"])
            txt = fmt_value(c["type"], v) if c["type"] != "text" else ("" if v is None else str(v))
            line.append(Paragraph(escape(txt), st["cell"]))
            color = _cell_color(c, v)
            if color is not None:
                style.append(("TEXTCOLOR", (ci, ri), (ci, ri), color))
                style.append(("BACKGROUND", (ci, ri), (ci, ri), colors.Color(color.red, color.green, color.blue, alpha=0.12)))
        data.append(line)
        if ri % 2 == 0:
            style.append(("BACKGROUND", (0, ri), (-1, ri), LIGHT))
    tb = Table(data, colWidths=_col_widths(cols, shown), repeatRows=1)
    tb.setStyle(TableStyle(style))
    out.append(tb)
    if len(rows) > len(shown):
        out.append(Paragraph("Showing %d of %d rows. The complete table is in the XLSX and JSON outputs." % (len(shown), len(rows)), st["small"]))
    if t.get("note"):
        out.append(Paragraph(escape(t["note"]), st["small"]))
    return out


def _chart(c, doc):
    t = doc["tables"][c["table"]]
    rows = [r for r in t["rows"] if any(r.get(s["key"]) is not None for s in c["series"])][:c["max_items"]]
    if not rows:
        return None
    w, h = USABLE * 0.62, 6.2 * mm * max(len(rows), 4) if c["type"] == "hbar" else 62 * mm
    h = min(max(h, 40 * mm), 110 * mm)
    d = Drawing(USABLE, h + 12 * mm)
    d.add(String(0, h + 3 * mm, c["title"], fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    palette = [colors.HexColor("#2f6db3"), colors.HexColor("#d98c00"), colors.HexColor("#2e8b57")]
    labels = [str(r.get(c["x"]))[:28] for r in rows]
    if c["type"] == "line":
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 40, 20, w - 40, h - 20
        lp.data = [[(i, r.get(s["key"])) for i, r in enumerate(rows) if r.get(s["key"]) is not None] or [(0, 0)] for s in c["series"]]
        for i in range(len(c["series"])):
            lp.lines[i].strokeColor = palette[i % 3]
            lp.lines[i].strokeWidth = 1.5
        lp.xValueAxis.labelTextFormat = lambda v, L=labels: L[int(v)] if 0 <= int(v) < len(L) and v == int(v) else ""
        lp.xValueAxis.valueSteps = list(range(len(rows)))
        lp.xValueAxis.labels.fontSize = 6
        lp.xValueAxis.labels.fontName = "Helvetica"
        lp.yValueAxis.labels.fontName = "Helvetica"
        lp.xValueAxis.labels.angle = 30
        lp.yValueAxis.labels.fontSize = 6
        lp.yValueAxis.labelTextFormat = lambda v, u=c.get("unit"): fmt_value("bps", v) if u == "bps" else ("%g" % v)
        d.add(lp)
        _legend(d, c, palette, w, h)
        return d
    ch = HorizontalBarChart() if c["type"] == "hbar" else VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 90 if c["type"] == "hbar" else 40, 18, w - (90 if c["type"] == "hbar" else 40), h - 18
    ch.data = [[r.get(s["key"]) for r in rows] for s in c["series"]]            # None = no bar (never drawn as zero)
    ch.categoryAxis.categoryNames = labels
    ch.categoryAxis.labels.fontSize = 6.5
    ch.categoryAxis.labels.fontName = "Helvetica"
    ch.valueAxis.labels.fontName = "Helvetica"
    if c["type"] == "bar":
        ch.categoryAxis.labels.angle = 20
        ch.categoryAxis.labels.dy = -8
    ch.valueAxis.labels.fontSize = 6.5
    ch.valueAxis.valueMin = 0
    if c.get("unit") == "%":
        ch.valueAxis.valueMax = 100
        vals = [v for ser in ch.data for v in ser if v is not None]
        if vals and min(vals) >= 90:                        # availability-style charts: zoom the axis, and say so
            floor = int(min(vals)) - 2
            ch.valueAxis.valueMin = max(0, floor)
            d.add(String(USABLE - 4, h + 3 * mm, "axis starts at %d%%" % max(0, floor), fontName="Helvetica", fontSize=7, fillColor=GREY, textAnchor="end"))
    ch.bars.strokeWidth = 0
    for i in range(len(c["series"])):
        ch.bars[i].fillColor = palette[i % 3]
    d.add(ch)
    _legend(d, c, palette, w, h)
    return d


def _legend(d, c, palette, w, h):
    if len(c["series"]) > 1:
        x = w + 10
        for i, s in enumerate(c["series"]):
            d.add(Rect(x, h - 9 - i * 11, 7, 7, fillColor=palette[i % 3], strokeWidth=0))
            d.add(String(x + 10, h - 8 - i * 11, s["label"], fontName="Helvetica", fontSize=7.5, fillColor=colors.black))


def render_pdf(doc, compress=True):
    """Returns PDF bytes. compress=False leaves page text readable in the file (used by reconciliation tests)."""
    saved = (rl_config.pageCompression, rl_config.invariant, getattr(rl_config, "useA85", 1))
    rl_config.pageCompression = 1 if compress else 0
    rl_config.useA85 = 1 if compress else 0
    rl_config.invariant = 1
    try:
        return _render(doc)
    finally:
        rl_config.pageCompression, rl_config.invariant, rl_config.useA85 = saved


def _render(doc):
    st = _styles()
    buf = io.BytesIO()
    p = doc["period"]
    footer = "%s | %s | generated %s | dataset %s" % (doc["title"], p["label"], doc["generated_at"][:19].replace("T", " "), doc["dataset_sha256"][:12])
    canvas_cls = type("C", (NumberedCanvas,), {"footer_text": footer})
    sd = SimpleDocTemplate(buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=12 * mm, bottomMargin=16 * mm,
                           title=doc["title"] + " " + p["label"], author="Zabbix Reporting Suite", subject=doc["title"],
                           keywords="dataset-sha256:%s" % doc["dataset_sha256"])
    el = []
    head = Table([[Paragraph(escape(doc["title"]), st["title"])],
                  [Paragraph(escape("%s  |  %s to %s (half-open)  |  generated %s" % (doc["subtitle"], p["start"][:16].replace("T", " "), p["end"][:16].replace("T", " "), doc["generated_at"][:16].replace("T", " "))), st["sub"])],
                  [Paragraph(escape("Source: %s  |  collector %s  |  devices in scope: %d  |  dataset %s" % (doc["source"]["zabbix"], doc["source"]["collector"], doc["source"]["scope_hosts"], doc["dataset_sha256"][:16])), st["sub"])]],
                 colWidths=[USABLE])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    el += [head, Spacer(1, 6), _kpi_grid(doc, st), Spacer(1, 6)]
    if doc["findings"]:
        el.append(Paragraph("Summary", st["h"]))
        for f in doc["findings"]:
            el.append(Paragraph("&bull; " + escape(f), st["p"]))
    if doc["warnings"]:
        box = Table([[Paragraph("<b>INCOMPLETE OR DEGRADED DATA</b><br/>" + "<br/>".join("&bull; " + escape(w) for w in doc["warnings"][:12]), st["warn"])]], colWidths=[USABLE])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff4d6")), ("BOX", (0, 0), (-1, -1), 0.8, STATUS_COLOR["warn"]), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
        el += [Spacer(1, 6), box]
    charts = dict((c["id"], c) for c in doc["charts"])
    for sec in doc["sections"]:
        el.append(Paragraph(escape(sec["title"]), st["h"]))
        if sec["text"]:
            el.append(Paragraph(escape(sec["text"]), st["p"]))
        for cid in sec["charts"]:
            d = _chart(charts[cid], doc)
            if d is not None:
                el.append(d)
        for tid in sec["tables"]:
            el.extend(_table(doc["tables"][tid], st))
    el.append(PageBreak())
    el.append(Paragraph("Definitions and method", st["h"]))
    for d in doc["dictionary"]:
        el.append(Paragraph("<b>%s</b> - %s" % (escape(d["term"]), escape(d["definition"])), st["small"]))
    a = doc["audit"]
    el += [Spacer(1, 8), Paragraph("Audit", st["h"]),
           Paragraph(escape("Dataset SHA-256: %s | API calls: %d | truncated requests: %d | failed requests: %d | generated %s | timezone %s" % (
               a["dataset_sha256"], a["api_calls"], len(a["truncated"]), len(a["failed"]), a["generated_at"], doc["timezone"])), st["small"]),
           Paragraph("The same dataset produces the PDF, XLSX and JSON versions of this report. N/A means no data exists; it never means zero.", st["small"])]
    sd.build(el, canvasmaker=canvas_cls)
    return buf.getvalue()
