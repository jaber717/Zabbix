"""Rollback = revert interfaces.yaml in Git and apply again. Proven here against the Zabbix 7.0 model."""
import glob
import json
import os
import unittest

from tests.helpers import BASIC, World

V2 = (BASIC.replace("threshold: 70, recovery: 65", "threshold: 80, recovery: 75")
      + "      HundredGigE0/0/0/0: {description: new, role: ISP, severity: warning}\n")
ACTION = ("alert_action:\n  name: NETOPS-IaC Interface Alerts\n  enabled: true\n"
          "  usergroups: [Network Operations]\n  media_type: Telegram\n")


def managed(world, host="RTR-01"):
    return dict(world.mock.host_macro_map(host))


class Rollback(unittest.TestCase):
    def test_revert_yaml_restores_exact_previous_managed_state(self):
        w = World()
        try:
            self.assertEqual(w.run()[0], 0)
            v1 = managed(w)
            w.set_yaml(V2)
            self.assertEqual(w.run()[0], 0)
            self.assertNotEqual(managed(w), v1)
            w.set_yaml(BASIC)                                   # git revert
            rc, out = w.run("--dry-run")
            self.assertIn("REMOVE macro", out)
            self.assertEqual(w.run()[0], 0)
            self.assertEqual(managed(w), v1)                    # byte-for-byte the earlier macros
            self.assertIn("No changes required.", w.run("--dry-run")[1])
        finally:
            w.close()

    def test_rollback_to_nothing_removes_only_what_the_tool_made(self):
        w = World()
        try:
            w.mock.add_macro(w.mock.host_id("RTR-01"), "{$SNMP_COMMUNITY}", "keep", "pre-existing")
            w.run()
            w.set_yaml("hosts: {}\n")
            self.assertEqual(w.run("--allow-empty")[0], 0)
            self.assertEqual(managed(w), {"{$SNMP_COMMUNITY}": "keep"})
            self.assertEqual(w.mock.hosts[w.mock.host_id("RTR-01")]["templates"], [])
        finally:
            w.close()

    def test_action_change_rolls_back(self):
        w = World(lab_extra=ACTION)
        try:
            w.mock.add_usergroup("Network Operations")
            w.mock.add_mediatype("Telegram")
            self.assertEqual(w.run()[0], 0)
            action = list(w.mock.actions.values())[0]
            before = json.dumps(action, sort_keys=True)
            action["status"] = "1"                              # someone disables it
            self.assertEqual(w.run()[0], 0)                     # re-apply = roll back to the Git state
            self.assertEqual(json.dumps(list(w.mock.actions.values())[0], sort_keys=True), before)
        finally:
            w.close()

    def test_backup_records_what_was_there_before_each_apply(self):
        w = World()
        try:
            w.run()
            w.set_yaml(V2)
            w.run()
            files = sorted(glob.glob(os.path.join(w.base, "state", "backups", "lab-*.json")))
            self.assertEqual(len(files), 2)
            with open(files[1]) as fh:
                prior = dict((m["macro"], m["value"]) for m in json.load(fh)["owned_macros"])
            self.assertEqual(prior['{$NETOPS.UTIL.MAX:"Gi0/0"}'], "70")
        finally:
            w.close()


if __name__ == "__main__":
    unittest.main()
