"""End-to-end through the real CLI -> planner -> applier -> ZabbixClient, against the Zabbix 7.0 model."""
import glob
import os
import unittest

from netalert import template as tpl
from netalert.zbx import ApiUnavailable
from tests.fake_zabbix import MockZabbix
from tests.helpers import BASIC, World


def macros_of(world, host="RTR-01"):
    return world.mock.host_macro_map(host)


class Check(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def test_pass_per_interface_and_no_writes(self):
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS  RTR-01 / Gi0/0", out)
        self.assertIn("PASS  RTR-01 / Gi0/1", out)
        self.assertIn("RESULT: PASS (2 interface(s))", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_host_missing(self):
        self.w.set_yaml("hosts:\n  NOPE:\n    interfaces:\n      Gi0/0: {description: x}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL  NOPE / Gi0/0  host 'NOPE' not found in Zabbix", out)

    def test_interface_typo_gets_suggestion(self):
        self.w.set_yaml("hosts:\n  RTR-01:\n    interfaces:\n      Gi0/10: {description: x}\n"
                        "      gi0/0: {description: y}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL  RTR-01 / Gi0/10  interface not found on host", out)
        self.assertIn("did you mean 'Gi0/0'", out)

    def test_bad_threshold_and_recovery(self):
        self.w.set_yaml("hosts:\n  RTR-01:\n    interfaces:\n      Gi0/0:\n        description: x\n"
                        "        utilization: {enabled: true, threshold: 70, recovery: 75}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("recovery (75) must be lower than utilization.threshold (70)", out)

    def test_invalid_severity(self):
        self.w.set_yaml("hosts:\n  RTR-01:\n    interfaces:\n      Gi0/0: {description: x, severity: critical}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("invalid severity 'critical'", out)

    def test_duplicates_differing_only_by_case(self):
        self.w.mock.add_host("RTR-09", ["Gi0/0", "gi0/0"])
        self.w.set_yaml("hosts:\n  RTR-09:\n    interfaces:\n      Gi0/0: {description: a}\n"
                        "      gi0/0: {description: b}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("duplicate of", out)

    def test_duplicate_yaml_key_is_a_hard_error(self):
        self.w.set_yaml("hosts:\n  RTR-01:\n    interfaces:\n      Gi0/0: {description: a}\n      Gi0/0: {description: b}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 2)
        self.assertIn("duplicate key", out)

    def test_disabled_host_and_no_snmp_interface(self):
        self.w.mock.add_host("OFF-1", ["Gi0/0"], status=1)
        self.w.mock.add_host("NOSNMP", ["Gi0/0"], snmp=False)
        self.w.set_yaml("hosts:\n  OFF-1:\n    interfaces:\n      Gi0/0: {description: a}\n"
                        "  NOSNMP:\n    interfaces:\n      Gi0/0: {description: a}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("host is disabled", out)
        self.assertIn("host has no SNMP interface", out)

    def test_host_without_interface_tags_cannot_be_verified(self):
        self.w.mock.add_host("BARE", [])
        self.w.set_yaml("hosts:\n  BARE:\n    interfaces:\n      Gi0/0: {description: a}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("cannot verify", out)

    def test_api_unavailable(self):
        class Down(object):
            def send(self, payload, authenticated=True):
                raise ApiUnavailable("cannot reach https://zbx.lab.example (timed out)")
        from netalert import cli
        lines = []
        rc = cli.run(["--env", "lab", "--check"], environ=self.w.env_vars, out=lines.append, base=self.w.base,
                     transport_factory=lambda u, t, v: Down())
        self.assertEqual(rc, 4)
        self.assertIn("API unavailable", "\n".join(lines))

    def test_failure_blocks_apply_and_changes_nothing(self):
        self.w.set_yaml(BASIC + "  NOPE:\n    interfaces:\n      Gi0/0: {description: x}\n")
        before = self.w.mock.snapshot()
        rc, out = self.w.run()
        self.assertEqual(rc, 1)
        self.assertIn("nothing applied", out)
        self.assertEqual(self.w.mock.writes(), [])
        self.assertEqual(before, self.w.mock.snapshot())


class DryRunAndApply(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def test_dry_run_lists_adds_and_writes_nothing(self):
        rc, out = self.w.run("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("ADD    template", out)
        self.assertIn("ADD    link", out)
        self.assertIn("ADD    macro      RTR-01 {$NETOPS.IF.MATCH}", out)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_full_cycle_idempotent(self):
        rc, out = self.w.run()
        self.assertEqual(rc, 0, out)
        self.assertIn("verification plan is empty", out)
        # state in Zabbix
        m = macros_of(self.w)
        self.assertEqual(m["{$NETOPS.IF.MATCH}"], "^(?:Gi0/0|Gi0/1)$")
        self.assertEqual(m['{$NETOPS.UTIL.MAX:"Gi0/0"}'], "70")
        self.assertEqual(m['{$NETOPS.UTIL.RECOVER:"Gi0/0"}'], "65")
        self.assertEqual(m['{$NETOPS.SEV:"Gi0/0"}'], "5")
        self.assertEqual(m['{$NETOPS.SEV:"Gi0/1"}'], "4")
        self.assertEqual(m['{$NETOPS.UTIL.ON:"Gi0/1"}'], "0")
        self.assertEqual(m['{$NETOPS.DESCR:"Gi0/0"}'], "STC Internet")
        hid = self.w.mock.host_id("RTR-01")
        tid = [t for t, v in self.w.mock.templates.items() if v["host"] == tpl.TEMPLATE_NAME][0]
        self.assertIn(tid, self.w.mock.hosts[hid]["templates"])
        # unselected interface / unselected host not touched
        self.assertNotIn(self.w.mock.host_id("RTR-02"), set(x["hostid"] for x in self.w.mock.macros.values()))
        self.assertEqual(len(self.w.mock.gmacros), 1)
        self.assertEqual(len(glob.glob(os.path.join(self.w.base, "state", "backups", "lab-*.json"))), 1)
        # LLD was queued
        self.assertEqual(len(self.w.mock.tasks), 1)
        # second run
        n = len(self.w.mock.writes())
        rc, out = self.w.run()
        self.assertEqual(rc, 0)
        self.assertIn("No changes required.", out)
        self.assertEqual(len(self.w.mock.writes()), n)
        rc, out = self.w.run("--dry-run")
        self.assertIn("No changes required.", out)

    def test_every_macro_carries_the_ownership_marker(self):
        self.w.run()
        for m in self.w.mock.macros.values():
            if m["macro"].startswith("{$NETOPS.") and m["hostid"] == self.w.mock.host_id("RTR-01"):
                self.assertIn(tpl.MARKER, m["description"], m["macro"])

    def test_drift_is_reported_as_live_to_git(self):
        self.w.run()
        hid = self.w.mock.host_id("RTR-01")
        row = [m for m in self.w.mock.macros.values()
               if m["hostid"] == hid and m["macro"] == '{$NETOPS.UTIL.MAX:"Gi0/0"}'][0]
        row["value"] = "80"                                  # someone edited production by hand
        rc, out = self.w.run("--dry-run")
        self.assertIn("CHANGE", out)
        self.assertIn("live '80' -> git '70'", out)
        rc, out = self.w.run()
        self.assertEqual(rc, 0, out)
        self.assertEqual(macros_of(self.w)['{$NETOPS.UTIL.MAX:"Gi0/0"}'], "70")
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_threshold_change_in_yaml(self):
        self.w.run()
        self.w.set_yaml(BASIC.replace("threshold: 70, recovery: 65", "threshold: 80, recovery: 75"))
        rc, out = self.w.run("--dry-run")
        self.assertIn("live '70' -> git '80'", out)
        self.assertIn("live '65' -> git '75'", out)
        self.assertEqual(self.w.run()[0], 0)
        self.assertEqual(macros_of(self.w)['{$NETOPS.UTIL.MAX:"Gi0/0"}'], "80")

    def test_add_and_remove_interface(self):
        self.w.run()
        self.w.set_yaml(BASIC + "      HundredGigE0/0/0/0: {description: new, role: ISP}\n")
        rc, out = self.w.run("--dry-run")
        self.assertIn("CHANGE macro", out)           # the selection regex
        self.assertIn('ADD    macro      RTR-01 {$NETOPS.DESCR:"HundredGigE0/0/0/0"}', out)
        self.w.run()
        self.assertIn("HundredGigE0/0/0/0", macros_of(self.w)["{$NETOPS.IF.MATCH}"])
        # remove Gi0/1 again
        self.w.set_yaml(BASIC.split("      Gi0/1:")[0])
        rc, out = self.w.run("--dry-run")
        self.assertIn('REMOVE macro      RTR-01 {$NETOPS.DESCR:"Gi0/1"}', out)
        self.assertEqual(self.w.run()[0], 0)
        self.assertFalse([k for k in macros_of(self.w) if '"Gi0/1"' in k])
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_remove_host_unlinks_and_cleans_only_owned(self):
        self.w.mock.add_macro(self.w.mock.host_id("RTR-01"), "{$SNMP_COMMUNITY}", "x", "pre-existing")
        self.w.run()
        self.w.set_yaml("hosts:\n  RTR-02:\n    interfaces:\n      Gi0/0: {description: only}\n")
        rc, out = self.w.run("--dry-run")
        self.assertIn("REMOVE link       RTR-01", out)
        self.assertEqual(self.w.run()[0], 0)
        m = macros_of(self.w)
        self.assertEqual(m, {"{$SNMP_COMMUNITY}": "x"})      # ours gone, theirs untouched
        self.assertEqual(self.w.mock.hosts[self.w.mock.host_id("RTR-01")]["templates"], [])

    def test_template_drift_is_repaired(self):
        self.w.run()
        victim = next(iter(self.w.mock.trigprotos))
        del self.w.mock.trigprotos[victim]                   # someone deleted a trigger prototype
        rc, out = self.w.run("--dry-run")
        self.assertIn("CHANGE template", out)
        self.assertIn("triggers: 1 missing", out)
        self.assertEqual(self.w.run()[0], 0)
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_template_changed_in_repository_is_detected(self):
        self.w.run()
        for t in self.w.mock.templates.values():
            t["description"] = t["description"].replace("hash=", "hash=0000")
        rc, out = self.w.run("--dry-run")
        self.assertIn("template version differs", out)


class OwnershipProtection(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def test_foreign_macro_in_our_namespace_blocks_apply(self):
        hid = self.w.mock.host_id("RTR-01")
        self.w.mock.add_macro(hid, "{$NETOPS.SITE}", "SOMEONE-ELSES", "handmade")
        before = self.w.mock.snapshot()
        rc, out = self.w.run()
        self.assertEqual(rc, 1)
        self.assertIn("REVIEW REQUIRED", out)
        self.assertIn("{$NETOPS.SITE}", out)
        self.assertEqual(before, self.w.mock.snapshot())
        self.assertEqual(self.w.mock.writes(), [])
        # check reports it as well
        self.assertEqual(self.w.run("--check")[0], 1)

    def test_unmanaged_namespace_macro_on_unlisted_host_is_a_conflict_not_deleted(self):
        self.w.mock.add_macro(self.w.mock.host_id("RTR-02"), "{$NETOPS.RANDOM}", "1", "mine")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("RTR-02", out)
        self.assertIn("{$NETOPS.RANDOM}", [m["macro"] for m in self.w.mock.macros.values()][0:1] +
                      [m["macro"] for m in self.w.mock.macros.values()])

    def test_foreign_template_with_our_name(self):
        tid = self.w.mock.nid()
        self.w.mock.templates[tid] = {"templateid": tid, "hostid": tid, "host": tpl.TEMPLATE_NAME,
                                      "description": "someone elses template"}
        rc, out = self.w.run("--dry-run")
        self.assertEqual(rc, 1)
        self.assertIn("not managed by this tool", out)

    def test_nothing_outside_netops_namespace_is_modified(self):
        hid = self.w.mock.host_id("RTR-01")
        self.w.mock.add_macro(hid, "{$SNMP_COMMUNITY}", "secret", "")
        self.w.mock.add_macro(hid, '{$IFCONTROL:"Gi0/0"}', "1", "stock")
        self.w.mock.add_macro(hid, "{$NETWORK.OTHER}", "7", "")
        self.assertEqual(self.w.run()[0], 0)
        m = macros_of(self.w)
        self.assertEqual((m["{$SNMP_COMMUNITY}"], m['{$IFCONTROL:"Gi0/0"}'], m["{$NETWORK.OTHER}"]),
                         ("secret", "1", "7"))

    def test_stock_items_of_unselected_interfaces_untouched(self):
        n_items = len(self.w.mock.items)
        self.w.run()
        self.assertEqual(len(self.w.mock.items), n_items)    # nothing removed from LLD / items


class Suppression(unittest.TestCase):
    def test_stock_alert_suppression_is_opt_in_and_owned(self):
        w = World(lab_extra="suppress_stock: true\n")
        try:
            self.assertEqual(w.run()[0], 0)
            m = macros_of(w)
            self.assertEqual(m['{$IFCONTROL:"Gi0/0"}'], "0")
            self.assertEqual(m['{$IFCONTROL:"Gi0/1"}'], "0")
            row = [x for x in w.mock.macros.values() if x["macro"] == '{$IFCONTROL:"Gi0/0"}'][0]
            self.assertIn(tpl.MARKER, row["description"])
            self.assertIn("No changes required.", w.run("--dry-run")[1])
        finally:
            w.close()

    def test_default_does_not_touch_ifcontrol(self):
        w = World()
        try:
            w.run()
            self.assertFalse([k for k in macros_of(w) if k.startswith("{$IFCONTROL")])
        finally:
            w.close()


class AlertAction(unittest.TestCase):
    EXTRA = ("alert_action:\n  name: NETOPS-IaC Interface Alerts\n  enabled: true\n"
             "  usergroups: [Network Operations]\n")

    def test_missing_usergroup_fails_check(self):
        w = World(lab_extra=self.EXTRA)
        try:
            rc, out = w.run("--check")
            self.assertEqual(rc, 1)
            self.assertIn("not found in Zabbix: Network Operations", out)
        finally:
            w.close()

    def test_create_update_and_idempotent(self):
        w = World(lab_extra=self.EXTRA)
        try:
            gid = w.mock.add_usergroup("Network Operations")
            self.assertEqual(w.run()[0], 0)
            a = list(w.mock.actions.values())[0]
            self.assertEqual(a["name"], "NETOPS-IaC Interface Alerts")
            self.assertEqual(a["status"], "0")
            self.assertEqual(a["filter"]["conditions"][0]["value"], tpl.TAG_ALERT)
            self.assertEqual(a["operations"][0]["opmessage_grp"][0]["usrgrpid"], gid)
            msg = a["operations"][0]["opmessage"]["message"]
            for needle in ("{HOST.NAME}", "{EVENT.TAGS.if_name}", "{EVENT.TAGS.if_descr}",
                           "{EVENT.TAGS.if_role}", "{EVENT.TAGS.site}", "{EVENT.SEVERITY}",
                           "{EVENT.TAGS.link_id}", "{EVENT.TAGS.direction}",
                           "{EVENT.TAGS.threshold}", "{EVENT.OPDATA}"):
                self.assertIn(needle, msg)
            self.assertIn("No changes required.", w.run("--dry-run")[1])
            a["status"] = "1"                                  # someone disabled it by hand
            rc, out = w.run("--dry-run")
            self.assertIn("CHANGE action", out)
            self.assertEqual(w.run()[0], 0)
            self.assertEqual(list(w.mock.actions.values())[0]["status"], "0")
        finally:
            w.close()

    def test_media_type_is_referenced_by_name_never_created(self):
        w = World(lab_extra=self.EXTRA + "  media_type: Email\n")
        try:
            w.mock.add_usergroup("Network Operations")
            mt = w.mock.add_mediatype("Email")
            self.assertEqual(w.run()[0], 0)
            a = list(w.mock.actions.values())[0]
            self.assertEqual(a["operations"][0]["opmessage"]["mediatypeid"], mt)
            self.assertEqual(len(w.mock.mediatypes), 1)
        finally:
            w.close()

    def test_named_media_is_exclusive_for_problem_and_recovery(self):
        w = World(lab_extra=self.EXTRA + "  media_type: Telegram\n")
        try:
            w.mock.add_usergroup("Network Operations")
            telegram = w.mock.add_mediatype("Telegram")
            w.mock.add_mediatype("Email")
            self.assertEqual(w.run()[0], 0)
            action = list(w.mock.actions.values())[0]
            self.assertEqual(action["operations"][0]["opmessage"]["mediatypeid"], telegram)
            self.assertEqual(action["recovery_operations"][0]["opmessage"]["mediatypeid"], telegram)
            self.assertEqual(action["operations"][0]["esc_step_from"], 1)
            self.assertEqual(action["operations"][0]["esc_step_to"], 1)
            self.assertEqual(action["operations"][0]["esc_period"], "0")
            self.assertEqual(action["filter"]["conditions"], [{
                "conditiontype": 25, "operator": 0, "value": tpl.TAG_ALERT}])
        finally:
            w.close()


class ReadOnlyServiceAccount(unittest.TestCase):
    """The situation we are in today: reads work, every write is refused by the server."""

    def setUp(self):
        self.w = World(mock=MockZabbix(token="tok-lab", readonly=True))
        self.w.mock.add_host("RTR-01", ["Gi0/0", "Gi0/1"])

    def tearDown(self):
        self.w.close()

    def test_check_and_dry_run_work_read_only(self):
        self.assertEqual(self.w.run("--check")[0], 0)
        rc, out = self.w.run("--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("DRY RUN", out)

    def test_apply_fails_cleanly_and_changes_nothing(self):
        before = self.w.mock.snapshot()
        rc, out = self.w.run()
        self.assertEqual(rc, 5)
        self.assertIn("APPLY STOPPED", out)
        self.assertIn("No permissions", out)
        self.assertEqual(before, self.w.mock.snapshot())


if __name__ == "__main__":
    unittest.main()
