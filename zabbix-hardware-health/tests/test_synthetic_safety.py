"""Negative regression tests for the synthetic-test safety review: window gate, live-state cleanup, ownership verification, signature manifest, media type."""
import datetime
import pathlib
import unittest

import yaml

from hwh import action as A
from hwh import synthetic as SY
from hwh.api import AuditError, ZabbixAPI
from tests.fakes import FakeZabbix
from tests.helpers import Project
from tests.test_synthetic import NOTIF, NOW, fake_lab, scope_dict, write_scope

HOUR = datetime.timedelta(hours=1)
OUTSIDE_BEFORE = NOW - 5 * HOUR
OUTSIDE_AFTER = NOW + 5 * HOUR


class Safety(unittest.TestCase):
    def setUp(self):
        self.fz = fake_lab()
        self.api = ZabbixAPI("https://f.example", "t", transport=self.fz)
        self.p = Project(fake=self.fz)
        self.scope = SY.load_scope(write_scope(self.p.base))
        self.p.write("config/notifications.lab.yaml", yaml.safe_dump(NOTIF))
        self.p.write("config/synthetic-test.yaml", yaml.safe_dump(scope_dict()))

    def tearDown(self):
        self.p.close()
        self.assertEqual(self.fz.writes(), [], "the synthetic tooling must never write to Zabbix")

    def fixtures(self, action_status="0", created_by_test=True, enabled_at="t", disabled_at=None):
        fz = self.fz
        fz.hostgroups["910"] = SY.HOSTGROUP
        hid = fz.add_host(SY.HOST)
        iid = fz.add_item(hid, SY.ITEM_KEY)
        ta = fz.add_trigger(hid, SY.CASE_TRIGGER["A"], [iid], tags=(("netops_hardware", "1"),))
        tb = fz.add_trigger(hid, SY.CASE_TRIGGER["B"], [iid], tags=(("scope", "availability"),))
        aid = fz.add_action(A.ACTION_NAME, A.hardware_filter(), status=action_status)
        led = SY.Ledger(str(pathlib.Path(self.p.base) / "state" / "synthetic" / "ledger.json"))
        for kind, zid in (("hostgroup", "910"), ("host", hid), ("item", iid), ("action", aid)):
            led.record(kind, zid)
        led.record("trigger", ta, "A")
        led.record("trigger", tb, "B")
        led.data.update(action_created_by_test=created_by_test, enabled_at=enabled_at, disabled_at=disabled_at)
        led.save()
        return led, dict(hid=hid, iid=iid, ta=ta, tb=tb, aid=aid)


class TestWindowIsAnExecutionGate(Safety):
    def test_require_window(self):
        SY.require_window(self.scope, NOW)
        for t in (OUTSIDE_BEFORE, OUTSIDE_AFTER):
            with self.assertRaises(AuditError) as cm:
                SY.require_window(self.scope, t)
            self.assertIn("OUTSIDE THE APPROVED WINDOW", str(cm.exception))

    def test_window_boundaries_are_inclusive(self):
        a, b = self.scope["_window"]
        SY.require_window(self.scope, a)
        SY.require_window(self.scope, b)
        with self.assertRaises(AuditError):
            SY.require_window(self.scope, b + datetime.timedelta(seconds=1))

    def test_cli_preflight_outside_the_window_is_refused_before_any_server_contact(self):
        for t in (OUTSIDE_BEFORE, OUTSIDE_AFTER):
            self.fz.calls.clear()
            rc, out, err = self.p.run("--env", "lab", "synthetic", "preflight", clock=t)
            self.assertEqual(rc, 3)
            self.assertIn("OUTSIDE THE APPROVED WINDOW", err)
            self.assertEqual(self.fz.calls, [])

    def test_cli_preflight_inside_the_window_passes(self):
        rc, out, err = self.p.run("--env", "lab", "synthetic", "preflight", clock=NOW)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("execution may start", out)

    def test_cli_review_works_at_any_time_and_never_authorises(self):
        for t in (OUTSIDE_BEFORE, NOW, OUTSIDE_AFTER):
            rc, out, err = self.p.run("--env", "lab", "synthetic", "review", clock=t)
            self.assertEqual(rc, 0, out + err)
            self.assertIn("never authorises execution", out)
        rc, out, err = self.p.run("--env", "lab", "synthetic", "review", clock=OUTSIDE_BEFORE)
        self.assertIn("outside the approved window", out)

    def test_review_reports_not_ready_when_the_namespace_is_dirty(self):
        self.fz.add_host(SY.HOST)
        rc, out, err = self.p.run("--env", "lab", "synthetic", "review", clock=OUTSIDE_BEFORE)
        self.assertEqual(rc, 1)
        self.assertIn("NOT READY", out)

    def test_recording_fixtures_or_marking_enabled_is_gated_by_the_window(self):
        ledger = str(pathlib.Path(self.p.base) / "l.json")
        rc, out, err = self.p.run("--env", "lab", "synthetic", "ledger-record", "--ledger", ledger, "--kind", "host", "--id", "5", clock=OUTSIDE_AFTER)
        self.assertEqual(rc, 3)
        rc, out, err = self.p.run("--env", "lab", "synthetic", "ledger-mark", "--ledger", ledger, "--event", "enabled", clock=OUTSIDE_BEFORE)
        self.assertEqual(rc, 3)
        self.assertFalse(pathlib.Path(ledger).exists())
        rc, out, err = self.p.run("--env", "lab", "synthetic", "ledger-record", "--ledger", ledger, "--kind", "host", "--id", "5", clock=NOW)
        self.assertEqual(rc, 0, err)

    def test_winding_down_is_never_gated(self):
        led, ids = self.fixtures()
        late = OUTSIDE_AFTER
        rc, out, err = self.p.run("--env", "lab", "synthetic", "ledger-mark", "--ledger", led.path, "--event", "disabled", clock=late)
        self.assertEqual(rc, 0, err)
        rc, out, err = self.p.run("--env", "lab", "synthetic", "cleanup-plan", "--ledger", led.path, clock=late)
        self.assertEqual(rc, 0, err)
        before = str(pathlib.Path(self.p.base) / "b.json")
        self.assertEqual(self.p.run("--env", "lab", "synthetic", "snapshot", "--out", before, clock=late)[0], 0)


class TestCleanupInspectsTheLiveAction(Safety):
    def test_enabled_action_is_disabled_first_even_if_the_ledger_has_no_marks(self):
        led, ids = self.fixtures(action_status="0", enabled_at=None, disabled_at=None)
        plan = SY.cleanup_plan(self.api, led)
        self.assertEqual(plan[0]["method"], "action.update")
        self.assertEqual(plan[0]["params"], {"actionid": ids["aid"], "status": 1})
        self.assertIn("FIRST STEP", plan[0]["why"])

    def test_enabled_action_is_disabled_first_even_if_the_ledger_claims_it_was_disabled(self):
        led, ids = self.fixtures(action_status="0", enabled_at="t1", disabled_at="t2")
        self.assertEqual(SY.cleanup_plan(self.api, led)[0]["method"], "action.update")

    def test_disabled_action_needs_no_disable_step(self):
        led, ids = self.fixtures(action_status="1")
        self.assertNotIn("action.update", [s["method"] for s in SY.cleanup_plan(self.api, led)])

    def test_enabled_hardware_action_that_is_not_in_the_ledger_blocks_everything(self):
        led, ids = self.fixtures()
        led.data["action"] = None
        led.save()
        with self.assertRaises(AuditError) as cm:
            SY.cleanup_plan(self.api, led)
        self.assertIn("not in the ledger", str(cm.exception))

    def test_a_different_hardware_action_than_the_recorded_one_blocks(self):
        led, ids = self.fixtures(action_status="1")
        led.data["action"] = "999999"
        led.save()
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led)

    def test_recorded_action_id_that_is_not_the_hardware_action_blocks(self):
        led, ids = self.fixtures(action_status="1")
        led.data["action"] = [a for a in self.fz.actions if a != ids["aid"]][0]           # the Interface Alerting action
        led.save()
        with self.assertRaises(AuditError) as cm:
            SY.cleanup_plan(self.api, led)
        self.assertIn("not the hardware action", str(cm.exception))

    def test_preexisting_action_is_left_in_place_and_never_rolled_back_or_deleted(self):
        led, ids = self.fixtures(action_status="0", created_by_test=False)
        plan = SY.cleanup_plan(self.api, led)
        methods = [s["method"] for s in plan]
        self.assertEqual(methods[0], "action.update")                 # still disabled first
        self.assertNotIn("(tool)", methods)
        self.assertNotIn("action.delete", methods)
        self.assertEqual(plan[-1]["method"], "(none)")
        self.assertIn("PRE-EXISTED", plan[-1]["why"])

    def test_cli_cleanup_plan_shows_the_disable_first(self):
        led, ids = self.fixtures(action_status="0", enabled_at=None)
        rc, out, err = self.p.run("--env", "lab", "synthetic", "cleanup-plan", "--ledger", led.path, clock=OUTSIDE_AFTER)
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.splitlines()[0].lstrip().startswith("action.update"))


class TestOwnershipVerification(Safety):
    def test_clean_ledger_verifies(self):
        led, ids = self.fixtures()
        self.assertEqual(SY.verify_ownership(self.api, led), [])

    def test_a_wrong_host_id_is_refused_and_nothing_is_planned(self):
        led, ids = self.fixtures()
        other = self.fz.add_host("PRODUCTION-LOOKING-HOST")
        led.data["host"] = other
        led.save()
        with self.assertRaises(AuditError) as cm:
            SY.cleanup_plan(self.api, led)
        self.assertIn("ownership verification failed", str(cm.exception))
        self.assertIn("PRODUCTION-LOOKING-HOST", str(cm.exception))

    def test_a_wrong_trigger_id_is_refused(self):
        led, ids = self.fixtures()
        victim = self.fz.add_trigger(self.fz.add_host("R9"), "someone elses trigger", [])
        led.data["triggers"]["A"] = victim
        led.save()
        with self.assertRaises(AuditError) as cm:
            SY.cleanup_plan(self.api, led)
        self.assertIn("someone elses trigger", str(cm.exception))

    def test_a_trigger_with_the_right_name_on_the_wrong_host_is_refused(self):
        led, ids = self.fixtures()
        stray = self.fz.add_trigger(self.fz.add_host("R9"), SY.CASE_TRIGGER["A"], [])
        led.data["triggers"]["A"] = stray
        led.save()
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led)

    def test_a_wrong_item_id_and_a_wrong_group_id_are_refused(self):
        led, ids = self.fixtures()
        other_item = self.fz.add_item(self.fz.add_host("R8"), "icmpping")
        led.data["item"] = other_item
        led.save()
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led)
        led, ids = self.fixtures()
        self.fz.hostgroups["911"] = "Linux servers"
        led.data["hostgroup"] = "911"
        led.save()
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led)

    def test_a_foreign_object_in_the_namespace_still_blocks(self):
        led, ids = self.fixtures()
        self.fz.add_trigger(ids["hid"], SY.TRIGGER_PREFIX + "extra", [ids["iid"]])
        with self.assertRaises(AuditError):
            SY.cleanup_plan(self.api, led)

    def test_deletion_params_are_only_recorded_ids(self):
        led, ids = self.fixtures()
        bystander = self.fz.add_host("BYSTANDER")
        plan = SY.cleanup_plan(self.api, led)
        flat = str([s["params"] for s in plan])
        self.assertNotIn(bystander, flat)
        self.assertEqual(plan[1]["params"], sorted([ids["ta"], ids["tb"]]))


class TestSignatureManifest(Safety):
    def snap(self):
        return SY.snapshot(self.api, self.scope, now=NOW)

    def test_manifest_carries_signature_and_hash(self):
        self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        h = self.snap()["hardware_action"]
        self.assertEqual(h["signature"]["evaltype"], "1")
        self.assertEqual(len(h["definition_sha256"]), 64)

    def test_unchanged_preexisting_action_has_no_difference(self):
        self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        before = self.snap()
        self.assertEqual(SY.diff(before, self.snap()), [])

    def test_definition_change_with_unchanged_status_is_detected(self):
        aid = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        before = self.snap()
        self.fz.actions[aid]["filter"]["conditions"] = [{"conditiontype": "25", "operator": "0", "value": "scope"}]
        d = SY.diff(before, self.snap())
        self.assertTrue(any("DEFINITION CHANGED" in x and "conds" in x for x in d), d)

    def test_message_text_change_is_detected(self):
        aid = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        self.fz.actions[aid]["operations"] = [{"operationtype": 0, "opmessage": {"subject": "a", "message": "b", "mediatypeid": "3"}, "opmessage_grp": [{"usrgrpid": "7"}]}]
        before = self.snap()
        self.fz.actions[aid]["operations"][0]["opmessage"]["message"] = "tampered"
        self.assertTrue(any("DEFINITION CHANGED" in x for x in SY.diff(before, self.snap())))

    def test_recipient_change_is_detected(self):
        aid = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        self.fz.actions[aid]["operations"] = [{"operationtype": 0, "opmessage": {"subject": "a", "message": "b", "mediatypeid": "3"}, "opmessage_grp": [{"usrgrpid": "7"}]}]
        before = self.snap()
        self.fz.actions[aid]["operations"][0]["opmessage_grp"] = [{"usrgrpid": "9"}]
        self.assertTrue(any("groups" in x for x in SY.diff(before, self.snap())))

    def test_a_field_outside_the_signature_is_still_caught_by_the_hash(self):
        aid = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        before = self.snap()
        self.fz.actions[aid]["esc_period"] = "30m"
        d = SY.diff(before, self.snap())
        self.assertTrue(any("definition hash differs" in x for x in d), d)

    def test_deleted_and_recreated_action_is_detected(self):
        aid = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        before = self.snap()
        del self.fz.actions[aid]
        self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        self.assertTrue(any("id changed" in x for x in SY.diff(before, self.snap())))

    def test_action_left_enabled_or_vanished_is_detected(self):
        aid = self.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        before = self.snap()
        self.fz.actions[aid]["status"] = "0"
        d = SY.diff(before, self.snap())
        self.assertTrue(any("ENABLED" in x for x in d))
        del self.fz.actions[aid]
        self.assertTrue(any("state differs" in x for x in SY.diff(before, self.snap())))


class TestMediaTypeAndPreexistingAction(Safety):
    def test_a_disabled_approved_media_type_refuses(self):
        self.fz.mediatypes[0]["status"] = "1"
        r = SY.preflight(self.api, self.scope, NOTIF, now=NOW)
        self.assertFalse(r["ok"])
        self.assertEqual(r["recipients"], [])
        users, problems = SY.recipients(self.api, self.scope)
        self.assertTrue(any("DISABLED" in x for x in problems))

    def test_an_enabled_media_type_is_accepted(self):
        self.assertTrue(SY.preflight(self.api, self.scope, NOTIF, now=NOW)["ok"])

    def test_acknowledgement_without_an_existing_action_is_refused(self):
        scope = SY.load_scope(write_scope(self.p.base, existing_hardware_action={"acknowledged": True, "note": "n/a really"}))
        r = SY.preflight(self.api, scope, NOTIF, now=NOW)
        self.assertFalse(r["ok"])

    def test_bad_acknowledgement_shapes_are_rejected(self):
        for bad in ({"acknowledged": False, "note": "xxx"}, {"acknowledged": True}, {"acknowledged": True, "note": "ok-ish", "extra": 1}, "yes"):
            with self.assertRaises(AuditError):
                SY.load_scope(write_scope(self.p.base, existing_hardware_action=bad))


class TestVerifyPreconditions(Safety):
    def test_zero_notification_result_requires_the_enabled_mark(self):
        led, ids = self.fixtures(enabled_at=None)
        r = SY.verify_case(self.api, "B", led, ["u1"])
        self.assertFalse(r["ok"])
        self.assertIn("enabled_at", r["findings"][0])

    def test_zero_notification_result_requires_a_positive_control(self):
        led, ids = self.fixtures()
        self.fz.events = [{"eventid": "b1", "r_eventid": "b2", "objectid": ids["tb"], "value": "1", "clock": "1"}]
        r = SY.verify_case(self.api, "B", led, ["u1"])
        self.assertFalse(r["ok"])
        self.assertTrue(any("no positive control" in f for f in r["findings"]))
        r = SY.verify_case(self.api, "C", led, ["u1"])
        self.assertTrue(any("no positive control" in f for f in r["findings"]))

    def test_failure_output_tells_the_tester_to_disable_the_action(self):
        led, ids = self.fixtures()
        rc, out, err = self.p.run("--env", "lab", "synthetic", "verify", "--ledger", led.path, "--case", "A", clock=NOW)
        self.assertEqual(rc, 1)
        self.assertIn("DISABLE THE HARDWARE ACTION NOW", out)


class TestPlanDocumentSafety(unittest.TestCase):
    DOC = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "SYNTHETIC-NOTIFICATION-TEST.md").read_text(encoding="utf-8")

    def test_action_stays_enabled_through_all_default_cases(self):
        self.assertIn("kept enabled through Cases A, B and C", self.DOC)
        self.assertNotIn("immediately after Case A: set the recorded action back to disabled", self.DOC)

    def test_disable_immediately_after_the_cases_or_on_any_failure(self):
        self.assertIn("immediately after the last case", self.DOC)
        self.assertIn("on any failure", self.DOC.lower())

    def test_review_vs_execute_and_window_gate_are_documented(self):
        for s in ("synthetic review", "synthetic preflight", "mandatory execution gate", "refused outside the approved window"):
            self.assertIn(s, self.DOC)

    def test_live_action_inspection_and_ownership_are_documented(self):
        for s in ("live", "ownership", "pre-existing", "signature"):
            self.assertIn(s, self.DOC.lower().replace("pre-existing", "pre-existing"))


if __name__ == "__main__":
    unittest.main()
