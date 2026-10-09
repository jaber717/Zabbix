#!/usr/bin/env python3
"""Reproduce v0.2.2 safety gaps against an in-memory fake; never contacts Zabbix."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hwh import action as A
from hwh import synthetic as S
from hwh.api import AuditError, ZabbixAPI
from tests.test_synthetic import TestVerifyCases, NOTIF


def fixture():
    t = TestVerifyCases(methodName="test_cases_b_c_require_zero_hardware_notifications")
    t.setUp()
    ledger, ids = t.make_fixtures()
    t.fz.events = [
        {"eventid": "e1", "r_eventid": "e2", "objectid": ids["ta"], "value": "1", "clock": "1"},
        {"eventid": "b1", "r_eventid": "b2", "objectid": ids["tb"], "value": "1", "clock": "2"},
    ]
    t.fz.alerts = [{"alertid": "a1", "actionid": ids["aid"], "eventid": "e1", "p_eventid": "0",
                     "userid": "u1", "status": "1", "retries": "0", "error": "", "alerttype": "0"}]
    return t, ledger, ids


def main():
    t, ledger, ids = fixture()
    try:
        t.fz.actions[ids["aid"]]["status"] = "1"  # disabled before B/C
        print("disabled_action_case_B_false_PASS", S.verify_case(t.api, "B", ledger, ["u1"])["ok"])
        print("disabled_action_case_C_false_PASS", S.verify_case(t.api, "C", ledger, ["u1"])["ok"])
        t.fz.actions[ids["aid"]]["status"] = "0"  # enabled again, but foreign trigger appears
        t.fz.add_trigger(ids["hid"], S.TRIGGER_PREFIX + "foreign", [ids["iid"]])
        try:
            S.cleanup_plan(t.api, ledger)
            print("foreign_trigger_cleanup_refused", False)
        except AuditError:
            print("foreign_trigger_cleanup_refused", True)
            print("emergency_disable_step_available", False)
        print("real_API_writes", t.fz.writes())
    finally:
        t.tearDown()

    # The ordinary action plan is not scoped by synthetic ownership.
    t, ledger, ids = fixture()
    try:
        t.api = ZabbixAPI("https://fake.invalid", "not-a-secret", transport=t.fz, write=True)
        t.fz.actions[ids["aid"]]["status"] = "1"  # pre-existing, disabled operator action
        ledger.data["action_created_by_test"] = False
        validation = str(pathlib.Path(t.p.base) / "no-validation.json")
        p = A.plan(t.api, "lab", NOTIF, False, validation)
        print("preexisting_action_plan_requests_update", any(x.startswith("UPDATE action") for x in p["changes"]))
        print("plan_conflicts", len(p["conflicts"]))
        try:
            A.apply(t.api, "lab", NOTIF, False, validation, t.p.base)
        except AuditError:
            pass  # Any later readback failure cannot undo an earlier action.update.
        print("preexisting_action_fake_update_executed", "action.update" in t.fz.writes())
        print("real_API_writes", False)
    finally:
        t.p.close()


if __name__ == "__main__":
    main()
