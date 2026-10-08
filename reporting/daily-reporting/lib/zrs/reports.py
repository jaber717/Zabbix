"""Dataset -> report document, for the six reports. Pure functions: no API access, no I/O, no clock."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .incidents import host_downtime, mttr_seconds
from .metrics import confidence
from .model import add_section, chart, col, kpi, new_doc, table
from .plans import REPORTS

FORMULAS = {
    "availability": "Per device: ICMP-ping samples with value 1 divided by all ICMP-ping samples in the period, when sample coverage is at "
                    "least the configured minimum (basis 'icmp'). Otherwise: 100 x (1 - merged downtime seconds from downtime-class problem "
                    "events / period seconds) with confidence LOW (basis 'events'). N/A when neither exists. Fleet/site value = mean of device values "
                    "that have a value (devices are weighted equally).",
    "coverage": "Samples present divided by samples expected from the item update interval (N/A when the interval is not a plain number).",
    "confidence": "HIGH coverage >= 95%, MEDIUM >= 80%, LOW > 0, NONE = no samples, UNKNOWN = expected samples cannot be derived.",
    "downtime": "Union (overlaps merged) of [start, recovery) intervals of downtime-class problems per device, clipped to the half-open period.",
    "incident": "One Zabbix problem event, de-duplicated by event id. A multi-host event is one incident, listed against every host it touches.",
    "mttr": "Mean of (recovery time - start time) over incidents resolved inside the period (full duration, not clipped). N/A if none resolved.",
    "flapping": "Devices with at least thresholds.flapping_events downtime-class incidents that started inside the period.",
    "stale": "Device whose newest ICMP item value is older than thresholds.stale_data_minutes at generation time. Devices without an ICMP item are not evaluated.",
    "utilization": "Interface average/peak rate divided by capacity (ifHighSpeed item maximum in the period, or the configured capacity_bps). N/A without capacity.",
    "p95_hourly": "Nearest-rank 95th percentile of hourly trend averages. NOT a 5-minute percentile; hourly means hide short peaks.",
    "p95_raw": "Nearest-rank 95th percentile of raw history samples (only for periods read from history).",
    "sla": "Availability compared with the configured SLA target, shown only when fleet confidence is at least MEDIUM; otherwise N/A.",
}


def _tz(ds):
    return ZoneInfo(ds["period"]["timezone"])


def _iso(ts, tz):
    return None if ts is None else datetime.fromtimestamp(ts, tz).isoformat(timespec="seconds")


def _gen_ts(ds):
    return int(datetime.fromisoformat(ds["generated_at"]).timestamp())


def _period(ds):
    class P(object):
        start_ts, end_ts = ds["period"]["start_ts"], ds["period"]["end_ts"]
        seconds = ds["period"]["seconds"]
    return P


def _best(items, kind):
    """Per host, the item of this kind with the most samples."""
    best = {}
    for it in items:
        if it["kind"] != kind or not it.get("stats"):
            continue
        cur = best.get(it["hostid"])
        if cur is None or (it["stats"]["samples"] or 0) > (cur["stats"]["samples"] or 0):
            best[it["hostid"]] = it
    return best


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def _pct(num, den):
    return None if not den else 100.0 * num / den


def availability_by_host(ds, cfg, items, incidents):
    """{hostid: dict} - see FORMULAS['availability']."""
    P = _period(ds)
    min_cov = float(cfg["suite"]["sla"]["min_coverage"])
    down = host_downtime(incidents, P, _gen_ts(ds))
    icmp = _best(items, "icmp_ping")
    out = {}
    for h in ds["hosts"]:
        hid = h["hostid"]
        it = icmp.get(hid)
        st = it["stats"] if it else None
        cov = st["coverage"] if st else None
        if st and st["up_ratio"] is not None and cov is not None and cov >= min_cov:
            value, basis, conf = st["up_ratio"] * 100.0, "icmp", confidence(cov)
        elif st and st["up_ratio"] is not None and cov is None:
            value, basis, conf = st["up_ratio"] * 100.0, "icmp", "UNKNOWN"
        elif st is not None or h["state_now"] != "UNKNOWN":
            value, basis, conf = 100.0 * (1 - down.get(hid, 0) / float(P.seconds)), "events", "LOW"
        else:
            value, basis, conf = None, "none", "NONE"
        out[hid] = {"availability_pct": value, "basis": basis, "coverage": cov, "confidence": conf,
                    "downtime_s": down.get(hid, 0), "icmp_item": it["itemid"] if it else None,
                    "lastclock": it["lastclock"] if it else None}
    return out


def _fleet(av, hosts, min_conf=("HIGH", "MEDIUM")):
    vals = [v["availability_pct"] for v in av.values() if v["availability_pct"] is not None]
    n = len(hosts)
    confs = [v["confidence"] for v in av.values() if v["availability_pct"] is not None]
    solid = sum(1 for c in confs if c in min_conf)
    return {"value": _mean(vals), "hosts_with_value": len(vals), "hosts": n,
            "solid_ratio": (solid / float(n)) if n else None}


def _status_for(value, target):
    if value is None:
        return "na"
    return "ok" if value >= target else ("warn" if value >= target - 0.5 else "bad")


def _incident_rows(incidents, tz, keep_order=False):
    rows = []
    for i in (incidents if keep_order else sorted(incidents, key=lambda x: (-x["severity"], x["start"]))):
        rows.append({"eventid": i["eventid"], "severity": i["severity_name"], "hosts": ", ".join(i["host_names"]),
                     "sites": ", ".join(i["sites"]), "problem": i["name"], "started": _iso(i["start"], tz),
                     "resolved": _iso(i["end"], tz), "duration_in_period_s": i["duration_in_window_s"],
                     "state": "OPEN" if i["open_at_period_end"] else "RESOLVED",
                     "acknowledged": "Yes" if i["acknowledged"] else "No",
                     "downtime_class": "Yes" if i["is_downtime"] else "No"})
    return rows


INCIDENT_COLS = [
    col("eventid", "Event ID", "text"), col("severity", "Severity", "status", cf={"mode": "status"}),
    col("hosts", "Device(s)"), col("sites", "Site(s)"), col("problem", "Problem"),
    col("started", "Started", "datetime"), col("resolved", "Resolved", "datetime",
                                                   desc="Empty = still open (or recovery time unavailable)."),
    col("duration_in_period_s", "Duration in period", "seconds", desc="Clipped to the reporting period."),
    col("state", "State at period end", "status", cf={"mode": "status"}), col("acknowledged", "Acknowledged"),
    col("downtime_class", "Counts as downtime"),
]


def _finish(doc, ds, used_formulas):
    doc["dictionary"] = [{"term": k, "definition": FORMULAS[k]} for k in sorted(set(used_formulas))]
    for t in doc["tables"].values():
        for c in t["columns"]:
            if c.get("description"):
                doc["dictionary"].append({"term": "%s / %s" % (t["title"], c["label"]), "definition": c["description"]})
    n = ds["audit"]["notes"]
    for t in n["truncated"]:
        doc["warnings"].append("DATA TRUNCATED - %s: %s" % (t["what"], t["detail"]))
    for f in n["failed"]:
        doc["warnings"].append("DATA REQUEST FAILED - %s: %s" % (f["what"], f["error"]))
    doc["warnings"].extend(n["warnings"])
    q = ds.get("incident_quality") or {}
    if q.get("recovery_time_unknown"):
        doc["warnings"].append("%d incident(s) are marked recovered but their recovery time could not be read; shown as open." % q["recovery_time_unknown"])
    doc["audit"] = {"dataset_sha256": ds["dataset_sha256"], "generated_at": ds["generated_at"], "period": ds["period"],
                    "collector_version": ds["collector_version"], "api_calls": ds["audit"]["api_calls"],
                    "api_by_method": ds["audit"]["api_by_method"], "scope": ds["audit"]["scope"],
                    "limits": ds["audit"]["limits"], "truncated": n["truncated"], "failed": n["failed"],
                    "data_notes": n["warnings"]}
    return doc


def _incident_counts(incs):
    return {"started": sum(1 for i in incs if i["started_in_window"]), "resolved": sum(1 for i in incs if i["resolved_in_window"]),
            "open": sum(1 for i in incs if i["open_at_period_end"]), "total": len(incs),
            "high": sum(1 for i in incs if i["severity"] >= 4)}


# =========================================================================== 1. Daily Network Health
def daily_network_health(ds, cfg):
    tz, P, now = _tz(ds), _period(ds), _gen_ts(ds)
    th, target = cfg["thresholds"], float(cfg["suite"]["sla"]["target_percent"])
    hosts, items, incs = ds["hosts"], ds["items"], ds["incidents"]
    av = availability_by_host(ds, cfg, items, incs)
    fl = _fleet(av, hosts)
    cnt = _incident_counts(incs)
    flap_th, stale_s = int(th["flapping_events"]), int(th["stale_data_minutes"]) * 60
    starts = Counter()
    for i in incs:
        if i["is_downtime"] and i["started_in_window"]:
            for h in i["hosts"]:
                starts[h["hostid"]] += 1
    flapping = {h: n for h, n in starts.items() if n >= flap_th}
    stale = {h["hostid"] for h in hosts if av[h["hostid"]]["lastclock"] is not None
             and (av[h["hostid"]]["lastclock"] == 0 or now - av[h["hostid"]]["lastclock"] > stale_s)}
    down_now = [h for h in hosts if h["state_now"] == "DOWN"]
    unknown = [h for h in hosts if h["state_now"] == "UNKNOWN"]
    open_hd = [p for p in ds["open_problems"] if p["severity"] >= 4]
    doc = new_doc("daily_network_health", "Daily Network Health", "Period %s (%s)" % (ds["period"]["label"], ds["period"]["timezone"]), ds, cfg)
    doc["kpis"] = [
        kpi("devices_monitored", "Devices monitored", len(hosts)),
        kpi("devices_up_now", "Available now", len(hosts) - len(down_now) - len(unknown), status="ok"),
        kpi("devices_down_now", "Down now", len(down_now), status="bad" if down_now else "ok"),
        kpi("availability_pct", "Availability (fleet)", fl["value"], "%", _status_for(fl["value"], target),
            note="%d of %d devices have a value" % (fl["hosts_with_value"], fl["hosts"]), formula="availability"),
        kpi("incidents_started", "Incidents started", cnt["started"], status="warn" if cnt["started"] else "ok", formula="incident"),
        kpi("incidents_resolved", "Incidents resolved", cnt["resolved"]),
        kpi("open_high_disaster", "Open High/Disaster now", len(open_hd), status="bad" if open_hd else "ok"),
        kpi("flapping_devices", "Flapping devices", len(flapping), status="warn" if flapping else "ok", formula="flapping"),
        kpi("stale_devices", "Stale devices", len(stale), status="warn" if stale else "ok", formula="stale"),
        kpi("unknown_devices", "State unknown", len(unknown), status="warn" if unknown else "ok"),
    ]
    sites = defaultdict(list)
    for h in hosts:
        sites[h["site"]].append(h)
    site_rows = []
    for s in sorted(sites):
        hs = sites[s]
        vals = [av[h["hostid"]]["availability_pct"] for h in hs]
        site_rows.append({"site": s, "devices": len(hs),
                          "up_now": sum(1 for h in hs if h["state_now"] == "UP"),
                          "down_now": sum(1 for h in hs if h["state_now"] == "DOWN"),
                          "availability_pct": _mean(vals),
                          "downtime_s": sum(av[h["hostid"]]["downtime_s"] for h in hs),
                          "incidents": len({i["eventid"] for i in incs if s in i["sites"]}),
                          "confidence": _worst([av[h["hostid"]]["confidence"] for h in hs])})
    t_site = table("site_summary", "Availability by site", [
        col("site", "Site"), col("devices", "Devices", "int"), col("up_now", "Up now", "int"), col("down_now", "Down now", "int", cf={"mode": "high", "warn": 1, "bad": 1}),
        col("availability_pct", "Availability", "pct", cf={"mode": "low", "warn": target, "bad": target - 0.5}, desc="Mean device availability; basis per device in the Devices table."),
        col("downtime_s", "Downtime (sum)", "seconds", desc="Sum of per-device merged downtime."),
        col("incidents", "Incidents", "int"), col("confidence", "Confidence", "status", cf={"mode": "status"})], site_rows)
    dev_rows = []
    for h in sorted(hosts, key=lambda x: ((av[x["hostid"]]["availability_pct"] is None), av[x["hostid"]]["availability_pct"] or 0, x["name"].lower())):
        a = av[h["hostid"]]
        dev_rows.append({"device": h["name"], "site": h["site"], "state_now": h["state_now"],
                         "availability_pct": a["availability_pct"], "basis": a["basis"], "coverage_pct": None if a["coverage"] is None else a["coverage"] * 100.0,
                         "confidence": a["confidence"], "downtime_s": a["downtime_s"],
                         "incidents_started": starts.get(h["hostid"], 0),
                         "flags": ", ".join(x for x, on in (("FLAPPING", h["hostid"] in flapping), ("STALE", h["hostid"] in stale)) if on)})
    t_dev = table("devices", "Devices", [
        col("device", "Device"), col("site", "Site"), col("state_now", "State now", "status", cf={"mode": "status"}),
        col("availability_pct", "Availability", "pct", cf={"mode": "low", "warn": target, "bad": target - 0.5}),
        col("basis", "Basis", desc="icmp = ping samples; events = reconstructed from problem events (confidence LOW); none = no data."),
        col("coverage_pct", "ICMP coverage", "pct", desc="See coverage definition."), col("confidence", "Confidence", "status", cf={"mode": "status"}),
        col("downtime_s", "Downtime", "seconds"), col("incidents_started", "Downtime incidents", "int"), col("flags", "Flags")], dev_rows, pdf_limit=30)
    t_inc = table("incidents", "Incidents in period", INCIDENT_COLS, _incident_rows(incs, tz), pdf_limit=25)
    t_open = table("open_high", "Open High / Disaster problems (now)", [
        col("eventid", "Event ID"), col("severity", "Severity", "status", cf={"mode": "status"}), col("hosts", "Device(s)"), col("problem", "Problem"),
        col("since", "Since", "datetime"), col("acknowledged", "Acknowledged")],
        [{"eventid": p["eventid"], "severity": {4: "High", 5: "Disaster"}.get(p["severity"], str(p["severity"])), "hosts": ", ".join(p["hosts"]),
          "problem": p["name"], "since": _iso(p["clock"], tz), "acknowledged": "Yes" if p["acknowledged"] else "No"}
         for p in sorted(open_hd, key=lambda x: (-x["severity"], x["clock"]))], pdf_limit=20)
    doc["findings"] = _daily_findings(cnt, down_now, flapping, stale, fl, target, unknown)
    add_section(doc, "Availability by site", [t_site], [chart("c_site_avail", "Availability by site (%)", "hbar", "site_summary", "site", [{"key": "availability_pct", "label": "Availability"}], "%")])
    add_section(doc, "Open High / Disaster problems", [t_open])
    add_section(doc, "Incidents", [t_inc])
    add_section(doc, "Devices", [t_dev])
    return _finish(doc, ds, ["availability", "coverage", "confidence", "downtime", "incident", "flapping", "stale"])


def _worst(confs):
    order = ["NONE", "UNKNOWN", "LOW", "MEDIUM", "HIGH"]
    confs = [c for c in confs if c]
    return min(confs, key=lambda c: order.index(c)) if confs else "NONE"


def _daily_findings(cnt, down_now, flapping, stale, fl, target, unknown):
    out = []
    if down_now:
        out.append("%d device(s) are DOWN now: %s." % (len(down_now), ", ".join(sorted(h["name"] for h in down_now)[:5]) + ("..." if len(down_now) > 5 else "")))
    if fl["value"] is None:
        out.append("Fleet availability is N/A: no device has ICMP data or a known state.")
    elif fl["value"] < target:
        out.append("Fleet availability %.2f%% is below the %.2f%% target." % (fl["value"], target))
    else:
        out.append("Fleet availability %.2f%% meets the %.2f%% target." % (fl["value"], target))
    if cnt["started"]:
        out.append("%d incident(s) started, %d resolved, %d still open at period end." % (cnt["started"], cnt["resolved"], cnt["open"]))
    else:
        out.append("No incidents started in the period.")
    if flapping:
        out.append("%d device(s) flapping." % len(flapping))
    if stale or unknown:
        out.append("Data quality: %d stale, %d state-unknown device(s)." % (len(stale), len(unknown)))
    return out


# =========================================================================== 2. WAN & ISP Performance
def _link_row(link, items, ds, cfg, tz):
    key = (link["hostid"], link["interface"])
    mine = [i for i in items if (i["hostid"], i["interface"]) == key]
    by = defaultdict(list)
    for i in mine:
        by[i["kind"]].append(i)
    st = lambda kind, f: (by[kind][0]["stats"] or {}).get(f) if by.get(kind) and by[kind][0].get("stats") else None
    cap = link.get("capacity_bps")
    cap_src = "configured" if cap else None
    if not cap:
        cap = st("if_speed", "max")
        cap_src = "ifHighSpeed item" if cap else "missing"
    th = float(cfg["thresholds"]["interface_utilization_percent"])
    in_avg, out_avg, in_max, out_max = st("if_in", "avg"), st("if_out", "avg"), st("if_in", "max"), st("if_out", "max")
    pc = lambda v: _pct(v, cap) if (v is not None and cap) else None
    up = st("if_status", "up_ratio")
    return {"isp": link.get("isp", ""), "site": link["site"], "device": link["host_name"], "interface": link["interface"],
            "capacity_bps": cap, "capacity_source": cap_src,
            "in_avg_bps": in_avg, "in_peak_bps": in_max, "in_p95_hourly_bps": st("if_in", "p95_of_hourly_avg") if st("if_in", "p95_of_hourly_avg") is not None else st("if_in", "p95_raw"),
            "out_avg_bps": out_avg, "out_peak_bps": out_max, "out_p95_hourly_bps": st("if_out", "p95_of_hourly_avg") if st("if_out", "p95_of_hourly_avg") is not None else st("if_out", "p95_raw"),
            "in_avg_util_pct": pc(in_avg), "in_peak_util_pct": pc(in_max), "out_avg_util_pct": pc(out_avg), "out_peak_util_pct": pc(out_max),
            "peak_util_pct": max([v for v in (pc(in_max), pc(out_max)) if v is not None], default=None),
            "link_availability_pct": None if up is None else up * 100.0, "status_coverage_pct": None if st("if_status", "coverage") is None else st("if_status", "coverage") * 100.0,
            "in_errors_avg": st("if_in_err", "avg"), "out_errors_avg": st("if_out_err", "avg"),
            "in_discards_avg": st("if_in_disc", "avg"), "out_discards_avg": st("if_out_disc", "avg"),
            "confidence": confidence(st("if_in", "coverage")),
            "_by": by}


def wan_isp_performance(ds, cfg):
    tz = _tz(ds)
    th = float(cfg["thresholds"]["interface_utilization_percent"])
    links = ds["wan_links"]
    rows = [_link_row(l, ds["interface_items"], ds, cfg, tz) for l in links]
    paths = defaultdict(dict)
    for it in ds["path_items"]:
        if it.get("stats"):
            paths[it["hostid"]][it["kind"]] = it["stats"]
    for r, l in zip(rows, links):
        p = paths.get(l["hostid"], {})
        r["rtt_avg_s"] = (p.get("icmp_rtt") or {}).get("avg")
        r["rtt_max_s"] = (p.get("icmp_rtt") or {}).get("max")
        r["loss_avg_pct"] = (p.get("icmp_loss") or {}).get("avg")
    isp = defaultdict(list)
    for r in rows:
        isp[r["isp"] or "Unassigned"].append(r)
    isp_rows = []
    for name in sorted(isp):
        rs = isp[name]
        isp_rows.append({"isp": name, "links": len(rs), "sites": ", ".join(sorted({r["site"] for r in rs})),
                         "avg_in_bps": _sum([r["in_avg_bps"] for r in rs]), "avg_out_bps": _sum([r["out_avg_bps"] for r in rs]),
                         "peak_util_pct": max([r["peak_util_pct"] for r in rs if r["peak_util_pct"] is not None], default=None),
                         "availability_pct": _mean([r["link_availability_pct"] for r in rs]),
                         "rtt_avg_s": _mean([r["rtt_avg_s"] for r in rs]), "loss_avg_pct": _mean([r["loss_avg_pct"] for r in rs])})
    over = [r for r in rows if r["peak_util_pct"] is not None and r["peak_util_pct"] >= th]
    no_cap = [r for r in rows if r["capacity_bps"] is None]
    avails = [r["link_availability_pct"] for r in rows]
    doc = new_doc("wan_isp_performance", "WAN & ISP Performance", "Week %s (%s)" % (ds["period"]["label"], ds["period"]["timezone"]), ds, cfg)
    doc["kpis"] = [
        kpi("links_monitored", "WAN links in report", len(rows)),
        kpi("isps", "ISPs", len(isp)),
        kpi("link_availability_pct", "Mean link availability", _mean(avails), "%", "info", note="from interface status history", formula="coverage"),
        kpi("peak_util_pct", "Highest peak utilization", max([r["peak_util_pct"] for r in rows if r["peak_util_pct"] is not None], default=None), "%",
            "bad" if over else "ok", note="hourly-average based peaks", formula="utilization"),
        kpi("links_over_threshold", "Links at/above %.0f%% peak" % th, len(over), status="warn" if over else "ok"),
        kpi("links_missing_capacity", "Links without capacity", len(no_cap), status="warn" if no_cap else "ok", note="utilization % is N/A for these"),
        kpi("links_unresolved", "Declared links not found", len(ds["wan_unresolved"]), status="warn" if ds["wan_unresolved"] else "ok"),
    ]
    link_cols = [
        col("isp", "ISP"), col("site", "Site"), col("device", "Device"), col("interface", "Interface"),
        col("capacity_bps", "Capacity", "bps", desc="Configured capacity_bps, else ifHighSpeed item maximum; empty = missing."),
        col("capacity_source", "Capacity source"),
        col("in_avg_bps", "In avg", "bps"), col("in_peak_bps", "In peak (hourly)", "bps", desc="Maximum of hourly trend maxima (or raw max for daily)."),
        col("in_p95_hourly_bps", "In P95 (hourly avg)", "bps", desc=FORMULAS["p95_hourly"]),
        col("out_avg_bps", "Out avg", "bps"), col("out_peak_bps", "Out peak (hourly)", "bps"), col("out_p95_hourly_bps", "Out P95 (hourly avg)", "bps", desc=FORMULAS["p95_hourly"]),
        col("in_avg_util_pct", "In avg util", "pct"), col("in_peak_util_pct", "In peak util", "pct", cf={"mode": "high", "warn": th * 0.8, "bad": th}),
        col("out_avg_util_pct", "Out avg util", "pct"), col("out_peak_util_pct", "Out peak util", "pct", cf={"mode": "high", "warn": th * 0.8, "bad": th}),
        col("link_availability_pct", "Link availability", "pct", cf={"mode": "low", "warn": 99.9, "bad": 99.0}), col("status_coverage_pct", "Status coverage", "pct"),
        col("in_errors_avg", "In errors (avg)", "float2", desc="Average of the item values over the period (item units); not a total."),
        col("out_errors_avg", "Out errors (avg)", "float2"), col("in_discards_avg", "In discards (avg)", "float2"), col("out_discards_avg", "Out discards (avg)", "float2"),
        col("peak_util_pct", "Peak util (in or out)", "pct", cf={"mode": "high", "warn": th * 0.8, "bad": th}),
        col("rtt_avg_s", "RTT avg (s)", "float2", desc="ICMP round-trip of the link host."), col("rtt_max_s", "RTT max (s)", "float2"), col("loss_avg_pct", "Loss avg", "pct"), col("confidence", "Confidence", "status", cf={"mode": "status"})]
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    t_links = table("links", "WAN links", link_cols, clean, pdf_limit=20)
    t_isp = table("isp_summary", "ISP comparison", [
        col("isp", "ISP"), col("links", "Links", "int"), col("sites", "Sites"), col("avg_in_bps", "Avg in (sum)", "bps"), col("avg_out_bps", "Avg out (sum)", "bps"),
        col("peak_util_pct", "Peak util", "pct", cf={"mode": "high", "warn": th * 0.8, "bad": th}), col("availability_pct", "Availability", "pct", cf={"mode": "low", "warn": 99.9, "bad": 99.0}),
        col("rtt_avg_s", "RTT avg (s)", "float2"), col("loss_avg_pct", "Loss avg", "pct")], isp_rows)
    trend_rows = _wan_trend(rows, tz)
    t_trend = table("daily_trend", "Daily peak and average rate (all declared links)", [
        col("day", "Day"), col("in_avg_bps", "In avg", "bps"), col("out_avg_bps", "Out avg", "bps"), col("in_peak_bps", "In peak (hourly)", "bps"), col("out_peak_bps", "Out peak (hourly)", "bps")],
        trend_rows, note="Sum over links of each day's hourly-trend average / maximum; hourly granularity.", pdf_limit=31)
    t_exc = table("exceptions", "Exceptions", [col("device", "Device"), col("interface", "Interface"), col("isp", "ISP"), col("issue", "Issue")],
                  [{"device": r["device"], "interface": r["interface"], "isp": r["isp"], "issue": "peak utilization %.1f%% >= %.0f%%" % (r["peak_util_pct"], th)} for r in over] +
                  [{"device": r["device"], "interface": r["interface"], "isp": r["isp"], "issue": "capacity unknown - utilization N/A"} for r in no_cap] +
                  [{"device": u["host"], "interface": u["interface"], "isp": "", "issue": u["reason"]} for u in ds["wan_unresolved"]], pdf_limit=30)
    t_inc = table("incidents", "WAN-device incidents in period", INCIDENT_COLS, _incident_rows(ds["incidents"], tz), pdf_limit=15)
    doc["findings"] = ["%d of %d link(s) reached %.0f%% peak utilization." % (len(over), len(rows), th) if rows else "No WAN links are configured (suite.json wan.links).",
                       "%d link(s) have no known capacity; their utilization is N/A." % len(no_cap) if no_cap else "All links have a known capacity."]
    add_section(doc, "ISP comparison", [t_isp], [chart("c_isp_peak", "Peak utilization by ISP (%)", "bar", "isp_summary", "isp", [{"key": "peak_util_pct", "label": "Peak utilization"}], "%"),
                                                  chart("c_isp_avail", "Availability by ISP (%)", "bar", "isp_summary", "isp", [{"key": "availability_pct", "label": "Availability"}], "%")])
    add_section(doc, "Daily trend", [t_trend], [chart("c_trend", "Daily average rate (bps)", "line", "daily_trend", "day", [{"key": "in_avg_bps", "label": "In"}, {"key": "out_avg_bps", "label": "Out"}], "bps")])
    add_section(doc, "Links", [t_links])
    add_section(doc, "Exceptions", [t_exc])
    add_section(doc, "Incidents on WAN devices", [t_inc])
    return _finish(doc, ds, ["utilization", "p95_hourly", "p95_raw", "coverage", "confidence", "incident"])


def _sum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def _wan_trend(rows, tz):
    days = defaultdict(lambda: {"in_avg_bps": 0.0, "out_avg_bps": 0.0, "in_peak_bps": 0.0, "out_peak_bps": 0.0, "n": 0})
    for r in rows:
        for kind, a, m in (("if_in", "in_avg_bps", "in_peak_bps"), ("if_out", "out_avg_bps", "out_peak_bps")):
            for it in r["_by"].get(kind, []):
                for d in ((it.get("stats") or {}).get("by_day") or []):
                    if d["avg"] is not None:
                        days[d["day"]][a] += d["avg"]
                        days[d["day"]][m] += d["max"] or 0
                        days[d["day"]]["n"] += 1
    return [{"day": d, "in_avg_bps": v["in_avg_bps"], "out_avg_bps": v["out_avg_bps"], "in_peak_bps": v["in_peak_bps"], "out_peak_bps": v["out_peak_bps"]} for d, v in sorted(days.items()) if v["n"]]


# =========================================================================== 3. Infrastructure Health
def infrastructure_health(ds, cfg):
    tz = _tz(ds)
    th = cfg["thresholds"]
    cpu_t, mem_t = float(th["cpu_percent"]), float(th["memory_percent"])
    top_n = int(cfg["suite"]["infra"]["top_n"])
    hosts = {h["hostid"]: h for h in ds["hosts"] if h["hostid"] in set(ds["infra_hostids"])}
    cpu, mem, upt = _best(ds["items"], "cpu"), _best(ds["items"], "memory"), _best(ds["items"], "uptime")
    incs_by_host = Counter()
    for i in ds["incidents"]:
        for h in i["hosts"]:
            incs_by_host[h["hostid"]] += 1
    rows = []
    for hid, h in hosts.items():
        c, m, u = (cpu.get(hid) or {}).get("stats"), (mem.get(hid) or {}).get("stats"), (upt.get(hid) or {}).get("stats")
        g = lambda s, f: None if not s else s.get(f)
        rows.append({"device": h["name"], "site": h["site"],
                     "cpu_avg_pct": g(c, "avg"), "cpu_max_pct": g(c, "max"), "cpu_p95_hourly_pct": g(c, "p95_of_hourly_avg"), "cpu_hours_over": g(c, "hours_over_threshold"),
                     "cpu_coverage_pct": None if g(c, "coverage") is None else g(c, "coverage") * 100.0,
                     "mem_avg_pct": g(m, "avg"), "mem_max_pct": g(m, "max"), "mem_p95_hourly_pct": g(m, "p95_of_hourly_avg"), "mem_hours_over": g(m, "hours_over_threshold"),
                     "mem_coverage_pct": None if g(m, "coverage") is None else g(m, "coverage") * 100.0,
                     "reboots": g(u, "counter_drops"), "incidents": incs_by_host.get(hid, 0),
                     "has_cpu": c is not None, "has_mem": m is not None})
    rows.sort(key=lambda r: ((r["cpu_p95_hourly_pct"] is None), -(r["cpu_p95_hourly_pct"] or 0), r["device"].lower()))
    exc = [r for r in rows if (r["cpu_hours_over"] or 0) > 0 or (r["mem_hours_over"] or 0) > 0 or (r["cpu_max_pct"] or 0) >= cpu_t or (r["mem_max_pct"] or 0) >= mem_t]
    no_cpu = [r for r in rows if not r["has_cpu"] or r["cpu_avg_pct"] is None]
    no_mem = [r for r in rows if not r["has_mem"] or r["mem_avg_pct"] is None]
    reboots = [r for r in rows if (r["reboots"] or 0) > 0]
    doc = new_doc("infrastructure_health", "Infrastructure Health", "Week %s (%s)" % (ds["period"]["label"], ds["period"]["timezone"]), ds, cfg)
    doc["kpis"] = [
        kpi("devices_assessed", "Devices assessed", len(rows)),
        kpi("cpu_fleet_avg_pct", "Fleet CPU average", _mean([r["cpu_avg_pct"] for r in rows]), "%", "info", note="mean of device averages (hourly trends)"),
        kpi("mem_fleet_avg_pct", "Fleet memory average", _mean([r["mem_avg_pct"] for r in rows]), "%", "info"),
        kpi("devices_over_threshold", "Devices with hours over threshold", len(exc), status="warn" if exc else "ok", note="CPU %.0f%% / memory %.0f%% on hourly averages" % (cpu_t, mem_t)),
        kpi("devices_no_cpu", "Devices without CPU data", len(no_cpu), status="warn" if no_cpu else "ok"),
        kpi("devices_no_memory", "Devices without memory data", len(no_mem), status="warn" if no_mem else "ok"),
        kpi("reboots_detected", "Devices with a reboot", len(reboots), status="warn" if reboots else "ok", note="uptime counter dropped between hours"),
    ]
    cols = [col("device", "Device"), col("site", "Site"),
            col("cpu_avg_pct", "CPU avg", "pct"), col("cpu_max_pct", "CPU max (hourly)", "pct", cf={"mode": "high", "warn": cpu_t * 0.9, "bad": cpu_t}),
            col("cpu_p95_hourly_pct", "CPU P95 (hourly avg)", "pct", desc=FORMULAS["p95_hourly"]), col("cpu_hours_over", "CPU hours over", "int", desc="Hours whose average was at/above the CPU threshold."),
            col("cpu_coverage_pct", "CPU coverage", "pct"),
            col("mem_avg_pct", "Mem avg", "pct"), col("mem_max_pct", "Mem max (hourly)", "pct", cf={"mode": "high", "warn": mem_t * 0.9, "bad": mem_t}),
            col("mem_p95_hourly_pct", "Mem P95 (hourly avg)", "pct", desc=FORMULAS["p95_hourly"]), col("mem_hours_over", "Mem hours over", "int"), col("mem_coverage_pct", "Mem coverage", "pct"),
            col("reboots", "Reboots", "int", desc="Number of hour-to-hour drops of the uptime counter."), col("incidents", "Incidents", "int")]
    clean = [{k: v for k, v in r.items() if k not in ("has_cpu", "has_mem")} for r in rows]
    t_all = table("devices", "Device resource summary", cols, clean, pdf_limit=30)
    t_exc = table("exceptions", "Threshold exceptions", cols, [{k: v for k, v in r.items() if k not in ("has_cpu", "has_mem")} for r in exc], pdf_limit=20)
    top_cpu = sorted([r for r in clean if r["cpu_p95_hourly_pct"] is not None], key=lambda r: -r["cpu_p95_hourly_pct"])[:top_n]
    top_mem = sorted([r for r in clean if r["mem_p95_hourly_pct"] is not None], key=lambda r: -r["mem_p95_hourly_pct"])[:top_n]
    t_tc = table("top_cpu", "Top CPU (P95 of hourly averages)", [col("device", "Device"), col("site", "Site"), col("cpu_p95_hourly_pct", "CPU P95 (hourly avg)", "pct"), col("cpu_max_pct", "CPU max", "pct")], top_cpu)
    t_tm = table("top_mem", "Top memory (P95 of hourly averages)", [col("device", "Device"), col("site", "Site"), col("mem_p95_hourly_pct", "Mem P95 (hourly avg)", "pct"), col("mem_max_pct", "Mem max", "pct")], top_mem)
    doc["findings"] = ["%d of %d device(s) had at least one hour over a configured threshold." % (len(exc), len(rows)) if rows else "No devices in scope.",
                       "%d device(s) expose no CPU item and %d no memory item; they are listed as N/A, not as healthy." % (len(no_cpu), len(no_mem))]
    add_section(doc, "Top resource consumers", [t_tc, t_tm], [chart("c_cpu", "Top CPU - P95 of hourly averages (%)", "hbar", "top_cpu", "device", [{"key": "cpu_p95_hourly_pct", "label": "CPU"}], "%"),
                                                              chart("c_mem", "Top memory - P95 of hourly averages (%)", "hbar", "top_mem", "device", [{"key": "mem_p95_hourly_pct", "label": "Memory"}], "%")])
    add_section(doc, "Threshold exceptions", [t_exc])
    add_section(doc, "All devices", [t_all])
    return _finish(doc, ds, ["p95_hourly", "coverage", "confidence"])


# =========================================================================== 4. Executive Summary (monthly)
def executive_summary(ds, cfg):
    tz = _tz(ds)
    target = float(cfg["suite"]["sla"]["target_percent"])
    hosts = ds["hosts"]
    av = availability_by_host(ds, cfg, ds["items"], ds["incidents"])
    prev_ds = dict(ds, period=ds["previous_period"])
    avp = availability_by_host(prev_ds, cfg, ds["previous_items"], ds["incidents_previous"])
    fl, flp = _fleet(av, hosts), _fleet(avp, hosts)
    cnt, cntp = _incident_counts(ds["incidents"]), _incident_counts(ds["incidents_previous"])
    mttr, mttrp = mttr_seconds(ds["incidents"]), mttr_seconds(ds["incidents_previous"])
    sla_ok = fl["solid_ratio"] is not None and fl["solid_ratio"] >= 0.5 and fl["value"] is not None
    sla_val = fl["value"] if sla_ok else None
    down_total = sum(a["downtime_s"] for a in av.values())
    sites = defaultdict(list)
    for h in hosts:
        sites[h["site"]].append(h["hostid"])
    site_rows = []
    for s in sorted(sites):
        cur, pre = _mean([av[h]["availability_pct"] for h in sites[s]]), _mean([avp[h]["availability_pct"] for h in sites[s]])
        site_rows.append({"site": s, "devices": len(sites[s]), "availability_pct": cur, "previous_pct": pre,
                          "delta_pts": None if cur is None or pre is None else cur - pre,
                          "meets_target": None if cur is None else ("Yes" if cur >= target else "No"),
                          "incidents": len({i["eventid"] for i in ds["incidents"] if s in i["sites"]}),
                          "downtime_s": sum(av[h]["downtime_s"] for h in sites[s]),
                          "confidence": _worst([av[h]["confidence"] for h in sites[s]])})
    sev_rows = []
    for name, num in (("Disaster", 5), ("High", 4), ("Average", 3), ("Warning", 2), ("Information", 1), ("Not classified", 0)):
        a = sum(1 for i in ds["incidents"] if i["severity"] == num)
        b = sum(1 for i in ds["incidents_previous"] if i["severity"] == num)
        if a or b or num >= 4:
            sev_rows.append({"severity": name, "current": a, "previous": b, "delta": a - b})
    worst = sorted([(h["name"], h["site"], av[h["hostid"]]["downtime_s"]) for h in hosts if av[h["hostid"]]["downtime_s"] > 0], key=lambda x: -x[2])[:int(cfg["suite"]["incident"]["top_n"])]
    wan_rows, over = [], []
    th = float(cfg["thresholds"]["interface_utilization_percent"])
    if ds.get("wan_links"):
        for l in ds["wan_links"]:
            r = _link_row(l, ds["interface_items"], ds, cfg, tz)
            wan_rows.append({"isp": r["isp"], "site": r["site"], "device": r["device"], "interface": r["interface"], "capacity_bps": r["capacity_bps"],
                             "peak_util_pct": r["peak_util_pct"], "in_avg_util_pct": r["in_avg_util_pct"], "out_avg_util_pct": r["out_avg_util_pct"]})
        over = [r for r in wan_rows if r["peak_util_pct"] is not None and r["peak_util_pct"] >= th]
    doc = new_doc("executive_summary", "Executive Summary", "Month %s (%s)" % (ds["period"]["label"], ds["period"]["timezone"]), ds, cfg)
    delta = None if fl["value"] is None or flp["value"] is None else fl["value"] - flp["value"]
    doc["kpis"] = [
        kpi("availability_pct", "Availability (fleet)", fl["value"], "%", _status_for(fl["value"], target), note="target %.2f%%; %d of %d devices have a value" % (target, fl["hosts_with_value"], fl["hosts"]), formula="availability"),
        kpi("availability_delta_pts", "Change vs previous month", delta, "pts", "info", note="percentage points; previous %s" % ("N/A" if flp["value"] is None else "%.2f%%" % flp["value"]), decimals=2),
        kpi("sla_status", "Availability vs SLA target", sla_val, "%", _status_for(sla_val, target), note="shown only when at least half the devices have HIGH/MEDIUM confidence", formula="sla"),
        kpi("incidents", "Incidents", cnt["total"], status="info", note="previous month %d" % cntp["total"], formula="incident"),
        kpi("incidents_high", "High / Disaster incidents", cnt["high"], status="bad" if cnt["high"] else "ok", note="previous month %d" % cntp["high"]),
        kpi("incidents_open", "Open at month end", cnt["open"], status="warn" if cnt["open"] else "ok"),
        kpi("mttr_seconds", "Mean time to resolve", mttr, "seconds", "info", note="previous month %s" % ("N/A" if mttrp is None else "%.0f s" % mttrp), formula="mttr"),
        kpi("downtime_total_s", "Total device downtime", down_total, "seconds", "info", formula="downtime"),
        kpi("wan_peak_util_pct", "Highest WAN peak utilization", max([r["peak_util_pct"] for r in wan_rows if r["peak_util_pct"] is not None], default=None), "%", "bad" if over else "info", formula="utilization"),
    ]
    findings = []
    if fl["value"] is None:
        findings.append("Availability could not be computed for any device; no SLA statement is made.")
    else:
        findings.append("Fleet availability was %.2f%% (%s the %.2f%% target)%s." % (fl["value"], "meeting" if fl["value"] >= target else "below", target, "" if delta is None else ", %+.2f points vs previous month" % delta))
    if not sla_ok:
        findings.append("SLA compliance is N/A: fewer than half of the devices have HIGH or MEDIUM confidence availability data.")
    findings.append("%d incident(s), %d High/Disaster; %d still open at month end." % (cnt["total"], cnt["high"], cnt["open"]))
    if worst:
        findings.append("Most downtime: %s (%s)." % (worst[0][0], worst[0][1]))
    if over:
        findings.append("%d WAN link(s) reached %.0f%% peak utilization - review capacity." % (len(over), th))
    doc["findings"] = findings
    t_site = table("site_scorecard", "Site scorecard", [
        col("site", "Site"), col("devices", "Devices", "int"), col("availability_pct", "Availability", "pct", cf={"mode": "low", "warn": target, "bad": target - 0.5}),
        col("previous_pct", "Previous month", "pct"), col("delta_pts", "Change (pts)", "float2"), col("meets_target", "Meets target", "status", cf={"mode": "status"}),
        col("incidents", "Incidents", "int"), col("downtime_s", "Downtime", "seconds"), col("confidence", "Confidence", "status", cf={"mode": "status"})], site_rows)
    t_sev = table("incidents_by_severity", "Incidents by severity", [col("severity", "Severity", "status", cf={"mode": "status"}), col("current", "This month", "int"), col("previous", "Previous month", "int"), col("delta", "Change", "int")], sev_rows)
    t_worst = table("worst_devices", "Devices with most downtime", [col("device", "Device"), col("site", "Site"), col("downtime_s", "Downtime", "seconds")],
                    [{"device": a, "site": b, "downtime_s": c} for a, b, c in worst])
    t_wan = table("wan_summary", "WAN utilization (peaks)", [col("isp", "ISP"), col("site", "Site"), col("device", "Device"), col("interface", "Interface"), col("capacity_bps", "Capacity", "bps"),
                                                            col("peak_util_pct", "Peak util", "pct", cf={"mode": "high", "warn": th * 0.8, "bad": th}), col("in_avg_util_pct", "In avg", "pct"), col("out_avg_util_pct", "Out avg", "pct")],
                  wan_rows, empty_text="No WAN links are declared (suite.json wan.links).")
    add_section(doc, "Site scorecard", [t_site], [chart("c_site", "Availability by site: this vs previous month (%)", "bar", "site_scorecard", "site",
                                                         [{"key": "availability_pct", "label": "This month"}, {"key": "previous_pct", "label": "Previous month"}], "%")])
    add_section(doc, "Incidents", [t_sev, t_worst], [chart("c_sev", "Incidents by severity", "bar", "incidents_by_severity", "severity", [{"key": "current", "label": "This month"}, {"key": "previous", "label": "Previous month"}])])
    add_section(doc, "WAN capacity watch", [t_wan])
    return _finish(doc, ds, ["availability", "sla", "incident", "mttr", "downtime", "utilization", "coverage", "confidence"])


# =========================================================================== 5. Incident Analysis
def incident_analysis(ds, cfg):
    tz = _tz(ds)
    incs = ds["incidents"]
    top_n = int(cfg["suite"]["incident"]["top_n"])
    cnt = _incident_counts(incs)
    acked = sum(1 for i in incs if i["acknowledged"])
    downtime_s = sum(i["duration_in_window_s"] for i in incs if i["is_downtime"])
    doc = new_doc("incident_analysis", "Incident Analysis", "Week %s (%s)" % (ds["period"]["label"], ds["period"]["timezone"]), ds, cfg)
    mt = mttr_seconds(incs)
    doc["kpis"] = [
        kpi("incidents", "Incidents in period", cnt["total"], formula="incident", note="started in or overlapping the period"),
        kpi("incidents_started", "Started in period", cnt["started"], status="warn" if cnt["started"] else "ok"),
        kpi("incidents_resolved", "Resolved in period", cnt["resolved"]),
        kpi("incidents_open", "Open at period end", cnt["open"], status="bad" if cnt["open"] else "ok"),
        kpi("incidents_high", "High / Disaster", cnt["high"], status="bad" if cnt["high"] else "ok"),
        kpi("mttr_seconds", "Mean time to resolve", mt, "seconds", formula="mttr"),
        kpi("ack_rate_pct", "Acknowledged", _pct(acked, len(incs)), "%", "info", note="%d of %d" % (acked, len(incs))),
        kpi("downtime_total_s", "Downtime-class impact", downtime_s, "seconds", formula="downtime", note="sum over incidents (not merged across devices)"),
    ]
    by_sev = Counter(i["severity_name"] for i in incs)
    sev_rows = [{"severity": n, "incidents": by_sev.get(n, 0)} for n in ("Disaster", "High", "Average", "Warning", "Information", "Not classified") if by_sev.get(n)]
    by_site = Counter(s for i in incs for s in i["sites"])
    site_rows = [{"site": s, "incidents": n} for s, n in sorted(by_site.items(), key=lambda x: (-x[1], x[0]))]
    by_host = Counter(h for i in incs for h in i["host_names"])
    host_rows = [{"device": h, "incidents": n} for h, n in sorted(by_host.items(), key=lambda x: (-x[1], x[0]))[:top_n]]
    by_name = Counter(i["name"] for i in incs)
    rec_rows = [{"problem": n, "incidents": c} for n, c in sorted(by_name.items(), key=lambda x: (-x[1], x[0])) if c >= 2][:top_n]
    day = Counter()
    day_rows = []
    for i in incs:
        if i["started_in_window"]:
            day[datetime.fromtimestamp(i["start"], tz).date().isoformat()] += 1
    start = datetime.fromtimestamp(ds["period"]["start_ts"], tz).date()
    end = datetime.fromtimestamp(ds["period"]["end_ts"], tz).date()
    d = start
    while d < end:
        day_rows.append({"day": d.isoformat(), "started": day.get(d.isoformat(), 0)})
        d += timedelta(days=1)
    longest = sorted([i for i in incs if i["duration_in_window_s"]], key=lambda i: -i["duration_in_window_s"])[:top_n]
    t_log = table("incident_log", "Incident log", INCIDENT_COLS, _incident_rows(incs, tz), pdf_limit=40)
    t_sev = table("by_severity", "By severity", [col("severity", "Severity", "status", cf={"mode": "status"}), col("incidents", "Incidents", "int")], sev_rows)
    t_site = table("by_site", "By site", [col("site", "Site"), col("incidents", "Incidents", "int")], site_rows)
    t_host = table("by_device", "Most affected devices", [col("device", "Device"), col("incidents", "Incidents", "int")], host_rows)
    t_rec = table("recurring", "Recurring problems (2 or more)", [col("problem", "Problem"), col("incidents", "Incidents", "int")], rec_rows)
    t_day = table("by_day", "Incidents started per day", [col("day", "Day"), col("started", "Started", "int")], day_rows)
    t_long = table("longest", "Longest incidents (in period)", INCIDENT_COLS, _incident_rows(longest, tz, keep_order=True), pdf_limit=10)
    doc["findings"] = ["%d incident(s) overlapped the period; %d are still open." % (cnt["total"], cnt["open"]),
                       ("Most frequent problem: %s (%d)." % (rec_rows[0]["problem"], rec_rows[0]["incidents"])) if rec_rows else "No problem recurred more than once."]
    add_section(doc, "Overview", [t_sev, t_site], [chart("c_sev", "Incidents by severity", "bar", "by_severity", "severity", [{"key": "incidents", "label": "Incidents"}]),
                                                     chart("c_day", "Incidents started per day", "bar", "by_day", "day", [{"key": "started", "label": "Started"}])])
    add_section(doc, "Trend by day", [t_day])
    add_section(doc, "Most affected devices", [t_host])
    add_section(doc, "Recurring problems", [t_rec])
    add_section(doc, "Longest incidents", [t_long])
    add_section(doc, "Incident log", [t_log])
    return _finish(doc, ds, ["incident", "mttr", "downtime"])


# =========================================================================== 6. Monitoring Quality
def monitoring_quality(ds, cfg):
    hosts = ds["hosts"]
    stale_s = int(cfg["thresholds"]["stale_data_minutes"]) * 60
    now = _gen_ts(ds)
    by_host = defaultdict(dict)
    for it in ds["items"]:
        cur = by_host[it["hostid"]].get(it["kind"])
        if cur is None or ((it.get("stats") or {}).get("samples") or 0) > ((cur.get("stats") or {}).get("samples") or 0):
            by_host[it["hostid"]][it["kind"]] = it
    unsupported = Counter(u["hostid"] for u in ds["unsupported_items"])
    rows = []
    for h in hosts:
        k = by_host.get(h["hostid"], {})
        cov = lambda kind: None if kind not in k or not k[kind].get("stats") or k[kind]["stats"]["coverage"] is None else k[kind]["stats"]["coverage"] * 100.0
        icmp = k.get("icmp_ping")
        issues = []
        if h["state_now"] != "UP":
            issues.append("state " + h["state_now"])
        if h["interface_errors"]:
            issues.append("interface error")
        if not icmp:
            issues.append("no ICMP item")
        elif icmp["lastclock"] == 0 or now - icmp["lastclock"] > stale_s:
            issues.append("stale ICMP")
        if h["site"] == "Unassigned":
            issues.append("no site")
        if unsupported.get(h["hostid"]):
            issues.append("%d unsupported item(s)" % unsupported[h["hostid"]])
        if "cpu" not in k:
            issues.append("no CPU item")
        if "memory" not in k:
            issues.append("no memory item")
        covs = [c for c in (cov("icmp_ping"), cov("cpu"), cov("memory")) if c is not None]
        rows.append({"device": h["name"], "site": h["site"], "state_now": h["state_now"], "icmp_coverage_pct": cov("icmp_ping"),
                     "cpu_coverage_pct": cov("cpu"), "memory_coverage_pct": cov("memory"), "unsupported_items": unsupported.get(h["hostid"], 0),
                     "confidence": confidence(min(covs) / 100.0) if covs else "NONE", "issues": "; ".join(issues)})
    rows.sort(key=lambda r: (not r["issues"], r["device"].lower()))
    with_issues = [r for r in rows if r["issues"]]
    n = ds["audit"]["notes"]
    diag = [{"area": "API truncation", "count": len(n["truncated"]), "detail": "; ".join(t["what"] for t in n["truncated"])[:300]},
            {"area": "Failed API requests", "count": len(n["failed"]), "detail": "; ".join(f["what"] for f in n["failed"])[:300]},
            {"area": "Collector warnings", "count": len(set(n["warnings"])), "detail": "; ".join(sorted(set(n["warnings"])))[:300]},
            {"area": "Declared WAN links not found", "count": len(ds.get("wan_unresolved", [])), "detail": "; ".join("%s %s" % (u["host"], u["interface"]) for u in ds.get("wan_unresolved", []))[:300]},
            {"area": "Devices without a site", "count": sum(1 for h in hosts if h["site"] == "Unassigned"), "detail": ""}]
    doc = new_doc("monitoring_quality", "Monitoring Quality", "Week %s (%s)" % (ds["period"]["label"], ds["period"]["timezone"]), ds, cfg)
    solid = sum(1 for r in rows if r["confidence"] in ("HIGH",))
    doc["kpis"] = [
        kpi("devices", "Devices in scope", len(hosts)),
        kpi("devices_with_issues", "Devices with data issues", len(with_issues), status="warn" if with_issues else "ok"),
        kpi("devices_high_confidence", "Devices with HIGH confidence", solid, status="info", note="min coverage of ICMP/CPU/memory >= 95%", formula="confidence"),
        kpi("unsupported_items", "Unsupported items", len(ds["unsupported_items"]), status="warn" if ds["unsupported_items"] else "ok"),
        kpi("devices_down_or_unknown", "Devices down / unknown now", sum(1 for h in hosts if h["state_now"] != "UP"), status="warn"),
        kpi("api_truncations", "API truncations", len(n["truncated"]), status="bad" if n["truncated"] else "ok"),
        kpi("api_failures", "Failed API requests", len(n["failed"]), status="bad" if n["failed"] else "ok"),
        kpi("links_unresolved", "Declared WAN links not found", len(ds.get("wan_unresolved", [])), status="warn" if ds.get("wan_unresolved") else "ok"),
    ]
    t_dev = table("device_quality", "Device data quality", [
        col("device", "Device"), col("site", "Site"), col("state_now", "State now", "status", cf={"mode": "status"}),
        col("icmp_coverage_pct", "ICMP coverage", "pct", cf={"mode": "low", "warn": 95, "bad": 80}, desc=FORMULAS["coverage"]),
        col("cpu_coverage_pct", "CPU coverage", "pct", cf={"mode": "low", "warn": 95, "bad": 80}), col("memory_coverage_pct", "Memory coverage", "pct", cf={"mode": "low", "warn": 95, "bad": 80}),
        col("unsupported_items", "Unsupported items", "int"), col("confidence", "Confidence", "status", cf={"mode": "status"}), col("issues", "Issues")], rows, pdf_limit=35)
    t_uns = table("unsupported", "Unsupported items", [col("device", "Device"), col("item", "Item"), col("key", "Key"), col("error", "Error")],
                  [{"device": next((h["name"] for h in hosts if h["hostid"] == u["hostid"]), u["hostid"]), "item": u["name"], "key": u["key"], "error": u["error"]} for u in ds["unsupported_items"]],
                  pdf_limit=25, empty_text="No unsupported items.")
    t_diag = table("collector", "Collector diagnostics", [col("area", "Area"), col("count", "Count", "int", cf={"mode": "high", "warn": 1, "bad": 1}), col("detail", "Detail")], diag, pdf_limit=10)
    doc["findings"] = ["%d of %d device(s) have at least one data-quality issue." % (len(with_issues), len(hosts)),
                       "Collector reported %d truncation(s) and %d failed request(s)." % (len(n["truncated"]), len(n["failed"]))]
    add_section(doc, "Collector diagnostics", [t_diag])
    add_section(doc, "Device data quality", [t_dev], [chart("c_icmp", "ICMP sample coverage by device (%)", "hbar", "device_quality", "device", [{"key": "icmp_coverage_pct", "label": "ICMP coverage"}], "%", max_items=15)])
    add_section(doc, "Unsupported items", [t_uns])
    return _finish(doc, ds, ["coverage", "confidence", "stale"])


BUILDERS = {"daily_network_health": daily_network_health, "wan_isp_performance": wan_isp_performance,
            "infrastructure_health": infrastructure_health, "executive_summary": executive_summary,
            "incident_analysis": incident_analysis, "monitoring_quality": monitoring_quality}


def build(ds, cfg):
    return BUILDERS[ds["report"]](ds, cfg)
