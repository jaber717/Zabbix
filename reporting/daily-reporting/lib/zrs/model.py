"""The report document model. Every renderer (JSON, PDF, XLSX) consumes exactly this structure,
so a number can never differ between formats."""
from __future__ import annotations

from datetime import datetime

DOC_SCHEMA = "zabbix-reporting-suite-report-v1"
NA = "N/A"

# column types -> how renderers format them (values are always stored raw: None means "no data")
TYPES = ("text", "int", "float1", "float2", "pct", "bps", "seconds", "datetime", "status")


def col(key, label, type="text", desc="", cf=None, width=None):
    """cf (conditional formatting): {"mode":"high"|"low"|"status", "warn":x, "bad":y} """
    return {"key": key, "label": label, "type": type, "description": desc, "cf": cf, "width": width}


def table(tid, title, columns, rows, note="", pdf_limit=40, empty_text="None in this period."):
    keys = [c["key"] for c in columns]
    rows = [dict((k, r.get(k)) for k in keys) for r in rows]          # exactly the declared columns, in every renderer
    return {"id": tid, "title": title, "columns": columns, "rows": rows, "note": note,
            "pdf_limit": pdf_limit, "empty_text": empty_text}


def kpi(kid, label, value, unit="", status="info", note="", coverage=None, formula="", decimals=None):
    return {"id": kid, "label": label, "value": value, "unit": unit, "status": status if value is not None else "na",
            "note": note, "coverage": coverage, "formula": formula, "decimals": decimals}


def chart(cid, title, ctype, table_id, x, series, unit="", max_items=12):
    return {"id": cid, "title": title, "type": ctype, "table": table_id, "x": x, "series": series,
            "unit": unit, "max_items": max_items}


# ------------------------------------------------------------------ formatting
def human_bps(v):
    for unit, scale in (("Tbps", 1e12), ("Gbps", 1e9), ("Mbps", 1e6), ("kbps", 1e3)):
        if abs(v) >= scale:
            return "%.2f %s" % (v / scale, unit)
    return "%.0f bps" % v


def human_seconds(v):
    v = int(round(v))
    d, r = divmod(v, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return "%dd %02dh %02dm" % (d, h, m)
    if h:
        return "%dh %02dm" % (h, m)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def fmt_value(ctype, v):
    """Display text for PDF (and a stable string form for tests). None -> N/A, never 0."""
    if v is None:
        return NA
    if ctype == "int":
        return "{:,}".format(int(v))
    if ctype == "float1":
        return "%.1f" % v
    if ctype == "float2":
        return "%.2f" % v
    if ctype == "pct":
        return "%.2f%%" % v
    if ctype == "bps":
        return human_bps(v)
    if ctype == "seconds":
        return human_seconds(v)
    if ctype == "datetime":
        try:
            return datetime.fromisoformat(v).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return str(v)
    return str(v)


def fmt_kpi(k):
    v = k["value"]
    if v is None:
        return NA
    d = k.get("decimals")
    unit = k.get("unit", "")
    if unit == "%":
        return ("%.*f%%" % (2 if d is None else d, v))
    if unit == "seconds":
        return human_seconds(v)
    if unit == "bps":
        return human_bps(v)
    if isinstance(v, float) and v != int(v):
        return "%.*f" % (1 if d is None else d, v) + ((" " + unit) if unit else "")
    return "{:,}".format(int(v)) + ((" " + unit) if unit else "")


def new_doc(report_key, title, subtitle, dataset, cfg):
    return {
        "schema": DOC_SCHEMA, "report": report_key, "title": title, "subtitle": subtitle,
        "period": dataset["period"], "generated_at": dataset["generated_at"],
        "timezone": dataset["period"]["timezone"], "dataset_sha256": dataset["dataset_sha256"],
        "source": {"zabbix": dataset["audit"]["source_api"], "collector": dataset["collector_version"],
                   "scope_hosts": len(dataset["hosts"])},
        "kpis": [], "findings": [], "sections": [], "tables": {}, "charts": [], "dictionary": [],
        "warnings": [], "audit": {},
    }


def add_section(doc, title, tables=(), charts=(), text=""):
    for t in tables:
        doc["tables"][t["id"]] = t
    for c in charts:
        doc["charts"].append(c)
    doc["sections"].append({"title": title, "text": text, "tables": [t["id"] for t in tables],
                            "charts": [c["id"] for c in charts]})
