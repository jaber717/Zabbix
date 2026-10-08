"""KPI and table values of the six reports against the deterministic fixture world (hand-computed expectations)."""
import copy
import unittest

from common import NOW, WAN_LINKS, dataset, make_cfg, world
import fakezbx
from zrs import plans
from zrs.reports import build


def kpis(doc):
    return dict((k["id"], k) for k in doc["kpis"])


def rows(doc, tid):
    return doc["tables"][tid]["rows"]


def row(doc, tid, **match):
    for r in rows(doc, tid):
        if all(r.get(k) == v for k, v in match.items()):
            return r
    raise AssertionError("no row %r in %s" % (match, tid))


class Daily(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.cfg, cls.w = dataset("daily_network_health")
        cls.doc = build(cls.ds, cls.cfg)
        cls.k = kpis(cls.doc)

    def test_period(self):
        self.assertEqual(self.ds["period"]["label"], "2026-10-07")
        self.assertEqual(self.ds["period"]["seconds"], 86400)

    def test_device_counts(self):
        self.assertEqual(self.k["devices_monitored"]["value"], 5)
        self.assertEqual(self.k["devices_up_now"]["value"], 4)
        self.assertEqual(self.k["devices_down_now"]["value"], 1)

    def test_availability_uses_icmp_samples_and_labels_the_weak_basis(self):
        br1 = row(self.doc, "devices", device="RTR-BR1")
        self.assertAlmostEqual(br1["availability_pct"], 1410 / 1440.0 * 100)
        self.assertEqual((br1["basis"], br1["confidence"]), ("icmp", "HIGH"))
        fw = row(self.doc, "devices", device="FW-HQ")                     # only 50 % of the samples exist
        self.assertEqual((fw["basis"], fw["confidence"]), ("events", "LOW"))
        self.assertAlmostEqual(fw["coverage_pct"], 50.0)
        sw = row(self.doc, "devices", device="SW-BR1")                    # no ICMP item at all
        self.assertEqual((sw["basis"], sw["confidence"]), ("events", "LOW"))
        self.assertIsNone(sw["coverage_pct"])
        dead = row(self.doc, "devices", device="DEAD-BR1")
        self.assertEqual(dead["availability_pct"], 0.0)

    def test_fleet_availability_mean(self):
        self.assertAlmostEqual(self.k["availability_pct"]["value"], (100 + 1410 / 14.40 + 100 + 100 + 0) / 5.0)

    def test_incident_counts_dedup_overlap_open_unknown(self):
        self.assertEqual(self.k["incidents_started"]["value"], 5)             # events 1,2,5,8,9
        self.assertEqual(self.k["incidents_resolved"]["value"], 5)            # events 1,2,3,8,9
        ids = sorted(r["eventid"] for r in rows(self.doc, "incidents"))
        self.assertEqual(ids, ["1", "2", "3", "4", "5", "8", "9"])            # 6 (after) and 7 (before) excluded
        self.assertEqual(row(self.doc, "incidents", eventid="3")["hosts"], "FW-HQ, RTR-HQ")   # multi-host: one row
        self.assertEqual(row(self.doc, "incidents", eventid="5")["state"], "OPEN")             # unreadable recovery -> open
        self.assertTrue(any("recovery time could not be read" in w for w in self.doc["warnings"]))

    def test_overlapping_downtime_is_merged_per_host(self):
        br1 = row(self.doc, "devices", device="RTR-BR1")
        self.assertEqual(br1["downtime_s"], 45 * 60 + 5 * 60 + 5 * 60)        # 10:00-10:45 union + two 5-minute events
        self.assertEqual(row(self.doc, "devices", device="DEAD-BR1")["downtime_s"], 86400)

    def test_flapping_stale_open_high(self):
        self.assertEqual(self.k["flapping_devices"]["value"], 1)
        self.assertEqual(row(self.doc, "devices", device="RTR-BR1")["flags"], "FLAPPING")
        self.assertEqual(self.k["stale_devices"]["value"], 1)
        self.assertEqual(row(self.doc, "devices", device="FW-HQ")["flags"], "STALE")
        self.assertEqual(self.k["open_high_disaster"]["value"], 1)
        self.assertEqual(rows(self.doc, "open_high")[0]["severity"], "Disaster")

    def test_site_table(self):
        br = row(self.doc, "site_summary", site="BR1")
        self.assertEqual((br["devices"], br["up_now"], br["down_now"]), (3, 2, 1))
        self.assertEqual(br["downtime_s"], 3300 + 86400)
        hq = row(self.doc, "site_summary", site="HQ")
        self.assertEqual(hq["devices"], 2)

    def test_no_value_is_fabricated_for_missing_icmp(self):
        # remove every ICMP item: availability must come from events (LOW) or N/A, never a confident 100
        w = world()
        for k in [k for k, i in w.items.items() if i["key_"] == "icmpping"]:
            del w.items[k]
        ds, cfg, _ = dataset("daily_network_health", w=w)
        doc = build(ds, cfg)
        self.assertTrue(all(r["confidence"] == "LOW" for r in rows(doc, "devices")))


class Wan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.cfg, cls.w = dataset("wan_isp_performance")
        cls.doc = build(cls.ds, cls.cfg)
        cls.k = kpis(cls.doc)

    def test_period_is_iso_week(self):
        self.assertEqual(self.ds["period"]["label"], "2026-W40")
        self.assertEqual(self.ds["period"]["seconds"], 7 * 86400)

    def test_link_with_capacity(self):
        r = row(self.doc, "links", device="RTR-HQ", interface="Gi0/0")
        self.assertEqual(r["capacity_bps"], 1e9)
        self.assertEqual(r["capacity_source"], "ifHighSpeed item")
        self.assertAlmostEqual(r["in_avg_bps"], 4e8)
        self.assertAlmostEqual(r["in_peak_bps"], 8e8)
        self.assertAlmostEqual(r["in_avg_util_pct"], 40.0)
        self.assertAlmostEqual(r["in_peak_util_pct"], 80.0)
        self.assertAlmostEqual(r["out_peak_util_pct"], 30.0)
        self.assertAlmostEqual(r["in_p95_hourly_bps"], 4e8)
        self.assertAlmostEqual(r["link_availability_pct"], 100.0)
        self.assertEqual(r["confidence"], "HIGH")

    def test_link_without_capacity_has_na_utilization_not_zero(self):
        r = row(self.doc, "links", device="RTR-BR1", interface="Gi0/1")
        self.assertIsNone(r["capacity_bps"])
        self.assertEqual(r["capacity_source"], "missing")
        self.assertIsNone(r["in_avg_util_pct"])
        self.assertIsNone(r["peak_util_pct"])
        self.assertAlmostEqual(r["in_avg_bps"], 1e8)                      # the rate itself is still reported
        self.assertAlmostEqual(r["link_availability_pct"], 10050 / 10080.0 * 100)
        self.assertIn("capacity unknown", " ".join(x["issue"] for x in rows(self.doc, "exceptions")))
        self.assertEqual(self.k["links_missing_capacity"]["value"], 1)

    def test_kpis(self):
        self.assertEqual(self.k["links_monitored"]["value"], 2)
        self.assertEqual(self.k["isps"]["value"], 2)
        self.assertEqual(self.k["peak_util_pct"]["value"], 80.0)
        self.assertEqual(self.k["links_over_threshold"]["value"], 1)       # threshold 80 %

    def test_p95_is_labelled_as_hourly(self):
        labels = [c["label"] for c in self.doc["tables"]["links"]["columns"]]
        self.assertIn("In P95 (hourly avg)", labels)
        self.assertFalse([l for l in labels if "P95" in l and "hourly" not in l])
        self.assertTrue(any(d["term"] == "p95_hourly" and "NOT a 5-minute" in d["definition"] for d in self.doc["dictionary"]))

    def test_isp_table(self):
        stc = row(self.doc, "isp_summary", isp="STC")
        self.assertEqual(stc["links"], 1)
        self.assertAlmostEqual(stc["availability_pct"], 100.0)
        mob = row(self.doc, "isp_summary", isp="MOBILY")
        self.assertIsNone(mob["peak_util_pct"])

    def test_daily_trend_sums_links_per_local_day(self):
        days = rows(self.doc, "daily_trend")
        self.assertEqual([d["day"] for d in days], ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"])
        self.assertAlmostEqual(days[0]["in_avg_bps"], 4e8 + 1e8)
        self.assertAlmostEqual(days[0]["in_peak_bps"], 8e8 + 1.5e8)

    def test_unresolved_declared_link_is_listed_not_invented(self):
        cfg = make_cfg(wan={"links": WAN_LINKS + [{"host": "NO-SUCH", "interface": "Gi9/9", "isp": "X"},
                                                   {"host": "RTR-HQ", "interface": "Gi7/7", "isp": "Y"}]})
        ds, cfg, w = dataset("wan_isp_performance", cfg=cfg)
        doc = build(ds, cfg)
        self.assertEqual(kpis(doc)["links_unresolved"]["value"], 2)
        issues = [x["issue"] for x in rows(doc, "exceptions")]
        self.assertTrue(any("host not found" in i for i in issues))
        self.assertTrue(any("no interface items" in i for i in issues))
        self.assertEqual(len(rows(doc, "links")), 3)                        # NO-SUCH never becomes a row

    def test_wan_incidents_limited_to_link_hosts(self):
        names = {r["hosts"] for r in rows(self.doc, "incidents")}
        self.assertTrue(names <= {"RTR-HQ", "RTR-BR1"})
        self.assertEqual(len(rows(self.doc, "incidents")), 3)               # events 20, 23, 25


class Infra(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.cfg, cls.w = dataset("infrastructure_health")
        cls.doc = build(cls.ds, cls.cfg)
        cls.k = kpis(cls.doc)

    def test_fleet_values(self):
        self.assertEqual(self.k["devices_assessed"]["value"], 5)
        self.assertAlmostEqual(self.k["cpu_fleet_avg_pct"]["value"], (20 + 60 + 90) / 3.0)
        self.assertAlmostEqual(self.k["mem_fleet_avg_pct"]["value"], (10 + 50 + 80) / 3.0)

    def test_devices_without_items_are_na_not_healthy(self):
        sw = row(self.doc, "devices", device="SW-BR1")
        self.assertIsNone(sw["cpu_avg_pct"])
        self.assertIsNone(sw["mem_avg_pct"])
        self.assertEqual(self.k["devices_no_cpu"]["value"], 2)
        self.assertEqual(self.k["devices_no_memory"]["value"], 2)

    def test_threshold_hours_and_exceptions(self):
        fw = row(self.doc, "devices", device="FW-HQ")
        self.assertEqual(fw["cpu_hours_over"], 168)                          # 90 % average every hour of the week
        self.assertEqual(fw["mem_hours_over"], 0)                            # memory average 80 % < 85
        self.assertAlmostEqual(fw["mem_max_pct"], 93.0)
        self.assertEqual([r["device"] for r in rows(self.doc, "exceptions")], ["FW-HQ"])

    def test_reboot_detected_from_uptime_counter_drop(self):
        self.assertEqual(row(self.doc, "devices", device="RTR-BR1")["reboots"], 1)
        self.assertEqual(row(self.doc, "devices", device="RTR-HQ")["reboots"], 0)
        self.assertEqual(self.k["reboots_detected"]["value"], 1)

    def test_p95_label_and_coverage(self):
        hq = row(self.doc, "devices", device="RTR-HQ")
        self.assertAlmostEqual(hq["cpu_p95_hourly_pct"], 20.0)
        self.assertAlmostEqual(hq["cpu_coverage_pct"], 100.0)
        self.assertIn("(hourly avg)", " ".join(c["label"] for c in self.doc["tables"]["devices"]["columns"]))

    def test_top_tables_sorted(self):
        self.assertEqual([r["device"] for r in rows(self.doc, "top_cpu")], ["FW-HQ", "RTR-BR1", "RTR-HQ"])

    def test_group_filter(self):
        cfg = make_cfg(infra={"host_groups": ["Firewalls"]})
        ds, cfg, w = dataset("infrastructure_health", cfg=cfg)
        self.assertEqual([r["device"] for r in rows(build(ds, cfg), "devices")], ["FW-HQ"])


class Executive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.cfg, cls.w = dataset("executive_summary")
        cls.doc = build(cls.ds, cls.cfg)
        cls.k = kpis(cls.doc)

    def test_month_windows(self):
        self.assertEqual(self.ds["period"]["label"], "2026-09")
        self.assertEqual(self.ds["previous_period"]["label"], "2026-08")
        self.assertEqual(self.ds["period"]["seconds"], 30 * 86400)

    def test_availability_and_delta(self):
        cur = (100 + (1 - 2 / 720.0) * 100 + 100 + 100 + 0) / 5.0
        prev = (100 + (1 - 4 / 744.0) * 100 + 100 + 100 + 0) / 5.0
        self.assertAlmostEqual(self.k["availability_pct"]["value"], cur)
        self.assertAlmostEqual(self.k["availability_delta_pts"]["value"], cur - prev)

    def test_incident_kpis_current_and_previous(self):
        self.assertEqual(self.k["incidents"]["value"], 3)
        self.assertEqual(self.k["incidents"]["note"], "previous month 2")
        self.assertEqual(self.k["incidents_high"]["value"], 1)
        self.assertEqual(self.k["incidents_open"]["value"], 0)
        self.assertAlmostEqual(self.k["mttr_seconds"]["value"], (7200 + 3600 + 1800) / 3.0)

    def test_sla_shown_only_with_adequate_confidence(self):
        self.assertIsNotNone(self.k["sla_status"]["value"])
        w = world()
        for k in [k for k, i in w.items.items() if i["key_"] == "icmpping"]:
            del w.items[k]                                           # no ICMP anywhere -> every device is LOW confidence
        ds, cfg, _ = dataset("executive_summary", w=w)
        doc = build(ds, cfg)
        self.assertIsNone(kpis(doc)["sla_status"]["value"])
        self.assertEqual(kpis(doc)["sla_status"]["status"], "na")
        self.assertTrue(any("SLA compliance is N/A" in f for f in doc["findings"]))

    def test_site_scorecard(self):
        br = row(self.doc, "site_scorecard", site="BR1")
        self.assertEqual(br["devices"], 3)
        self.assertEqual(br["meets_target"], "No")
        self.assertIsNotNone(br["previous_pct"])
        self.assertEqual(rows(self.doc, "incidents_by_severity")[0]["severity"], "Disaster")

    def test_wan_peak_in_exec(self):
        self.assertEqual(self.k["wan_peak_util_pct"]["value"], 80.0)
        self.assertEqual(len(rows(self.doc, "wan_summary")), 2)

    def test_without_wan_links_table_is_empty_and_kpi_na(self):
        cfg = make_cfg()
        ds, cfg, w = dataset("executive_summary", cfg=cfg)
        doc = build(ds, cfg)
        self.assertIsNone(kpis(doc)["wan_peak_util_pct"]["value"])
        self.assertEqual(rows(doc, "wan_summary"), [])

    def test_year_rollover_month(self):
        from zrs import plans
        from zrs.periods import containing
        from datetime import date, datetime
        import common
        cfg = make_cfg()
        w = world()
        now = datetime(2027, 1, 5, 7, 0, tzinfo=common.TZ)
        period = containing("monthly", date(2026, 12, 15), common.TZ)
        ds = plans.collect(w, cfg, now, "executive_summary", period)
        self.assertEqual((ds["period"]["label"], ds["previous_period"]["label"]), ("2026-12", "2026-11"))
        self.assertEqual(ds["period"]["end"], "2027-01-01T00:00:00+03:00")


class IncidentAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.cfg, cls.w = dataset("incident_analysis")
        cls.doc = build(cls.ds, cls.cfg)
        cls.k = kpis(cls.doc)

    def test_counts(self):
        self.assertEqual(self.k["incidents"]["value"], 4)                     # 20, 23, 24, 25
        self.assertEqual(self.k["incidents_started"]["value"], 4)
        self.assertEqual(self.k["incidents_resolved"]["value"], 3)            # 25 resolves after the week
        self.assertEqual(self.k["incidents_open"]["value"], 1)
        self.assertEqual(self.k["incidents_high"]["value"], 3)
        self.assertAlmostEqual(self.k["mttr_seconds"]["value"], (7200 + 1200 + 7200) / 3.0)
        self.assertAlmostEqual(self.k["ack_rate_pct"]["value"], 25.0)

    def test_spanning_incident_is_clipped_but_listed_open(self):
        r = row(self.doc, "incident_log", eventid="25")
        self.assertEqual(r["state"], "OPEN")
        self.assertEqual(r["duration_in_period_s"], 30 * 60)                  # 23:30 -> window end 00:00

    def test_recurring_and_top_devices(self):
        self.assertEqual(rows(self.doc, "recurring")[0], {"problem": "Unavailable by ICMP ping", "incidents": 3})
        self.assertEqual(rows(self.doc, "by_device")[0]["device"], "RTR-BR1")
        self.assertEqual(rows(self.doc, "by_device")[0]["incidents"], 2)

    def test_per_day_series_has_every_day(self):
        days = rows(self.doc, "by_day")
        self.assertEqual(len(days), 7)
        self.assertEqual(sum(d["started"] for d in days), 4)
        self.assertEqual(next(d for d in days if d["day"] == "2026-09-30")["started"], 1)

    def test_longest_first(self):
        self.assertEqual(rows(self.doc, "longest")[0]["eventid"] in ("20", "24"), True)

    def test_empty_period(self):
        w = world(events=False)
        ds, cfg, _ = dataset("incident_analysis", w=w)
        doc = build(ds, cfg)
        self.assertEqual(kpis(doc)["incidents"]["value"], 0)
        self.assertIsNone(kpis(doc)["mttr_seconds"]["value"])                  # no incidents -> N/A, not 0
        self.assertEqual(rows(doc, "incident_log"), [])


class Quality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.cfg, cls.w = dataset("monitoring_quality")
        cls.doc = build(cls.ds, cls.cfg)
        cls.k = kpis(cls.doc)

    def test_issue_detection(self):
        self.assertEqual(self.k["devices"]["value"], 5)
        self.assertEqual(self.k["devices_with_issues"]["value"], 3)
        self.assertEqual(row(self.doc, "device_quality", device="RTR-HQ")["issues"], "")
        self.assertIn("stale ICMP", row(self.doc, "device_quality", device="FW-HQ")["issues"])
        sw = row(self.doc, "device_quality", device="SW-BR1")["issues"]
        for part in ("no ICMP item", "no CPU item", "no memory item", "1 unsupported item(s)"):
            self.assertIn(part, sw)
        self.assertIn("state DOWN", row(self.doc, "device_quality", device="DEAD-BR1")["issues"])

    def test_unsupported_items_listed(self):
        self.assertEqual(self.k["unsupported_items"]["value"], 2)
        self.assertEqual(sorted(r["device"] for r in rows(self.doc, "unsupported")), ["DEAD-BR1", "SW-BR1"])

    def test_coverage_and_confidence(self):
        hq = row(self.doc, "device_quality", device="RTR-HQ")
        self.assertAlmostEqual(hq["icmp_coverage_pct"], 100.0)
        self.assertEqual(hq["confidence"], "HIGH")
        self.assertEqual(row(self.doc, "device_quality", device="SW-BR1")["confidence"], "NONE")

    def test_collector_diagnostics_report_truncation_and_failures(self):
        w = world()
        w.fail["item.get"] = 0
        cfg = make_cfg(limits={"items": 1})
        ds, cfg, _ = dataset("monitoring_quality", cfg=cfg, w=w)
        doc = build(ds, cfg)
        self.assertGreaterEqual(kpis(doc)["api_truncations"]["value"], 1)
        self.assertEqual(kpis(doc)["api_truncations"]["status"], "bad")
        self.assertTrue(any(d["area"] == "API truncation" and d["count"] >= 1 for d in rows(doc, "collector")))

    def test_devices_without_site_flagged(self):
        w = world()
        w.add_host("6", "ORPHAN", None, tags=[], groups=("Discovered hosts",))
        ds, cfg, _ = dataset("monitoring_quality", w=w)
        doc = build(ds, cfg)
        self.assertIn("no site", row(doc, "device_quality", device="ORPHAN")["issues"])


class Common(unittest.TestCase):
    def test_every_report_has_kpis_dictionary_audit_and_hash(self):
        for key in ("daily_network_health", "wan_isp_performance", "infrastructure_health", "executive_summary", "incident_analysis", "monitoring_quality"):
            ds, cfg, w = dataset(key)
            doc = build(ds, cfg)
            self.assertTrue(doc["kpis"], key)
            self.assertTrue(doc["dictionary"], key)
            self.assertEqual(doc["audit"]["dataset_sha256"], ds["dataset_sha256"])
            self.assertEqual(len(ds["dataset_sha256"]), 64)
            for t in doc["tables"].values():
                for r in t["rows"]:
                    self.assertEqual(set(r) - set(c["key"] for c in t["columns"]), set(), "%s/%s has undeclared keys" % (key, t["id"]))

    def test_table_column_labels_and_keys_are_unique(self):
        for key in plans.REPORTS:
            ds, cfg, w = dataset(key)
            doc = build(ds, cfg)
            for t in doc["tables"].values():
                labels = [c["label"] for c in t["columns"]]
                self.assertEqual(len(labels), len(set(labels)), "%s/%s labels" % (key, t["id"]))      # Excel tables need unique headers
                keys = [c["key"] for c in t["columns"]]
                self.assertEqual(len(keys), len(set(keys)), "%s/%s keys" % (key, t["id"]))

    def test_dataset_is_deterministic(self):
        a, _, _ = dataset("daily_network_health")
        b, _, _ = dataset("daily_network_health")
        self.assertEqual(a["dataset_sha256"], b["dataset_sha256"])

    def test_hash_changes_when_data_changes(self):
        a, _, _ = dataset("daily_network_health")
        w = world()
        w.history["101"] = w.history["101"][:-60]
        b, _, _ = dataset("daily_network_health", w=w)
        self.assertNotEqual(a["dataset_sha256"], b["dataset_sha256"])

    def test_nothing_uses_lastvalue(self):
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[2] / "reporting" / "daily-reporting" / "lib" / "zrs"
        for p in src.glob("*.py"):
            self.assertNotIn("lastvalue", p.read_text(), p.name)


if __name__ == "__main__":
    unittest.main()
