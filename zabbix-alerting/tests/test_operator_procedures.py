"""The exact operator procedures documented in OPERATOR-GUIDE.md, executed through the real CLI."""
import re
import unittest

from netalert import template as tpl
from tests.helpers import BASIC, World

EMAIL = ("alert_action:\n  name: NETOPS-IaC Interface Alerts\n  enabled: true\n"
         "  usergroups: [Network Operations]\n  media_type: %s\n")


def action(w):
    return list(w.mock.actions.values())[0]


class SwitchTelegramToEmail(unittest.TestCase):
    def setUp(self):
        self.w = World(lab_extra=EMAIL % "Telegram")
        self.w.mock.add_usergroup("Network Operations")
        self.tg = self.w.mock.add_mediatype("Telegram")
        self.mail = self.w.mock.add_mediatype("Email")

    def tearDown(self):
        self.w.close()

    def test_changing_only_the_environment_file_switches_media(self):
        self.assertEqual(self.w.run()[0], 0)
        a = action(self.w)
        self.assertEqual(a["operations"][0]["opmessage"]["mediatypeid"], self.tg)
        self.w.close()
        self.w = self.rebuild(EMAIL % "Email")
        self.assertEqual(self.w.run()[0], 0)          # fresh server with e-mail from the start
        a = action(self.w)
        self.assertEqual(a["operations"][0]["opmessage"]["mediatypeid"], self.w.mail_id)
        self.assertEqual(a["recovery_operations"][0]["opmessage"]["mediatypeid"], self.w.mail_id)

    def rebuild(self, extra):
        w = World(lab_extra=extra)
        w.mock.add_usergroup("Network Operations")
        w.mock.add_mediatype("Telegram")
        w.mail_id = w.mock.add_mediatype("Email")
        return w

    def test_in_place_switch_changes_only_the_action(self):
        self.assertEqual(self.w.run()[0], 0)
        tpl_before = sorted((t["description"], t["_expr"], t["_rec"]) for t in self.w.mock.trigprotos.values())
        macros_before = dict(self.w.mock.macros)
        env_file = self.w.base + "/config/environments/lab.yaml"
        with open(env_file) as fh:
            txt = fh.read()
        with open(env_file, "w") as fh:
            fh.write(txt.replace("media_type: Telegram", "media_type: Email"))
        rc, out = self.w.run("--dry-run")
        changes = [l for l in out.splitlines() if re.match(r"\s+(ADD|CHANGE|REMOVE) ", l)]
        self.assertEqual(len(changes), 1, out)
        self.assertIn("CHANGE action", changes[0])
        self.assertEqual(self.w.run()[0], 0)
        a = action(self.w)
        self.assertEqual(a["operations"][0]["opmessage"]["mediatypeid"], self.mail)
        self.assertEqual(a["recovery_operations"][0]["opmessage"]["mediatypeid"], self.mail)
        self.assertEqual(tpl_before, sorted((t["description"], t["_expr"], t["_rec"])
                                            for t in self.w.mock.trigprotos.values()))      # trigger logic untouched
        self.assertEqual(macros_before, dict(self.w.mock.macros))
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_problem_and_recovery_messages_are_delivered_by_the_same_media(self):
        self.w.run()
        a = action(self.w)
        prob, rec = a["operations"][0], a["recovery_operations"][0]
        self.assertEqual(prob["opmessage_grp"], rec["opmessage_grp"])
        self.assertTrue(prob["opmessage"]["subject"].startswith("[{EVENT.SEVERITY}]"))
        self.assertTrue(rec["opmessage"]["subject"].startswith("[RESOLVED]"))

    def test_unknown_media_type_fails_check_without_changes(self):
        env_file = self.w.base + "/config/environments/lab.yaml"
        with open(env_file) as fh:
            txt = fh.read()
        with open(env_file, "w") as fh:
            fh.write(txt.replace("media_type: Telegram", "media_type: Nope"))
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("media type 'Nope'", out)

    def test_production_environment_can_declare_its_own_email_action(self):
        w = World(env_name="production")
        try:
            path = w.base + "/config/environments/production.yaml"
            with open(path) as fh:
                txt = fh.read()
            with open(path, "w") as fh:
                fh.write(txt + "alert_action:\n  name: NETOPS-IaC Interface Alerts\n  enabled: true\n"
                         "  usergroups: [Prod NOC]\n  media_type: Email\n")
            w.mock.add_usergroup("Prod NOC")
            mail = w.mock.add_mediatype("Email")
            self.assertEqual(w.run("--init-identity", "--confirm", "production")[0], 0)
            self.assertEqual(w.run("--confirm", "production")[0], 0)
            self.assertEqual(action(w)["operations"][0]["opmessage"]["mediatypeid"], mail)
            self.assertNotIn("Telegram", str(w.mock.mediatypes))
        finally:
            w.close()


class DailyProcedures(unittest.TestCase):
    def setUp(self):
        self.w = World()
        assert self.w.run()[0] == 0

    def tearDown(self):
        self.w.close()

    def macros(self, host="RTR-01"):
        return self.w.mock.host_macro_map(host)

    def test_add_an_interface_to_an_existing_host(self):
        self.w.set_yaml(BASIC + "      HundredGigE0/0/0/0:\n        description: New link\n        role: P2P\n"
                                "        link_id: P2P-009\n")
        self.assertEqual(self.w.run("--check")[0], 0)
        out = self.w.run("--dry-run")[1]
        self.assertIn('ADD    macro      RTR-01 {$NETOPS.DESCR:"HundredGigE0/0/0/0"}', out)
        self.assertEqual(self.w.run()[0], 0)
        self.assertIn("HundredGigE0/0/0/0", self.macros()["{$NETOPS.IF.MATCH}"])
        self.assertEqual(self.macros()['{$NETOPS.LINKID:"HundredGigE0/0/0/0"}'], "P2P-009")
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_a_misspelt_interface_is_refused_with_a_hint(self):
        self.w.set_yaml(BASIC + "      Gi0/10:\n        description: typo\n")
        rc, out = self.w.run()
        self.assertEqual(rc, 1)
        self.assertIn("did you mean", out)

    def test_remove_an_interface(self):
        self.w.set_yaml(BASIC.split("      Gi0/1:")[0])
        self.assertIn('REMOVE macro      RTR-01 {$NETOPS.DESCR:"Gi0/1"}', self.w.run("--dry-run")[1])
        self.assertEqual(self.w.run()[0], 0)
        self.assertNotIn("Gi0/1", self.macros()["{$NETOPS.IF.MATCH}"])
        self.assertFalse([k for k in self.macros() if '"Gi0/1"' in k])

    def test_change_a_utilization_threshold(self):
        self.w.set_yaml(BASIC.replace("threshold: 70, recovery: 65", "threshold: 85, recovery: 80"))
        out = self.w.run("--dry-run")[1]
        self.assertIn("live '70' -> git '85'", out)
        self.assertIn("live '65' -> git '80'", out)
        self.assertEqual(self.w.run()[0], 0)
        self.assertEqual(self.macros()['{$NETOPS.UTIL.MAX:"Gi0/0"}'], "85")
        self.assertEqual(self.macros()['{$NETOPS.UTIL.RECOVER:"Gi0/0"}'], "80")

    def test_recovery_not_below_threshold_is_refused(self):
        self.w.set_yaml(BASIC.replace("threshold: 70, recovery: 65", "threshold: 70, recovery: 70"))
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("must be lower", out)

    def test_new_host_end_to_end(self):
        new = BASIC + ("  RTR-NEW:\n    site: BR\n    interfaces:\n      Gi0/0:\n        description: To HQ\n"
                       "        role: P2P\n        link_id: P2P-010\n")
        self.w.set_yaml(new)
        # 1. the host is not in Zabbix yet: the tool says so, changes nothing (it does not create hosts)
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("host 'RTR-NEW' not found in Zabbix", out)
        before = self.w.mock.snapshot()
        self.assertEqual(self.w.run()[0], 1)
        self.assertEqual(before, self.w.mock.snapshot())
        # 2. host created in Zabbix with an SNMP interface but the interface items are not there yet
        self.w.mock.add_host("RTR-NEW", [])
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("no items tagged interface", out)
        # 3. after the stock SNMP interface template has discovered its interfaces
        hid = self.w.mock.host_id("RTR-NEW")
        iid = self.w.mock.nid()
        self.w.mock.items[iid] = {"itemid": iid, "hostid": hid, "key_": "net.if.status[ifOperStatus.1]",
                                  "name": "Gi0/0 status", "tags": [{"tag": "interface", "value": "Gi0/0"}]}
        self.assertEqual(self.w.run("--check")[0], 0)
        self.assertEqual(self.w.run()[0], 0)
        self.assertEqual(self.w.mock.host_macro_map("RTR-NEW")['{$NETOPS.LINKID:"Gi0/0"}'], "P2P-010")
        self.assertIn(tpl.TEMPLATE_NAME, str([self.w.mock.templates[t]["host"]
                                              for t in self.w.mock.hosts[hid]["templates"]]))
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_host_without_snmp_interface_is_refused(self):
        self.w.mock.add_host("RTR-ICMP", ["Gi0/0"], snmp=False)
        self.w.set_yaml(BASIC + "  RTR-ICMP:\n    interfaces:\n      Gi0/0: {description: x}\n")
        rc, out = self.w.run("--check")
        self.assertEqual(rc, 1)
        self.assertIn("host has no SNMP interface", out)


if __name__ == "__main__":
    unittest.main()
