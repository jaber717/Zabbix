import json
import os
import pathlib
import tempfile
import unittest

import yaml

from hwh import action as A
from hwh import matrix
from hwh.api import AuditError, ZabbixAPI
from tests.fakes import FakeZabbix
from tests.helpers import CATALOGUE, ROOT, Project, audit_host, cisco_policy, fan_sensor, good_fake


def obs_file(text):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "o.yaml")
    with open(p, "w") as fh:
        fh.write(text)
    return p


class TestMatrix(unittest.TestCase):
    def test_no_devices_means_blocked_everywhere_never_green(self):
        m = matrix.build(CATALOGUE, [])
        for f in m["families"].values():
            for c in f["categories"].values():
                self.assertEqual(c["verdict"], matrix.BLOCKED)
                self.assertIn("NOT TESTABLE", c["notes"][0])

    def test_all_four_vendors_and_every_family_are_in_the_output(self):
        text = matrix.render_markdown(matrix.build(CATALOGUE, []))
        for v in ("Cisco", "Palo Alto Networks", "Fortinet", "Huawei"):
            self.assertIn("## " + v, text)
        for t in ("ASR 8500", "Nexus", "IOS-XE", "PAN-OS", "FortiGate", "FortiProxy", "VRP switch", "AR8140"):
            self.assertIn(t, text)

    def test_pass_cannot_be_asserted_by_hand(self):
        p = obs_file("observations:\n  - {hosts: [X], family: cisco-nxos, source: s, categories: {fan: {verdict: PASS, evidence: 'looks fine to me honestly'}}}\n")
        with self.assertRaises(AuditError):
            matrix.load_observations(p)

    def test_observation_needs_evidence_and_known_category(self):
        with self.assertRaises(AuditError):
            matrix.load_observations(obs_file("observations:\n  - {hosts: [X], family: cisco-nxos, source: s, categories: {fan: {verdict: GAP, evidence: ''}}}\n"))
        with self.assertRaises(AuditError):
            matrix.load_observations(obs_file("observations:\n  - {hosts: [X], family: cisco-nxos, source: s, categories: {redundancy: {verdict: GAP, evidence: 'twelve chars+'}}}\n"))

    def test_unknown_family_is_rejected(self):
        with self.assertRaises(AuditError):
            matrix.build(CATALOGUE, [{"hosts": ["X"], "family": "f5-bigip", "source": "s", "categories": {}}])

    def test_aggregation_gap_beats_blocked_beats_pass(self):
        ent = lambda v: {"hosts": ["h" + v], "family": "cisco-nxos", "source": "s", "categories": {"fan": {"verdict": v, "evidence": "e"}}}
        self.assertEqual(matrix.build(CATALOGUE, [ent("PASS"), ent("BLOCKED")])["families"]["cisco-nxos"]["categories"]["fan"]["verdict"], "BLOCKED")
        self.assertEqual(matrix.build(CATALOGUE, [ent("PASS"), ent("BLOCKED"), ent("GAP")])["families"]["cisco-nxos"]["categories"]["fan"]["verdict"], "GAP")
        self.assertEqual(matrix.build(CATALOGUE, [ent("PASS")])["families"]["cisco-nxos"]["categories"]["fan"]["verdict"], "PASS")
        self.assertEqual(matrix.build(CATALOGUE, [ent("N/A")])["families"]["cisco-nxos"]["categories"]["fan"]["verdict"], "N/A")

    def test_a_category_nobody_recorded_is_a_gap_not_blank(self):
        m = matrix.build(CATALOGUE, [{"hosts": ["X"], "family": "cisco-nxos", "source": "s", "categories": {"fan": {"verdict": "GAP", "evidence": "e"}}}])
        self.assertEqual(m["families"]["cisco-nxos"]["categories"]["power"]["verdict"], "GAP")

    def test_matrix_from_a_live_audit_report(self):
        fz, hid, iid = good_fake()
        rep = {"generated_at_utc": "t", "hosts": [audit_host(fz, cisco_policy([fan_sensor()]))]}
        m = matrix.build(CATALOGUE, matrix.entries_from_report(rep))
        self.assertEqual(m["families"]["cisco-nxos"]["categories"]["fan"]["verdict"], "PASS")
        self.assertEqual(m["families"]["cisco-nxos"]["categories"]["power"]["verdict"], "GAP")
        self.assertEqual(m["families"]["cisco-asr8500"]["categories"]["fan"]["verdict"], "BLOCKED")

    def test_na_flows_through_from_policy_evidence(self):
        fz, hid, iid = good_fake()
        s = cisco_policy([fan_sensor()], not_applicable={"hw_redundancy": {"evidence": "single fixed supply per datasheet DS-1"}})
        rep = {"generated_at_utc": "t", "hosts": [audit_host(fz, s)]}
        m = matrix.build(CATALOGUE, matrix.entries_from_report(rep))
        self.assertEqual(m["families"]["cisco-nxos"]["categories"]["hw_redundancy"]["verdict"], "N/A")

    def test_shipped_observations_build_the_discovery_matrix(self):
        obs = matrix.load_observations(str(ROOT / "docs" / "observations" / "lab-discovery-2026-10-09.yaml"))
        m = matrix.build(CATALOGUE, obs)
        verdicts = [c["verdict"] for f in m["families"].values() for c in f["categories"].values()]
        self.assertNotIn("PASS", verdicts)                       # nothing in the LAB is accepted
        self.assertEqual(m["families"]["cisco-iosxe"]["categories"]["fan"]["verdict"], "GAP")
        self.assertEqual(m["families"]["fortinet-fortigate"]["categories"]["ha"]["verdict"], "BLOCKED")
        self.assertEqual(m["families"]["huawei-ar8140"]["categories"]["temperature"]["verdict"], "BLOCKED")

    def test_committed_matrix_document_is_current(self):
        obs = matrix.load_observations(str(ROOT / "docs" / "observations" / "lab-discovery-2026-10-09.yaml"))
        text = matrix.render_markdown(matrix.build(CATALOGUE, obs))
        with open(str(ROOT / "docs" / "COVERAGE-MATRIX.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().replace("\r\n", "\n"), text)

    def test_cli_matrix(self):
        p = Project()
        try:
            out_md = os.path.join(p.base, "m.md")
            rc, out, err = p.run("matrix", "--observations", str(ROOT / "docs" / "observations" / "lab-discovery-2026-10-09.yaml"), "--out", out_md)
            self.assertEqual(rc, 0, err)
            self.assertIn("BLOCKED", pathlib.Path(out_md).read_text(encoding="utf-8"))
        finally:
            p.close()


class TestActionDesign(unittest.TestCase):
    def test_filter_is_a_positive_allowlist_on_the_dedicated_tag(self):
        f = A.hardware_filter()
        self.assertEqual(f["evaltype"], 1)
        self.assertIn({"conditiontype": 26, "operator": 0, "value": "netops_hardware", "value2": "1"}, f["conditions"])
        self.assertIn({"conditiontype": 25, "operator": 1, "value": "netops_alert"}, f["conditions"])
        self.assertEqual(len(f["conditions"]), 2)          # no host group, no trigger name, no scope tag

    def test_created_disabled_with_problem_and_recovery_operations(self):
        p = A.build_params("3", ["7"], enabled=False)
        self.assertEqual(p["status"], 1)
        self.assertEqual(len(p["operations"]), 1)
        self.assertEqual(len(p["recovery_operations"]), 1)
        self.assertTrue(p["name"].startswith("NETOPS-HW "))
        for k in ("{EVENT.NAME}", "{HOST.NAME}", "{EVENT.SEVERITY}", "{EVENT.ID}", "{EVENT.STATUS}", '{EVENT.TAGS."hardware_component"}', '{EVENT.TAGS."hardware_slot"}', "{EVENT.DATE}"):
            self.assertIn(k, p["operations"][0]["opmessage"]["message"] + p["operations"][0]["opmessage"]["subject"])
        self.assertIn("{EVENT.RECOVERY.DATE}", p["recovery_operations"][0]["opmessage"]["message"])

    def test_no_event_crosses_between_the_two_actions(self):
        rep = A.crossover_report()
        self.assertEqual([r for r in rep if not r["ok"]], [])
        by = dict((r["event"], r) for r in rep)
        self.assertTrue(by["hardware fan event"]["hardware_action"] and not by["hardware fan event"]["interface_action"])
        self.assertTrue(by["interface link_down event"]["interface_action"] and not by["interface link_down event"]["hardware_action"])
        self.assertFalse(by["stock hardware trigger (scope only)"]["hardware_action"])      # broad scope tags never route
        self.assertFalse(by["linux component=system notice"]["hardware_action"])
        self.assertFalse(by["mis-tagged trigger carrying both"]["hardware_action"])

    def test_a_live_interface_action_that_could_match_hardware_events_is_detected(self):
        bad = {"evaltype": 0, "conditions": [{"conditiontype": 25, "operator": 0, "value": "netops_hardware"}]}
        self.assertTrue([r for r in A.crossover_report([bad]) if not r["ok"]])


class ActionBase(unittest.TestCase):
    def setUp(self):
        self.fz = FakeZabbix()
        self.iface = self.fz.add_action("NETOPS-IaC Interface Alerts", {"evaltype": 0, "conditions": [{"conditiontype": 25, "operator": 0, "value": "netops_alert"}]})
        self.p = Project(fake=self.fz)
        self.p.write("config/notifications.lab.yaml", "media_type: Telegram\nusergroups: [Network Operations]\napproved_by: noc-lead\napproval_reference: T-1\n")

    def tearDown(self):
        self.p.close()

    def hw(self):
        return [a for a in self.fz.actions.values() if a["name"] == A.ACTION_NAME]

    def validate(self, ok=True):
        e = lambda: {"verified": ok, "evidence": "tester transcript T-1 event 123 delivered"}
        self.p.write("config/action-validation.yaml", yaml.safe_dump({"problem_delivery": e(), "recovery_delivery": e(), "interface_exclusion": e(), "validated_by": "codex"}))


class TestActionLifecycle(ActionBase):
    def test_plan_is_read_only(self):
        rc, out, err = self.p.run("--env", "lab", "action", "plan")
        self.assertEqual(rc, 0, err)
        self.assertIn("CREATE", out)
        self.assertEqual(self.fz.writes(), [])

    def test_apply_creates_a_disabled_action_and_never_touches_the_interface_action(self):
        before = json.dumps(self.fz.actions[self.iface], sort_keys=True)
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 0, err + out)
        self.assertEqual(len(self.hw()), 1)
        self.assertEqual(self.hw()[0]["status"], "1")
        self.assertEqual(json.dumps(self.fz.actions[self.iface], sort_keys=True), before)
        self.assertEqual(self.fz.writes(), ["action.create"])

    def test_apply_is_idempotent(self):
        self.p.run("--env", "lab", "action", "apply")
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertIn("no changes", out)
        self.assertEqual(self.fz.writes(), ["action.create"])

    def test_enable_is_refused_without_independent_validation(self):
        self.p.run("--env", "lab", "action", "apply")
        rc, out, err = self.p.run("--env", "lab", "action", "apply", "--enable")
        self.assertEqual(rc, 3)
        self.assertIn("--enable refused", err)
        self.assertEqual(self.hw()[0]["status"], "1")

    def test_partial_validation_is_not_enough(self):
        self.validate(ok=False)
        rc, out, err = self.p.run("--env", "lab", "action", "apply", "--enable")
        self.assertEqual(rc, 3)

    def test_enable_with_complete_evidence(self):
        self.validate()
        self.p.run("--env", "lab", "action", "apply")
        rc, out, err = self.p.run("--env", "lab", "action", "apply", "--enable")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.hw()[0]["status"], "0")

    def test_an_enabled_action_without_evidence_is_flagged_and_disabled_again(self):
        self.p.run("--env", "lab", "action", "apply")
        self.hw()[0]["status"] = "0"                       # someone enabled it by hand
        rc, out, err = self.p.run("--env", "lab", "action", "plan")
        self.assertIn("ENABLED without validation evidence", out)
        self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(self.hw()[0]["status"], "1")

    def test_drift_in_the_filter_is_repaired(self):
        self.p.run("--env", "lab", "action", "apply")
        self.hw()[0]["filter"]["conditions"] = []
        rc, out, err = self.p.run("--env", "lab", "action", "plan")
        self.assertIn("UPDATE", out)
        self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(len(self.hw()[0]["filter"]["conditions"]), 2)

    def test_missing_media_type_or_group_is_a_conflict_and_nothing_is_created(self):
        self.p.write("config/notifications.lab.yaml", "media_type: Nope\nusergroups: [Network Operations]\napproved_by: noc-lead\napproval_reference: T-1\n")
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 3)
        self.assertEqual(self.hw(), [])
        self.assertEqual(self.fz.writes(), [])

    def test_production_is_refused_in_this_release(self):
        fz = FakeZabbix(identity="production")
        pr = Project(env="production", fake=fz, extra_top="zabbix: {url_regex: '^https://zbx\\\\.prod\\\\.example$'}\n")
        try:
            rc, out, err = pr.run("--env", "production", "action", "plan")
            self.assertEqual(rc, 3)
            self.assertIn("LAB only", err)
            self.assertEqual(fz.calls, [])
            rc, out, err = pr.run("--env", "production", "action", "apply")
            self.assertEqual(rc, 3)
            self.assertEqual(fz.writes(), [])
        finally:
            pr.close()

    def test_rollback_of_a_creation_removes_only_our_action(self):
        self.p.run("--env", "lab", "action", "apply")
        backup = [os.path.join(self.p.base, "state", "backups", f) for f in os.listdir(os.path.join(self.p.base, "state", "backups"))][0]
        rc, out, err = self.p.run("--env", "lab", "action", "rollback", "--backup", backup)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.hw(), [])
        self.assertIn(self.iface, self.fz.actions)

    def test_rollback_of_an_update_restores_the_previous_definition(self):
        self.p.run("--env", "lab", "action", "apply")
        self.validate()
        self.p.run("--env", "lab", "action", "apply", "--enable")
        self.assertEqual(self.hw()[0]["status"], "0")
        backups = sorted(os.listdir(os.path.join(self.p.base, "state", "backups")))
        newest = os.path.join(self.p.base, "state", "backups", backups[-1])
        rc, out, err = self.p.run("--env", "lab", "action", "rollback", "--backup", newest)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.hw()[0]["status"], "1")

    def test_backup_is_private_and_holds_no_credentials(self):
        self.p.run("--env", "lab", "action", "apply")
        d = os.path.join(self.p.base, "state", "backups")
        for f in os.listdir(d):
            text = pathlib.Path(d, f).read_text(encoding="utf-8")
            self.assertNotIn("lab-token-aaa", text)

    def test_apply_writes_only_action_methods_on_a_write_client(self):
        self.p.run("--env", "lab", "action", "apply")
        self.assertTrue(set(self.fz.writes()) <= {"action.create", "action.update", "action.delete"})


class TestShippedConfig(unittest.TestCase):
    def test_validation_record_ships_unvalidated_so_the_action_cannot_be_enabled(self):
        self.assertFalse(A.load_validation(str(ROOT / "config" / "action-validation.yaml"))["ok"])

    def test_example_notifications_are_refused_until_approved_by_an_operator(self):
        with self.assertRaises(AuditError):
            A.load_spec(str(ROOT / "config" / "notifications.example.yaml"))

    def test_action_name_is_fixed(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "n.yaml")
        pathlib.Path(p).write_text("name: Something else\nmedia_type: x\nusergroups: [g]\n")
        with self.assertRaises(AuditError):
            A.load_spec(p)


if __name__ == "__main__":
    unittest.main()
