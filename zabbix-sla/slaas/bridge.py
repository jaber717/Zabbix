"""Hand-off to the existing automated PDF / Excel reporting suite (branch claude/reporting-suite-v1) - without duplicating it.

This project computes SLA figures and emits them as a document in the suite's own model (schema `zabbix-reporting-suite-report-v1`:
kpis / findings / sections / tables / charts / dictionary / warnings / audit). The suite's renderers (JSON, PDF, XLSX) consume exactly
that model, so rendering, e-mail delivery, scheduling and archiving stay in the suite. Nothing here renders a PDF or workbook.

The shape builders are re-stated locally (a dozen lines) instead of imported, so the two projects have no code dependency; tests pin the
shape. The suite needs one small adapter to accept an external document (`--document FILE` -> renderers); see docs/INTEGRATION-REPORTING.md.
"""
import datetime
import hashlib
import json

from . import slo

DOC_SCHEMA = "zabbix-reporting-suite-report-v1"
NA = "N/A"


def human_seconds(v):
    v = int(round(abs(v))) * (1 if v >= 0 else -1)
    sign, v = ("-" if v < 0 else ""), abs(v)
    d, r = divmod(v, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return "%s%dd %02dh %02dm" % (sign, d, h, m)
    if h:
        return "%s%dh %02dm" % (sign, h, m)
    if m:
        return "%s%dm %02ds" % (sign, m, s)
    return "%s%ds" % (sign, s)


def _col(key, label, type="text", desc="", cf=None, width=None):
    return {"key": key, "label": label, "type": type, "description": desc, "cf": cf, "width": width}


def _table(tid, title, columns, rows, note="", pdf_limit=60, empty_text="None in this period."):
    keys = [c["key"] for c in columns]
    return {"id": tid, "title": title, "columns": columns, "rows": [dict((k, r.get(k)) for k in keys) for r in rows], "note": note,
            "pdf_limit": pdf_limit, "empty_text": empty_text}


def _kpi(kid, label, value, unit="", status="info", note="", formula="", decimals=None):
    return {"id": kid, "label": label, "value": value, "unit": unit, "status": status if value is not None else "na", "note": note,
            "coverage": None, "formula": formula, "decimals": decimals}


DEFINITIONS = [
    ("SLI", "Service level indicator: the share of the measured time a service was not in a problem state, as computed by Zabbix (sla.getsli)."),
    ("SLO", "Service level objective: the target SLI for the month. Values marked 'placeholder' have not been approved."),
    ("Error budget", "The downtime the SLO allows in the whole period: period length x (1 - SLO). 'Remaining' is the budget minus recorded downtime; negative = breached."),
    ("Burn rate", "Downtime rate relative to the rate the SLO allows. 1.0 consumes exactly the budget over the period; above 1.0 the budget runs out early."),
    ("COMPLIANT / BREACHED / INSUFFICIENT_DATA", "INSUFFICIENT_DATA means the monitoring behind the figure cannot support a compliance statement; it is never shown as 100%."),
    ("Inferred (T2) vs verified (T3)", "Inferred figures come from link states; verified figures additionally require active end-to-end probes with routing proof."),
    ("Signal quality", "full: every link end is monitored. partial: a link end is not monitored. blind: a link can never raise a problem."),
    ("Planned downtime", "Approved, ticketed maintenance windows excluded from the SLI. They are listed in this report."),
    ("Provider SLA", "Contractual provider claims are not part of this report; these are measurements on our side of the link."),
]


def to_suite_document(rep, collector_version):
    p = rep["period"]
    svc = rep["services"]
    kpis = [
        _kpi("services_reported", "Services reported", len(svc)),
        _kpi("services_compliant", "Compliant", rep["summary"].get(slo.COMPLIANT, 0), status="ok"),
        _kpi("services_breached", "Breached", rep["summary"].get(slo.BREACHED, 0), status="bad" if rep["summary"].get(slo.BREACHED, 0) else "ok"),
        _kpi("services_insufficient", "Insufficient data", rep["summary"].get(slo.INSUFFICIENT, 0), status="warn" if rep["summary"].get(slo.INSUFFICIENT, 0) else "ok",
             note="Not reported as available: the monitoring behind them cannot support a statement."),
    ]
    rows = []
    for s in svc:
        rows.append({
            "name": s["name"].replace("NETOPS-SLA: ", ""), "site": s.get("site") or "", "evidence": s["evidence"], "state": s["state"],
            "sli": s["sli_pct_reportable"], "slo": s["slo_pct"], "budget_total": s["budget_total_s"], "budget_left": s["budget_remaining_s"],
            "burn": s["burn_rate"], "coverage": 100.0 * s["coverage"], "signal": s["signal_quality"],
            "notes": "; ".join(s["reasons"] + s["caveats"])})
    t_services = _table("services", "Service availability against SLO", [
        _col("name", "Service"), _col("site", "Site"), _col("evidence", "Evidence", desc="Inferred (T2) or verified end to end (T3)."),
        _col("state", "Status", "status", "COMPLIANT, BREACHED or INSUFFICIENT_DATA", cf={"mode": "status"}),
        _col("sli", "SLI", "pct", "N/A when the data cannot support a figure"), _col("slo", "SLO", "pct"),
        _col("budget_total", "Error budget", "seconds"), _col("budget_left", "Budget left", "seconds"),
        _col("burn", "Burn rate", "float2"), _col("coverage", "Data coverage", "pct"), _col("signal", "Signal"), _col("notes", "Notes / caveats", width=60)],
        rows, note="Provider contractual SLAs are not included; see the dictionary.")
    t_pd = _table("planned_downtime", "Planned downtime applied", [_col("name", "Window"), _col("sla_class", "SLA class"),
                                                                    _col("start", "From", "datetime"), _col("end", "To", "datetime")],
                  [{"name": e["name"], "sla_class": e["sla_class"], "start": datetime.datetime.fromtimestamp(e["start_ts"], datetime.timezone.utc).isoformat(),
                    "end": datetime.datetime.fromtimestamp(e["end_ts"], datetime.timezone.utc).isoformat()} for e in rep["planned_downtime"]],
                  empty_text="No planned downtime was applied in this period.")
    t_sig = _table("link_signals", "Monitoring signal per link", [_col("link", "Link"), _col("quality", "Signal", "status", cf={"mode": "status"}), _col("hosts", "Monitored by"),
                                                                    _col("detail", "Detail", width=60)],
                   [{"link": r["link_id"], "quality": r["quality"], "hosts": ", ".join(r["hosts"]), "detail": r["detail"]} for r in sorted(rep["link_signals"].values(), key=lambda r: r["link_id"])])
    findings = []
    if rep["summary"].get(slo.BREACHED):
        findings.append("%d service(s) breached their SLO." % rep["summary"][slo.BREACHED])
    if rep["summary"].get(slo.INSUFFICIENT):
        findings.append("%d service(s) have insufficient monitoring data and are NOT reported as available." % rep["summary"][slo.INSUFFICIENT])
    if not svc:
        findings.append("No service figures could be produced; nothing is reported as available.")
    if not findings:
        findings.append("All %d reported service(s) met their SLO with sufficient data." % len(svc))
    audit = {"generated_at": rep["generated_at"], "period": p, "collector_version": collector_version, "environment": rep["environment"],
             "zabbix_version": rep["zabbix_version"], "api_methods": ["service.get", "sla.get", "sla.getsli", "trigger.get", "host.get", "item.get"], "writes": 0}
    doc = {
        "schema": DOC_SCHEMA, "report": "sla", "title": "Service availability and SLA", "subtitle": "%s (%s)" % (p["label"], p["timezone"]),
        "period": {"kind": "monthly", "label": p["label"], "timezone": p["timezone"], "start": p["start"], "end": p["end"], "start_ts": p["start_ts"], "end_ts": p["end_ts"],
                   "seconds": p["seconds"], "boundaries": p["boundaries"]},
        "generated_at": rep["generated_at"], "timezone": p["timezone"],
        "source": {"zabbix": rep["zabbix_version"], "collector": collector_version, "scope_hosts": 0},
        "kpis": kpis, "findings": findings,
        "sections": [{"title": "Service availability against SLO", "text": "", "tables": ["services"], "charts": []},
                     {"title": "Planned downtime", "text": "", "tables": ["planned_downtime"], "charts": []},
                     {"title": "Monitoring signal quality", "text": "A link without a working availability signal makes the services that use it INSUFFICIENT_DATA.", "tables": ["link_signals"], "charts": []}],
        "tables": {"services": t_services, "planned_downtime": t_pd, "link_signals": t_sig},
        "charts": [], "dictionary": [{"term": k, "definition": v} for k, v in DEFINITIONS],
        "warnings": list(rep["warnings"]), "audit": audit,
    }
    body = json.dumps(dict((k, v) for k, v in doc.items() if k != "dataset_sha256"), sort_keys=True, default=str).encode("utf-8")
    doc["dataset_sha256"] = hashlib.sha256(body).hexdigest()
    return doc
