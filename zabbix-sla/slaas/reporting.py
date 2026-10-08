"""Monthly SLI / SLO / error-budget report and the monitoring-quality check. Read-only: only *.get and sla.getsli are called.

Everything is computed from Zabbix's own SLA engine (sla.getsli) - this project does not re-derive availability from raw events.
What it adds is qualification: coverage of the measurable window, signal quality of the underlying monitoring (a link that cannot
raise a problem makes a service 'blind'), probe freshness for T3, planned-downtime listing and a hard separation from provider SLA claims.
"""
import datetime
import json
import zoneinfo

from . import bridge, slo
from . import state as S
from . import tags as T
from .model import FRESHNESS_CLASS

SCHEMA = "zabbix-sla-report-v1"


def _tag(rows, key):
    for t in rows:
        if t[0] == key:
            return t[1]
    return None


def components_of(desired, sid, seen=None):
    seen = seen if seen is not None else set()
    if sid in seen:
        return set()
    seen.add(sid)
    s = desired.services[sid]
    if s["layer"] == "component":
        return {sid}
    out = set()
    for c in s["children"]:
        out |= components_of(desired, c, seen)
    return out


def link_signals(client, desired):
    """{component id: {"link_id", "quality", "detail", "expected_ends", "found"}} from the link_down triggers that exist right now."""
    res = {}
    for cid, s in desired.services.items():
        if s["layer"] != "component":
            continue
        lid = dict((t, v) for t, _, v in s["problem_tags"]).get(T.NETOPS_LINK_ID)
        rows = client.call("trigger.get", {"output": ["triggerid", "status", "state", "error"], "selectHosts": ["host"], "evaltype": 0,
                                           "tags": [{"tag": T.NETOPS_LINK_ID, "value": lid, "operator": 1}, {"tag": T.NETOPS_ALERT, "value": "link_down", "operator": 1}]})
        ends = s.get("meta", {}).get("expected_ends", 2)
        q, detail = slo.link_quality(rows, ends)
        res[cid] = {"link_id": lid, "quality": q, "detail": detail, "expected_ends": ends, "found": len(rows),
                    "hosts": sorted(set(h["host"] for r in rows for h in r.get("hosts", [])))}
    return res


def quality_report(client, desired):
    links = link_signals(client, desired)
    services = {}
    for sid, s in desired.services.items():
        if s["layer"] not in ("business", "connectivity", "path"):
            continue
        comps = components_of(desired, sid)
        quals = [links[c]["quality"] for c in comps if c in links]
        declared_partial = any(links[c]["expected_ends"] < 2 for c in comps if c in links)
        services[sid] = slo.service_signal_quality(quals, declared_partial)
    return {"links": links, "services": services}


def _period(month, tz, now):
    y, m = [int(x) for x in month.split("-")]
    z = zoneinfo.ZoneInfo(tz)
    start = datetime.datetime(y, m, 1, tzinfo=z)
    end = datetime.datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=z)
    return start, end


def _parse_sli(res, period_from):
    periods, sids, sli = res.get("periods", []), res.get("serviceids", []), res.get("sli", [])
    best = None
    for i, p in enumerate(periods):
        d = abs(int(p["period_from"]) - period_from)
        if d <= 3 * 86400 and (best is None or d < best[0]):
            best = (d, i)
    if best is None:
        return {}
    row = sli[best[1]]
    return dict((sid, row[j]) for j, sid in enumerate(sids))


def build_report(client, desired, month, env, version, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    live, _, _ = S.read_live(client)
    qual = quality_report(client, desired)
    out = {"schema": SCHEMA, "environment": env["environment"], "month": month, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "zabbix_version": version, "services": [], "warnings": [], "planned_downtime": [], "link_signals": qual["links"],
           "provider_sla": {"note": "Provider contractual SLA claims are NOT part of this report. These figures are measured on our side of the link; "
                                    "a provider claim must be compared only after its scope and measurement point are confirmed (evidence E-08)."}}
    freshness_by_probe, tz0 = {}, None
    for cls in sorted(desired.slas, key=lambda c: c != FRESHNESS_CLASS):       # freshness first: T3 figures depend on it
        a = desired.slas[cls]
        tz0 = tz0 or a["timezone"]
        start, end = _period(month, a["timezone"], now)
        p_from, p_to = int(start.timestamp()), int(end.timestamp())
        eff = a["effective_date"]
        window = max(0, min(p_to, int(now.timestamp())) - max(p_from, eff))
        out.setdefault("period", {"label": month, "timezone": a["timezone"], "start": start.isoformat(), "end": end.isoformat(), "start_ts": p_from, "end_ts": p_to,
                                  "seconds": p_to - p_from, "boundaries": "half-open [start, end)"})
        if cls in live["slas"]:
            slaid = live["slas"][cls]["_id"]
        else:
            out["warnings"].append("SLA '%s' is not provisioned in this Zabbix: no figures can be reported for it" % cls)
            continue
        members = [sid for sid, s in desired.services.items()
                   if (s["layer"] == "quality") == (cls == FRESHNESS_CLASS) and (cls == FRESHNESS_CLASS or s["tags"].get("sla_class") == cls)]
        ids = dict((sid, live["services"][sid]["_id"]) for sid in members if sid in live["services"])
        for sid in members:
            if sid not in ids:
                out["warnings"].append("service '%s' is not provisioned: not reported" % sid)
        if not ids:
            continue
        res = client.call("sla.getsli", {"slaid": slaid, "serviceids": sorted(ids.values()), "period_from": p_from, "period_to": p_to - 1})
        cells = _parse_sli(res, p_from)
        by_sid = dict((sid, cells.get(zid)) for sid, zid in ids.items())
        if cls == FRESHNESS_CLASS:
            for sid, c in by_sid.items():
                if sid.startswith("quality.") and sid != "quality.root":
                    freshness_by_probe[sid[len("quality."):]] = None if c is None else float(c.get("downtime", 0))
            continue
        for sid in sorted(members):
            s = desired.services[sid]
            probes = [c[len("probe."):] for c in s["children"] if c.startswith("probe.")]
            stale = None
            if s["tags"].get("tier") == "T3":
                vals = [freshness_by_probe.get(p) for p in probes]
                stale = None if (not vals or any(v is None for v in vals)) else max(vals)
            comps = components_of(desired, sid)
            caveats = []
            if s["tags"].get("tier") == "T2":
                caveats.append("inferred from link state (T2): not verified by end-to-end probes")
            for c in sorted(comps):
                lq = qual["links"][c]
                if lq["quality"] in ("PARTIAL", "MISSING", "DISABLED", "UNKNOWN"):
                    caveats.append("link %s: %s" % (lq["link_id"], lq["detail"]))
            r = slo.assess(by_sid.get(sid), a["slo"], p_to - p_from, window, qual["services"].get(sid, "full"), stale, caveats, tier=s["tags"].get("tier", "T2"))
            if not a.get("approved", False):
                r["caveats"].append("SLO %.3g%% is a placeholder, not approved" % a["slo"])
            out["services"].append(dict(r, sla_id=sid, name=s["name"], tier=s["tags"].get("tier"), sla_class=cls, site=s["tags"].get("site"),
                                        evidence="verified end to end" if s["tags"].get("tier") == "T3" else "inferred from link state"))
        for e in a["excluded_downtimes"]:
            if e["period_from"] < p_to and e["period_to"] > p_from:
                out["planned_downtime"].append({"sla_class": cls, "name": e["name"], "start_ts": e["period_from"], "end_ts": e["period_to"]})
    if not out["services"]:
        out["warnings"].append("no service figures could be produced: nothing is reported as available")
    out["summary"] = dict((st, sum(1 for s in out["services"] if s["state"] == st)) for st in (slo.COMPLIANT, slo.BREACHED, slo.INSUFFICIENT))
    return out


def run(args, env, desired, client, out, now):
    if args.cmd == "quality":
        q = quality_report(client, desired)
        bad = 0
        for cid, r in sorted(q["links"].items()):
            flag = "ok  " if r["quality"] == "OK" else "WARN"
            bad += r["quality"] != "OK"
            out("  %s %-34s %-9s %s" % (flag, r["link_id"], r["quality"], r["detail"]))
        for sid, sq in sorted(q["services"].items()):
            if desired.services[sid]["layer"] == "business":
                out("  service %-34s signal quality: %s" % (sid, sq))
        out("  %s" % ("every link has a working availability signal" if not bad else "%d link(s) have a degraded signal: figures for services using them are qualified" % bad))
        return 0 if not bad else 2
    version = client.call("apiinfo.version")
    rep = build_report(client, desired, args.month, env, version, now)
    text = json.dumps(rep, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        out("report written: %s" % args.out)
    else:
        out(text)
    if getattr(args, "suite_doc", None):
        from . import VERSION
        with open(args.suite_doc, "w", encoding="utf-8") as fh:
            json.dump(bridge.to_suite_document(rep, "zabbix-sla/" + VERSION), fh, indent=2, sort_keys=True)
        out("suite document written: %s" % args.suite_doc)
    for s in rep["services"]:
        out("  %-34s %-18s SLI %s  SLO %.3g%%  budget left %s" % (s["sla_id"], s["state"], "N/A" if s["sli_pct_reportable"] is None else "%.3f%%" % s["sli_pct_reportable"],
                                                              s["slo_pct"], bridge.human_seconds(s["budget_remaining_s"])))
    return 0
