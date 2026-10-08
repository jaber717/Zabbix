"""What each report collects. Only the item kinds a report needs are requested, only for the hosts
and interfaces in scope."""
from __future__ import annotations

from .apiclient import get_chunked
from .collector import Collector, UP_KINDS
from .periods import preceding

REPORTS = {
    "daily_network_health": {"kind": "daily", "title": "Daily Network Health", "slug": "daily-network-health"},
    "wan_isp_performance": {"kind": "weekly", "title": "WAN & ISP Performance", "slug": "wan-isp-performance"},
    "infrastructure_health": {"kind": "weekly", "title": "Infrastructure Health", "slug": "infrastructure-health"},
    "executive_summary": {"kind": "monthly", "title": "Executive Summary", "slug": "executive-summary"},
    "incident_analysis": {"kind": "weekly", "title": "Incident Analysis", "slug": "incident-analysis"},
    "monitoring_quality": {"kind": "weekly", "title": "Monitoring Quality", "slug": "monitoring-quality"},
}
ALIASES = {"daily": "daily_network_health", "wan": "wan_isp_performance", "infra": "infrastructure_health",
           "executive": "executive_summary", "exec": "executive_summary", "incident": "incident_analysis",
           "incidents": "incident_analysis", "quality": "monitoring_quality"}


def resolve(name):
    name = name.strip().lower().replace("-", "_")
    name = ALIASES.get(name, name)
    if name not in REPORTS:
        raise ValueError("unknown report %r (choose from: %s)" % (name, ", ".join(sorted(REPORTS))))
    return name


def _avail_mode(period):
    return lambda it: ("history" if period.kind == "daily" else "trend") if it["kind"] == "icmp_ping" else "trend"


def _links(c):
    """Declared WAN links resolved to hosts; unresolved links are reported, never guessed."""
    by_name = {h["host"]: h for h in c.hosts.values()}
    by_name.update({h["name"]: h for h in c.hosts.values()})
    out, missing = [], []
    for link in c.cfg["suite"]["wan"]["links"]:
        h = by_name.get(link["host"])
        if not h:
            missing.append({"host": link["host"], "interface": link["interface"], "reason": "host not found in scope"})
            continue
        out.append(dict(link, hostid=h["hostid"], host_name=h["name"], site=link.get("site") or h["site"]))
    return out, missing


def _wan(c, period, light=False):
    links, missing = _links(c)
    ifaces = defaultdict_set()
    for l in links:
        ifaces[l["hostid"]].add(l["interface"])
    if_items = []
    for hostid, names in ifaces.items():
        kinds = {"if_in", "if_out", "if_speed"} if light else {"if_in", "if_out", "if_status", "if_speed", "if_in_err", "if_out_err", "if_in_disc", "if_out_disc"}
        if_items.extend(c.find_items(kinds, [hostid], tags_interface=names))
    link_hosts = sorted(ifaces)
    path_items = [] if light else c.find_items({"icmp_rtt", "icmp_loss"}, link_hosts)
    use_hist = period.kind == "daily"
    mode = lambda it: "history" if (it["kind"] == "if_status" or use_hist) else "trend"
    c.attach_stats(if_items, period, mode, p95_raw_kinds=("if_in", "if_out") if use_hist else ())
    c.attach_stats(path_items, period, lambda it: "history" if use_hist else "trend")
    # a declared interface that matched no item is listed, not invented
    found = {(i["hostid"], i["interface"]) for i in if_items}
    for l in links:
        if (l["hostid"], l["interface"]) not in found:
            missing.append({"host": l["host"], "interface": l["interface"], "reason": "no interface items found (tag 'interface')"})
    return {"wan_links": links, "wan_unresolved": missing, "interface_items": if_items, "path_items": path_items}


def defaultdict_set():
    from collections import defaultdict
    return defaultdict(set)


def collect(api, cfg, now, report_key, period, week_start=0):
    c = Collector(api, cfg, now)
    c.load_hosts()
    hostids = sorted(c.hosts)
    extra = {}
    if report_key == "daily_network_health":
        items = c.find_items({"icmp_ping"}, hostids)
        c.attach_stats(items, period, _avail_mode(period))
        incidents, q = c.load_incidents(period, hostids)
        extra.update(items=items, incidents=incidents, incident_quality=q, open_problems=_slim(c.open_problems()))
    elif report_key == "wan_isp_performance":
        extra.update(_wan(c, period))
        incidents, q = c.load_incidents(period, sorted({l["hostid"] for l in extra["wan_links"]}))
        extra.update(incidents=incidents, incident_quality=q)
    elif report_key == "infrastructure_health":
        gh = set(cfg["suite"]["infra"].get("host_groups", []))
        ids = [h for h in hostids if not gh or gh & set(c.hosts[h]["groups"])]
        items = c.find_items({"cpu", "memory", "uptime"}, ids)
        c.attach_stats(items, period, lambda it: "trend",
                       thresholds={"cpu": float(cfg["thresholds"]["cpu_percent"]), "memory": float(cfg["thresholds"]["memory_percent"])})
        incidents, q = c.load_incidents(period, ids)
        extra.update(items=items, incidents=incidents, incident_quality=q, infra_hostids=ids)
    elif report_key == "incident_analysis":
        incidents, q = c.load_incidents(period, hostids)
        extra.update(incidents=incidents, incident_quality=q, open_problems=_slim(c.open_problems()))
    elif report_key == "monitoring_quality":
        items = c.find_items({"icmp_ping", "cpu", "memory"}, hostids)
        c.attach_stats(items, period, lambda it: "trend")
        bad = get_chunked(api, c.notes, "item.get", {"output": ["itemid", "hostid", "name", "key_", "error"],
                          "filter": {"state": 1, "status": 0}, "monitored": True}, "hostids", hostids,
                          int(c.lim.get("hosts_per_request", 100)), int(c.lim["items"]), "item.get unsupported")
        links, missing = _links(c)
        extra.update(items=items, unsupported_items=[dict(itemid=str(b["itemid"]), hostid=str(b["hostid"]), name=b["name"],
                                                          key=b["key_"], error=b.get("error", "")) for b in bad],
                     wan_links=links, wan_unresolved=missing)
    elif report_key == "executive_summary":
        prev = preceding(period, week_start)
        items = c.find_items({"icmp_ping"}, hostids)
        c.attach_stats(items, period, lambda it: "trend")
        prev_items = [dict(i) for i in items]
        c.attach_stats(prev_items, prev, lambda it: "trend")
        incidents, q = c.load_incidents(period, hostids)
        incidents_prev, _ = c.load_incidents(prev, hostids)
        extra.update(items=items, previous_items=prev_items, incidents=incidents, incidents_previous=incidents_prev,
                     incident_quality=q, previous_period=prev, open_problems=_slim(c.open_problems()))
        if cfg["suite"]["wan"]["links"]:
            extra.update(_wan(c, period, light=True))
    else:
        raise ValueError(report_key)
    return c.finish(report_key, period, extra)


def _slim(rows):
    return [{"eventid": str(r["eventid"]), "clock": int(r["clock"]), "name": r["name"], "severity": int(r["severity"]),
             "acknowledged": str(r.get("acknowledged", "0")) == "1",
             "hostids": [str(h["hostid"]) for h in r.get("hosts", [])],
             "hosts": sorted(h.get("name", "") for h in r.get("hosts", []))} for r in rows]
