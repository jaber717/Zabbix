import datetime
import json
import unittest

from slaas import evaluator, inventory, model
from tests.helpers import MINI, World


class FlowBase(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()


class TestCheck(FlowBase):
    def test_check_is_offline_and_ok(self):
        rc, out = self.w.run("check")
        self.assertEqual(rc, 0, out)
        self.assertIn("inventory OK", out)
        self.assertEqual(self.w.mock.calls, [])           # nothing contacted

    def test_check_rejects_wrong_environment_inventory(self):
        self.w.set_inventory(MINI.replace("environment: lab", "environment: production"))
        rc, out = self.w.run("check")
        self.assertEqual(rc, 1)
        self.assertIn("declares environment='production'", out)


class TestPlanApplyVerify(FlowBase):
    def test_plan_is_read_only_and_lists_creates(self):
        rc, out = self.w.run("plan")
        self.assertEqual(rc, 0, out)
        self.assertIn("CREATE", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_apply_creates_everything_and_verifies(self):
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("readback verification: PASS", out)
        m = self.w.mock
        self.assertTrue(m.services and m.slas and m.triggers)
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 0, out)

    def test_second_apply_is_a_noop(self):
        self.w.run("apply")
        before = self.w.mock.sla_snapshot()
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 0)
        self.assertIn("no changes", out)
        self.assertEqual(before, self.w.mock.sla_snapshot())
        self.assertEqual(len(self.w.backups()), 1)         # the no-op did not take a second backup

    def test_redundancy_is_parallel_in_zabbix(self):
        self.w.run("apply")
        by = dict((dict((t["tag"], t["value"]) for t in s["tags"])["sla_id"], s) for s in self.w.mock.services.values())
        self.assertEqual(by["conn.net"]["algorithm"], "1")          # most critical if ALL children have problems
        self.assertEqual(by["p.a"]["algorithm"], "2")               # series
        kids = sorted(dict((t["tag"], t["value"]) for t in self.w.mock.services[c]["tags"])["sla_id"] for c in by["conn.net"]["children"])
        self.assertEqual(kids, ["p.a", "p.b"])

    def test_link_condition_needs_link_id_and_link_down(self):
        self.w.run("apply")
        by = dict((dict((t["tag"], t["value"]) for t in s["tags"])["sla_id"], s) for s in self.w.mock.services.values())
        pt = sorted((t["tag"], t["value"]) for t in by["c.x"]["problem_tags"])
        self.assertEqual(pt, [("link_id", "lx"), ("netops_alert", "link_down")])

    def test_probe_objects_created_on_runner(self):
        self.w.run("apply")
        m = self.w.mock
        keys = sorted(i["key_"] for i in m.items.values() if i["key_"].startswith(("icmpping", "sla.probe")))
        self.assertEqual(keys, ["icmpping[192.0.2.1,3,200,,1000]", "icmpping[192.0.2.2,3,200,,1000]", "icmpping[192.0.2.3,3,200,,1000]", "sla.probe.up[probe.net]"])
        descs = sorted(t["description"] for t in m.triggers.values())
        self.assertEqual(len(descs), 2)
        self.assertTrue(all(d.startswith("[NETOPS-SLA] ") for d in descs))


class TestDrift(FlowBase):
    def setUp(self):
        FlowBase.setUp(self)
        self.w.run("apply")

    def _svc(self, sla_id):
        for s in self.w.mock.services.values():
            if dict((t["tag"], t["value"]) for t in s["tags"]).get("sla_id") == sla_id:
                return s

    def test_changed_algorithm_is_semantic_drift(self):
        self._svc("conn.net")["algorithm"] = "2"
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 2)
        self.assertIn("conn.net", out)
        self.assertIn("algorithm", out)

    def test_changed_problem_tag_is_drift_and_apply_repairs(self):
        self._svc("c.x")["problem_tags"] = [{"tag": "netops_alert", "operator": "0", "value": "util_rx"}]
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 2)
        self.assertIn("problem_tags", out)
        self.assertEqual(self.w.run("apply")[0], 0)
        self.assertEqual(self.w.run("verify")[0], 0)

    def test_removed_child_link_is_drift(self):
        self._svc("conn.net")["children"] = self._svc("conn.net")["children"][:1]
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 2)
        self.assertIn("children", out)

    def test_changed_slo_is_drift(self):
        for s in self.w.mock.slas.values():
            s["slo"] = "90.0"
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 2)
        self.assertIn("slo", out)

    def test_service_ids_do_not_matter_only_meaning(self):
        # delete + recreate the same service by hand: ids change, meaning does not -> no drift in services
        s = self._svc("p.b")
        self.assertIsNotNone(s)
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 0, out)

    def test_operator_added_child_is_preserved(self):
        manual = self.w.mock.m_service_create({"name": "Manual", "algorithm": 2})["serviceids"][0]
        root = self._svc("root")
        root["children"].append(manual)
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 0, out)                        # a foreign child is not drift
        self._svc("conn.net")["algorithm"] = "2"
        self.assertEqual(self.w.run("apply")[0], 0)
        self.assertIn(manual, self._svc("root")["children"])


class TestOwnership(FlowBase):
    def test_unmanaged_service_with_same_name_is_a_conflict_not_adopted(self):
        self.w.mock.m_service_create({"name": "NETOPS-SLA: Link lx", "algorithm": 2})
        rc, out = self.w.run("plan")
        self.assertEqual(rc, 1)
        self.assertIn("never adopted", out)
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 1)
        self.assertEqual(self.w.mock.writes(), [])

    def test_orphans_are_kept_unless_prune(self):
        self.w.run("apply")
        trimmed = MINI.replace("  c.z: {kind: link, link_id: lz}\n", "").replace("  p.b: {components: [c.z]}\n", "").replace("[p.a, p.b]", "[p.a]")
        self.w.set_inventory(trimmed)
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("ORPHAN", out)
        self.assertTrue(any(dict((t["tag"], t["value"]) for t in s["tags"]).get("sla_id") == "c.z" for s in self.w.mock.services.values()))
        rc, out = self.w.run("apply", "--prune")
        self.assertEqual(rc, 0, out)
        self.assertFalse(any(dict((t["tag"], t["value"]) for t in s["tags"]).get("sla_id") == "c.z" for s in self.w.mock.services.values()))

    def test_foreign_objects_are_never_touched(self):
        fid = self.w.mock.m_service_create({"name": "Someone else", "algorithm": 0})["serviceids"][0]
        self.w.run("apply", "--prune")
        self.w.run("apply", "--prune")
        self.assertIn(fid, self.w.mock.services)

    def test_empty_desired_is_refused(self):
        self.w.set_inventory("schema: zabbix-sla-inventory-v1\nenvironment: lab\ntag_semantics: and\n")
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 1)
        self.assertIn("empty", out)
        self.assertEqual(self.w.mock.writes(), [])


if __name__ == "__main__":
    unittest.main()


class TestHistoryImmutable(unittest.TestCase):
    PD = ("planned_downtime:\n  - {id: pd1, slas: [std], start: '%s', end: '%s', reason: Maintenance, ticket: CHG-1, approver: noc-lead}\n")

    def setUp(self):
        from tests.helpers import MINI
        self.base = MINI.replace("planned_downtime: []\n", "")
        self.w = World(inventory_text=self.base)
        self.w.run("apply")

    def tearDown(self):
        self.w.close()

    def test_new_window_in_a_closed_month_is_refused_by_the_planner(self):
        self.w.set_inventory(self.base + self.PD % ("2026-01-10T01:00:00+03:00", "2026-01-10T03:00:00+03:00"))
        rc, out = self.w.run("plan")
        self.assertEqual(rc, 1)
        self.assertIn("closed month", out)
        self.assertEqual(self.w.run("apply")[0], 1)

    def test_window_in_the_current_or_future_is_accepted_and_applied(self):
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
        a = future.replace(hour=1, minute=0, second=0, microsecond=0)
        b = a + datetime.timedelta(hours=2)
        self.w.set_inventory(self.base + self.PD % (a.isoformat(), b.isoformat()))
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 0, out)
        names = [e["name"] for s in self.w.mock.slas.values() for e in s["excluded_downtimes"]]
        self.assertEqual(len(names), 1)
        self.assertIn("CHG-1", names[0])
        # removing it again is allowed while it is not in a closed month
        self.w.set_inventory(self.base)
        self.assertEqual(self.w.run("apply")[0], 0)
        self.assertFalse([e for s in self.w.mock.slas.values() for e in s["excluded_downtimes"]])

    def test_effective_date_cannot_be_moved_once_reached(self):
        self.w.set_inventory(self.base.replace("effective_date: 2026-01-01, timezone: Asia/Riyadh}\n  ver", "effective_date: 2026-03-01, timezone: Asia/Riyadh}\n  ver"))
        rc, out = self.w.run("plan")
        self.assertEqual(rc, 1)
        self.assertIn("effective_date", out)

    def test_existing_closed_month_window_is_kept_and_not_flagged(self):
        # simulate an entry that was applied while its month was current, then the month closed
        sla = next(s for s in self.w.mock.slas.values() if "sla_id=std " in s["description"])
        a = datetime.datetime(2026, 1, 10, 1, 0, tzinfo=datetime.timezone.utc)
        sla["excluded_downtimes"] = [{"name": "PD pd1 CHG-1", "period_from": str(int(a.timestamp())), "period_to": str(int(a.timestamp()) + 7200)}]       # Jan 2026
        self.w.set_inventory(self.base + self.PD % (a.isoformat(), (a + datetime.timedelta(hours=2)).isoformat()))
        rc, out = self.w.run("verify")
        self.assertEqual(rc, 0, out)
        # but silently deleting history is refused
        self.w.set_inventory(self.base)
        rc, out = self.w.run("plan")
        self.assertEqual(rc, 1)
        self.assertIn("closed month", out)
