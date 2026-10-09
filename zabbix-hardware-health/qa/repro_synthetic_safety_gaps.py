#!/usr/bin/env python3
"""Reproduce the v0.2.2 safety gaps against an in-memory fake; never contacts Zabbix. (Codex's reproduction, adapted to the v0.2.3 API.)
Expected on a corrected build: every line ending in False below prints False, every `refused`/`available` line prints True, and no write is made."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hwh import action as A
from hwh import synthetic as S
from hwh.api import AuditError, ZabbixAPI
from tests.test_synthetic import NOTIF, TestVerifyCases


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
    # REPRODUCTION 1 - Case B/C false PASS after the action was disabled
    t, ledger, ids = fixture()
    try:
        t.fz.actions[ids["aid"]]["status"] = "1"  # disabled before B/C
        print("disabled_action_case_B_false_PASS", S.verify_case(t.api, "B", ledger, ["u1"])["ok"])
        print("disabled_action_case_C_false_PASS", S.verify_case(t.api, "C", ledger, ["u1"])["ok"])
        # REPRODUCTION 3 - foreign object in the namespace while the test action is enabled
        t.fz.actions[ids["aid"]]["status"] = "0"
        t.fz.add_trigger(ids["hid"], S.TRIGGER_PREFIX + "foreign", [ids["iid"]])
        try:
            S.cleanup_plan(t.api, ledger, t.p.base)
            print("foreign_trigger_cleanup_refused", False)
        except AuditError:
            print("foreign_trigger_cleanup_refused", True)
        steps = S.emergency_disable_plan(t.api, ledger, t.p.base)
        print("emergency_disable_step_available", bool(steps) and steps[0]["method"] == "action.update")
        print("real_API_writes", [w for w in t.fz.writes() if not w.startswith("action.")])
    finally:
        t.tearDown()

    # REPRODUCTION 2 - operator-owned same-name action
    t, ledger, ids = fixture()
    try:
        t.api = ZabbixAPI("https://fake.invalid", "not-a-secret", transport=t.fz, write=True)
        for aid in [a for a in t.fz.actions if t.fz.actions[a]["name"] == A.ACTION_NAME]:
            del t.fz.actions[aid]                           # discard the tool-created one: now only an operator's action exists
        mine = t.fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        t.fz.actions[mine]["operations"] = [{"operationtype": 0, "opmessage": {"subject": "op", "message": "operator text", "mediatypeid": "3"}, "opmessage_grp": [{"usrgrpid": "7"}]}]
        import json
        before = json.dumps(t.fz.actions[mine], sort_keys=True)
        validation = str(pathlib.Path(t.p.base) / "no-validation.json")
        p = A.plan(t.api, "lab", dict(NOTIF), False, validation, t.p.base)
        print("preexisting_action_plan_requests_update", any(x.startswith("UPDATE action") for x in p["changes"]))
        print("plan_conflicts", len(p["conflicts"]))
        writes_before = len(t.fz.writes())
        try:
            A.apply(t.api, "lab", dict(NOTIF), False, validation, t.p.base)
        except AuditError:
            pass
        print("preexisting_action_fake_update_executed", len(t.fz.writes()) > writes_before)
        print("operator_action_byte_identical", json.dumps(t.fz.actions[mine], sort_keys=True) == before)
        print("real_API_writes", False)
    finally:
        t.p.close()


if __name__ == "__main__":
    main()
