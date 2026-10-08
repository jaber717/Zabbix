"""Collector behaviour: targeting, batching, truncation, failures, retries, honest statistics."""
import copy
import unittest
import urllib.error

from common import NOW, TZ, WAN_LINKS, dataset, make_cfg, period_for, world
import fakezbx
from zrs import plans
from zrs.apiclient import ApiClient, ApiError, Notes, fetch_time_split, get_limited
from zrs.metrics import Agg, confidence, fetch_history, fetch_trends


class Targeting(unittest.TestCase):
    def test_no_unrestricted_item_scan(self):
        for key in plans.REPORTS:
            ds, cfg, w = dataset(key)
            for method, params in w.calls:
                if method == "item.get":
                    self.assertTrue(params.get("hostids"), "%s: item.get without hostids" % key)
                    self.assertTrue(params.get("search") or params.get("filter"), "%s: item.get without key search" % key)
                    self.assertNotIn("lastvalue", params["output"])
                    self.assertIn("limit", params)

    def test_requested_kinds_only(self):
        ds, cfg, w = dataset("daily_network_health")
        searches = [p["search"]["key_"] for m, p in w.calls if m == "item.get"]
        self.assertEqual(searches, [["icmpping"]])
        ds, cfg, w = dataset("infrastructure_health")
        keys = [k for m, p in w.calls if m == "item.get" for k in p["search"]["key_"]]
        self.assertEqual(sorted(set(keys)), ["system.cpu.util", "system.net.uptime", "system.uptime", "sysuptime", "vm.memory.util"])
        self.assertNotIn("net.if.in[", keys)

    def test_wan_interface_items_filtered_by_interface_tag(self):
        ds, cfg, w = dataset("wan_isp_performance")
        tagged = [p for m, p in w.calls if m == "item.get" and p.get("tags")]
        self.assertEqual(len(tagged), 2)
        for p in tagged:
            self.assertEqual(p["tags"][0]["tag"], "interface")
            self.assertEqual(len(p["hostids"]), 1)

    def test_history_only_for_daily_availability_trends_otherwise(self):
        ds, cfg, w = dataset("daily_network_health")
        self.assertIn("history.get", w.stats)
        self.assertNotIn("trend.get", w.stats)
        for key in ("infrastructure_health", "monitoring_quality", "executive_summary"):
            ds, cfg, w = dataset(key)
            self.assertNotIn("history.get", w.stats, key)
            self.assertIn("trend.get", w.stats, key)

    def test_half_open_query_bounds(self):
        ds, cfg, w = dataset("daily_network_health")
        p = period_for("daily_network_health", cfg)
        for m, params in w.calls:
            if m in ("history.get", "trend.get", "event.get") and "time_till" in params:
                self.assertLessEqual(params["time_till"], p.end_ts - 1)
                self.assertGreaterEqual(params["time_from"], p.start_ts - 31 * 86400)

    def test_batched_requests_not_per_item(self):
        w = world()
        for i in range(300, 460):                                       # 160 more hosts with ICMP items
            w.add_host(str(i), "H%d" % i, "S%d" % (i % 4))
            w.add_item(str(10000 + i), str(i), "icmpping", "ICMP ping", "3", "1m", lastclock=1)
            w.history[str(10000 + i)] = [(t, 1) for t in range(fakezbx.ts(2026, 10, 7), fakezbx.ts(2026, 10, 7, 1), 60)]
        ds, cfg, w = dataset("daily_network_health", w=w)
        n_hist = w.stats["history.get"]
        n_items = sum(1 for i in w.items.values() if i["key_"] == "icmpping")
        self.assertLess(n_hist, n_items / 4.0)
        self.assertLessEqual(w.stats["item.get"], 3)


class Statistics(unittest.TestCase):
    def test_absent_data_is_none_not_zero(self):
        s = Agg().stats(86400, "1m")
        self.assertIsNone(s["avg"])
        self.assertIsNone(s["max"])
        self.assertEqual(s["coverage"], 0.0)
        self.assertEqual(s["samples"], 0)
        self.assertEqual(confidence(s["coverage"]), "NONE")

    def test_coverage_unknown_when_delay_is_a_macro(self):
        a = Agg()
        a.add_sample(1.0)
        s = a.stats(86400, "{$DELAY}")
        self.assertIsNone(s["coverage"])
        self.assertEqual(confidence(None), "UNKNOWN")

    def test_p95_raw_only_from_raw_samples_never_from_trends(self):
        raw = Agg(keep_values=True)
        for v in range(1, 101):
            raw.add_sample(float(v))
        self.assertEqual(raw.stats(6000, "1m")["p95_raw"], 95.0)
        tr = Agg()
        for h in range(10):
            tr.add_trend(60, 1.0, float(h), 100.0, 3600 * h)
        s = tr.stats(36000, "1m")
        self.assertIsNone(s["p95_raw"])                     # a true P95 cannot be derived from hourly data
        self.assertEqual(s["p95_of_hourly_avg"], 9.0)       # and the hourly figure carries its own name
        self.assertEqual(s["max"], 100.0)

    def test_raw_overflow_disables_percentile(self):
        import zrs.metrics as m
        old, m.MAX_RAW_VALUES_KEPT = m.MAX_RAW_VALUES_KEPT, 5
        try:
            a = Agg(keep_values=True)
            for v in range(10):
                a.add_sample(float(v))
            self.assertIsNone(a.stats(600, "1m")["p95_raw"])
        finally:
            m.MAX_RAW_VALUES_KEPT = old

    def test_trend_weighting_by_num(self):
        a = Agg()
        a.add_trend(10, 0.0, 10.0, 20.0, 0)
        a.add_trend(30, 0.0, 30.0, 40.0, 3600)
        self.assertAlmostEqual(a.stats(7200, "1m")["avg"], (10 * 10 + 30 * 30) / 40.0)

    def test_counter_drops_detect_reboot(self):
        a = Agg()
        a.add_trend(60, 1000, 1500, 2000, 0)
        a.add_trend(60, 2000, 2500, 3000, 3600)
        a.add_trend(60, 5, 900, 1800, 7200)            # counter restarted
        self.assertEqual(a.stats(10800, "1m")["counter_drops"], 1)

    def test_by_day_uses_local_calendar_days(self):
        a = Agg(tz=TZ)
        a.add_trend(60, 0, 10.0, 20.0, fakezbx.ts(2026, 10, 7, 23))        # 23:00 local on the 7th
        a.add_trend(60, 0, 30.0, 40.0, fakezbx.ts(2026, 10, 8, 0))         # 00:00 local on the 8th
        days = a.stats(7200, "1m")["by_day"]
        self.assertEqual([d["day"] for d in days], ["2026-10-07", "2026-10-08"])


class Resilience(unittest.TestCase):
    def test_get_limited_flags_truncation(self):
        w = world()
        notes = Notes()
        rows = get_limited(w, notes, "host.get", {"output": ["hostid"]}, 3, "host.get")
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(notes.truncated), 1)
        self.assertEqual(notes.truncated[0]["limit"], 3)
        notes2 = Notes()
        self.assertEqual(len(get_limited(w, notes2, "host.get", {"output": ["hostid"]}, 5, "host.get")), 5)
        self.assertEqual(notes2.truncated, [])             # exactly at the limit is NOT truncation

    def test_collection_surfaces_host_truncation_in_the_report(self):
        cfg = make_cfg(wan={"links": WAN_LINKS})
        cfg["zabbix"]["maximum_hosts"] = 3
        from zrs.reports import build
        ds, cfg, w = dataset("daily_network_health", cfg=cfg)
        self.assertEqual(len(ds["hosts"]), 3)
        self.assertTrue(ds["audit"]["notes"]["truncated"])
        doc = build(ds, cfg)
        self.assertTrue(any("DATA TRUNCATED" in x for x in doc["warnings"]))

    def test_time_split_recovers_all_rows_when_windows_are_halved(self):
        w = fakezbx.FakeApi()
        for i in range(50):
            w.add_event(str(i), ["1"], "x", 3, 1000 + i * 100)
        w.add_host("1", "H", "S")
        notes = Notes()
        rows = fetch_time_split(w, notes, "event.get", {"output": ["eventid", "clock"], "hostids": ["1"], "source": 0, "object": 0, "value": 1},
                                1000, 1000 + 50 * 100, 10, "events", "eventid", min_span=100)
        self.assertEqual(len({r["eventid"] for r in rows}), 50)
        self.assertEqual(notes.truncated, [])

    def test_time_split_reports_remaining_truncation_at_minimum_span(self):
        w = fakezbx.FakeApi()
        w.add_host("1", "H", "S")
        for i in range(20):
            w.add_event(str(i), ["1"], "x", 3, 5000)                       # all in the same second
        notes = Notes()
        rows = fetch_time_split(w, notes, "event.get", {"output": ["eventid", "clock"], "hostids": ["1"]}, 4000, 6000, 5, "events", "eventid", min_span=500)
        self.assertEqual(len(rows), 5)
        self.assertTrue(notes.truncated)

    def test_history_split_by_item_then_time(self):
        w = fakezbx.FakeApi()
        base = fakezbx.ts(2026, 10, 7)
        for iid in ("1", "2", "3"):
            w.add_host(iid, "H" + iid, "S")
            w.add_item(iid, iid, "icmpping", "ICMP", "3", "1m")
            w.history[iid] = [(base + i * 60, 1) for i in range(600)]
        aggs = dict((i, Agg()) for i in ("1", "2", "3"))
        notes = Notes()
        fetch_history(w, notes, {3: ["1", "2", "3"]}, base, base + 86400, aggs, chunk=3, limit=700, min_span=3600)
        self.assertEqual([aggs[i].n for i in ("1", "2", "3")], [600, 600, 600])
        self.assertEqual(notes.truncated, [])

    def test_failed_batch_is_recorded_other_batches_continue(self):
        w = world()
        w.fail["trend.get"] = 1
        notes = Notes()
        aggs = {"211": Agg(), "221": Agg()}
        fetch_trends(w, notes, ["211"], fakezbx.ts(2026, 10, 1), fakezbx.ts(2026, 10, 2), aggs, chunk=1)
        fetch_trends(w, notes, ["221"], fakezbx.ts(2026, 10, 1), fakezbx.ts(2026, 10, 2), aggs, chunk=1)
        self.assertEqual(len(notes.failed), 1)
        self.assertEqual(aggs["211"].n, 0)
        self.assertGreater(aggs["221"].n, 0)

    def test_failed_batch_shows_in_report_as_incomplete(self):
        w = world()
        w.fail["trend.get"] = 1
        cfg = make_cfg(wan={"links": WAN_LINKS})
        from zrs.reports import build
        ds = plans.collect(w, cfg, NOW, "infrastructure_health", period_for("infrastructure_health", cfg))
        doc = build(ds, cfg)
        self.assertTrue(any("DATA REQUEST FAILED" in x for x in doc["warnings"]))

    def test_trends_outside_window_are_ignored(self):
        w = world()
        aggs = {"211": Agg()}
        notes = Notes()
        t0, t1 = fakezbx.ts(2026, 10, 1), fakezbx.ts(2026, 10, 2)
        fetch_trends(w, notes, ["211"], t0, t1, aggs)
        self.assertEqual(aggs["211"].hours, 24)


class Retries(unittest.TestCase):
    def client(self, outcomes):
        c = ApiClient({"api_url": "https://zbx.example/api_jsonrpc.php", "request_timeout_seconds": 1}, retries=3, backoff=0.01, sleep=lambda s: None)
        c.token = "t"
        seq = list(outcomes)

        def fake_open(request):
            o = seq.pop(0)
            if isinstance(o, Exception):
                raise o
            return o
        c._open = fake_open
        c._seq = seq
        return c

    def test_retries_timeout_then_succeeds(self):
        c = self.client([TimeoutError("t"), urllib.error.URLError("down"), {"result": [1]}])
        self.assertEqual(c.call("host.get", {}), [1])
        self.assertEqual(c.stats["host.get"], 1)

    def test_retries_rate_limit_and_server_errors(self):
        e429 = urllib.error.HTTPError("u", 429, "slow down", {}, None)
        e503 = urllib.error.HTTPError("u", 503, "busy", {}, None)
        c = self.client([e429, e503, {"result": "ok"}])
        self.assertEqual(c.call("apiinfo.version", {}, False), "ok")

    def test_gives_up_after_retries_with_clear_error(self):
        c = self.client([TimeoutError("t")] * 4)
        with self.assertRaises(ApiError) as cm:
            c.call("host.get", {})
        self.assertIn("failed after 4 attempts", str(cm.exception))

    def test_non_retryable_http_and_api_errors_fail_immediately(self):
        c = self.client([urllib.error.HTTPError("u", 403, "no", {}, None), {"result": 1}])
        with self.assertRaises(ApiError):
            c.call("host.get", {})
        self.assertEqual(len(c._seq), 1)                    # the second outcome was never consumed
        c2 = self.client([{"error": {"message": "Invalid params.", "data": "No permissions"}}, {"result": 1}])
        with self.assertRaises(ApiError) as cm:
            c2.call("host.get", {})
        self.assertIn("No permissions", str(cm.exception))
        self.assertEqual(len(c2._seq), 1)

    def test_credentials_required(self):
        c = ApiClient({"api_url": "https://zbx.example/api_jsonrpc.php"})
        c.token = c.user = c.password = ""
        with self.assertRaises(ApiError):
            c.call("host.get", {})

    def test_tls_verification_is_never_disabled(self):
        import ssl
        c = ApiClient({"api_url": "https://zbx.example/api_jsonrpc.php"})
        self.assertEqual(c.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(c.context.check_hostname)


if __name__ == "__main__":
    unittest.main()
