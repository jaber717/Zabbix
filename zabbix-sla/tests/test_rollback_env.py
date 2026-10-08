import json
import os
import unittest

from slaas.client import SlaClient
from slaas import state as S
from tests.helpers import MINI, World


def norm(world):
    """Semantic state of everything the project owns, ids stripped."""
    client = SlaClient(world.mock.transport("tok"))
    st = S.read_live(client)[0]
    return dict((k, dict((n, dict((f, v) for f, v in o.items() if not f.startswith("_")) ) for n, o in objs.items())) for k, objs in st.items())


class TestRollback(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def test_rollback_of_first_apply_returns_to_empty_and_spares_foreign(self):
        foreign = self.w.mock.m_service_create({"name": "Not ours", "algorithm": 0})["serviceids"][0]
        self.assertEqual(self.w.run("apply")[0], 0)
        backup = self.w.backups()[0]
        rc, out = self.w.run("rollback", "--backup", backup)
        self.assertEqual(rc, 0, out)
        self.assertIn("readback verification: PASS", out)
        self.assertEqual(sum(len(v) for v in norm(self.w).values()), 0)
        self.assertEqual(list(self.w.mock.services), [foreign])
        self.assertFalse([i for i in self.w.mock.items.values() if i["key_"].startswith("sla.probe")])

    def test_rollback_restores_previous_version_exactly(self):
        self.w.run("apply")
        v1 = norm(self.w)
        self.w.set_inventory(MINI.replace("slo: 99.9", "slo: 99.95").replace("  c.z: {kind: link, link_id: lz}\n", "  c.z: {kind: link, link_id: lz}\n  c.w: {kind: link, link_id: lw}\n")
                             .replace("p.b: {components: [c.z]}", "p.b: {components: [c.z, c.w]}"))
        self.assertEqual(self.w.run("apply")[0], 0)
        v2 = norm(self.w)
        self.assertNotEqual(v1, v2)
        backup = self.w.backups()[-1]
        rc, out = self.w.run("rollback", "--backup", backup)
        self.assertEqual(rc, 0, out)
        self.assertEqual(norm(self.w), v1)

    def test_partial_failure_midway_is_recoverable(self):
        pre = norm(self.w)
        self.w.mock.fail_on["sla.create"] = 1
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 1)
        self.assertIn("rollback --backup", out)
        self.assertTrue(self.w.mock.services, "services were created before the failure")
        self.w.mock.fail_on.clear()
        rc, out = self.w.run("rollback", "--backup", self.w.backups()[0])
        self.assertEqual(rc, 0, out)
        self.assertEqual(norm(self.w), pre)
        journals = os.listdir(os.path.join(self.w.base, "state", "journal"))
        self.assertTrue(journals)

    def test_failure_in_trigger_step_leaves_no_half_probe_after_rollback(self):
        self.w.mock.fail_on["trigger.create"] = 2
        rc, _ = self.w.run("apply")
        self.assertEqual(rc, 1)
        self.w.mock.fail_on.clear()
        self.assertEqual(self.w.run("rollback", "--backup", self.w.backups()[0])[0], 0)
        self.assertFalse([i for i in self.w.mock.items.values() if i["key_"].startswith(("sla.probe", "icmpping"))])
        self.assertFalse(self.w.mock.triggers)

    def test_rollback_is_itself_reversible(self):
        self.w.run("apply")
        v1 = norm(self.w)
        self.w.run("rollback", "--backup", self.w.backups()[0])
        self.assertEqual(len(self.w.backups()), 2)
        self.assertEqual(self.w.run("rollback", "--backup", self.w.backups()[1])[0], 0)
        self.assertEqual(norm(self.w), v1)

    def test_backup_of_another_environment_is_refused(self):
        self.w.run("apply")
        path = self.w.backups()[0]
        with open(path) as fh:
            data = json.load(fh)
        data["environment"] = "production"
        with open(path, "w") as fh:
            json.dump(data, fh)
        rc, out = self.w.run("rollback", "--backup", path)
        self.assertEqual(rc, 1)
        self.assertIn("for environment 'production'", out)

    def test_backup_file_is_private_and_holds_no_secret(self):
        self.w.run("apply")
        with open(self.w.backups()[0]) as fh:
            text = fh.read()
        self.assertNotIn("tok", text.replace("token", ""))


class TestEnvironmentIsolation(unittest.TestCase):
    def tearDown(self):
        self.w.close()

    def test_identity_mismatch_blocks_everything(self):
        self.w = World(identity="production")
        for cmd in ("plan", "verify", "apply"):
            rc, out = self.w.run(cmd)
            self.assertEqual(rc, 1, cmd)
            self.assertIn("IDENTITY MISMATCH", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_uninitialised_identity_allows_plan_but_never_apply(self):
        self.w = World(identity=None)
        self.assertEqual(self.w.run("plan")[0], 0)
        rc, out = self.w.run("apply")
        self.assertEqual(rc, 1)
        self.assertIn("does not claim a server", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_production_apply_needs_confirm_and_checks_before_contact(self):
        self.w = World(identity="production")
        rc, out = self.w.run("--env", "production", "apply")
        self.assertEqual(rc, 1)
        self.assertIn("--confirm production", out)
        self.assertEqual(self.w.mock.calls, [])             # refused before the server was even contacted

    def test_production_rollback_needs_confirm(self):
        self.w = World(identity="production")
        rc, out = self.w.run("--env", "production", "rollback", "--backup", "x.json")
        self.assertEqual(rc, 1)
        self.assertIn("--confirm production", out)

    def test_production_refuses_unapproved_slo(self):
        self.w = World(identity="production", prod_inventory=MINI.replace("environment: lab", "environment: production").replace("approved: true", "approved: false"))
        rc, out = self.w.run("--env", "production", "plan")
        self.assertEqual(rc, 1)
        self.assertIn("not approved", out)

    def test_production_apply_with_confirm_and_correct_identity(self):
        self.w = World(identity="production")
        rc, out = self.w.run("--env", "production", "--confirm", "production", "apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("(PRODUCTION)", out)

    def test_lab_inventory_cannot_be_applied_to_production(self):
        self.w = World(identity="production", prod_inventory=MINI)             # production.yaml mistakenly declares environment: lab
        rc, out = self.w.run("--env", "production", "--confirm", "production", "apply")
        self.assertEqual(rc, 1)
        self.assertIn("declares environment='lab'", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_production_url_pointing_at_lab_is_blocked(self):
        self.w = World(identity="production")
        self.w.env_vars["ZABBIX_SLA_URL_PRODUCTION"] = "https://zbx.lab.example"
        rc, out = self.w.run("--env", "production", "--confirm", "production", "apply")
        self.assertEqual(rc, 1)
        self.assertEqual(self.w.mock.writes(), [])

    def test_assume_tag_semantics_can_never_write(self):
        self.w = World()
        rc, out = self.w.run("--assume-tag-semantics", "and", "apply")
        self.assertEqual(rc, 1)
        self.assertEqual(self.w.mock.writes(), [])

    def test_unknown_environment_refused(self):
        self.w = World()
        rc, out = self.w.run("--env", "staging", "plan")
        self.assertEqual(rc, 1)
        self.assertIn("no such environment", out)

    def test_wrong_token_is_rejected(self):
        self.w = World()
        self.w.env_vars["ZABBIX_SLA_TOKEN_LAB"] = "wrong"
        rc, out = self.w.run("plan")
        self.assertEqual(rc, 1)
        self.assertEqual(self.w.mock.writes(), [])


if __name__ == "__main__":
    unittest.main()
