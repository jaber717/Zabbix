import datetime
import json
import os
import unittest

from slaas.client import SlaClient
from slaas import _compat, bridge, inventory, model, reporting, slo
from slaas import state as S
from tests.helpers import MINI, World

NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc)
OCT = 31 * 86400        # October has 31 days; Asia/Riyadh has no DST


class TestSloMath(unittest.TestCase):
    def a(self, **kw):
        row = {"uptime": OCT - 60, "downtime": 60, "sli": 100.0 * (OCT - 60) / OCT, "error_budget": 0, "excluded_downtime": 0}
        row.update(kw.pop("row", {}))
        args = dict(slo=99.9, period_seconds=OCT, window_seconds=OCT)
        args.update(kw)
        return slo.assess(row, **args)

    def test_compliant(self):
        r = self.a()
        self.assertEqual(r["state"], slo.COMPLIANT)
        self.assertAlmostEqual(r["budget_total_s"], OCT * 0.001, places=3)
        self.assertAlmostEqual(r["budget_remaining_s"], OCT * 0.001 - 60, places=3)
        self.assertLess(r["burn_rate"], 1)

    def test_breached_when_sli_below_slo(self):
        r = self.a(row={"uptime": OCT - 4000, "downtime": 4000, "sli": 100.0 * (OCT - 4000) / OCT})
        self.assertEqual(r["state"], slo.BREACHED)
        self.assertLess(r["budget_remaining_s"], 0)
        self.assertGreater(r["burn_rate"], 1)

    def test_no_sli_is_insufficient_never_100(self):
        r = self.a(row={"uptime": 0, "downtime": 0, "sli": -1})
        self.assertEqual(r["state"], slo.INSUFFICIENT)
        self.assertIsNone(r["sli_pct_reportable"])

    def test_perfect_sli_with_low_coverage_is_insufficient(self):
        r = self.a(row={"uptime": 3600, "downtime": 0, "sli": 100.0})
        self.assertEqual(r["state"], slo.INSUFFICIENT)
        self.assertIsNone(r["sli_pct_reportable"])
        self.assertTrue(any("recorded status" in x for x in r["reasons"]))

    def test_blind_signal_is_insufficient_even_with_perfect_sli(self):
        r = self.a(row={"uptime": OCT, "downtime": 0, "sli": 100.0}, signal_quality="blind")
        self.assertEqual(r["state"], slo.INSUFFICIENT)

    def test_partial_signal_is_compliant_with_a_caveat(self):
        r = self.a(row={"uptime": OCT, "downtime": 0, "sli": 100.0}, signal_quality="partial")
        self.assertEqual(r["state"], slo.COMPLIANT)
        self.assertTrue(any("partial signal" in c for c in r["caveats"]))

    def test_certain_breach_survives_incomplete_data(self):
        r = self.a(row={"uptime": 100000, "downtime": 5000, "sli": 95.2})
        self.assertEqual(r["state"], slo.BREACHED)
        self.assertTrue(any("certain" in c for c in r["caveats"]))

    def test_t3_needs_fresh_probe_data(self):
        good = self.a(tier="T3", stale_seconds=0)
        stale = self.a(tier="T3", stale_seconds=OCT * 0.10)
        unknown = self.a(tier="T3", stale_seconds=None)
        self.assertEqual(good["state"], slo.COMPLIANT)
        self.assertEqual(stale["state"], slo.INSUFFICIENT)
        self.assertEqual(unknown["state"], slo.INSUFFICIENT)

    def test_excluded_downtime_counts_as_seen_not_as_downtime(self):
        r = self.a(row={"uptime": OCT - 7200, "downtime": 0, "excluded_downtime": 7200, "sli": 100.0})
        self.assertEqual(r["state"], slo.COMPLIANT)
        self.assertEqual(r["budget_consumed_s"], 0)
        self.assertGreaterEqual(r["coverage"], 0.99)

    def test_partial_month_is_flagged(self):
        r = slo.assess({"uptime": 86400, "downtime": 0, "sli": 100.0}, 99.9, OCT, 86400)
        self.assertTrue(r["partial_period"])
        self.assertEqual(r["state"], slo.COMPLIANT)

    def test_link_quality_classes(self):
        self.assertEqual(slo.link_quality([], 2)[0], "MISSING")
        self.assertEqual(slo.link_quality([{"status": "1"}], 2)[0], "DISABLED")
        self.assertEqual(slo.link_quality([{"status": "0", "state": "1", "error": "x"}], 1)[0], "UNKNOWN")
        self.assertEqual(slo.link_quality([{"status": "0", "state": "0"}], 2)[0], "PARTIAL")
        self.assertEqual(slo.link_quality([{"status": "0"}, {"status": "0"}], 2)[0], "OK")
        self.assertEqual(slo.service_signal_quality(["OK", "MISSING"], False), "blind")
        self.assertEqual(slo.service_signal_quality(["OK", "PARTIAL"], False), "partial")
        self.assertEqual(slo.service_signal_quality(["OK"], True), "partial")


class ReportBase(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.w.mock.add_host("RTR-02", ["Gi0/0"])
        self.w.run("apply")
        data = inventory.yaml.load(MINI, Loader=inventory.UniqueKeyLoader)
        self.desired = model.compile_inventory(inventory.validate(data))
        self.client = SlaClient(self.w.mock.transport("tok"), read_only=True)
        self.env = {"environment": "lab"}
        self.p_from = int(datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=3))).timestamp())
        self.w.mock.sli_periods = [{"period_from": str(self.p_from), "period_to": str(self.p_from + OCT - 1)}]

    def tearDown(self):
        self.w.close()

    def add_link_triggers(self, links=("lx", "ly", "lz"), hosts=("RTR-01", "RTR-02")):
        for h in hosts:
            for lid in links:
                self.w.mock.m_trigger_create({"description": "Link down %s %s" % (h, lid), "expression": "last(/%s/net.if.in[Gi0/0])=0" % h, "priority": 5,
                                              "tags": [{"tag": "link_id", "value": lid}, {"tag": "netops_alert", "value": "link_down"}]})

    def sid(self, sla_id):
        for s in self.w.mock.services.values():
            if dict((t["tag"], t["value"]) for t in s["tags"]).get("sla_id") == sla_id:
                return s["serviceid"]

    def slaid(self, cls):
        for a in self.w.mock.slas.values():
            if "sla_id=%s " % cls in a["description"]:
                return a["slaid"]

    def feed(self, sla_id, cls, up, down, sli, excl=0):
        self.w.mock.sli_data[(self.slaid(cls), self.sid(sla_id))] = [{"uptime": up, "downtime": down, "sli": sli, "error_budget": 0, "excluded_downtime": excl}]

    def report(self):
        return reporting.build_report(self.client, self.desired, "2026-10", self.env, "7.0.30", NOW)

    def by(self, rep, sid):
        return next(s for s in rep["services"] if s["sla_id"] == sid)


class TestReport(ReportBase):
    def good(self):
        self.add_link_triggers()
        for sid in ("svc.net",):
            self.feed(sid, "std", OCT - 60, 60, 99.998)
        self.feed("svc.net.verified", "ver", OCT, 0, 100.0)
        self.feed("quality.probe.net", "data-freshness", OCT, 0, 100.0)

    def test_compliant_when_everything_is_monitored_and_fresh(self):
        self.good()
        rep = self.report()
        self.assertEqual(self.by(rep, "svc.net")["state"], slo.COMPLIANT)
        self.assertEqual(self.by(rep, "svc.net.verified")["state"], slo.COMPLIANT)
        self.assertEqual(self.by(rep, "svc.net")["evidence"], "inferred from link state")
        self.assertEqual(self.by(rep, "svc.net.verified")["evidence"], "verified end to end")
        self.assertEqual(rep["summary"][slo.COMPLIANT], 2)

    def test_service_without_any_status_history_is_not_reported_as_available(self):
        self.add_link_triggers()
        rep = self.report()               # no sli rows at all
        for s in rep["services"]:
            self.assertEqual(s["state"], slo.INSUFFICIENT)
            self.assertIsNone(s["sli_pct_reportable"])

    def test_link_without_a_signal_makes_the_service_blind(self):
        self.add_link_triggers(links=("lx", "ly"))                      # lz has NO link_down trigger anywhere
        self.feed("svc.net", "std", OCT, 0, 100.0)
        rep = self.report()
        r = self.by(rep, "svc.net")
        self.assertEqual(r["signal_quality"], "blind")
        self.assertEqual(r["state"], slo.INSUFFICIENT)
        self.assertIsNone(r["sli_pct_reportable"])
        self.assertTrue(any("lz" in c for c in r["caveats"] + r["reasons"]))

    def test_one_monitored_end_only_is_partial_with_caveat(self):
        self.add_link_triggers(hosts=("RTR-01",))
        self.feed("svc.net", "std", OCT, 0, 100.0)
        r = self.by(self.report(), "svc.net")
        self.assertEqual(r["signal_quality"], "partial")
        self.assertEqual(r["state"], slo.COMPLIANT)
        self.assertTrue(any("monitored" in c for c in r["caveats"]))

    def test_stale_probe_blocks_a_verified_statement(self):
        self.add_link_triggers()
        self.feed("svc.net.verified", "ver", OCT, 0, 100.0)
        self.feed("quality.probe.net", "data-freshness", OCT - 400000, 400000, 85.0)
        r = self.by(self.report(), "svc.net.verified")
        self.assertEqual(r["state"], slo.INSUFFICIENT)

    def test_breach_is_reported_with_negative_budget(self):
        self.add_link_triggers()
        self.feed("svc.net", "std", OCT - 9000, 9000, 99.71)
        r = self.by(self.report(), "svc.net")
        self.assertEqual(r["state"], slo.BREACHED)
        self.assertLess(r["budget_remaining_s"], 0)

    def test_unprovisioned_sla_is_reported_not_guessed(self):
        self.add_link_triggers()
        self.w.mock.slas.clear()
        rep = self.report()
        self.assertEqual(rep["services"], [])
        self.assertTrue(any("not provisioned" in x for x in rep["warnings"]))
        self.assertTrue(any("nothing is reported as available" in x for x in rep["warnings"]))

    def test_unapproved_slo_is_flagged_in_the_report(self):
        self.add_link_triggers()
        self.feed("svc.net", "std", OCT, 0, 100.0)
        self.desired.slas["std"]["approved"] = False
        self.assertTrue(any("placeholder" in c for c in self.by(self.report(), "svc.net")["caveats"]))

    def test_report_makes_no_writes(self):
        self.good()
        before = len(self.w.mock.writes())
        self.report()
        self.assertEqual(len(self.w.mock.writes()), before)

    def test_provider_claims_are_kept_separate(self):
        self.good()
        self.assertIn("NOT part of this report", self.report()["provider_sla"]["note"])

    def test_planned_downtime_is_listed(self):
        self.good()
        a = self.desired.slas["std"]
        a["excluded_downtimes"] = [{"name": "PD pd1 CHG-1", "period_from": self.p_from + 3600, "period_to": self.p_from + 7200}]
        rep = self.report()
        self.assertEqual([e["name"] for e in rep["planned_downtime"]], ["PD pd1 CHG-1"])

    def test_cli_report_and_quality(self):
        self.add_link_triggers()
        self.feed("svc.net", "std", OCT, 0, 100.0)
        rc, out = self.w.run("quality")
        self.assertEqual(rc, 0, out)
        path = os.path.join(self.w.base, "r.json")
        suite = os.path.join(self.w.base, "doc.json")
        rc, out = self.w.run("report", "--month", "2026-10", "--out", path, "--suite-doc", suite)
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.load(open(path, encoding="utf-8"))["schema"], reporting.SCHEMA)
        self.assertEqual(json.load(open(suite, encoding="utf-8"))["schema"], bridge.DOC_SCHEMA)
        self.assertEqual(self.w.mock.writes().count("sla.getsli"), 0)

    def test_cli_quality_flags_missing_signal_with_exit_2(self):
        rc, out = self.w.run("quality")
        self.assertEqual(rc, 2)
        self.assertIn("MISSING", out)


class TestBridge(ReportBase):
    def test_document_has_the_suite_shape_and_survives_json(self):
        self.add_link_triggers(links=("lx", "ly"))
        self.feed("svc.net", "std", OCT, 0, 100.0)
        doc = bridge.to_suite_document(self.report(), "zabbix-sla/test")
        for key in ("schema", "report", "title", "subtitle", "period", "generated_at", "timezone", "dataset_sha256", "source", "kpis", "findings",
                    "sections", "tables", "charts", "dictionary", "warnings", "audit"):
            self.assertIn(key, doc)
        for k in doc["kpis"]:
            self.assertEqual(sorted(k), sorted(["id", "label", "value", "unit", "status", "note", "coverage", "formula", "decimals"]))
        for t in doc["tables"].values():
            self.assertEqual(sorted(t), sorted(["id", "title", "columns", "rows", "note", "pdf_limit", "empty_text"]))
            keys = [c["key"] for c in t["columns"]]
            for r in t["rows"]:
                self.assertEqual(list(r), keys)
            for c in t["columns"]:
                self.assertIn(c["type"], ("text", "int", "float1", "float2", "pct", "bps", "seconds", "datetime", "status"))
        for s in doc["sections"]:
            for tid in s["tables"]:
                self.assertIn(tid, doc["tables"])
        json.dumps(doc)

    def test_insufficient_data_is_never_a_percentage_in_the_document(self):
        self.add_link_triggers(links=("lx", "ly"))                      # lz blind
        self.feed("svc.net", "std", OCT, 0, 100.0)
        doc = bridge.to_suite_document(self.report(), "x")
        row = next(r for r in doc["tables"]["services"]["rows"] if r["name"] == "Business svc.net" or r["name"].endswith("svc.net"))
        self.assertEqual(row["state"], "INSUFFICIENT_DATA")
        self.assertIsNone(row["sli"])
        self.assertTrue(any("INSUFFICIENT" in f or "insufficient" in f for f in doc["findings"]))

    def test_human_seconds(self):
        self.assertEqual(bridge.human_seconds(59), "59s")
        self.assertEqual(bridge.human_seconds(3660), "1h 01m")
        self.assertEqual(bridge.human_seconds(-90), "-1m 30s")


if __name__ == "__main__":
    unittest.main()
