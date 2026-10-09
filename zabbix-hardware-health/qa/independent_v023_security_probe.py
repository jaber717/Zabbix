#!/usr/bin/env python3
"""Independent, entirely in-memory v0.2.3 security sequences. No live API client."""
import copy
import datetime
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hwh import action as A
from hwh import synthetic as S
from hwh.api import AuditError, ZabbixAPI
from tests.fakes import FakeZabbix

SPEC = {"media_type": "Telegram", "usergroups": ["Network Operations"]}
T = int(datetime.datetime(2026, 10, 9, tzinfo=datetime.timezone.utc).timestamp())


def lab():
    f = FakeZabbix()
    f.add_action("NETOPS-IaC Interface Alerts", A.interface_filter())
    return f, ZabbixAPI("https://fake.invalid", "fake-only", transport=f)


def owned(f, base, status="0"):
    nonce = A.new_nonce()
    aid = f.nid()
    f.actions[aid] = dict(A.build_params("3", ["7"], enabled=status == "0", nonce=nonce), actionid=aid)
    f.actions[aid]["status"] = status
    A.save_ownership(base, "lab", {"schema": 1, "environment": "lab", "actionid": aid,
                                   "nonce": nonce, "core_sha256": A.core_sha256(f.actions[aid]),
                                   "created_utc": "2026-10-09T00:00:00Z"})
    return aid


def case_fixture(f, base):
    aid = owned(f, base)
    hid = f.add_host(S.HOST)
    iid = f.add_item(hid, S.ITEM_KEY)
    ta = f.add_trigger(hid, S.CASE_TRIGGER["A"], [iid])
    tb = f.add_trigger(hid, S.CASE_TRIGGER["B"], [iid])
    led = S.Ledger(str(pathlib.Path(base) / "state" / "synthetic" / "ledger.json"))
    led.data.update(host=hid, item=iid, action=aid, action_created_by_test=True,
                    triggers={"A": ta, "B": tb}, enabled_at="2026-10-09T00:00:00Z")
    f.events = [{"eventid": "a1", "r_eventid": "a2", "objectid": ta, "value": "1", "clock": str(T - 100)},
                {"eventid": "b1", "r_eventid": "b2", "objectid": tb, "value": "1", "clock": str(T + 20)}]
    f.alerts = [{"alertid": "al1", "actionid": aid, "eventid": "a1", "p_eventid": "0",
                 "userid": "u1", "status": "1", "retries": "0", "error": "", "alerttype": "0"}]
    return led, aid, hid, iid


def observations(led, aid, core, case, before=T, after=T + 60, status="0"):
    led.data.setdefault("observations", []).extend([
        {"case": case, "phase": "before", "utc": before, "actionid": aid, "status": status, "core_sha256": core},
        {"case": case, "phase": "after", "utc": after, "actionid": aid, "status": status, "core_sha256": core},
    ])
    led.data.setdefault("sent", {})[case] = [before + 10]


def negative_cases():
    with tempfile.TemporaryDirectory() as base:
        f, api = lab()
        led, aid, _, _ = case_fixture(f, base)
        f.actions[aid]["status"] = "1"  # disabled before B and C; Case A already alerted
        plain = {c: S.verify_case(api, c, led, ["u1"])["ok"] for c in ("B", "C")}
        print("A_plain_disabled_BC_rejected", plain == {"B": False, "C": False})
        core = A.core_sha256(f.actions[aid])
        observations(led, aid, core, "B")
        observations(led, aid, core, "C", T + 100, T + 160)
        led.data["sent"]["C"] = [T + 110]
        # This demonstrates that ledger observations can be altered to claim
        # status=enabled although the fake server stayed disabled throughout.
        forged = {c: S.verify_case(api, c, led, ["u1"])["ok"] for c in ("B", "C")}
        print("A_forged_enabled_observations_false_PASS", forged)
        led.data["observations"][0]["actionid"] = "wrong"
        print("A_wrong_action_id_rejected", not S.verify_case(api, "B", led, ["u1"])["ok"])
        led.data["observations"][0]["actionid"] = aid
        led.data["observations"][0]["core_sha256"] = "0" * 64
        print("A_wrong_hash_rejected", not S.verify_case(api, "B", led, ["u1"])["ok"])
        led.data["observations"][0]["core_sha256"] = core
        led.data["observations"][1]["status"] = "1"
        print("A_contradictory_disabled_observation_rejected", not S.verify_case(api, "B", led, ["u1"])["ok"])
        led.data["observations"][1]["status"] = "0"
        led.data["observations"][1]["utc"] = T
        print("A_nonpositive_timestamp_interval_rejected", not S.verify_case(api, "B", led, ["u1"])["ok"])
        led.data["observations"][1]["utc"] = T + 901
        print("A_expired_observation_rejected", not S.verify_case(api, "B", led, ["u1"])["ok"])
        print("A_no_Zabbix_writes", f.writes() == [])

    # A second, stronger sequence uses the *actual observation recorder*.
    # The action is enabled for both reads but disabled while Case B's event
    # occurs. No ledger field is forged; the unobserved toggle is invisible.
    with tempfile.TemporaryDirectory() as base:
        f, api = lab()
        led, aid, _, _ = case_fixture(f, base)
        at = lambda sec: datetime.datetime.fromtimestamp(sec, datetime.timezone.utc)
        S.record_observation(api, led, "B", "before", base, at(T))
        f.actions[aid]["status"] = "1"  # disabled at the B event
        led.data.setdefault("sent", {})["B"] = [T + 10]
        f.actions[aid]["status"] = "0"  # re-enabled before the after read
        S.record_observation(api, led, "B", "after", base, at(T + 60))
        print("A_unobserved_midcase_disable_false_PASS", S.verify_case(api, "B", led, ["u1"])["ok"])
        print("A_actual_observer_no_Zabbix_writes", f.writes() == [])

    with tempfile.TemporaryDirectory() as base:
        f, api = lab()
        led, aid, _, _ = case_fixture(f, base)
        core = A.core_sha256(f.actions[aid])
        observations(led, aid, core, "C")
        # Only the local 'sent' mark changed. No fake Zabbix item value or
        # history was updated, yet Case C has no trigger/event to cross-check.
        print("A_C_local_sent_mark_without_item_evidence_PASS", S.verify_case(api, "C", led, ["u1"])["ok"])


def operator_action():
    with tempfile.TemporaryDirectory() as base:
        f, api = lab()
        aid = f.add_action(A.ACTION_NAME, A.hardware_filter(), status="1")
        before = copy.deepcopy(f.actions[aid])
        p = A.plan(api, "lab", SPEC, False, str(pathlib.Path(base) / "missing-validation"), base)
        wapi = ZabbixAPI("https://fake.invalid", "fake-only", transport=f, write=True)
        try:
            A.apply(wapi, "lab", SPEC, False, str(pathlib.Path(base) / "missing-validation"), base)
            applied = True
        except AuditError:
            applied = False
        print("B_operator_plan_conflict", bool(p["conflicts"]) and not p["changes"])
        print("B_operator_apply_refused_unchanged", not applied and f.actions[aid] == before and not f.writes())
        try:
            A.apply(wapi, "lab", SPEC, True, str(pathlib.Path(base) / "missing-validation"), base)
            enabled = True
        except AuditError:
            enabled = False
        print("B_operator_enable_refused_unchanged", not enabled and f.actions[aid] == before and not f.writes())
        old = pathlib.Path(base) / "old.json"
        old.write_text(json.dumps({"environment": "lab", "action": A.ACTION_NAME, "existed": False}))
        try:
            A.rollback(wapi, "lab", str(old), base)
            rolled_back = True
        except AuditError:
            rolled_back = False
        print("B_old_backup_refused_unchanged", not rolled_back and f.actions[aid] == before and not f.writes())


def ownership_edges():
    with tempfile.TemporaryDirectory() as base:
        f, api = lab()
        aid = owned(f, base)
        record_path = pathlib.Path(A.ownership_path(base, "lab"))
        record = json.loads(record_path.read_text())
        validation = str(pathlib.Path(base) / "missing-validation")

        record_path.unlink()
        missing = A.plan(api, "lab", SPEC, False, validation, base)
        print("B_missing_ownership_refused", bool(missing["conflicts"]))
        A.save_ownership(base, "lab", record)
        f.actions[aid]["operations"][0]["opmessage"]["message"] = "nonce removed"
        no_nonce = A.plan(api, "lab", SPEC, False, validation, base)
        print("B_missing_live_nonce_refused", bool(no_nonce["conflicts"]))
        f.actions[aid]["operations"][0]["opmessage"]["message"] = A.build_params("3", ["7"], False, record["nonce"])["operations"][0]["opmessage"]["message"]
        A.save_ownership(base, "lab", dict(record, actionid="different-id"))
        wrong_id = A.plan(api, "lab", SPEC, False, validation, base)
        print("B_different_record_id_refused", bool(wrong_id["conflicts"]))

    with tempfile.TemporaryDirectory() as base:
        f, _ = lab()
        aid = owned(f, base, "0")  # enabled, so apply would otherwise disable
        original_dispatch = f.dispatch
        swapped = {"done": False}

        def concurrent_change(method, params):
            if method == "action.get" and params.get("actionids") and not swapped["done"]:
                swapped["done"] = True
                f.actions[aid]["esc_period"] = "2h"  # operator edit after plan, before guarded write
            return original_dispatch(method, params)

        f.dispatch = concurrent_change
        wapi = ZabbixAPI("https://fake.invalid", "fake-only", transport=f, write=True)
        try:
            A.apply(wapi, "lab", SPEC, False, str(pathlib.Path(base) / "missing-validation"), base)
            wrote = True
        except AuditError:
            wrote = False
        print("B_concurrent_definition_change_refused", not wrote and not f.writes())

    with tempfile.TemporaryDirectory() as base:
        f, _ = lab()
        aid = owned(f, base)
        record = A.load_ownership(base, "lab")
        wapi = ZabbixAPI("https://fake.invalid", "fake-only", transport=f, write=True)
        backups = [
            {"environment": "lab", "action": A.ACTION_NAME, "existed": False},
            {"schema": 2, "environment": "lab", "action": A.ACTION_NAME, "existed": False, "actionid": aid},
            {"schema": 2, "environment": "lab", "action": A.ACTION_NAME, "existed": False, "actionid": "different-id", "nonce": record["nonce"]},
            {"schema": 2, "environment": "lab", "action": A.ACTION_NAME, "existed": False, "actionid": aid, "nonce": "foreign-nonce"},
        ]
        refused = []
        for i, data in enumerate(backups):
            path = pathlib.Path(base) / ("backup-%d.json" % i)
            path.write_text(json.dumps(data))
            try:
                A.rollback(wapi, "lab", str(path), base)
                refused.append(False)
            except AuditError:
                refused.append(True)
        print("B_old_idless_and_foreign_nonce_refused", refused[0] and refused[1] and refused[3])
        print("B_different_id_backup_safe_noop", not refused[2] and aid in f.actions)
        print("B_rollback_zero_writes", not f.writes())


def emergency():
    with tempfile.TemporaryDirectory() as base:
        f, api = lab()
        aid = owned(f, base, "0")
        hid = f.add_host(S.HOST)
        iid = f.add_item(hid, S.ITEM_KEY)
        f.add_trigger(hid, S.TRIGGER_PREFIX + "foreign", [iid])
        led = S.Ledger(str(pathlib.Path(base) / "ledger.json"))
        led.data.update(action=aid, action_created_by_test=True, host=hid, item=iid)
        try:
            S.cleanup_plan(api, led, base)
            deletion_refused = False
        except AuditError:
            deletion_refused = True
        steps = S.emergency_disable_plan(api, led, base)
        print("C_foreign_cleanup_refused", deletion_refused)
        print("C_disable_plan_exact_owned_id", len(steps) == 1 and steps[0]["params"] == {"actionid": aid, "status": 1})
        print("C_disable_only_planned_not_executed", f.actions[aid]["status"] == "0" and not f.writes())
        f.actions[aid]["operations"][0]["opmessage"]["message"] = "operator-owned now"
        try:
            S.emergency_disable_plan(api, led, base)
            foreign_refused = False
        except AuditError:
            foreign_refused = True
        print("C_ownership_mismatch_refused", foreign_refused and f.actions[aid]["status"] == "0")
        foreign_id = f.add_action(A.ACTION_NAME, A.hardware_filter(), status="0")
        led.data["action"] = foreign_id
        try:
            S.emergency_disable_plan(api, led, base)
            unrelated_refused = False
        except AuditError:
            unrelated_refused = True
        print("C_unrelated_action_id_refused", unrelated_refused and f.actions[foreign_id]["status"] == "0")


if __name__ == "__main__":
    negative_cases()
    operator_action()
    ownership_edges()
    emergency()
