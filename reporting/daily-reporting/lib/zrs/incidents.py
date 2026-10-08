"""Historical incident reconstruction from Zabbix problem events.

An *incident* is one problem event (de-duplicated by eventid). It may be attributed to several hosts;
fleet counts use incidents once, per-host tables count it for every host it touches.
Time windows are half-open. Downtime is the UNION of overlapping downtime incidents per host.
"""
from __future__ import annotations

SEVERITY_NAMES = {0: "Not classified", 1: "Information", 2: "Warning", 3: "Average", 4: "High", 5: "Disaster"}


def matches_any(text, patterns):
    t = (text or "").lower()
    return any(p.lower() in t for p in patterns)


def build_incidents(events, recoveries, period, now_ts, downtime_patterns, host_site):
    """events: problem events {eventid, clock, name, severity, acknowledged, r_eventid, hosts:[{hostid,name}]}
    recoveries: {r_eventid: clock}. Returns (incidents, quality) where quality counts oddities."""
    by_id, dup = {}, 0
    for e in events:
        eid = str(e["eventid"])
        if eid in by_id:
            dup += 1
            continue
        by_id[eid] = e
    out, unknown_recovery = [], 0
    for eid in sorted(by_id, key=lambda x: (int(by_id[x]["clock"]), int(x))):
        e = by_id[eid]
        start = int(e["clock"])
        r_eid = str(e.get("r_eventid") or "0")
        end = None
        if r_eid != "0":
            if r_eid in recoveries:
                end = int(recoveries[r_eid])
            else:
                unknown_recovery += 1          # recovered, but its time could not be read: treat as open, flag it
        if start >= period.end_ts or (end is not None and end <= period.start_ts):
            continue                            # no overlap with [start, end)
        effective_end = end if end is not None else max(now_ts, start)
        clipped = max(0, min(effective_end, period.end_ts) - max(start, period.start_ts))
        hosts = [{"hostid": str(h["hostid"]), "name": h.get("name", "")} for h in e.get("hosts", [])]
        out.append({
            "eventid": eid, "name": e.get("name", ""), "severity": int(e.get("severity", 0)),
            "severity_name": SEVERITY_NAMES.get(int(e.get("severity", 0)), "Unknown"),
            "start": start, "end": end, "hosts": hosts,
            "host_names": sorted(h["name"] for h in hosts),
            "sites": sorted({host_site.get(h["hostid"], "Unassigned") for h in hosts}),
            "acknowledged": str(e.get("acknowledged", "0")) == "1",
            "started_in_window": period.start_ts <= start < period.end_ts,
            "resolved_in_window": end is not None and period.start_ts <= end < period.end_ts,
            "open_at_period_end": end is None or end >= period.end_ts,
            "duration_total_s": (None if end is None else max(0, end - start)),
            "duration_in_window_s": clipped,
            "is_downtime": matches_any(e.get("name", ""), downtime_patterns),
            "recovery_time_unknown": r_eid != "0" and end is None,
        })
    return out, {"duplicate_events_removed": dup, "recovery_time_unknown": unknown_recovery}


def union_seconds(intervals):
    """Total length of the union of [a, b) intervals."""
    total, cur_a, cur_b = 0, None, None
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += cur_b - cur_a
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += cur_b - cur_a
    return total


def host_downtime(incidents, period, now_ts):
    """{hostid: downtime seconds inside the window} from downtime incidents (overlaps merged)."""
    spans = {}
    for i in incidents:
        if not i["is_downtime"]:
            continue
        end = i["end"] if i["end"] is not None else max(now_ts, i["start"])
        a, b = max(i["start"], period.start_ts), min(end, period.end_ts)
        if b > a:
            for h in i["hosts"]:
                spans.setdefault(h["hostid"], []).append((a, b))
    return dict((h, union_seconds(v)) for h, v in spans.items())


def mttr_seconds(incidents):
    """Mean time to resolve over incidents that were RESOLVED inside the window (full duration, not clipped)."""
    d = [i["duration_total_s"] for i in incidents if i["resolved_in_window"] and i["duration_total_s"] is not None]
    return (sum(d) / float(len(d))) if d else None
