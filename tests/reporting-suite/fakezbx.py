"""Deterministic in-memory Zabbix 7.0 API for the reporting-suite tests.

It honours the semantics the collector depends on: `limit` (so truncation is real), half-open-friendly
inclusive `time_till`, hostids/itemids filters, key/name `search` with searchByAny, item tag filters, value types
for history.get, trend rows per hour, event/problem relations (r_eventid) and injectable failures.
"""
from __future__ import annotations

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Riyadh")


def ts(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp())


class FakeApi(object):
    """Quacks like zrs.apiclient.ApiClient."""

    def __init__(self):
        self.serial = 0
        self.stats = {}
        self.hosts = {}
        self.items = {}
        self.history = {}      # itemid -> [(clock, value)]
        self.trends = {}       # itemid -> [(clock, num, min, avg, max)]
        self.events = {}       # eventid -> dict(eventid, clock, name, severity, acknowledged, r_eventid, hostids)
        self.recovery = {}     # recovery eventid -> clock
        self.fail = {}         # method -> number of upcoming calls that raise
        self.calls = []        # (method, params)
        self.token = "x"

    # ---- ApiClient surface
    def authenticate(self):
        return None

    def version(self):
        return "7.0.30"

    def call(self, method, params, auth=True):
        self.serial += 1
        self.stats[method] = self.stats.get(method, 0) + 1
        self.calls.append((method, copy.deepcopy(params)))
        if self.fail.get(method, 0) > 0:
            self.fail[method] -= 1
            raise RuntimeError("%s: simulated failure" % method)
        return getattr(self, "m_" + method.replace(".", "_"))(params)

    # ---- world building
    def add_host(self, hostid, name, site, available="1", groups=("Routers",), tags=None):
        self.hosts[hostid] = {"hostid": hostid, "host": name, "name": name, "interfaces": [{"available": available, "type": "2", "error": ""}],
                              "tags": tags if tags is not None else [{"tag": "site", "value": site}],
                              "hostgroups": [{"groupid": "1", "name": g} for g in groups]}

    def add_item(self, itemid, hostid, key, name, value_type="0", delay="1m", state="0", lastclock=0, tags=None, trends="365d", error=""):
        self.items[itemid] = {"itemid": itemid, "hostid": hostid, "key_": key, "name": name, "units": "", "value_type": value_type,
                              "delay": delay, "state": state, "status": "0", "lastclock": str(lastclock), "error": error,
                              "trends": trends, "tags": tags or []}

    def add_event(self, eventid, hostids, name, severity, start, end=None, ack="0", r_eventid=None):
        r = "0"
        if end is not None:
            r = r_eventid or "9%s" % eventid
            self.recovery[r] = end
        elif r_eventid:
            r = r_eventid                  # recovered but recovery event unknown to event.get
        self.events[str(eventid)] = {"eventid": str(eventid), "clock": str(start), "name": name, "severity": str(severity),
                                     "acknowledged": ack, "r_eventid": r, "hostids": [str(h) for h in hostids]}

    # ---- helpers
    @staticmethod
    def _limit(rows, params):
        lim = params.get("limit")
        return rows[:lim] if lim else rows

    def _hosts_of(self, hostids):
        return [{"hostid": h, "name": self.hosts[h]["name"]} for h in hostids if h in self.hosts]

    # ---- API methods
    def m_host_get(self, p):
        return self._limit([copy.deepcopy(h) for h in self.hosts.values()], p)

    def m_item_get(self, p):
        rows = []
        for it in self.items.values():
            if p.get("hostids") and it["hostid"] not in p["hostids"]:
                continue
            f = p.get("filter") or {}
            if "state" in f and str(it["state"]) != str(f["state"]):
                continue
            s = p.get("search") or {}
            if s:
                hit = False
                for field, pats in s.items():
                    pats = pats if isinstance(pats, list) else [pats]
                    val = it["key_" if field == "key_" else "name"].lower()
                    hit = hit or any(x.lower() in val for x in pats)
                if not hit:
                    continue
            if p.get("tags"):
                want = [(t["tag"], t["value"]) for t in p["tags"]]
                have = [(t["tag"], t["value"]) for t in it["tags"]]
                if not any(w in have for w in want):
                    continue
            rows.append(copy.deepcopy(it))
        return self._limit(rows, p)

    def m_trend_get(self, p):
        rows = []
        for iid in p["itemids"]:
            for clock, num, vmin, vavg, vmax in self.trends.get(str(iid), []):
                if p["time_from"] <= clock <= p["time_till"]:
                    rows.append({"itemid": str(iid), "clock": str(clock), "num": str(num), "value_min": str(vmin), "value_avg": str(vavg), "value_max": str(vmax)})
        return self._limit(rows, p)

    def m_history_get(self, p):
        rows = []
        for iid in p["itemids"]:
            if str(self.items[str(iid)]["value_type"]) != str(p["history"]):
                continue
            for clock, value in self.history.get(str(iid), []):
                if p["time_from"] <= clock <= p["time_till"]:
                    rows.append({"itemid": str(iid), "clock": str(clock), "value": str(value)})
        rows.sort(key=lambda r: int(r["clock"]))
        return self._limit(rows, p)

    def _event_rows(self, evs, p):
        out = []
        for e in evs:
            row = {"eventid": e["eventid"], "clock": e["clock"], "name": e["name"], "severity": e["severity"],
                   "acknowledged": e["acknowledged"], "r_eventid": e["r_eventid"]}
            if p.get("selectHosts"):
                row["hosts"] = self._hosts_of(e["hostids"])
            out.append(row)
        return out

    def m_event_get(self, p):
        if p.get("eventids"):
            rows = []
            for eid in p["eventids"]:
                if eid in self.recovery:
                    rows.append({"eventid": eid, "clock": str(self.recovery[eid])})
                elif eid in self.events:
                    rows += self._event_rows([self.events[eid]], p)
            return rows
        evs = [e for e in self.events.values()
               if (not p.get("hostids") or set(e["hostids"]) & set(p["hostids"]))
               and p["time_from"] <= int(e["clock"]) <= p["time_till"]]
        evs.sort(key=lambda e: (int(e["clock"]), int(e["eventid"])))
        return self._limit(self._event_rows(evs, p), p)

    def m_problem_get(self, p):
        if "selectHosts" in p:
            raise RuntimeError("problem.get: Invalid parameter \"/\": unexpected parameter \"selectHosts\".")     # like Zabbix 7.0
        evs = [e for e in self.events.values() if e["r_eventid"] == "0" and (not p.get("hostids") or set(e["hostids"]) & set(p["hostids"]))]
        evs.sort(key=lambda e: int(e["clock"]))
        return self._limit(self._event_rows(evs, p), p)


# ----------------------------------------------------------------------------- the standard world
def hourly_trend(start, end, fn, num=60):
    """Trend rows for each full hour in [start, end)."""
    rows, t = [], start
    while t < end:
        vmin, vavg, vmax = fn(t)
        rows.append((t, num, vmin, vavg, vmax))
        t += 3600
    return rows


def standard_world():
    """Riyadh (UTC+3, no DST). 'Now' for the tests is 2026-10-08 07:00 +03.

    Daily period: 2026-10-07.  Weekly: 2026-10-08 is a Thursday, so the last COMPLETE ISO week is 2026-W40
    (Mon 2026-09-28 .. Mon 2026-10-05, end exclusive). Monthly: 2026-09.
    """
    w = FakeApi()
    w.add_host("1", "RTR-HQ", "HQ")
    w.add_host("2", "RTR-BR1", "BR1")
    w.add_host("3", "FW-HQ", "HQ", groups=("Firewalls",))
    w.add_host("4", "SW-BR1", "BR1", groups=("Switches",))                    # no ICMP item at all
    w.add_host("5", "DEAD-BR1", "BR1", available="2")                         # down now
    now = ts(2026, 10, 8, 7)
    # ICMP ping (history, value_type 3 unsigned, 1 per minute)
    for hid, iid in (("1", "101"), ("2", "102"), ("3", "103"), ("5", "105")):
        w.add_item(iid, hid, "icmpping", "ICMP ping", "3", "1m", lastclock=now - 30)
    w.items["103"]["lastclock"] = str(now - 3 * 3600)                         # stale ICMP
    d0, d1 = ts(2026, 10, 7), ts(2026, 10, 8)
    out_a, out_b = ts(2026, 10, 7, 10, 0), ts(2026, 10, 7, 10, 30)
    w.history["101"] = [(t, 1) for t in range(d0, d1, 60)]
    w.history["102"] = [(t, 0 if out_a <= t < out_b else 1) for t in range(d0, d1, 60)]
    w.history["103"] = [(t, 1) for t in range(d0, d0 + 12 * 3600, 60)]        # only 50% coverage
    w.history["105"] = [(t, 0) for t in range(d0, d1, 60)]
    # CPU / memory (float, trends)
    for hid, base in (("1", 20), ("2", 60), ("3", 90)):
        w.add_item("2%s1" % hid, hid, "system.cpu.util", "CPU utilization", "0", "1m", lastclock=now - 30)
        w.add_item("2%s2" % hid, hid, "vm.memory.util", "Memory utilization", "0", "1m", lastclock=now - 30)
        w.add_item("2%s3" % hid, hid, "system.uptime", "System uptime", "3", "1m", lastclock=now - 30)
    return w, now


def add_trends_for_windows(w):
    """Hourly trends for 2026-09-14 .. 2026-10-08 for ICMP/CPU/memory/uptime/interfaces (deterministic)."""
    a, b = ts(2026, 8, 1), ts(2026, 10, 8)
    # ICMP: RTR-HQ always up; RTR-BR1 down 02:00-04:00 on 2026-09-30; FW-HQ up; DEAD-BR1 always down
    w.trends["101"] = hourly_trend(a, b, lambda t: (1, 1.0, 1))
    w.trends["102"] = hourly_trend(a, b, lambda t: (0, 0.0, 0) if (ts(2026, 9, 30, 2) <= t < ts(2026, 9, 30, 4) or ts(2026, 8, 10, 8) <= t < ts(2026, 8, 10, 12) or ts(2026, 10, 2, 9) <= t < ts(2026, 10, 2, 10)) else (1, 1.0, 1))
    w.trends["103"] = hourly_trend(a, b, lambda t: (1, 1.0, 1))
    w.trends["105"] = hourly_trend(a, b, lambda t: (0, 0.0, 0))
    for hid, base in (("1", 20.0), ("2", 60.0), ("3", 90.0)):
        w.trends["2%s1" % hid] = hourly_trend(a, b, lambda t, base=base: (base - 5, base, base + 8))
        w.trends["2%s2" % hid] = hourly_trend(a, b, lambda t, base=base: (base - 2, base - 10, base + 3))
        w.trends["2%s3" % hid] = hourly_trend(a, b, lambda t, hid=hid: _uptime(t, hid))
    return w


def _uptime(t, hid):
    boot = ts(2026, 9, 30, 12) if (hid == "2" and t >= ts(2026, 9, 30, 12)) else ts(2025, 12, 1)
    up = t - boot
    return (max(0, up), up + 1800, up + 3599)


def add_wan(w):
    """Two WAN links with interface items. Gi0/0 on RTR-HQ (ISP STC, 1G), Gi0/1 on RTR-BR1 (ISP MOBILY, capacity missing)."""
    now = ts(2026, 10, 8, 7)
    a, b = ts(2026, 8, 1), ts(2026, 10, 8)
    specs = [("1", "Gi0/0", "11"), ("2", "Gi0/1", "12")]
    for hid, ifn, base in specs:
        tg = [{"tag": "interface", "value": ifn}]
        w.add_item(base + "1", hid, "net.if.in[%s]" % ifn, "Interface %s: Bits received" % ifn, "0", "1m", lastclock=now - 30, tags=tg)
        w.add_item(base + "2", hid, "net.if.out[%s]" % ifn, "Interface %s: Bits sent" % ifn, "0", "1m", lastclock=now - 30, tags=tg)
        w.add_item(base + "3", hid, "net.if.status[%s]" % ifn, "Interface %s: Operational status" % ifn, "3", "1m", lastclock=now - 30, tags=tg)
        w.add_item(base + "4", hid, "net.if.in.errors[%s]" % ifn, "Interface %s: Inbound errors" % ifn, "0", "1m", lastclock=now - 30, tags=tg)
        w.add_item(base + "5", hid, "net.if.out.errors[%s]" % ifn, "Interface %s: Outbound errors" % ifn, "0", "1m", lastclock=now - 30, tags=tg)
    w.add_item("116", "1", "net.if.speed[Gi0/0]", "Interface Gi0/0: Speed", "3", "1h", lastclock=now - 30, tags=[{"tag": "interface", "value": "Gi0/0"}])
    # Gi0/0 carries 400 Mbps avg, peaks 800 Mbps; Gi0/1 carries 100 Mbps avg, peak 150 Mbps; speed only known for Gi0/0
    w.trends["111"] = hourly_trend(a, b, lambda t: (3e8, 4e8, 8e8 if t % 86400 == 0 else 5e8))
    w.trends["112"] = hourly_trend(a, b, lambda t: (1e8, 2e8, 3e8))
    w.trends["121"] = hourly_trend(a, b, lambda t: (5e7, 1e8, 1.5e8))
    w.trends["122"] = hourly_trend(a, b, lambda t: (2e7, 4e7, 6e7))
    w.trends["114"] = hourly_trend(a, b, lambda t: (0, 0.1, 1))
    w.trends["115"] = hourly_trend(a, b, lambda t: (0, 0.0, 0))
    w.trends["124"] = hourly_trend(a, b, lambda t: (0, 0.0, 0))
    w.trends["125"] = hourly_trend(a, b, lambda t: (0, 0.2, 2))
    w.trends["116"] = hourly_trend(a, b, lambda t: (1e9, 1e9, 1e9), num=1)
    # interface status history for the weekly window: Gi0/0 up always; Gi0/1 down 30 minutes
    d0, d1 = ts(2026, 9, 28), ts(2026, 10, 5)
    w.history["113"] = [(t, 1) for t in range(d0, d1, 60)]
    w.history["123"] = [(t, 2 if ts(2026, 10, 1, 8) <= t < ts(2026, 10, 1, 8, 30) else 1) for t in range(d0, d1, 60)]
    return w


def add_events(w):
    d = lambda day, h=0, m=0: ts(2026, 10, day, h, m)
    # 1: resolved inside the day, one host
    w.add_event("1", ["2"], "Unavailable by ICMP ping", 4, d(7, 10, 0), d(7, 10, 30), ack="1")
    # 2: overlapping downtime on the SAME host (10:15-10:45) -> union is 10:00-10:45
    w.add_event("2", ["2"], "No SNMP data collection", 3, d(7, 10, 15), d(7, 10, 45))
    # 3: multi-host utilization event that started two days earlier and resolved inside the day
    w.add_event("3", ["1", "3"], "Interface Gi0/0: High bandwidth usage", 2, d(5, 22, 0), d(7, 3, 0))
    # 4: still open, started the day before the window (down host)
    w.add_event("4", ["5"], "Unavailable by ICMP ping", 5, d(6, 6, 0))
    # 5: marked recovered but the recovery event cannot be read
    w.add_event("5", ["1"], "High CPU utilization", 3, d(7, 12, 0), r_eventid="777")
    # 6: starts after the window
    w.add_event("6", ["1"], "Unavailable by ICMP ping", 4, d(8, 3, 0), d(8, 4, 0))
    # 7: ended before the window
    w.add_event("7", ["1"], "Unavailable by ICMP ping", 4, d(5, 1, 0), d(5, 2, 0))
    # 8: three downtime starts on host 2 inside the day -> flapping (threshold 4 with events 1 and 2 => add two)
    w.add_event("8", ["2"], "Unavailable by ICMP ping", 4, d(7, 14, 0), d(7, 14, 5))
    w.add_event("9", ["2"], "Unavailable by ICMP ping", 4, d(7, 16, 0), d(7, 16, 5))
    return w


def add_september_events(w):
    d = lambda mo, day, h=0, m=0: ts(2026, mo, day, h, m)
    w.add_event("20", ["2"], "Unavailable by ICMP ping", 4, d(9, 30, 2, 0), d(9, 30, 4, 0))
    w.add_event("21", ["3"], "High CPU utilization", 3, d(9, 15, 8, 0), d(9, 15, 9, 0), ack="1")
    w.add_event("22", ["1"], "Interface Gi0/0: High bandwidth usage", 2, d(9, 20, 8, 0), d(9, 20, 8, 30))
    w.add_event("30", ["2"], "Unavailable by ICMP ping", 4, d(8, 10, 8, 0), d(8, 10, 12, 0))     # previous month
    w.add_event("31", ["1"], "Disk space is low", 4, d(8, 20, 8, 0), d(8, 21, 8, 0))
    return w


def add_week_events(w):
    d = lambda mo, day, h=0, m=0: ts(2026, mo, day, h, m)
    w.add_event("23", ["2"], "Unavailable by ICMP ping", 4, d(10, 2, 9, 0), d(10, 2, 9, 20))
    w.add_event("24", ["3"], "High CPU utilization", 3, d(10, 3, 10, 0), d(10, 3, 12, 0), ack="1")
    w.add_event("25", ["1"], "Unavailable by ICMP ping", 5, d(10, 4, 23, 30), d(10, 5, 0, 30))      # resolves after W40 ends
    return w


def add_unsupported(w):
    w.add_item("901", "4", "net.if.in[Gi0/9]", "Interface Gi0/9: Bits received", "0", "1m", state="1", error="Timeout while connecting")
    w.add_item("902", "5", "net.if.out[Gi0/9]", "Interface Gi0/9: Bits sent", "0", "1m", state="1", error="Authentication failure")
    return w
