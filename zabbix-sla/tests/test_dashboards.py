import json
import os
import unittest

from slaas import dashboards as D
from tests.helpers import World, write

SPEC = """\
name: Test board
pages:
  - name: P
    widgets:
      - {type: slareport, name: A, x: 0, y: 0, width: 12, height: 5, fields: {sla: std, service: svc.net, show_periods: 3}}
      - {type: problems, name: B, x: 12, y: 0, width: 12, height: 5, fields: {tags: [{tag: netops_alert, operator: 1, value: link_down}], show_tags: 3}}
"""


class TestDashboards(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.w.run("apply")
        write(os.path.join(self.w.base, "dashboards", "t.yaml"), SPEC)

    def tearDown(self):
        self.w.close()

    def verify_types(self):
        write(os.path.join(self.w.base, "evidence", "widget-field-types.json"), json.dumps({"verified": True, "field_types": {"service": 9, "sla": 10}}))

    def test_plan_works_without_evidence_but_says_unverified(self):
        rc, out = self.w.run("dashboards", "plan")
        self.assertEqual(rc, 0, out)
        self.assertIn("CREATE", out)
        self.assertIn("UNVERIFIED", out)
        self.assertEqual(self.w.mock.dashboards, {})

    def test_apply_is_refused_until_field_types_are_verified(self):
        rc, out = self.w.run("dashboards", "apply")
        self.assertEqual(rc, 1)
        self.assertIn("not verified", out)
        self.assertEqual(self.w.mock.dashboards, {})

    def test_apply_with_evidence_creates_then_is_idempotent(self):
        self.verify_types()
        rc, out = self.w.run("dashboards", "apply")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.w.mock.dashboards), 1)
        d = list(self.w.mock.dashboards.values())[0]
        self.assertEqual(d["name"], "NETOPS-SLA: Test board")
        names = sorted(f["name"] for f in d["pages"][0]["widgets"][0]["fields"])
        self.assertEqual(names, ["serviceid.0", "show_periods", "slaid.0"])
        rc, out = self.w.run("dashboards", "plan")
        self.assertIn("no changes", out)
        self.assertNotIn("UNVERIFIED", out)

    def test_drift_in_a_widget_is_detected_and_repaired(self):
        self.verify_types()
        self.w.run("dashboards", "apply")
        d = list(self.w.mock.dashboards.values())[0]
        d["pages"][0]["widgets"][0]["width"] = 6
        rc, out = self.w.run("dashboards", "plan")
        self.assertIn("UPDATE", out)
        self.w.run("dashboards", "apply")
        self.assertIn("no changes", self.w.run("dashboards", "plan")[1])

    def test_unknown_service_is_reported_not_guessed(self):
        write(os.path.join(self.w.base, "dashboards", "t.yaml"), SPEC.replace("svc.net", "svc.nope"))
        rc, out = self.w.run("dashboards", "plan")
        self.assertIn("not provisioned", out)
        self.assertNotIn("CREATE", out)

    def test_foreign_dashboards_are_never_touched(self):
        self.w.mock.m_dashboard_create({"name": "Someone else", "pages": []})
        self.verify_types()
        self.w.run("dashboards", "apply")
        self.assertEqual(len(self.w.mock.dashboards), 2)

    def test_production_dashboard_apply_needs_confirm(self):
        w = World(identity="production")
        try:
            rc, out = w.run("--env", "production", "dashboards", "apply")
            self.assertEqual(rc, 1)
            self.assertIn("--confirm", out)
        finally:
            w.close()

    def test_shipped_specs_parse(self):
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        specs = D.load_specs(base)
        self.assertEqual(sorted(s["name"] for s in specs), ["Executive service availability", "NOC service view"])


if __name__ == "__main__":
    unittest.main()
