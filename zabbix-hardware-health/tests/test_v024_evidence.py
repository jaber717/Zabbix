"""v0.2.4: evidence integrity. A negative synthetic case is PASS only with adequate AUTHORITATIVE (server-side) evidence; otherwise INCONCLUSIVE or FAIL.

Covers: forged observations, disable-during-event / re-enable, missing / truncated / late / unparseable audit history, unavailable evidence sources,
missing or contradictory item history, and the flaky-ID-substring regression."""
import datetime
import json
import pathlib
import unittest

import yaml

from hwh import action as A
from hwh import evidence as E
from hwh import synthetic as SY
from hwh.api import ZabbixAPI
from tests.helpers import Project, add_evidence, create_owned_action, deletion_ids, seed_audit, seed_history
from tests.test_synthetic import NOTIF, NOW, fake_lab, scope_dict
from tests.test_v023_regressions import Mixin

T0 = int(NOW.timestamp())


def dt(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)


def row(aid, clock, action, details, rtype="5", rid=None, name=A.ACTION_NAME):
    return {"auditid": "x%s%s" % (clock, action), "clock": str(clock), "action": str(action), "resourcetype": rtype, "resourceid": str(rid if rid is not None else aid),
            "resourcename": name, "details": details if isinstance(details, str) else json.dumps(details)}


class EvBase(Mixin, unittest.TestCase):
    def ready(self, case="B", enable=T0 - 100, disable=T0 + 500, created=T0 - 1000, extra=None, hist=None, event=T0 + 20, sent=T0 + 10, audit=True):
        led, ids = self.fixtures()
        self.caseA_alert(ids)
        if case == "B":
            add_evidence(self.fz, led, ids, "B", T0, T0 + 60, sent=sent, event_clock=event)
            hist = [(T0 + 10, 2), (T0 + 50, 0)] if hist is None else hist
        else:
            add_evidence(self.fz, led, ids, "C", T0, T0 + 60, sent=sent)
            hist = [(T0 + 10, 5)] if hist is None else hist
        if audit:
            seed_audit(self.fz, ids["aid"], created=created, enable=enable, disable=disable, extra=extra)
        seed_history(self.fz, ids["iid"], hist)
        self.ids = ids
        return led, ids

    def v(self, case, led, off=1000, scope=None):
        return SY.verify_case(self.api, case, led, ["u1"], scope, dt(T0 + off))

    def has(self, r, text):
        self.assertTrue(any(text in f for f in r["findings"]), r["findings"])

    def verdict(self, r, want):
        self.assertEqual(r["verdict"], want, r["findings"])
        self.assertEqual(r["ok"], want == "PASS")


class TestPassOnlyWithAdequateAuthoritativeEvidence(EvBase):
    def test_complete_consistent_evidence_passes_B_and_C(self):
        led, ids = self.ready("B")
        self.verdict(self.v("B", led), "PASS")
        led2, ids2 = self.fixtures_again()
        led2, ids2 = self.ready("C")
        self.verdict(self.v("C", led2), "PASS")

    def fixtures_again(self):
        self.tearDown()
        self.setUp()
        return None, None

    def test_local_evidence_alone_is_never_a_pass(self):
        led, ids = self.ready("B", audit=False)
        self.fz.history.clear()
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")

    def test_the_acceptance_rule_text_is_in_the_result_contract(self):
        self.assertIn("never an assumed PASS", SY.verify_case.__doc__)


class TestAuditEvidenceUnavailableOrIncomplete(EvBase):
    def test_unavailable_to_the_account_is_inconclusive_with_the_permission_note(self):
        led, ids = self.ready("B")
        self.fz.denied.add("auditlog.get")
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "Super Admin")
        self.has(r, "never requests")

    def test_settings_unreadable_is_inconclusive(self):
        led, ids = self.ready("B")
        self.fz.denied.add("settings.get")
        self.verdict(self.v("B", led), "INCONCLUSIVE")

    def test_audit_logging_disabled_is_inconclusive(self):
        led, ids = self.ready("B")
        self.fz.settings["auditlog_enabled"] = "0"
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "audit logging is not enabled")
        self.fz.settings.update(auditlog_enabled="1")

    def test_auditlog_mode_is_not_an_evidence_gate(self):
        # Zabbix 7.0: auditlog_mode only controls LLD / network-discovery / autoregistration logging by the server; it says nothing about user changes
        led, ids = self.ready("B")
        self.fz.settings.update(auditlog_enabled="1", auditlog_mode="0")
        self.verdict(self.v("B", led), "PASS")

    def test_auditlog_mode_change_record_does_not_break_continuity(self):
        led, ids = self.ready("B")
        self.fz.auditlog.append(row(0, T0 - 500, 1, {"settings.auditlog_mode": ["update", "1", "0"]}, rtype="39", rid="1", name=""))
        self.verdict(self.v("B", led), "PASS")

    def test_an_empty_audit_response_is_never_read_as_no_changes(self):
        led, ids = self.ready("B", audit=False)
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "no 'add' record")
        self.has(r, "NOT evidence of no change")

    def test_records_of_another_resource_type_do_not_count(self):
        led, ids = self.ready("B")
        for r_ in self.fz.auditlog:
            r_["resourcetype"] = "6"
        self.verdict(self.v("B", led), "INCONCLUSIVE")

    def test_too_early_to_trust_the_log(self):
        led, ids = self.ready("B")
        r = self.v("B", led, off=60 + 10)               # 'after' is at T0+60; need >= 60 s of settling
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "asynchronously")

    def test_truncated_audit_result_is_inconclusive(self):
        led, ids = self.ready("B")
        old = E.LIMIT
        E.LIMIT = 3                                      # add + enable + disable = 3 rows = the limit
        self.addCleanup(setattr, E, "LIMIT", old)
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "truncated")

    def test_row_count_mismatch_is_inconclusive(self):
        led, ids = self.ready("B")
        self.fz.audit_count_delta = 2
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "incomplete")

    def test_no_audit_record_after_the_interval_means_continuity_is_not_shown(self):
        led, ids = self.ready("B", disable=None)
        self.fz.actions[ids["aid"]]["status"] = "0"
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "no audit record for the action exists after the interval")

    def test_unparseable_update_details_are_inconclusive(self):
        led, ids = self.ready("B", extra=[row(0, T0 - 50, 1, "this is not json", rid=None)])
        for r_ in self.fz.auditlog:
            r_["resourceid"] = str(ids["aid"])
        self.verdict(self.v("B", led), "INCONCLUSIVE")

    def test_audit_settings_changed_since_creation_is_inconclusive(self):
        led, ids = self.ready("B", extra=[row(0, T0 - 500, 1, {"settings.auditlog_enabled": ["update", "1", "0"]}, rtype="39", rid="1", name="")])
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "audit logging settings were changed")

    def test_enabling_within_clock_skew_of_the_first_send_is_ambiguous(self):
        led, ids = self.ready("B", enable=T0 + 8)         # sent at T0+10: only 2 s apart (< SKEW)
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "clock skew")

    def test_no_add_record_but_a_later_update_is_still_inconclusive(self):
        led, ids = self.ready("B")
        self.fz.auditlog[:] = [x for x in self.fz.auditlog if x["action"] != "0"]
        self.verdict(self.v("B", led), "INCONCLUSIVE")


class TestAuditEvidenceContradictions(EvBase):
    def test_forged_enabled_observations_while_the_server_says_disabled_throughout(self):
        led, ids = self.ready("B", enable=None, disable=None)       # audit: created disabled, never enabled
        r = self.v("B", led)
        self.verdict(r, "FAIL")
        self.has(r, "NOT enabled")

    def test_disabled_during_the_event_and_re_enabled_before_the_after_observation(self):
        extra = [row(0, T0 + 20, 1, {"action.status": ["update", "1", "0"]}), row(0, T0 + 40, 1, {"action.status": ["update", "0", "1"]})]
        led, ids = self.ready("B", extra=extra)
        for r_ in self.fz.auditlog:
            r_["resourceid"] = str(ids["aid"])
        r = self.v("B", led)
        self.verdict(r, "FAIL")
        self.has(r, "status changing during case B")

    def test_enabled_only_after_the_value_was_sent(self):
        led, ids = self.ready("B", enable=T0 + 30)
        self.verdict(self.v("B", led), "FAIL")

    def test_definition_update_inside_the_interval_fails_and_outside_is_inconclusive(self):
        inside = [row(0, T0 + 30, 1, {"action.filter.evaltype": ["update", "0", "1"]})]
        led, ids = self.ready("B", extra=inside)
        for r_ in self.fz.auditlog:
            r_["resourceid"] = str(ids["aid"])
        self.verdict(self.v("B", led), "FAIL")
        self.tearDown()
        self.setUp()
        outside = [row(0, T0 - 50, 1, {"action.esc_period": ["update", "1h", "2h"]})]
        led, ids = self.ready("B", extra=outside)
        for r_ in self.fz.auditlog:
            r_["resourceid"] = str(ids["aid"])
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "definition")

    def test_deletion_of_the_action_is_a_fail(self):
        led, ids = self.ready("B", extra=[row(0, T0 + 200, 2, {})])
        for r_ in self.fz.auditlog:
            r_["resourceid"] = str(ids["aid"])
        r = self.v("B", led)
        self.verdict(r, "FAIL")
        self.has(r, "DELETION")

    def test_a_same_named_action_created_later_is_a_recreate_fail(self):
        led, ids = self.ready("B", extra=[row(0, T0 + 300, 0, {"action.status": ["add", "0"]}, rid="99999")])
        r = self.v("B", led)
        self.verdict(r, "FAIL")
        self.has(r, "recreate/duplicate")

    def test_audit_and_live_state_contradict(self):
        led, ids = self.ready("B")
        self.fz.actions[ids["aid"]]["status"] = "0"       # audit says disabled (final), Zabbix says enabled
        r = self.v("B", led)
        self.verdict(r, "FAIL")
        self.has(r, "CONTRADICTION")

    def test_two_add_records_for_one_action_fail(self):
        led, ids = self.ready("B", extra=[row(0, T0 - 900, 0, {"action.status": ["add", "1"]})])
        for r_ in self.fz.auditlog:
            r_["resourceid"] = str(ids["aid"])
        self.verdict(self.v("B", led), "FAIL")


class TestItemHistoryIsRequired(EvBase):
    def test_local_sent_mark_without_item_history_is_inconclusive(self):
        led, ids = self.ready("C", hist=[])
        r = self.v("C", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "no history sample exists")

    def test_history_with_the_value_five_passes(self):
        led, ids = self.ready("C")
        self.verdict(self.v("C", led), "PASS")

    def test_wrong_value_in_the_c_interval_is_a_contradiction(self):
        led, ids = self.ready("C", hist=[(T0 + 10, 5), (T0 + 30, 1)])
        r = self.v("C", led)
        self.verdict(r, "FAIL")
        self.has(r, "unexpected value")

    def test_only_a_different_value_means_five_was_never_seen(self):
        led, ids = self.ready("C", hist=[(T0 + 10, 7)])
        r = self.v("C", led)
        self.assertIn(r["verdict"], ("FAIL",))
        self.has(r, "unexpected")

    def test_a_five_that_predates_the_recorded_send_is_not_the_sent_value(self):
        led, ids = self.ready("C", hist=[(T0 - 3, 5)], sent=T0 + 30)
        r = self.v("C", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "at or after the recorded send time")

    def test_item_that_stores_no_history_or_the_wrong_item_is_inconclusive(self):
        led, ids = self.ready("C")
        for it in self.fz.items[ids["hid"]]:
            if it["itemid"] == ids["iid"]:
                it["history"] = "0"
        self.verdict(self.v("C", led), "INCONCLUSIVE")
        led.data["item"] = [i["itemid"] for i in self.fz.items[self.fz.add_host("OTHER")] or []] or [self.fz.add_item(self.fz.add_host("OTHER2"), "icmpping")]
        self.verdict(self.v("C", led), "INCONCLUSIVE")

    def test_truncated_history_is_inconclusive(self):
        led, ids = self.ready("C")
        old = E.LIMIT
        E.LIMIT = 1
        self.addCleanup(setattr, E, "LIMIT", old)
        seed_history(self.fz, ids["iid"], [(T0 + 11, 5)])
        # the audit query would also hit the tiny limit; the history path is exercised on its own:
        f, i = E.history_evidence(self.api, led, "C", T0, T0 + 60, [T0 + 10])
        self.assertTrue(any("truncated" in x for x in i), i)

    def test_history_not_readable_is_inconclusive(self):
        led, ids = self.ready("C")
        self.fz.denied.add("history.get")
        self.verdict(self.v("C", led), "INCONCLUSIVE")

    def test_case_b_history_must_show_both_values(self):
        led, ids = self.ready("B", hist=[(T0 + 10, 2)])
        r = self.v("B", led)
        self.verdict(r, "INCONCLUSIVE")
        self.has(r, "expected value(s) ['0']")


class TestOriginalCodexReproductionsFailClosed(EvBase):
    def test_forged_ledger_observations_with_a_really_disabled_action(self):
        led, ids = self.ready("B", enable=None, disable=None)
        self.assertEqual(self.fz.actions[ids["aid"]]["status"], "1")
        self.verdict(self.v("B", led), "FAIL")

    def test_honest_observations_but_unobserved_disable_re_enable(self):
        extra = [row(0, T0 + 15, 1, {"action.status": ["update", "1", "0"]}), row(0, T0 + 45, 1, {"action.status": ["update", "0", "1"]})]
        led, ids = self.ready("B", extra=extra)
        for r_ in self.fz.auditlog:
            r_["resourceid"] = str(ids["aid"])
        self.verdict(self.v("B", led), "FAIL")

    def test_case_c_with_a_local_sent_mark_and_two_enabled_snapshots_only(self):
        led, ids = self.ready("C", audit=False, hist=[])
        self.verdict(self.v("C", led), "INCONCLUSIVE")


class TestCliVerdicts(EvBase):
    def test_exit_codes_distinguish_pass_inconclusive_and_fail(self):
        led, ids = self.ready("B")
        late = dt(T0 + 1000)
        rc, out, err = self.p.run("--env", "lab", "synthetic", "verify", "--ledger", led.path, "--case", "B", clock=late)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("NOTIFICATION PIPELINE CHECK PASS", out)
        self.fz.denied.add("auditlog.get")
        rc, out, err = self.p.run("--env", "lab", "synthetic", "verify", "--ledger", led.path, "--case", "B", clock=late)
        self.assertEqual(rc, 4)
        self.assertIn("NOT a pass", out)
        self.fz.denied.clear()
        self.fz.settings["auditlog_enabled"] = "1"
        self.fz.auditlog[:] = [x for x in self.fz.auditlog if x["action"] == "0"]            # audit says disabled the whole time
        self.fz.actions[ids["aid"]]["status"] = "1"
        rc, out, err = self.p.run("--env", "lab", "synthetic", "verify", "--ledger", led.path, "--case", "B", clock=late)
        self.assertEqual(rc, 1)

    def test_audit_probe_reports_availability_read_only(self):
        rc, out, err = self.p.run("--env", "lab", "synthetic", "audit-probe", clock=NOW)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("AUTHORITATIVE EVIDENCE AVAILABLE", out)
        self.fz.denied.add("auditlog.get")
        rc, out, err = self.p.run("--env", "lab", "synthetic", "audit-probe", clock=NOW)
        self.assertEqual(rc, 4)
        self.assertIn("UNAVAILABLE", out)
        self.assertEqual(self.fz.writes(), [w for w in self.fz.writes() if w.startswith("action.")])

    def test_the_new_evidence_methods_are_reads_only(self):
        from hwh.api import READ_METHODS
        for m in ("auditlog.get", "history.get", "settings.get"):
            self.assertIn(m, READ_METHODS)
        api = ZabbixAPI("https://f.example", "t", transport=self.fz)
        for m in ("settings.update", "auditlog.delete", "history.clear", "user.create", "role.update"):
            with self.assertRaises(Exception):
                api.call(m, {})


class TestFlakyIdSubstringRegression(EvBase):
    def test_a_bystander_id_that_appears_inside_a_precondition_hash_is_not_a_deletion(self):
        led, ids = self.fixtures(action_status="0")
        import re
        live_hash = A.core_sha256(self.fz.actions[ids["aid"]])
        used = set(self.fz.hosts) | set(ids.values()) | set(self.fz.actions) | set(i["itemid"] for v in self.fz.items.values() for i in v)
        runs = [r for r in re.findall(r"[1-9][0-9]{2}", live_hash) if r not in used]
        if not runs:
            self.skipTest("this action hash holds no unused 3-digit run")
        self.fz._n = int(runs[0]) - 1                                                # the next object id is a digit run that occurs INSIDE the precondition hash
        bystander_host = self.fz.add_host("BYSTANDER")
        self.assertEqual(bystander_host, runs[0])
        plan = SY.cleanup_plan(self.api, led, self.p.base)
        self.assertIn(bystander_host, json.dumps(plan))                              # a naive substring search WOULD be fooled ...
        self.assertNotIn(bystander_host, deletion_ids(plan))                         # ... the parsed deletion-id set is not
        self.assertEqual(deletion_ids(plan), {ids["ta"], ids["tb"], ids["iid"], ids["hid"], "910"})


if __name__ == "__main__":
    unittest.main()
