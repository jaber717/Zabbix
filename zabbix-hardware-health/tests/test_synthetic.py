"""Read-only machinery for the LAB synthetic notification test: approval scope, preflight, manifest, id ledger, cleanup plan, verification."""
import copy
import datetime
import json
import pathlib
import unittest

import yaml

from hwh import action as A
from hwh import synthetic as SY
from hwh.api import AuditError, ZabbixAPI
from tests.fakes import FakeZabbix
from tests.helpers import ROOT, Project, add_evidence, create_owned_action, seed_audit, seed_history, deletion_ids

NOW = datetime.datetime.now(datetime.timezone.utc)
FMT = "%Y-%m-%dT%H:%M:%S+00:00"
NOTIF = {"media_type": "Telegram", "usergroups": ["Network Operations"], "approved_by": "noc-lead", "approval_reference": "CHG-1"}


def scope_dict(**over):
    s = {"approved_by": "noc-lead", "approval_reference": "CHG-1", "window_start": (NOW - datetime.timedelta(hours=1)).strftime(FMT),
         "window_end": (NOW + datetime.timedelta(hours=2)).strftime(FMT), "media_type": "Telegram", "usergroups": ["Network Operations"],
         "test_scope": {"hostgroup": SY.HOSTGROUP, "host": SY.HOST, "cases": ["A", "B", "C"]}}
    s.update(over)
    return s


def write_scope(tmp, **over):
    p = pathlib.Path(tmp) / "scope.yaml"
    p.write_text(yaml.safe_dump(scope_dict(**over)), encoding="utf-8")
    return str(p)


def fake_lab():
    fz = FakeZabbix()
    fz.add_action("NETOPS-IaC Interface Alerts", {"evaltype": 0, "conditions": [{"conditiontype": 25, "operator": 0, "value": "netops_alert"}]})
    fz.users = [{"userid": "u1", "usrgrpids": ["7"], "medias": [{"mediatypeid": "3", "active": "0"}]},
                {"userid": "u2", "usrgrpids": ["7"], "medias": [{"mediatypeid": "3", "active": "0"}]}]
    return fz


class Base(unittest.TestCase):
    def setUp(self):
        self.fz = fake_lab()
        self.api = ZabbixAPI("https://f.example", "t", transport=self.fz)
        self.p = Project(fake=self.fz)
        self.scope = SY.load_scope(write_scope(self.p.base))

    def tearDown(self):
        self.p.close()
        self.assertEqual([w for w in self.fz.writes() if not w.startswith("action.")], [], "the synthetic tooling must never write to Zabbix (only the test fixture setup may call action apply)")

    def pre(self):
        return SY.preflight(self.api, self.scope, NOTIF, now=NOW)

    def failing(self, r):
        return [c["check"] for c in r["checks"] if not c["ok"]]


class TestScopeApproval(unittest.TestCase):
    def load(self, **over):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            return SY.load_scope(write_scope(d, **over))

    def test_valid(self):
        self.assertEqual(self.load()["test_scope"]["cases"], ["A", "B", "C"])

    def test_every_approval_field_is_mandatory_no_fallback(self):
        for k in ("approved_by", "approval_reference", "media_type"):
            with self.assertRaises(AuditError, msg=k):
                self.load(**{k: ""})
        for bad in ([], [""], None):
            with self.assertRaises(AuditError):
                self.load(usergroups=bad)

    def test_shipped_example_is_refused(self):
        with self.assertRaises(AuditError):
            SY.load_scope(str(ROOT / "config" / "synthetic-test.example.yaml"))

    def test_namespace_is_fixed(self):
        with self.assertRaises(AuditError):
            self.load(test_scope={"hostgroup": "Production", "host": SY.HOST, "cases": ["A"]})
        with self.assertRaises(AuditError):
            self.load(test_scope={"hostgroup": SY.HOSTGROUP, "host": "RTR-01", "cases": ["A"]})

    def test_case_d_is_excluded_from_the_default_and_needs_its_own_approval(self):
        with self.assertRaises(AuditError) as cm:
            self.load(test_scope={"hostgroup": SY.HOSTGROUP, "host": SY.HOST, "cases": ["A", "D"]})
        self.assertIn("case_d", str(cm.exception))
        ok = self.load(test_scope={"hostgroup": SY.HOSTGROUP, "host": SY.HOST, "cases": ["A", "D"]},
                       case_d={"approved_by": "noc-lead", "approval_reference": "CHG-2", "interface_recipients_notified": True})
        self.assertIn("D", ok["test_scope"]["cases"])
        with self.assertRaises(AuditError):
            self.load(test_scope={"hostgroup": SY.HOSTGROUP, "host": SY.HOST, "cases": ["A", "D"]},
                      case_d={"approved_by": "noc-lead", "approval_reference": "CHG-2", "interface_recipients_notified": False})
        with self.assertRaises(AuditError):
            self.load(case_d={"approved_by": "x" * 5, "approval_reference": "y" * 5, "interface_recipients_notified": True})   # D not in cases
        self.assertEqual(SY.DEFAULT_CASES, ("A", "B", "C"))

    def test_window_rules(self):
        n = NOW
        with self.assertRaises(AuditError):
            self.load(window_start=n.strftime("%Y-%m-%dT%H:%M:%S"), window_end=(n + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"))   # no offset
        with self.assertRaises(AuditError):
            self.load(window_start=(n + datetime.timedelta(hours=2)).strftime(FMT), window_end=n.strftime(FMT))
        with self.assertRaises(AuditError):
            self.load(window_start=n.strftime(FMT), window_end=(n + datetime.timedelta(hours=9)).strftime(FMT))

    def test_unknown_keys_rejected(self):
        with self.assertRaises(AuditError):
            self.load(extra="x")


class TestPreflight(Base):
    def test_clean_lab_passes(self):
        r = self.pre()
        self.assertTrue(r["ok"], r["checks"])
        self.assertEqual(r["recipients"], ["u1", "u2"])

    def test_scope_recipients_must_equal_the_action_configuration(self):
        for bad in (dict(NOTIF, usergroups=["Zabbix administrators"]), dict(NOTIF, media_type="Email")):
            r = SY.preflight(self.api, self.scope, bad, now=NOW)
            self.assertFalse(r["ok"])
            self.assertIn("scope recipients equal the action configuration", self.failing(r))

    def test_every_preexisting_synthetic_object_refuses_execution(self):
        cases = {
            "hostgroups": lambda fz: fz.hostgroups.update({"900": SY.HOSTGROUP}),
            "hosts": lambda fz: fz.add_host(SY.HOST),
            "items": lambda fz: fz.add_item(fz.add_host("OTHER-HOST"), SY.ITEM_KEY),
            "triggers": lambda fz: fz.add_trigger(fz.add_host("OTHER-HOST"), SY.TRIGGER_PREFIX + "someone elses", []),
        }
        for kind, make in cases.items():
            self.setUp()
            make(self.fz)
            r = self.pre()
            self.assertFalse(r["ok"], kind)
            self.assertEqual(self.failing(r), ["synthetic namespace empty: %s" % kind], kind)
            self.tearDown()
        self.setUp()

    def test_any_trigger_already_carrying_netops_hardware_refuses(self):
        hid = self.fz.add_host("R1")
        self.fz.add_trigger(hid, "real hw", [], tags=(("netops_hardware", "1"),))
        self.assertIn("no trigger carries netops_hardware (nothing else can fire through the hardware action)", self.failing(self.pre()))

    def test_an_enabled_hardware_action_refuses(self):
        self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="0")
        self.assertEqual(len(self.failing(self.pre())), 1)
        self.assertIn("PRE-EXISTING", self.failing(self.pre())[0])

    def test_an_absent_hardware_action_is_fine(self):
        self.assertTrue(self.pre()["ok"])

    def test_a_preexisting_disabled_action_blocks_the_test_and_there_is_no_acknowledgement_path(self):
        self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        r = self.pre()
        self.assertFalse(r["ok"])
        self.assertIn("PRE-EXISTING", self.failing(r)[0])
        with self.assertRaises(AuditError) as cm:
            SY.load_scope(write_scope(self.p.base, existing_hardware_action={"acknowledged": True, "note": "left over from HW-N1"}))
        self.assertIn("cannot be acknowledged", str(cm.exception))

    def test_missing_interface_action_refuses(self):
        self.fz.actions.clear()
        self.assertIn("Interface Alerting action present and snapshotted", self.failing(self.pre()))

    def test_unapproved_or_missing_recipients_refuse_and_never_fall_back(self):
        self.fz.usergroups[:] = [{"usrgrpid": "9", "name": "Zabbix administrators"}]
        r = self.pre()
        self.assertFalse(r["ok"])
        self.assertEqual(r["recipients"], [])
        self.fz.usergroups[:] = [{"usrgrpid": "7", "name": "Network Operations"}]
        self.fz.users[:] = []
        self.assertFalse(self.pre()["ok"])

    def test_outside_the_window_execution_is_refused_but_review_is_allowed(self):
        later = NOW + datetime.timedelta(days=5)
        r = SY.preflight(self.api, self.scope, NOTIF, now=later)               # execute mode (default)
        self.assertFalse(r["ok"])
        self.assertFalse(r["execution_allowed"])
        self.assertEqual(self.failing(r), ["INSIDE THE APPROVED WINDOW (mandatory to execute)"])
        rv = SY.preflight(self.api, self.scope, NOTIF, now=later, mode="review")
        self.assertTrue(rv["ok"])
        self.assertFalse(rv["execution_allowed"])                                # ready is not permission
        inside = SY.preflight(self.api, self.scope, NOTIF, now=NOW)
        self.assertTrue(inside["execution_allowed"])

    def test_cli_preflight_exit_codes_and_no_writes(self):
        p = self.p
        p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        p.write("config/synthetic-test.yaml", yaml.safe_dump(scope_dict()))
        rc, out, err = p.run("--env", "lab", "synthetic", "preflight")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("PREFLIGHT PASS", out)
        self.fz.add_host(SY.HOST)
        rc, out, err = p.run("--env", "lab", "synthetic", "preflight")
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", out)

    def test_cli_refuses_production_before_contact(self):
        pr = Project(env="production", fake=FakeZabbix(identity="production"), extra_top="zabbix: {url_regex: '^https://zbx\\\\.prod\\\\.example$'}\n")
        try:
            rc, out, err = pr.run("--env", "production", "synthetic", "preflight")
            self.assertEqual(rc, 3)
            self.assertIn("LAB only", err)
            self.assertEqual(pr.fake.calls, [])
        finally:
            pr.close()


class TestManifest(Base):
    def test_snapshot_records_the_interface_action_and_is_stable(self):
        a = SY.snapshot(self.api, self.scope, now=NOW)
        b = SY.snapshot(self.api, self.scope, now=NOW + datetime.timedelta(minutes=5))
        self.assertEqual(len(a["interface_actions"]), 1)
        self.assertEqual(a["interface_actions"][0]["name"], "NETOPS-IaC Interface Alerts")
        self.assertEqual(a["manifest_sha256"], b["manifest_sha256"])
        self.assertEqual(a["hardware_action"], {"exists": False, "actionid": None, "status": None, "signature": None, "definition_sha256": None})
        self.assertEqual(a["recipients"], ["u1", "u2"])
        self.assertEqual(SY.diff(a, b), [])

    def test_diff_detects_a_changed_interface_action(self):
        before = SY.snapshot(self.api, self.scope, now=NOW)
        ia = next(iter(self.fz.actions.values()))
        ia["filter"]["conditions"][0]["value"] = "something_else"
        self.assertTrue(any("CHANGED" in d for d in SY.diff(before, SY.snapshot(self.api, self.scope, now=NOW))))

    def test_diff_detects_leftovers_and_an_enabled_hardware_action(self):
        before = SY.snapshot(self.api, self.scope, now=NOW)
        self.fz.hostgroups["901"] = SY.HOSTGROUP
        self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="0")
        d = SY.diff(before, SY.snapshot(self.api, self.scope, now=NOW))
        self.assertTrue(any("synthetic hostgroups still present" in x for x in d))
        self.assertTrue(any("left ENABLED" in x for x in d))
        self.assertTrue(any("hardware action state differs" in x for x in d))

    def test_diff_detects_new_hardware_tagged_triggers(self):
        before = SY.snapshot(self.api, self.scope, now=NOW)
        self.fz.add_trigger(self.fz.add_host("R2"), "x", [], tags=(("netops_hardware", "1"),))
        self.assertTrue(any("netops_hardware" in x for x in SY.diff(before, SY.snapshot(self.api, self.scope, now=NOW))))

    def test_cli_snapshot_and_diff(self):
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.write("config/synthetic-test.yaml", yaml.safe_dump(scope_dict()))
        out = str(pathlib.Path(self.p.base) / "before.json")
        self.assertEqual(self.p.run("--env", "lab", "synthetic", "snapshot", "--out", out)[0], 0)
        self.assertEqual(self.p.run("--env", "lab", "synthetic", "diff", "--before", out, "--after", out)[0], 0)


class TestLedgerAndCleanup(Base):
    def make_fixtures(self):
        fz = self.fz
        gid = "910"
        fz.hostgroups[gid] = SY.HOSTGROUP
        hid = fz.add_host(SY.HOST)
        iid = fz.add_item(hid, SY.ITEM_KEY)
        ta = fz.add_trigger(hid, SY.CASE_TRIGGER["A"], [iid], tags=(("netops_hardware", "1"), ("hardware_component", "fan")))
        tb = fz.add_trigger(hid, SY.CASE_TRIGGER["B"], [iid], tags=(("scope", "availability"),))
        aid = create_owned_action(self.p, "0")
        led = SY.Ledger(str(pathlib.Path(self.p.base) / "state" / "synthetic" / "ledger.json"))
        led.record("hostgroup", gid)
        led.record("host", hid)
        led.record("item", iid)
        led.record("trigger", ta, "A")
        led.record("trigger", tb, "B")
        led.record("action", aid)
        led.data["action_created_by_test"] = True
        led.data["enabled_at"] = "t"
        led.save()
        return led, dict(gid=gid, hid=hid, iid=iid, ta=ta, tb=tb, aid=aid)

    def test_empty_ledger_refuses(self):
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, SY.Ledger(str(pathlib.Path(self.p.base) / "l.json")), self.p.base)

    def test_plan_contains_exactly_the_ledger_ids_in_safe_order(self):
        led, ids = self.make_fixtures()
        plan = SY.cleanup_plan(self.api, led, self.p.base)
        self.assertEqual([s["method"] for s in plan], ["action.update", "trigger.delete", "item.delete", "host.delete", "hostgroup.delete", "(tool)"])
        self.assertEqual(plan[0]["params"], {"actionid": ids["aid"], "status": 1})
        self.assertEqual(plan[1]["params"], sorted([ids["ta"], ids["tb"]]))
        self.assertEqual(plan[2]["params"], [ids["iid"]])
        self.assertEqual(plan[3]["params"], [ids["hid"]])
        self.assertEqual(plan[4]["params"], [ids["gid"]])
        for s in plan:
            self.assertNotIn("name", json.dumps(s["params"]).lower() if s["method"] != "(tool)" else "")

    def test_an_object_the_test_did_not_create_blocks_cleanup(self):
        led, ids = self.make_fixtures()
        self.fz.add_trigger(ids["hid"], SY.TRIGGER_PREFIX + "another operator's trigger", [ids["iid"]])
        with self.assertRaises(AuditError) as cm:
            SY.cleanup_plan(self.api, led, self.p.base)
        self.assertIn("did not create", str(cm.exception))

    def test_someone_elses_preexisting_fixture_is_never_planned_for_deletion(self):
        led, ids = self.make_fixtures()
        other_host = self.fz.add_host("UNRELATED")
        other_trig = self.fz.add_trigger(other_host, "unrelated", [])
        plan = SY.cleanup_plan(self.api, led, self.p.base)
        doomed = deletion_ids(plan)
        self.assertNotIn(other_trig, doomed)
        self.assertNotIn(other_host, doomed)
        self.assertEqual(doomed, {ids["ta"], ids["tb"], ids["iid"], ids["hid"], ids["gid"]})

    def test_already_deleted_objects_are_skipped_and_action_not_redisabled(self):
        led, ids = self.make_fixtures()
        led.data["disabled_at"] = "t2"
        self.fz.actions[ids["aid"]]["status"] = "1"                              # really disabled on Zabbix
        self.fz.triggers[ids["hid"]] = []
        plan = SY.cleanup_plan(self.api, led, self.p.base)
        methods = [s["method"] for s in plan]
        self.assertNotIn("trigger.delete", methods)
        self.assertNotIn("action.update", methods)

    def test_an_action_the_test_did_not_create_is_never_claimed(self):
        led, ids = self.make_fixtures()
        led.data["action_created_by_test"] = False
        with self.assertRaises(AuditError) as cm:
            SY.cleanup_plan(self.api, led, self.p.base)
        self.assertIn("does not say this test created action", str(cm.exception))

    def test_ledger_roundtrip_and_private_mode(self):
        led, ids = self.make_fixtures()
        again = SY.Ledger.load(led.path)
        self.assertEqual(again.ids()["triggers"], sorted([ids["ta"], ids["tb"]]))
        with self.assertRaises(AuditError):
            led.record("trigger", "1", "Z")
        with self.assertRaises(AuditError):
            led.record("bogus", "1")

    def test_cli_cleanup_plan_prints_ids_only(self):
        led, ids = self.make_fixtures()
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.write("config/synthetic-test.yaml", yaml.safe_dump(scope_dict()))
        rc, out, err = self.p.run("--env", "lab", "synthetic", "cleanup-plan", "--ledger", led.path)
        self.assertEqual(rc, 0, err)
        self.assertIn(ids["ta"], out)
        self.assertIn("trigger.delete", out)


class TestVerifyCases(TestLedgerAndCleanup):
    GOOD = ("[HARDWARE PROBLEM] x on h", "Model:       SYNTHETIC-NOT-A-DEVICE\nVendor: synthetic\nSite:        LAB\nComponent:   fan  slot synthetic-1\nEvent ID: 5")

    def run_case_a(self, led, ids, users=("u1", "u2"), mutate=None):
        self.fz.events = [{"eventid": "e1", "r_eventid": "e2", "objectid": ids["ta"], "value": "1", "clock": "1"}]
        alerts = []
        for i, u in enumerate(users):
            alerts.append({"alertid": "p%d" % i, "actionid": ids["aid"], "eventid": "e1", "p_eventid": "0", "userid": u, "status": "1", "retries": "0", "error": "",
                           "subject": self.GOOD[0], "message": self.GOOD[1], "alerttype": "0"})
            alerts.append({"alertid": "r%d" % i, "actionid": ids["aid"], "eventid": "e2", "p_eventid": "e1", "userid": u, "status": "1", "retries": "0", "error": "",
                           "subject": "[HARDWARE RESOLVED] x", "message": "Resolved:    t\n" + self.GOOD[1], "alerttype": "0"})
        if mutate:
            mutate(alerts)
        self.fz.alerts = alerts
        return SY.verify_case(self.api, "A", led, ["u1", "u2"])

    def test_case_a_passes_with_one_problem_and_one_recovery_per_recipient(self):
        led, ids = self.make_fixtures()
        r = self.run_case_a(led, ids)
        self.assertTrue(r["ok"], r["findings"])

    def test_case_a_scales_with_recipients_not_globally_two(self):
        led, ids = self.make_fixtures()
        self.assertTrue(self.run_case_a(led, ids)["ok"])
        self.assertEqual(len(self.fz.alerts), 4)                       # 2 recipients x (1 Problem + 1 Recovery)

    def test_case_a_failures(self):
        led, ids = self.make_fixtures()
        r = self.run_case_a(led, ids, users=("u1",))
        self.assertFalse(r["ok"])
        r = self.run_case_a(led, ids, mutate=lambda al: al.append(dict(al[0], alertid="dup")))
        self.assertTrue(any("more than one" in f for f in r["findings"]))
        r = self.run_case_a(led, ids, mutate=lambda al: al[0].update(message="Model: *UNKNOWN*"))
        self.assertTrue(any("unexpanded macro" in f for f in r["findings"]))
        self.assertTrue(any("lacks the expanded value" in f for f in r["findings"]))
        r = self.run_case_a(led, ids, mutate=lambda al: al[1].update(status="2", error="boom"))
        self.assertTrue(any("not delivered cleanly" in f for f in r["findings"]))
        r = self.run_case_a(led, ids, mutate=lambda al: al.append(dict(al[0], alertid="x", userid="u9")))
        self.assertFalse(r["ok"])

    def test_case_a_unrecovered_problem_is_reported(self):
        led, ids = self.make_fixtures()
        self.fz.events = [{"eventid": "e1", "r_eventid": "0", "objectid": ids["ta"], "value": "1", "clock": "1"}]
        r = SY.verify_case(self.api, "A", led, ["u1", "u2"])
        self.assertTrue(any("not recovered" in f for f in r["findings"]))

    def test_cases_b_c_require_zero_hardware_notifications(self):
        led, ids = self.make_fixtures()
        add_evidence(self.fz, led, ids, "B", 1000, 1100, sent=1010, event_clock=1050)
        add_evidence(self.fz, led, ids, "C", 1200, 1300, sent=1210)
        seed_audit(self.fz, ids["aid"], created=100, enable=500, disable=2000)
        seed_history(self.fz, ids["iid"], [(1010, 2), (1060, 0), (1210, 5)])
        self.later = datetime.datetime.fromtimestamp(5000, datetime.timezone.utc)
        self.fz.events = [{"eventid": "e1", "r_eventid": "e2", "objectid": ids["ta"], "value": "1", "clock": "900"},
                          {"eventid": "b1", "r_eventid": "b2", "objectid": ids["tb"], "value": "1", "clock": "1050"}]
        self.fz.alerts = [{"alertid": "ctl", "actionid": ids["aid"], "eventid": "e1", "p_eventid": "0", "userid": "u1", "status": "1", "retries": "0", "error": "",
                           "subject": "s", "message": "m", "alerttype": "0"}]                     # positive control: the action was live for Case A
        self.assertTrue(SY.verify_case(self.api, "B", led, ["u1"], now=self.later)["ok"])
        self.fz.alerts.append({"alertid": "z", "actionid": ids["aid"], "eventid": "b1", "p_eventid": "0", "userid": "u1", "status": "1", "retries": "0", "error": "",
                           "subject": "s", "message": "m", "alerttype": "0"})
        r = SY.verify_case(self.api, "B", led, ["u1"], now=self.later)
        self.assertFalse(r["ok"])
        self.assertTrue(any("ZERO hardware-action notifications" in f for f in r["findings"]))
        self.assertTrue(any("exclusion violated" in f for f in r["findings"]))
        self.fz.alerts = self.fz.alerts[:1]
        self.assertTrue(SY.verify_case(self.api, "C", led, ["u1"], now=self.later)["ok"])

    def test_the_hardware_action_delivering_for_an_unrelated_event_is_caught(self):
        led, ids = self.make_fixtures()
        self.assertTrue(self.run_case_a(led, ids)["ok"])
        self.fz.alerts.append({"alertid": "s", "actionid": ids["aid"], "eventid": "unrelated-77", "p_eventid": "0", "userid": "u1", "status": "1", "retries": "0",
                               "error": "", "subject": "s", "message": "m", "alerttype": "0"})
        r = SY.verify_case(self.api, "C", led, ["u1"])
        self.assertTrue(any("unrelated-77" in f for f in r["findings"]))

    def test_interface_alerting_must_not_act_on_synthetic_events_in_the_default_cases(self):
        led, ids = self.make_fixtures()
        ia = [a for a in self.fz.actions.values() if a["name"].startswith("NETOPS-IaC")][0]["actionid"]
        self.run_case_a(led, ids)
        self.fz.alerts.append({"alertid": "i", "actionid": ia, "eventid": "e1", "p_eventid": "0", "userid": "u1", "status": "1", "retries": "0", "error": "",
                               "subject": "s", "message": "m", "alerttype": "0"})
        r = SY.verify_case(self.api, "A", led, ["u1", "u2"])
        self.assertTrue(any("Interface Alerting action" in f for f in r["findings"]))

    def test_verify_refuses_when_the_ledger_action_is_not_on_zabbix(self):
        led, ids = self.make_fixtures()
        led.data["action"] = "99999"
        self.assertFalse(SY.verify_case(self.api, "A", led, ["u1"])["ok"])


class TestPlanDocument(unittest.TestCase):
    DOC = (ROOT / "docs" / "SYNTHETIC-NOTIFICATION-TEST.md").read_text(encoding="utf-8")

    def test_message_counts_are_per_recipient_and_not_six(self):
        self.assertNotIn("6 messages", self.DOC)
        self.assertIn("1 Problem + 1 Recovery per approved recipient", self.DOC)
        self.assertIn("Case B", self.DOC)
        self.assertIn("zero hardware", self.DOC.lower())

    def test_three_result_labels_are_kept_distinct(self):
        for label in ("AUDIT PASS", "NOTIFICATION PIPELINE PASS (synthetic)", "REAL HARDWARE COVERAGE PASS"):
            self.assertIn(label, self.DOC)

    def test_case_d_is_excluded_by_default(self):
        self.assertIn("Case D is excluded from the default test", self.DOC)

    def test_cleanup_is_by_recorded_id_never_by_name(self):
        self.assertIn("never by name", self.DOC)
        self.assertIn("ledger", self.DOC)


if __name__ == "__main__":
    unittest.main()
