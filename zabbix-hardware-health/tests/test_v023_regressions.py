"""v0.2.3: the three independently reproduced safety defects, as regression tests, including combined sequences.

FIX 1  Case B/C false PASS when the action was disabled after Case A
FIX 2  an operator-owned same-name action must never be updated, adopted or rolled back
FIX 3  emergency disable must not depend on fixture cleanup being possible
"""
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
from tests.helpers import Project, add_evidence, create_owned_action, seed_audit, seed_history
from tests.test_synthetic import NOTIF, NOW, fake_lab, scope_dict

T0 = int(NOW.timestamp())


class Mixin(object):
    def setUp(self):
        self.fz = fake_lab()
        self.api = ZabbixAPI("https://f.example", "t", transport=self.fz)
        self.p = Project(fake=self.fz)
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.write("config/synthetic-test.yaml", yaml.safe_dump(scope_dict()))

    def tearDown(self):
        self.p.close()
        self.assertEqual([w for w in self.fz.writes() if not w.startswith("action.")], [])

    def hw(self):
        return [a for a in self.fz.actions.values() if a["name"] == A.ACTION_NAME]

    def fixtures(self, action_status="0"):
        fz = self.fz
        fz.hostgroups["910"] = SY.HOSTGROUP
        hid = fz.add_host(SY.HOST)
        iid = fz.add_item(hid, SY.ITEM_KEY)
        ta = fz.add_trigger(hid, SY.CASE_TRIGGER["A"], [iid], tags=(("netops_hardware", "1"),))
        tb = fz.add_trigger(hid, SY.CASE_TRIGGER["B"], [iid], tags=(("scope", "availability"),))
        aid = create_owned_action(self.p, action_status)
        led = SY.Ledger(str(pathlib.Path(self.p.base) / "state" / "synthetic" / "ledger.json"))
        for kind, zid in (("hostgroup", "910"), ("host", hid), ("item", iid), ("action", aid)):
            led.record(kind, zid)
        led.record("trigger", ta, "A")
        led.record("trigger", tb, "B")
        led.data.update(action_created_by_test=True, enabled_at="2026-01-01T00:00:00Z", disabled_at=None)
        led.save()
        return led, dict(hid=hid, iid=iid, ta=ta, tb=tb, aid=aid)

    def caseA_alert(self, ids):
        self.fz.events = [{"eventid": "e1", "r_eventid": "e2", "objectid": ids["ta"], "value": "1", "clock": str(T0 - 5000)}]
        self.fz.alerts = [{"alertid": "a1", "actionid": ids["aid"], "eventid": "e1", "p_eventid": "0", "userid": "u1", "status": "1", "retries": "0", "error": "",
                           "subject": "s", "message": "m", "alerttype": "0"}]

    def verify(self, case, led, scope=None):
        return SY.verify_case(self.api, case, led, ["u1"], scope)


# =========================================================================================================== FIX 1
class TestFix1NegativeCasesNeedEvidence(Mixin, unittest.TestCase):
    def test_original_reproduction_action_disabled_before_B_and_C_is_no_longer_a_pass(self):
        led, ids = self.fixtures()
        self.caseA_alert(ids)
        self.fz.events.append({"eventid": "b1", "r_eventid": "b2", "objectid": ids["tb"], "value": "1", "clock": "2"})
        self.fz.actions[ids["aid"]]["status"] = "1"            # disabled after Case A, before B/C
        for case in ("B", "C"):
            r = self.verify(case, led)
            self.assertFalse(r["ok"], case)
            self.assertTrue(any("INCONCLUSIVE" in f for f in r["findings"]), r["findings"])

    def test_even_with_the_action_enabled_a_bare_zero_is_inconclusive_without_observations(self):
        led, ids = self.fixtures()
        self.caseA_alert(ids)
        self.fz.events.append({"eventid": "b1", "r_eventid": "b2", "objectid": ids["tb"], "value": "1", "clock": "2"})
        r = self.verify("B", led)                              # action is enabled, no alerts for B, ledger enabled_at present, Case A alert present
        self.assertFalse(r["ok"])
        self.assertIn("need exactly one 'before' and one 'after'", r["findings"][0])

    def good_B(self, led, ids, **kw):
        self.caseA_alert(ids)
        args = dict(sent=T0 + 10, event_clock=T0 + 20)
        args.update(kw)
        add_evidence(self.fz, led, ids, "B", T0, T0 + 60, **args)

    def test_complete_consistent_evidence_without_server_side_evidence_is_inconclusive_not_a_pass(self):
        led, ids = self.fixtures()
        self.good_B(led, ids)
        add_evidence(self.fz, led, ids, "C", T0 + 100, T0 + 160, sent=T0 + 110)
        for case in ("B", "C"):
            r = SY.verify_case(self.api, case, led, ["u1"], None, datetime.datetime.fromtimestamp(T0 + 1000, datetime.timezone.utc))
            self.assertEqual(r["verdict"], "INCONCLUSIVE", r["findings"])
            self.assertFalse(r["ok"])

    def test_complete_consistent_local_and_server_side_evidence_passes_B_and_C(self):
        led, ids = self.fixtures()
        self.good_B(led, ids)
        add_evidence(self.fz, led, ids, "C", T0 + 100, T0 + 160, sent=T0 + 110)
        seed_audit(self.fz, ids["aid"], created=T0 - 1000, enable=T0 - 100, disable=T0 + 500)
        seed_history(self.fz, ids["iid"], [(T0 + 10, 2), (T0 + 50, 0), (T0 + 110, 5)])
        late = datetime.datetime.fromtimestamp(T0 + 1000, datetime.timezone.utc)
        for case in ("B", "C"):
            r = SY.verify_case(self.api, case, led, ["u1"], None, late)
            self.assertEqual(r["verdict"], "PASS", r["findings"])
            self.assertTrue(r["ok"])

    def test_an_observation_showing_the_action_disabled_is_rejected(self):
        led, ids = self.fixtures()
        self.good_B(led, ids, status="1")
        r = self.verify("B", led)
        self.assertFalse(r["ok"])
        self.assertTrue(any("DISABLED" in f for f in r["findings"]))

    def test_a_disabled_observation_in_the_middle_of_the_interval_is_rejected(self):
        led, ids = self.fixtures()
        self.good_B(led, ids, disabled_between=True)
        r = self.verify("B", led)
        self.assertTrue(any("inside the interval shows the action DISABLED" in f for f in r["findings"]))

    def test_missing_after_or_before_is_rejected(self):
        led, ids = self.fixtures()
        self.good_B(led, ids)
        led.data["observations"] = [o for o in led.data["observations"] if o["phase"] != "after"]
        self.assertFalse(self.verify("B", led)["ok"])
        led.data["observations"] = []
        self.assertFalse(self.verify("B", led)["ok"])

    def test_an_interval_that_is_too_long_is_inconclusive(self):
        led, ids = self.fixtures()
        self.caseA_alert(ids)
        add_evidence(self.fz, led, ids, "B", T0, T0 + SY.MAX_CASE_SECONDS + 1, sent=T0 + 10, event_clock=T0 + 20)
        r = self.verify("B", led)
        self.assertTrue(any("could have been toggled unseen" in f for f in r["findings"]))

    def test_after_not_later_than_before_is_rejected(self):
        led, ids = self.fixtures()
        self.caseA_alert(ids)
        add_evidence(self.fz, led, ids, "B", T0 + 50, T0 + 50, sent=T0 + 50, event_clock=T0 + 50)
        self.assertTrue(any("not later than" in f for f in self.verify("B", led)["findings"]))

    def test_value_sent_or_event_outside_the_observed_interval_is_rejected(self):
        led, ids = self.fixtures()
        self.good_B(led, ids, sent=T0 + 500)
        self.assertTrue(any("outside the observed interval" in f for f in self.verify("B", led)["findings"]))
        led2, ids2 = self.fixtures_again()
        self.good_B(led2, ids2, event_clock=T0 + 500)
        self.assertTrue(any("event at" in f and "outside" in f for f in self.verify("B", led2)["findings"]))

    def fixtures_again(self):
        self.tearDown()
        self.setUp()
        return self.fixtures()

    def test_no_sent_mark_means_the_send_time_is_not_tied_to_the_interval(self):
        led, ids = self.fixtures()
        self.good_B(led, ids, sent=None)
        self.assertTrue(any("no 'sent' mark" in f for f in self.verify("B", led)["findings"]))

    def test_evidence_for_another_action_id_or_a_changed_definition_is_rejected(self):
        led, ids = self.fixtures()
        self.good_B(led, ids)
        led.data["observations"][0]["actionid"] = "424242"
        self.assertTrue(any("not the recorded" in f for f in self.verify("B", led)["findings"]))
        led, ids = self.fixtures_again()
        self.good_B(led, ids)
        self.fz.actions[ids["aid"]]["esc_period"] = "5m"
        self.fz.actions[ids["aid"]]["operations"][0]["opmessage"]["message"] += "x"
        self.assertTrue(any("definition changed" in f for f in self.verify("B", led)["findings"]))

    def test_ledger_disabled_before_the_end_of_the_interval_is_inconsistent(self):
        led, ids = self.fixtures()
        self.good_B(led, ids)
        led.data["disabled_at"] = datetime.datetime.fromtimestamp(T0 + 30, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertTrue(any("disabled at" in f for f in self.verify("B", led)["findings"]))

    def test_observations_outside_the_approved_window_are_rejected(self):
        led, ids = self.fixtures()
        self.caseA_alert(ids)
        far = T0 + 10 * 86400
        add_evidence(self.fz, led, ids, "B", far, far + 60, sent=far + 10, event_clock=far + 20)
        scope = SY.load_scope(str(pathlib.Path(self.p.base) / "config" / "synthetic-test.yaml"))
        self.assertTrue(any("outside the approved window" in f for f in self.verify("B", led, scope)["findings"]))

    def test_a_non_empty_alert_list_still_fails_even_with_perfect_evidence(self):
        led, ids = self.fixtures()
        self.good_B(led, ids)
        self.fz.alerts.append({"alertid": "z", "actionid": ids["aid"], "eventid": "xB1", "p_eventid": "0", "userid": "u1", "status": "1", "retries": "0", "error": "",
                               "subject": "s", "message": "m", "alerttype": "0"})
        r = self.verify("B", led)
        self.assertFalse(r["ok"])
        self.assertTrue(any("ZERO" in f for f in r["findings"]))

    def test_case_D_is_also_a_negative_case_for_the_hardware_action(self):
        led, ids = self.fixtures()
        self.assertIn("D", SY.NEGATIVE_CASES)

    # ---- the real command flow: observe -> events -> observe -> verify
    def cli(self, *args, clock):
        return self.p.run("--env", "lab", "synthetic", *args, clock=clock)

    def test_combined_sequence_through_the_cli(self):
        led, ids = self.fixtures(action_status="0")
        self.caseA_alert(ids)
        t = NOW
        step = datetime.timedelta
        self.assertEqual(self.cli("ledger-mark", "--ledger", led.path, "--event", "enabled", clock=t)[0], 0)
        self.assertEqual(self.cli("observe", "--ledger", led.path, "--case", "B", "--phase", "before", clock=t)[0], 0)
        self.assertEqual(self.cli("ledger-mark", "--ledger", led.path, "--event", "sent", "--case", "B", clock=t + step(seconds=10))[0], 0)
        self.fz.events.append({"eventid": "b1", "r_eventid": "b2", "objectid": ids["tb"], "value": "1", "clock": str(int((t + step(seconds=20)).timestamp()))})
        self.assertEqual(self.cli("observe", "--ledger", led.path, "--case", "B", "--phase", "after", clock=t + step(seconds=60))[0], 0)
        # a verify straight after the case is too early for the server to have flushed its audit log: INCONCLUSIVE (exit 4), never a pass
        rc, out, err = self.cli("verify", "--ledger", led.path, "--case", "B", clock=t + step(seconds=70))
        self.assertEqual(rc, 4, out + err)
        self.assertIn("INCONCLUSIVE - this is NOT a pass", out)
        # the test ends: the action is disabled (audit rows + item history exist on the server), then B is verified with authoritative evidence
        base = int(t.timestamp())
        seed_audit(self.fz, ids["aid"], created=base - 1000, enable=base - 100, disable=base + 150)
        seed_history(self.fz, ids["iid"], [(base + 10, 2), (base + 50, 0)])
        rc, out, err = self.cli("verify", "--ledger", led.path, "--case", "B", clock=t + step(seconds=300))
        self.assertEqual(rc, 0, out + err)
        # Case C has no observations at all
        rc, out, err = self.cli("verify", "--ledger", led.path, "--case", "C", clock=t + step(seconds=400))
        self.assertEqual(rc, 4)
        self.assertIn("INCONCLUSIVE", out)
        # observing while disabled records the fact and the case is then rejected
        self.assertEqual(self.cli("observe", "--ledger", led.path, "--case", "C", "--phase", "before", clock=t + step(seconds=210))[0], 0)
        self.assertEqual(self.cli("observe", "--ledger", led.path, "--case", "C", "--phase", "after", clock=t + step(seconds=230))[0], 0)
        self.assertEqual(self.cli("ledger-mark", "--ledger", led.path, "--event", "sent", "--case", "C", clock=t + step(seconds=220))[0], 0)
        rc, out, err = self.cli("verify", "--ledger", led.path, "--case", "C", clock=t + step(seconds=500))
        self.assertEqual(rc, 1)
        self.assertIn("DISABLED", out)

    def test_observe_is_window_gated_unique_and_refuses_unowned_actions(self):
        led, ids = self.fixtures()
        late = NOW + datetime.timedelta(days=3)
        self.assertEqual(self.cli("observe", "--ledger", led.path, "--case", "B", "--phase", "before", clock=late)[0], 3)
        self.assertEqual(self.cli("observe", "--ledger", led.path, "--case", "B", "--phase", "before", clock=NOW)[0], 0)
        rc, out, err = self.cli("observe", "--ledger", led.path, "--case", "B", "--phase", "before", clock=NOW)
        self.assertEqual(rc, 3)
        self.assertIn("never overwritten or duplicated", err)
        self.fz.actions[ids["aid"]]["operations"][0]["opmessage"]["message"] = "someone rewrote it"
        rc, out, err = self.cli("observe", "--ledger", led.path, "--case", "B", "--phase", "after", clock=NOW)
        self.assertEqual(rc, 3)
        self.assertIn("does not demonstrably own", err)

    def test_the_sent_mark_is_window_gated(self):
        led, ids = self.fixtures()
        late = NOW + datetime.timedelta(days=3)
        self.assertEqual(self.cli("ledger-mark", "--ledger", led.path, "--event", "sent", "--case", "B", clock=late)[0], 3)


# =========================================================================================================== FIX 2
class TestFix2PreExistingActionOwnership(Mixin, unittest.TestCase):
    def operator_action(self, status="1"):
        aid = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status=status)
        self.fz.actions[aid]["operations"] = [{"operationtype": 0, "opmessage": {"subject": "mine", "message": "operator text", "mediatypeid": "3"}, "opmessage_grp": [{"usrgrpid": "7"}]}]
        return aid

    def snapshot(self, aid):
        return json.dumps(self.fz.actions[aid], sort_keys=True)

    def test_original_reproduction_plan_is_a_conflict_not_an_update(self):
        aid = self.operator_action()
        rc, out, err = self.p.run("--env", "lab", "action", "plan")
        self.assertEqual(rc, 1)
        self.assertNotIn("UPDATE", out)
        self.assertIn("not demonstrably owned by this deployment", out)

    def test_apply_refuses_and_the_operator_action_is_byte_identical(self):
        aid = self.operator_action()
        before = self.snapshot(aid)
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 3)
        self.assertEqual(self.snapshot(aid), before)
        self.assertEqual(self.fz.writes(), [])
        self.assertFalse(list((pathlib.Path(self.p.base) / "state").rglob("*.json")) if (pathlib.Path(self.p.base) / "state").exists() else [])

    def test_enable_cannot_be_used_to_reach_an_operator_action(self):
        aid = self.operator_action()
        before = self.snapshot(aid)
        self.p.run("--env", "lab", "action", "apply", "--enable")
        self.assertEqual(self.snapshot(aid), before)
        self.assertEqual(self.fz.writes(), [])

    def test_api_level_apply_also_refuses_with_a_write_enabled_client(self):
        aid = self.operator_action()
        before = self.snapshot(aid)
        wapi = ZabbixAPI("https://f.example", "t", transport=self.fz, write=True)
        with self.assertRaises(AuditError):
            A.apply(wapi, "lab", A.load_spec(self.p.write("config/n.yaml", yaml.safe_dump(NOTIF))), False, str(pathlib.Path(self.p.base) / "none.yaml"), self.p.base)
        self.assertEqual(self.snapshot(aid), before)
        self.assertEqual(wapi.writes_made(), [])

    def test_a_stale_ownership_record_for_a_different_id_does_not_grant_ownership(self):
        create_owned_action(self.p, "1")
        mine = self.hw()[0]["actionid"]
        del self.fz.actions[mine]                              # the operator deleted ours and made their own with the same name
        theirs = self.operator_action()
        before = self.snapshot(theirs)
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 3)
        self.assertEqual(self.snapshot(theirs), before)

    def test_the_same_id_with_rewritten_text_is_no_longer_owned(self):
        create_owned_action(self.p, "1")
        aid = self.hw()[0]["actionid"]
        self.fz.actions[aid]["operations"][0]["opmessage"]["message"] = "operator rewrote the message"
        before = self.snapshot(aid)
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 3)
        self.assertEqual(self.snapshot(aid), before)

    def test_write_path_guard_catches_a_swap_between_plan_and_write(self):
        create_owned_action(self.p, "1")
        aid = self.hw()[0]["actionid"]
        spec = A.load_spec(self.p.write("config/n.yaml", yaml.safe_dump(NOTIF)))
        fz = self.fz
        orig = fz.dispatch
        state = {"swapped": False}

        def hooked(method, params):
            if method == "action.get" and params.get("actionids") and not state["swapped"]:
                state["swapped"] = True
                fz.actions[aid]["operations"][0]["opmessage"]["message"] = "swapped by someone else after the plan"
            return orig(method, params)
        fz.dispatch = hooked
        fz.actions[aid]["status"] = "0"                        # makes the plan want an update (disable)
        wapi = ZabbixAPI("https://f.example", "t", transport=fz, write=True)
        before_writes = len(fz.writes())
        with self.assertRaises(AuditError) as cm:
            A.apply(wapi, "lab", spec, False, str(pathlib.Path(self.p.base) / "none.yaml"), self.p.base)
        self.assertIn("REFUSED at the write", str(cm.exception))
        self.assertEqual(len(fz.writes()), before_writes)
        self.assertEqual(fz.actions[aid]["operations"][0]["opmessage"]["message"], "swapped by someone else after the plan")

    def test_an_owned_action_is_still_manageable(self):
        create_owned_action(self.p, "1")
        aid = self.hw()[0]["actionid"]
        self.fz.actions[aid]["status"] = "0"                   # enabled by hand: the tool disables it again (status is the one allowed difference)
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.fz.actions[aid]["status"], "1")
        self.assertEqual(len(self.hw()), 1)

    # ---- rollback
    def backups(self):
        d = pathlib.Path(self.p.base) / "state" / "backups"
        return sorted(str(x) for x in d.glob("hardware-action-lab-*.json")) if d.exists() else []

    def test_rollback_deletes_only_the_owned_action_it_created(self):
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.run("--env", "lab", "action", "apply")
        bk = self.backups()[0]
        bystander = self.fz.add_action("NETOPS-IaC Other", {"evaltype": 0, "conditions": []})
        before = self.snapshot(bystander)
        rc, out, err = self.p.run("--env", "lab", "action", "rollback", "--backup", bk)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.hw(), [])
        self.assertEqual(self.snapshot(bystander), before)
        self.assertFalse((pathlib.Path(self.p.base) / "state" / "ownership" / "hardware-action-lab.json").exists())

    def test_an_old_backup_never_deletes_a_different_action_with_the_same_name(self):
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.run("--env", "lab", "action", "apply")
        bk = self.backups()[0]
        mine = self.hw()[0]["actionid"]
        del self.fz.actions[mine]                              # ours is gone; the operator creates their own with the same name
        theirs = self.operator_action("0")
        before = self.snapshot(theirs)
        rc, out, err = self.p.run("--env", "lab", "action", "rollback", "--backup", bk)
        self.assertEqual(rc, 0, err)                           # recorded id no longer exists: nothing to do
        self.assertIn("nothing to do", out)
        self.assertEqual(self.snapshot(theirs), before)
        self.assertEqual(self.fz.writes().count("action.delete"), 0)        # the tool deleted nothing: theirs is untouched

    def test_rollback_refuses_when_the_id_matches_but_ownership_does_not(self):
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.run("--env", "lab", "action", "apply")
        bk = self.backups()[0]
        aid = self.hw()[0]["actionid"]
        self.fz.actions[aid]["operations"][0]["opmessage"]["message"] = "rewritten"
        before = self.snapshot(aid)
        rc, out, err = self.p.run("--env", "lab", "action", "rollback", "--backup", bk)
        self.assertEqual(rc, 3)
        self.assertEqual(self.snapshot(aid), before)

    def test_old_format_or_idless_backups_are_refused(self):
        aid = self.operator_action("0")
        before = self.snapshot(aid)
        for data in ({"environment": "lab", "action": A.ACTION_NAME, "existed": False, "previous": None},
                     {"schema": 2, "environment": "lab", "action": A.ACTION_NAME, "existed": False, "actionid": None, "nonce": None, "previous": None}):
            p = self.p.write("state/backups/hardware-action-lab-old.json", json.dumps(data))
            rc, out, err = self.p.run("--env", "lab", "action", "rollback", "--backup", p)
            self.assertEqual(rc, 3)
            self.assertIn("REFUSED", err)
            self.assertEqual(self.snapshot(aid), before)
        self.assertEqual(self.fz.writes(), [])

    def test_a_backup_from_another_deployment_with_a_foreign_nonce_is_refused(self):
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.run("--env", "lab", "action", "apply")
        bk = self.backups()[0]
        data = json.loads(pathlib.Path(bk).read_text(encoding="utf-8"))
        data["nonce"] = "hw-ffffffffffff"
        pathlib.Path(bk).write_text(json.dumps(data), encoding="utf-8")
        aid = self.hw()[0]["actionid"]
        before = self.snapshot(aid)
        rc, out, err = self.p.run("--env", "lab", "action", "rollback", "--backup", bk)
        self.assertEqual(rc, 3)
        self.assertEqual(self.snapshot(aid), before)

    def test_synthetic_workflow_refuses_a_preexisting_action_entirely(self):
        self.operator_action("1")
        rc, out, err = self.p.run("--env", "lab", "synthetic", "review", clock=NOW)
        self.assertEqual(rc, 1)
        self.assertIn("PRE-EXISTING", out)
        rc, out, err = self.p.run("--env", "lab", "synthetic", "ledger-record", "--ledger", str(pathlib.Path(self.p.base) / "l.json"), "--kind", "action", "--id", "5", clock=NOW)
        self.assertEqual(rc, 3)
        self.assertIn("--created-by-test", err)


# =========================================================================================================== FIX 3
class TestFix3EmergencyDisableIsIndependent(Mixin, unittest.TestCase):
    def test_original_reproduction_foreign_trigger_blocks_deletion_but_not_the_disable(self):
        led, ids = self.fixtures(action_status="0")
        self.fz.add_trigger(ids["hid"], SY.TRIGGER_PREFIX + "foreign", [ids["iid"]])
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led, self.p.base)                       # every deletion is blocked
        steps = SY.emergency_disable_plan(self.api, led, self.p.base)         # the disable is not
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["method"], "action.update")
        self.assertEqual(steps[0]["params"], {"actionid": ids["aid"], "status": 1})
        self.assertEqual(steps[0]["preconditions"]["actionid"], ids["aid"])
        self.assertEqual(len(steps[0]["preconditions"]["core_sha256"]), 64)

    def test_cli_cleanup_plan_refuses_deletions_and_still_prints_the_disable(self):
        led, ids = self.fixtures(action_status="0")
        self.fz.add_trigger(ids["hid"], SY.TRIGGER_PREFIX + "foreign", [ids["iid"]])
        rc, out, err = self.p.run("--env", "lab", "synthetic", "cleanup-plan", "--ledger", led.path, clock=NOW)
        self.assertEqual(rc, 1)
        self.assertIn("CLEANUP REFUSED (no deletion is planned)", out)
        self.assertIn("action.update", out)
        self.assertNotIn("trigger.delete", out)
        self.assertNotIn("host.delete", out)

    def test_cli_emergency_command_works_alone(self):
        led, ids = self.fixtures(action_status="0")
        rc, out, err = self.p.run("--env", "lab", "synthetic", "emergency-disable-plan", "--ledger", led.path, clock=NOW + datetime.timedelta(days=9))
        self.assertEqual(rc, 0, err)
        self.assertIn("EMERGENCY DISABLE", out)
        self.assertIn("preconditions to re-check", out)

    def test_works_with_an_incomplete_ledger(self):
        led, ids = self.fixtures(action_status="0")
        for k in ("hostgroup", "host", "item"):
            led.data[k] = None
        led.data["triggers"] = {}
        led.save()
        steps = SY.emergency_disable_plan(self.api, led, self.p.base)
        self.assertEqual([s["method"] for s in steps], ["action.update"])

    def test_works_when_fixture_ids_are_wrong_or_missing_on_zabbix(self):
        led, ids = self.fixtures(action_status="0")
        led.data["host"] = "999999"
        led.data["triggers"] = {"A": "888888"}
        led.save()
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led, self.p.base)
        self.assertEqual(len(SY.emergency_disable_plan(self.api, led, self.p.base)), 1)

    def test_nothing_to_do_when_the_owned_action_is_already_disabled(self):
        led, ids = self.fixtures(action_status="1")
        self.assertEqual(SY.emergency_disable_plan(self.api, led, self.p.base), [])

    def test_never_disables_an_unowned_action_by_name(self):
        # (a) an operator action with our name, ledger points at its id
        led, ids = self.fixtures(action_status="1")
        del self.fz.actions[ids["aid"]]
        theirs = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="0")
        led.data["action"] = theirs
        led.save()
        with self.assertRaises(AuditError) as cm:
            SY.emergency_disable_plan(self.api, led, self.p.base)
        self.assertIn("NOT being disabled by this tool", str(cm.exception))
        # (b) ledger has no action id but an enabled hardware action exists
        led.data["action"] = None
        led.save()
        with self.assertRaises(AuditError) as cm:
            SY.emergency_disable_plan(self.api, led, self.p.base)
        self.assertIn("NOT being disabled by name", str(cm.exception))
        # (c) ledger id gone, a different enabled hardware action exists
        led.data["action"] = "777777"
        led.save()
        with self.assertRaises(AuditError):
            SY.emergency_disable_plan(self.api, led, self.p.base)

    def test_missing_ownership_record_or_nonce_prevents_the_disable_and_preserves_evidence(self):
        led, ids = self.fixtures(action_status="0")
        (pathlib.Path(self.p.base) / "state" / "ownership" / "hardware-action-lab.json").unlink()
        with self.assertRaises(AuditError) as cm:
            SY.emergency_disable_plan(self.api, led, self.p.base)
        msg = str(cm.exception)
        self.assertIn("Manual recovery evidence", msg)
        ev = json.loads(msg.split("Manual recovery evidence: ")[1])
        self.assertEqual(ev["live_actionid"], ids["aid"])
        self.assertFalse(ev["record_present"])
        self.assertEqual(len(ev["live_core_sha256"]), 64)
        self.assertNotIn("message", ev)                       # ids and hashes only: no message text
        led2, ids2 = self.fixtures_again()
        self.fz.actions[ids2["aid"]]["operations"][0]["opmessage"]["message"] = "no nonce any more"
        with self.assertRaises(AuditError):
            SY.emergency_disable_plan(self.api, led2, self.p.base)

    def fixtures_again(self):
        self.tearDown()
        self.setUp()
        return self.fixtures(action_status="0")

    def test_ledger_not_saying_the_test_created_the_action_means_no_disable(self):
        led, ids = self.fixtures(action_status="0")
        led.data["action_created_by_test"] = False
        with self.assertRaises(AuditError):
            SY.emergency_disable_plan(self.api, led, self.p.base)

    def test_foreign_or_mismatched_fixture_ids_block_all_deletions(self):
        led, ids = self.fixtures(action_status="0")
        other = self.fz.add_host("NOT-OURS")
        led.data["host"] = other
        led.save()
        with self.assertRaises(AuditError) as cm:
            SY.cleanup_plan(self.api, led, self.p.base)
        self.assertIn("refusing to plan any deletion", str(cm.exception))
        self.assertEqual(len(SY.emergency_disable_plan(self.api, led, self.p.base)), 1)

    def test_clean_cleanup_still_starts_with_the_disable(self):
        led, ids = self.fixtures(action_status="0")
        plan = SY.cleanup_plan(self.api, led, self.p.base)
        self.assertEqual(plan[0]["method"], "action.update")
        self.assertEqual([s["method"] for s in plan[1:]], ["trigger.delete", "item.delete", "host.delete", "hostgroup.delete", "(tool)"])

    def test_a_different_hardware_action_than_the_recorded_one_blocks_deletion(self):
        led, ids = self.fixtures(action_status="1")
        led.data["action"] = "999999"
        led.save()
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led, self.p.base)


# =========================================================================================================== all three together
class TestCombinedSequence(Mixin, unittest.TestCase):
    def test_full_failure_story_ends_safe(self):
        led, ids = self.fixtures(action_status="0")                  # owned, enabled for the test
        self.fz.add_trigger(ids["hid"], SY.TRIGGER_PREFIX + "foreign", [ids["iid"]])   # something foreign shows up mid-test
        self.fz.actions[ids["aid"]]["status"] = "0"
        # 1. verification of a negative case is inconclusive (no evidence) - never a pass
        self.assertFalse(SY.verify_case(self.api, "B", led, ["u1"])["ok"])
        # 2. deletion is refused because of the foreign object ...
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led, self.p.base)
        # 3. ... but the tester can still make the action safe
        steps = SY.emergency_disable_plan(self.api, led, self.p.base)
        self.assertEqual(steps[0]["params"], {"actionid": ids["aid"], "status": 1})
        # 4. the tester disables it; the plan then reports nothing left to disable
        self.fz.actions[ids["aid"]]["status"] = "1"
        self.assertEqual(SY.emergency_disable_plan(self.api, led, self.p.base), [])
        # 5. an operator's same-named action can never be touched by the tool afterwards
        del self.fz.actions[ids["aid"]]
        theirs = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        snap = json.dumps(self.fz.actions[theirs], sort_keys=True)
        self.assertEqual(self.p.run("--env", "lab", "action", "apply")[0], 3)
        self.assertEqual(json.dumps(self.fz.actions[theirs], sort_keys=True), snap)


if __name__ == "__main__":
    unittest.main()
