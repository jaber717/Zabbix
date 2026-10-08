"""History/trend retrieval and honest aggregation.

* Raw history is used only where raw samples are needed (daily availability, true percentiles).
* Trend data is hourly; any percentile derived from it is labelled `p95_of_hourly_avg`, never "P95".
* The latest-value field of an item is never used as a historical statistic.
* Coverage = samples actually present / samples expected from the item's update interval (None when unknown).
"""
from __future__ import annotations

from datetime import datetime

from .util import chunks, parse_delay, percentile_nearest_rank, to_float

MAX_RAW_VALUES_KEPT = 200000


class Agg(object):
    """Accumulator for one item over one window."""

    def __init__(self, keep_values=False, tz=None, threshold=None):
        self.tz = tz
        self.threshold = threshold
        self.n = 0                 # samples (history) or sum of trend `num`
        self.up = 0                # samples with value > 0 (availability-style items) - history only
        self.sum = 0.0             # sum of values (history) / sum(avg*num) (trend)
        self.min = None
        self.max = None
        self.hourly_avgs = []      # trend only
        self.hourly = []           # trend only: (clock, min, avg, max) per hour
        self.hours = 0
        self.keep = keep_values
        self.values = []
        self.overflow = False
        self.source = None         # "history" | "trend"

    def add_sample(self, value):
        self.source = "history"
        self.n += 1
        self.sum += value
        self.up += 1 if value == 1 else 0
        self.min = value if self.min is None else min(self.min, value)
        self.max = value if self.max is None else max(self.max, value)
        if self.keep:
            if len(self.values) < MAX_RAW_VALUES_KEPT:
                self.values.append(value)
            else:
                self.overflow = True

    def add_trend(self, num, vmin, vavg, vmax, clock=0):
        self.source = "trend"
        self.hourly.append((clock, vmin, vavg, vmax, num))
        self.hours += 1
        self.n += num
        self.sum += vavg * num
        self.hourly_avgs.append(vavg)
        self.min = vmin if self.min is None else min(self.min, vmin)
        self.max = vmax if self.max is None else max(self.max, vmax)

    def stats(self, window_seconds, delay, pct=95):
        """Normalized, serialisable statistics. Absent data -> every statistic None (never 0)."""
        interval = parse_delay(delay)
        expected = (window_seconds / float(interval)) if interval else None
        coverage = None if not expected else min(1.0, self.n / expected)
        if self.n == 0:
            return {"source": self.source, "samples": 0, "avg": None, "min": None, "max": None,
                    "p95_raw": None, "p95_of_hourly_avg": None, "up_ratio": None,
                    "coverage": 0.0 if expected else None, "hours": self.hours}
        out = {"source": self.source, "samples": self.n, "avg": self.sum / self.n, "min": self.min,
               "max": self.max, "coverage": coverage, "hours": self.hours,
               "p95_raw": None, "p95_of_hourly_avg": None, "up_ratio": None}
        if self.source == "history":
            out["up_ratio"] = self.up / float(self.n)
            if self.keep and not self.overflow:
                out["p95_raw"] = percentile_nearest_rank(self.values, pct)
        else:
            out["p95_of_hourly_avg"] = percentile_nearest_rank(self.hourly_avgs, pct)
            rows = sorted(self.hourly)
            out["counter_drops"] = sum(1 for p, c in zip(rows, rows[1:]) if c[1] < p[3] - 60)   # for uptime items: reboots
            out["up_ratio"] = out["avg"]     # for 0/1 items the weighted mean of hourly means is the up ratio
            if self.threshold is not None:
                out["hours_over_threshold"] = sum(1 for _, _, a, _, _ in rows if a >= self.threshold)
            if self.tz is not None:
                days = {}
                for clock, _, a, mx, num in rows:
                    d = datetime.fromtimestamp(clock, self.tz).date().isoformat()
                    s = days.setdefault(d, [0.0, 0, None])
                    s[0] += a * num
                    s[1] += num
                    s[2] = mx if s[2] is None else max(s[2], mx)
                out["by_day"] = [{"day": d, "avg": (v[0] / v[1]) if v[1] else None, "max": v[2]} for d, v in sorted(days.items())]
        return out


def confidence(coverage, high=0.95, medium=0.80):
    if coverage is None:
        return "UNKNOWN"
    if coverage <= 0:
        return "NONE"
    if coverage >= high:
        return "HIGH"
    if coverage >= medium:
        return "MEDIUM"
    return "LOW"


def fetch_trends(api, notes, itemids, t0, t1, aggs, chunk=50, limit=20000):
    """trend.get for [t0, t1). Splits batches on truncation; records what stays partial."""
    def run(ids):
        rows = api.call("trend.get", {"output": ["itemid", "clock", "num", "value_min", "value_avg", "value_max"],
                                      "itemids": ids, "time_from": t0, "time_till": t1 - 1, "limit": limit + 1})
        if len(rows) > limit:
            if len(ids) > 1:
                half = len(ids) // 2
                run(ids[:half])
                run(ids[half:])
                return
            notes.truncated.append({"what": "trend.get item %s" % ids[0], "limit": limit,
                                    "detail": "single item exceeds limit; statistics are partial"})
            rows = rows[:limit]
        for r in rows:
            a = aggs.get(str(r["itemid"]))
            vmin, vavg, vmax, num = to_float(r["value_min"]), to_float(r["value_avg"]), to_float(r["value_max"]), to_float(r["num"])
            if a is not None and None not in (vmin, vavg, vmax, num) and t0 <= int(r["clock"]) < t1:
                a.add_trend(int(num), vmin, vavg, vmax, int(r["clock"]))
    for part in chunks([str(i) for i in itemids], chunk):
        try:
            run(part)
        except Exception as exc:     # a failed batch must be visible, not silently empty
            notes.failed.append({"what": "trend.get %d items" % len(part), "error": str(exc)})


def fetch_history(api, notes, items_by_type, t0, t1, aggs, chunk=20, limit=50000, min_span=3600):
    """history.get for [t0, t1), grouped by Zabbix value type (0 float, 3 unsigned). Splits by item batch
    and then by time on truncation."""
    def run(vt, ids, a, b):
        rows = api.call("history.get", {"output": ["itemid", "clock", "value"], "history": vt, "itemids": ids,
                                        "time_from": a, "time_till": b - 1, "sortfield": "clock",
                                        "sortorder": "ASC", "limit": limit + 1})
        if len(rows) > limit:
            if len(ids) > 1:
                half = len(ids) // 2
                run(vt, ids[:half], a, b)
                run(vt, ids[half:], a, b)
                return
            if b - a > min_span:
                mid = a + (b - a) // 2
                run(vt, ids, a, mid)
                run(vt, ids, mid, b)
                return
            notes.truncated.append({"what": "history.get item %s" % ids[0], "limit": limit,
                                    "detail": "window %d-%d exceeds the limit at the minimum span" % (a, b)})
            rows = rows[:limit]
        for r in rows:
            agg = aggs.get(str(r["itemid"]))
            v = to_float(r["value"])
            if agg is not None and v is not None and a <= int(r["clock"]) < b:
                agg.add_sample(v)
    for vt, ids in sorted(items_by_type.items()):
        for part in chunks([str(i) for i in ids], chunk):
            try:
                run(vt, part, t0, t1)
            except Exception as exc:
                notes.failed.append({"what": "history.get type %s %d items" % (vt, len(part)), "error": str(exc)})
