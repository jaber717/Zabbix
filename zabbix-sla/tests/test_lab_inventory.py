"""The inventory that ships for LAB, driven through the real CLI against the mock."""
import os
import unittest

from tests.helpers import World

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def lab_text(semantics=None):
    with open(os.path.join(ROOT, "inventory", "lab.yaml"), encoding="utf-8") as fh:
        t = fh.read()
    return t.replace("tag_semantics: unknown", "tag_semantics: %s" % semantics) if semantics else t


class TestShippedLab(unittest.TestCase):
    def tearDown(self):
        self.w.close()

    def test_check_is_refused_until_and_semantics_is_proven(self):
        self.w = World(inventory_text=lab_text())
        rc, out = self.w.run("check")
        self.assertEqual(rc, 1)
        self.assertIn("tag_semantics", out)
        self.assertIn("accept_tag_semantics.py", out)

    def test_apply_is_refused_while_semantics_unknown_and_nothing_is_written(self):
        self.w = World(inventory_text=lab_text())
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 1)
        self.assertEqual(self.w.mock.writes(), [])

    def test_plan_with_assumption_is_read_only_and_flagged_non_authoritative(self):
        self.w = World(inventory_text=lab_text())
        rc, out = self.w.run("--assume-tag-semantics", "and", "plan")
        self.assertEqual(rc, 0, out)
        self.assertIn("ASSUMED", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_full_apply_verify_rollback_with_proven_semantics(self):
        self.w = World(inventory_text=lab_text("and"))
        rc, out = self.w.run("check")
        self.assertEqual(rc, 0, out)
        self.assertIn("deferred", out)                      # proposed probes and the verified services are deferred
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 0, out)
        names = sorted(s["name"] for s in self.w.mock.services.values())
        self.assertEqual(len(names), 32)
        self.assertTrue(all(n.startswith("NETOPS-SLA: ") for n in names))
        self.assertEqual(len(self.w.mock.slas), 2)
        self.assertFalse([i for i in self.w.mock.items.values() if i["key_"].startswith(("sla.probe", "icmpping"))])
        self.assertEqual(self.w.mock.triggers, {})
        self.assertEqual(self.w.run("verify")[0], 0)
        rc, out = self.w.run("rollback", "--backup", self.w.backups()[0])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.mock.services, {})
        self.assertEqual(self.w.mock.slas, {})

    def test_simulate_single_isp_failure_keeps_internet_up(self):
        self.w = World(inventory_text=lab_text("and"))
        rc, out = self.w.run("simulate", "--down", "int-core--mobily")
        self.assertEqual(rc, 0, out)
        line = [x for x in out.splitlines() if x.split()[:2] == ["business", "svc.siteA.internet"]][0]
        self.assertIn("OK", line)
        rc, out = self.w.run("simulate", "--down", "int-core--mobily,int-core--stc")
        line = [x for x in out.splitlines() if x.split()[:2] == ["business", "svc.siteA.internet"]][0]
        self.assertIn("PROBLEM", line)

    def test_simulate_utilization_alert_is_not_downtime(self):
        self.w = World(inventory_text=lab_text("and"))
        rc, out = self.w.run("simulate", "--alert", "int-core--mobily:util_rx,int-core--stc:util_rx")
        self.assertNotIn("PROBLEM", out)

    def test_production_skeleton_is_empty_and_refuses_apply(self):
        with open(os.path.join(ROOT, "inventory", "production.yaml"), encoding="utf-8") as fh:
            prod = fh.read()
        self.w = World(identity="production", prod_inventory=prod)
        rc, out = self.w.run("--env", "production", "--confirm", "production", "apply")
        self.assertEqual(rc, 1)
        self.assertEqual(self.w.mock.writes(), [])


if __name__ == "__main__":
    unittest.main()
