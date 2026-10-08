"""Targeted, batched collection into one normalized dataset (the single source for PDF, XLSX and JSON)."""
from __future__ import annotations

import re
from collections import defaultdict

from . import DATASET_SCHEMA, SUITE_VERSION
from .apiclient import Notes, fetch_time_split, get_chunked, get_limited
from .incidents import build_incidents
from .metrics import Agg, fetch_history, fetch_trends
from .periods import preceding
from .util import canonical_json, parse_delay, sha256_text, to_float

# metric kind -> (exact key or key prefix list, name fragments). Matching is done client-side on `key_`.
KEY_RULES = {
    "icmp_ping": (("icmpping",), ()),
    "icmp_rtt": (("icmppingsec",), ()),
    "icmp_loss": (("icmppingloss",), ()),
    "cpu": (("system.cpu.util",), ("cpu utilization",)),
    "memory": (("vm.memory.util",), ("memory utilization",)),
    "uptime": (("system.uptime", "system.net.uptime", "sysuptime"), ()),
    "if_in": (("net.if.in[",), ()),
    "if_out": (("net.if.out[",), ()),
    "if_status": (("net.if.status[",), ()),
    "if_speed": (("net.if.speed[",), ()),
    "if_in_err": (("net.if.in.errors[",), ()),
    "if_out_err": (("net.if.out.errors[",), ()),
    "if_in_disc": (("net.if.in.discards[",), ()),
    "if_out_disc": (("net.if.out.discards[",), ()),
}
UP_KINDS = ("icmp_ping", "if_status")          # items whose value 1 means "up"


def classify(item):
    key = (item.get("key_") or "").lower()
    name = (item.get("name") or "").lower()
    for kind, (keys, names) in KEY_RULES.items():
        for k in keys:
            if (k.endswith("[") and key.startswith(k)) or (not k.endswith("[") and (key == k or key.startswith(k + "["))):
                return kind
        if any(n in name for n in names) and kind in ("cpu", "memory"):
            return kind
    return None


def key_search_terms(kinds):
    keys, names = [], []
    for k in kinds:
        keys.extend(x for x in KEY_RULES[k][0])
        names.extend(KEY_RULES[k][1])
    return keys, names


def interface_name(item):
    for t in item.get("tags", []) or []:
        if t.get("tag") == "interface" and t.get("value"):
            return t["value"]
    m = re.match(r"\s*Interface\s+(\S+?):", item.get("name", ""))
    return m.group(1) if m else None


def site_of(host, cfg):
    tag = cfg["scope"].get("site_tag", "site").lower()
    for row in host.get("tags", []) or []:
        if row.get("tag", "").lower() == tag and row.get("value", "").strip():
            return row["value"].strip()
    groups = [g["name"] for g in host.get("hostgroups", []) or [] if g.get("name") != "Discovered hosts"]
    return groups[0] if groups else "Unassigned"


def host_state(host):
    states = {str(i.get("available", "0")) for i in host.get("interfaces", []) or []}
    if "2" in states:
        return "DOWN"
    if "1" in states:
        return "UP"
    return "UNKNOWN"


def in_scope(host, cfg):
    groups = {g["name"] for g in host.get("hostgroups", []) or []}
    inc, exc = set(cfg["scope"].get("include_host_groups", [])), set(cfg["scope"].get("exclude_host_groups", []))
    if exc & groups or (inc and not inc & groups):
        return False
    sites = set(cfg["scope"].get("sites", []))
    return not sites or site_of(host, cfg) in sites


class Collector(object):
    def __init__(self, api, cfg, now):
        self.api, self.cfg, self.now = api, cfg, now
        self.now_ts = int(now.timestamp())
        self.notes = Notes()
        self.lim = cfg["suite"]["limits"]
        self.hosts = {}

    # ---------------------------------------------------------------- hosts
    def load_hosts(self):
        z = self.cfg["zabbix"]
        rows = get_limited(self.api, self.notes, "host.get", {
            "output": ["hostid", "host", "name"], "selectInterfaces": ["available", "type", "error"],
            "selectTags": ["tag", "value"], "selectHostGroups": ["groupid", "name"], "monitored_hosts": True},
            int(z["maximum_hosts"]), "host.get")
        for h in rows:
            h = dict(h, hostid=str(h["hostid"]))
            if in_scope(h, self.cfg):
                self.hosts[h["hostid"]] = {
                    "hostid": h["hostid"], "host": h["host"], "name": h["name"], "site": site_of(h, self.cfg),
                    "state_now": host_state(h), "groups": sorted(g["name"] for g in h.get("hostgroups", [])),
                    "interface_errors": sorted({i.get("error", "") for i in h.get("interfaces", []) if i.get("error")})}
        return self.hosts

    # ---------------------------------------------------------------- items
    def find_items(self, kinds, hostids, tags_interface=None):
        """Targeted item.get: only the keys of the requested kinds, only the given hosts, chunked."""
        if not hostids:
            return []
        keys, names = key_search_terms(kinds)
        base = {"output": ["itemid", "hostid", "name", "key_", "units", "value_type", "delay", "state", "status",
                           "lastclock", "error", "trends"],
                "selectTags": ["tag", "value"], "monitored": True,
                "search": {"key_": keys, "name": names} if names else {"key_": keys}, "searchByAny": True}
        if tags_interface:
            base["tags"] = [{"tag": "interface", "value": v, "operator": 1} for v in sorted(tags_interface)]
            base["evaltype"] = 2
            base["search"] = {"key_": keys}
        size = int(self.lim.get("hosts_per_request", 100))
        rows = get_chunked(self.api, self.notes, "item.get", base, "hostids", sorted(hostids), size,
                           int(self.lim["items"]), "item.get[%s]" % ",".join(sorted(kinds)))
        out, seen = [], set()
        for r in rows:
            kind = classify(r)
            if kind not in kinds or str(r["itemid"]) in seen:
                continue
            seen.add(str(r["itemid"]))
            out.append({
                "itemid": str(r["itemid"]), "hostid": str(r["hostid"]), "kind": kind, "key": r["key_"],
                "name": r.get("name", ""), "units": r.get("units", ""), "value_type": str(r.get("value_type", "0")),
                "delay": r.get("delay", ""), "state": str(r.get("state", "0")), "status": str(r.get("status", "0")),
                "lastclock": int(r.get("lastclock") or 0), "error": r.get("error", ""),
                "trends_days": str(r.get("trends", "")), "interface": interface_name(r)})
        return out

    def attach_stats(self, items, period, mode, p95_raw_kinds=(), thresholds=None):
        """mode 'history' (raw samples) or 'trend' (hourly) per item kind via `mode(kind)`; fills item['stats']."""
        aggs, hist, trend = {}, defaultdict(list), []
        raw_budget = int(self.lim.get("history_p95_max_items", 200))
        for it in items:
            m = mode(it)
            if m == "history":
                aggs[it["itemid"]] = Agg(keep_values=(it["kind"] in p95_raw_kinds and raw_budget > 0))
                raw_budget -= 1 if it["kind"] in p95_raw_kinds else 0
                hist[int(it["value_type"]) if it["value_type"] in ("0", "3") else 0].append(it["itemid"])
            elif m == "trend":
                aggs[it["itemid"]] = Agg(tz=period.tz, threshold=(thresholds or {}).get(it["kind"]))
                trend.append(it["itemid"])
        fetch_trends(self.api, self.notes, trend, period.start_ts, period.end_ts, aggs,
                     chunk=int(self.lim.get("trend_items_per_request", 50)), limit=int(self.lim["trend_rows"]))
        fetch_history(self.api, self.notes, hist, period.start_ts, period.end_ts, aggs,
                      chunk=int(self.lim.get("history_items_per_request", 20)), limit=int(self.lim["history_rows"]))
        for it in items:
            a = aggs.get(it["itemid"])
            it["stats"] = a.stats(period.seconds, it["delay"]) if a is not None else None
            if it["stats"] is not None and it["trends_days"] == "0" and mode(it) == "trend":
                self.notes.warnings.append("item %s (%s) has trends disabled; no trend statistics exist" % (it["itemid"], it["key"]))
        return items

    # ---------------------------------------------------------------- incidents
    def load_incidents(self, period, hostids):
        z, lookback = self.cfg["zabbix"], int(self.cfg["suite"]["incident"]["lookback_days"])
        limit = int(z["maximum_problems"])
        if not hostids:
            return [], {"duplicate_events_removed": 0, "recovery_time_unknown": 0}
        ids = sorted(hostids)
        events = []
        for part in [ids[i:i + 200] for i in range(0, len(ids), 200)]:
            events.extend(fetch_time_split(
                self.api, self.notes, "event.get",
                {"output": ["eventid", "clock", "name", "severity", "acknowledged", "r_eventid"], "source": 0,
                 "object": 0, "value": 1, "hostids": part, "selectHosts": ["hostid", "name"],
                 "sortfield": ["clock", "eventid"], "sortorder": "ASC"},
                period.start_ts - lookback * 86400, period.end_ts, limit, "event.get problems", "eventid"))
        # still-open problems of ANY age
        current = get_limited(self.api, self.notes, "problem.get",
                              {"output": ["eventid", "clock", "name", "severity", "acknowledged", "r_eventid"],
                               "hostids": ids, "suppressed": None, "symptom": False,
                               "selectHosts": ["hostid", "name"]}, limit, "problem.get open")
        known = {str(e["eventid"]) for e in events}
        for p in current:
            if str(p["eventid"]) not in known:
                p = dict(p)
                p.setdefault("hosts", [])
                events.append(p)
        # problem.get has no host list on all builds: fill missing hosts through event.get by id
        missing = [str(e["eventid"]) for e in events if not e.get("hosts")]
        for part in [missing[i:i + 200] for i in range(0, len(missing), 200)]:
            if part:
                fill = {str(r["eventid"]): r for r in self.api.call(
                    "event.get", {"output": ["eventid"], "eventids": part, "selectHosts": ["hostid", "name"]})}
                for e in events:
                    if str(e["eventid"]) in fill:
                        e["hosts"] = fill[str(e["eventid"])].get("hosts", [])
        events = [e for e in events if any(str(h["hostid"]) in self.hosts for h in e.get("hosts", []))]
        r_ids = sorted({str(e["r_eventid"]) for e in events if str(e.get("r_eventid") or "0") != "0"})
        recoveries = {}
        for part in [r_ids[i:i + 200] for i in range(0, len(r_ids), 200)]:
            for r in self.api.call("event.get", {"output": ["eventid", "clock"], "eventids": part}):
                recoveries[str(r["eventid"])] = int(r["clock"])
        host_site = {h["hostid"]: h["site"] for h in self.hosts.values()}
        patterns = self.cfg["classification"]["downtime_problem_patterns"]
        return build_incidents(events, recoveries, period, self.now_ts, patterns, host_site)

    def open_problems(self):
        z = self.cfg["zabbix"]
        ids = sorted(self.hosts)
        rows = []
        for part in [ids[i:i + 200] for i in range(0, len(ids), 200)]:
            rows.extend(get_limited(self.api, self.notes, "problem.get",
                                    {"output": ["eventid", "clock", "name", "severity", "acknowledged"], "hostids": part,
                                     "suppressed": None, "symptom": False, "selectHosts": ["hostid", "name"]},
                                    int(z["maximum_problems"]), "problem.get current"))
        return rows

    # ---------------------------------------------------------------- dataset
    def finish(self, report_key, period, extra):
        previous = extra.pop("previous_period", None)
        ds = {"schema": DATASET_SCHEMA, "collector_version": SUITE_VERSION, "report": report_key,
              "period": period.to_dict(), "previous_period": previous.to_dict() if previous else None}
        ds.update(extra)
        ds["hosts"] = [self.hosts[k] for k in sorted(self.hosts, key=lambda x: self.hosts[x]["name"].lower())]
        ds["dataset_sha256"] = sha256_text(canonical_json(ds))   # content only: audit counters and the clock are excluded
        ds["audit"] = {"notes": self.notes.to_dict(), "api_calls": self.api.serial,
                       "api_by_method": dict(sorted(getattr(self.api, "stats", {}).items())),
                       "source_api": self.cfg["zabbix"]["api_url"].split("/api_jsonrpc.php")[0],
                       "scope": {"sites": self.cfg["scope"].get("sites", []),
                                 "include_host_groups": self.cfg["scope"].get("include_host_groups", []),
                                 "exclude_host_groups": self.cfg["scope"].get("exclude_host_groups", [])},
                       "limits": self.lim}
        ds["generated_at"] = self.now.isoformat()      # excluded from the hash on purpose (idempotent reruns)
        return ds
