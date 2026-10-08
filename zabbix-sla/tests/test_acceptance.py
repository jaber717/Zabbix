import unittest

from slaas import acceptance, dashboards
from slaas.client import SlaClient
from tests.helpers import World


class TestTagSemanticsAcceptance(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.client = SlaClient(self.w.mock.transport("tok"))

    def tearDown(self):
        self.w.close()

    def run_it(self):
        return acceptance.tag_semantics(self.client, "RTR-01", "net.if.in[Gi0/0]", timeout=0, interval=1, sleep=lambda s: None, log=lambda m: None)

    def test_proves_and(self):
        self.w.mock.semantics = "and"
        r = self.run_it()
        self.assertEqual(r["outcome"], "and", r)
        self.assertEqual(r["cleanup"], "ok")

    def test_proves_or(self):
        self.w.mock.semantics = "or"
        r = self.run_it()
        self.assertEqual(r["outcome"], "or", r)

    def test_cleans_up_everything(self):
        self.run_it()
        self.assertEqual(self.w.mock.services, {})
        self.assertEqual(self.w.mock.triggers, {})

    def test_inconclusive_when_the_control_never_fires(self):
        orig = self.w.mock._status
        self.w.mock._status = lambda sid, memo=None: -1
        r = self.run_it()
        self.assertEqual(r["outcome"], "inconclusive")
        self.assertIn("control", r["detail"])
        self.w.mock._status = orig

    def test_cleanup_failure_is_reported_loudly(self):
        self.w.mock.fail_on["service.delete"] = 1
        r = self.run_it()
        self.assertTrue(r["cleanup"].startswith("FAILED"))

    def test_unknown_host_is_inconclusive_and_creates_nothing(self):
        r = acceptance.tag_semantics(self.client, "NOPE", "x", timeout=0, sleep=lambda s: None, log=lambda m: None)
        self.assertEqual(r["outcome"], "inconclusive")
        self.assertEqual(self.w.mock.writes(), [])

    def test_never_uses_netops_tags(self):
        self.run_it()
        # the temporary trigger was already deleted; check the calls instead of the state
        self.assertTrue(all("netops" not in str(m) for m, ok in self.w.mock.calls))
        self.assertNotIn("netops_alert", acceptance.ACC_TAG_A + acceptance.ACC_TAG_B)


class TestApiShapes(unittest.TestCase):
    def test_passes_against_provisioned_lab(self):
        w = World()
        try:
            w.run("apply")
            res = acceptance.api_shapes(SlaClient(w.mock.transport("tok"), read_only=True))
            failed = [c for c in res["checks"] if not c["ok"]]
            self.assertEqual(failed, [])
        finally:
            w.close()

    def test_empty_lab_fails_with_a_clear_instruction(self):
        w = World()
        try:
            res = acceptance.api_shapes(SlaClient(w.mock.transport("tok"), read_only=True))
            self.assertFalse(res["ok"])
            self.assertTrue(any("apply the LAB inventory first" in c["detail"] for c in res["checks"]))
        finally:
            w.close()


class TestWidgetEvidence(unittest.TestCase):
    ROW = {"name": "x", "pages": [{"widgets": [
        {"type": "slareport", "fields": [{"type": "10", "name": "slaid.0", "value": "55"}, {"type": "9", "name": "serviceid.0", "value": "77"}, {"type": "0", "name": "show_periods", "value": "7"}]},
        {"type": "problems", "fields": [{"type": "1", "name": "tags.0.tag", "value": "netops_alert"}, {"type": "0", "name": "tags.0.operator", "value": "1"},
                                        {"type": "1", "name": "tags.0.value", "value": "link_down"}, {"type": "0", "name": "show_tags", "value": "3"}]}]}]}

    def test_derives_types_and_names(self):
        ev = dashboards.derive_evidence(self.ROW, 55, 77, 7)
        self.assertEqual(ev["field_types"], {"sla": 10, "service": 9, "int": 0, "str": 1})
        self.assertEqual(ev["field_names"]["sla"], "slaid.0")
        self.assertEqual(ev["field_names"]["tag"], "tags.%d.tag")

    def test_missing_pieces_are_reported_not_guessed(self):
        row = {"pages": [{"widgets": [{"type": "slareport", "fields": [{"type": "10", "name": "slaid.0", "value": "55"}]}]}]}
        with self.assertRaises(dashboards.DashboardError) as cm:
            dashboards.derive_evidence(row, 55, 77, 7)
        self.assertIn("service", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
