"""Read-only support for the LAB synthetic notification test (docs/SYNTHETIC-NOTIFICATION-TEST.md). NOTHING in this module writes to Zabbix.

  preflight     refuses execution unless approvals are complete, recipients match, and the whole synthetic namespace is EMPTY
  snapshot/diff exact before/after manifest (Interface Alerting action snapshots, hardware action state, synthetic objects)
  Ledger        local record of the exact Zabbix ids the TEST created; cleanup may touch only ids in it
  cleanup_plan  turns a ledger into the exact delete calls (verified by id AND name); never selects anything by name prefix
  verify_case   read-only check of events, alerts, macro expansion and exclusion after a case ran

The tester creates and deletes the fixtures with an approved LAB token; this module only checks, records and plans."""
import datetime
import hashlib
import json
import os

import yaml

from . import action as A
from .api import AuditError

HOSTGROUP = "NETOPS-HW-SYNTH"
HOST = "NETOPS-HW-SYNTH-01"
ITEM_KEY = "netops.hw.synthetic.state"
TRIGGER_PREFIX = "[NETOPS-HW-SYNTH] "
CASE_TRIGGER = {"A": TRIGGER_PREFIX + "case A hardware-tagged", "B": TRIGGER_PREFIX + "case B stock-style tags", "D": TRIGGER_PREFIX + "case D tagged for both families"}
DEFAULT_CASES = ("A", "B", "C")
MAX_WINDOW_HOURS = 4
EXPECTED_TEXT = ["SYNTHETIC-NOT-A-DEVICE", "synthetic-1", "LAB", "fan"]        # expanded hardware_model / slot / site / component values of trigger A
SENT = "1"                                                                      # alert.status: 0 not sent, 1 sent, 2 failed, 3 new


# ----------------------------------------------------------------------------------------------------------------- approval scope
def _dt(v):
    d = v if isinstance(v, datetime.datetime) else datetime.datetime.fromisoformat(str(v))
    if d.tzinfo is None:
        raise AuditError("window times need a UTC offset, e.g. 2026-10-10T10:00:00+03:00")
    return d


def load_scope(path):
    """The explicit approval record. Every field is mandatory; there is no default recipient, media type, reference or scope."""
    with open(path, encoding="utf-8") as fh:
        s = yaml.safe_load(fh) or {}
    allowed = {"approved_by", "approval_reference", "window_start", "window_end", "media_type", "usergroups", "test_scope", "case_d"}
    if "existing_hardware_action" in s:
        raise AuditError("synthetic scope: a pre-existing hardware action cannot be acknowledged into this test. It is never adopted, modified or rolled back: "
                         "remove it through its own approved change, then run the test against an empty namespace")
    if set(s) - allowed:
        raise AuditError("synthetic scope: unknown keys " + ", ".join(sorted(set(s) - allowed)))
    for k in ("approved_by", "approval_reference", "media_type"):
        if len(str(s.get(k) or "").strip()) < 3:
            raise AuditError("synthetic scope: '%s' is required (explicit approval; no fallback)" % k)
    groups = s.get("usergroups")
    if not isinstance(groups, list) or not groups or any(not isinstance(g, str) or not g.strip() for g in groups):
        raise AuditError("synthetic scope: usergroups must list the exact approved group names (no fallback recipient)")
    ts = s.get("test_scope") or {}
    if set(ts) - {"hostgroup", "host", "cases"}:
        raise AuditError("synthetic scope: test_scope has unknown keys")
    if ts.get("hostgroup") != HOSTGROUP or ts.get("host") != HOST:
        raise AuditError("synthetic scope: test_scope must name exactly hostgroup '%s' and host '%s' (the fixed synthetic namespace)" % (HOSTGROUP, HOST))
    cases = ts.get("cases")
    if not isinstance(cases, list) or not cases or any(c not in ("A", "B", "C", "D") for c in cases) or len(set(cases)) != len(cases):
        raise AuditError("synthetic scope: test_scope.cases must be a unique list drawn from A, B, C, D")
    if "D" in cases:
        d = s.get("case_d") or {}
        if len(str(d.get("approved_by") or "").strip()) < 3 or len(str(d.get("approval_reference") or "").strip()) < 3 or d.get("interface_recipients_notified") is not True:
            raise AuditError("synthetic scope: case D can reach Interface Alerting recipients and needs its own case_d.approved_by, case_d.approval_reference "
                             "and case_d.interface_recipients_notified: true. It is not part of the default test")
    elif s.get("case_d"):
        raise AuditError("synthetic scope: case_d approval given but D is not listed in test_scope.cases")
    try:
        a, b = _dt(s.get("window_start")), _dt(s.get("window_end"))
    except (ValueError, TypeError) as exc:
        raise AuditError("synthetic scope: window_start/window_end must be ISO-8601 with an offset (%s)" % exc)
    if b <= a or (b - a).total_seconds() > MAX_WINDOW_HOURS * 3600:
        raise AuditError("synthetic scope: the approved window must be positive and at most %d hours" % MAX_WINDOW_HOURS)
    s["_window"] = (a, b)
    return s


def require_window(scope, now=None):
    """EXECUTION GATE. Raises unless `now` is inside the approved window. Used by preflight (execute mode) and by every command that
    starts or advances the test; cleanup, snapshot, review and verify are deliberately NOT gated so a test can always be wound down."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    a, b = scope["_window"]
    if not a <= now <= b:
        raise AuditError("OUTSIDE THE APPROVED WINDOW (%s .. %s, now %s): execution refused. Use 'synthetic review' for a read-only readiness check."
                         % (a.isoformat(), b.isoformat(), now.strftime("%Y-%m-%dT%H:%M:%SZ")))


def recipients_match(scope, notif_spec):
    """The scope's recipients must be exactly those of the action configuration - one approval, one source of truth."""
    if sorted(scope["usergroups"]) != sorted(notif_spec["usergroups"]) or scope["media_type"] != notif_spec["media_type"]:
        raise AuditError("synthetic scope recipients/media type differ from config/notifications.lab.yaml: the test and the action must use the same approved recipients")


# ----------------------------------------------------------------------------------------------------------------- reads
def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _strip_ids(o):
    """Drop volatile ids so two reads of an unchanged action hash equal."""
    if isinstance(o, dict):
        return dict((k, _strip_ids(v)) for k, v in o.items() if k not in ("operationid", "actionid", "opmessageid", "opmessage_grpid", "opmessage_usrid", "conditionid"))
    if isinstance(o, list):
        return [_strip_ids(x) for x in o]
    return o


def interface_actions(api):
    rows = api.call("action.get", {"output": "extend", "search": {"name": A.INTERFACE_PREFIX}, "startSearch": True,
                                   "selectFilter": "extend", "selectOperations": "extend", "selectRecoveryOperations": "extend"})
    out = []
    for a in rows:
        d = _strip_ids(a)
        out.append({"actionid": str(a["actionid"]), "name": a["name"], "status": str(a["status"]), "definition_sha256": hashlib.sha256(_canon(d).encode()).hexdigest(), "definition": d})
    return sorted(out, key=lambda x: x["actionid"])


def synthetic_objects(api):
    """Everything in the fixed synthetic namespace, by exact name/key/prefix. Used to prove the namespace is empty (preflight) or restored (diff)."""
    groups = api.call("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": [HOSTGROUP]}})
    hosts = api.call("host.get", {"output": ["hostid", "host"], "filter": {"host": [HOST]}})
    items = api.call("item.get", {"output": ["itemid", "key_"], "filter": {"key_": ITEM_KEY}})
    trigs = api.call("trigger.get", {"output": ["triggerid", "description"], "search": {"description": TRIGGER_PREFIX}, "startSearch": True})
    return {"hostgroups": sorted((str(g["groupid"]), g["name"]) for g in groups), "hosts": sorted((str(h["hostid"]), h["host"]) for h in hosts),
            "items": sorted((str(i["itemid"]), i["key_"]) for i in items), "triggers": sorted((str(t["triggerid"]), t["description"]) for t in trigs)}


def hardware_triggers(api):
    return api.call("trigger.get", {"output": ["triggerid"], "tags": [{"tag": A.TAG_HW, "operator": 4}]})


def hardware_action_state(api):
    a = A.get_action(api, A.ACTION_NAME)
    if a is None:
        return {"exists": False, "actionid": None, "status": None, "signature": None, "definition_sha256": None}
    sig = A.signature(a)
    h = hashlib.sha256(_canon(_strip_ids(a)).encode()).hexdigest()
    return {"exists": True, "actionid": str(a["actionid"]), "status": str(a["status"]), "signature": sig, "definition_sha256": h}


def recipients(api, scope):
    ug = api.call("usergroup.get", {"output": ["usrgrpid", "name"], "filter": {"name": scope["usergroups"]}})
    mt = api.call("mediatype.get", {"output": ["mediatypeid", "name", "status"], "filter": {"name": [scope["media_type"]]}})
    problems = []
    found = set(g["name"] for g in ug)
    for n in scope["usergroups"]:
        if n not in found:
            problems.append("approved user group '%s' not found (no fallback recipient is ever used)" % n)
    if len(mt) != 1:
        problems.append("approved media type '%s' not found" % scope["media_type"])
        return [], problems
    if str(mt[0].get("status")) != "0":
        problems.append("approved media type '%s' is DISABLED (status %s): nothing would be delivered" % (scope["media_type"], mt[0].get("status")))
        return [], problems
    users = []
    if ug:
        rows = api.call("user.get", {"output": ["userid"], "usrgrpids": [g["usrgrpid"] for g in ug], "selectMedias": ["mediatypeid", "active"]})
        for u in rows:
            if any(str(m.get("mediatypeid")) == str(mt[0]["mediatypeid"]) and str(m.get("active")) == "0" for m in u.get("medias", [])):
                users.append(str(u["userid"]))
    if not users and not problems:
        problems.append("no user in the approved group(s) has an enabled medium of the approved media type: nobody would receive anything")
    return sorted(users), problems


# ----------------------------------------------------------------------------------------------------------------- preflight / manifest
def preflight(api, scope, notif_spec, now=None, mode="execute", base=None, expected_actionid=None):
    """-> {"ok", "checks", "recipients", "in_window", "execution_allowed"}.
    mode "review": read-only readiness check that may run at any time (before the window). It can say READY but never authorises execution.
    mode "execute": the EXECUTION GATE - the approved window is mandatory; outside it ok is False and nothing may start."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    checks = []

    def chk(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    try:
        recipients_match(scope, notif_spec)
        chk("scope recipients equal the action configuration", True)
    except AuditError as exc:
        chk("scope recipients equal the action configuration", False, str(exc))
    users, problems = recipients(api, scope)
    chk("approved media type (enabled) and user group(s) exist and have recipients", not problems, "; ".join(problems) or "%d recipient user(s)" % len(users))
    objs = synthetic_objects(api)
    for key in ("hostgroups", "hosts", "items", "triggers"):
        chk("synthetic namespace empty: %s" % key, not objs[key], ("already exists (ids %s) - refusing; the test never adopts or deletes pre-existing objects" % [i for i, _ in objs[key]]) if objs[key] else "")
    hw = hardware_triggers(api)
    chk("no trigger carries netops_hardware (nothing else can fire through the hardware action)", not hw, "%d trigger(s) carry it" % len(hw) if hw else "")
    st = hardware_action_state(api)
    pre_existing = st["exists"]
    if not pre_existing:
        chk("no hardware action exists yet (this test creates its own, disabled, with 'action apply')", True)
    elif expected_actionid is not None and st["actionid"] == str(expected_actionid):
        live = A.get_action_by_id(api, st["actionid"])
        own = A.verify_owned(live, A.load_ownership(base, "lab") if base else None, expect_actionid=expected_actionid)
        chk("the hardware action is the ledger-recorded one, demonstrably owned by this deployment, and DISABLED", not own and st["status"] == "1",
            "; ".join(own) or ("action %s is enabled" % st["actionid"] if st["status"] != "1" else ""))
    else:
        chk("no PRE-EXISTING hardware action (a pre-existing action blocks the test; it is never adopted, modified, rolled back or deleted)", False,
            "action %s already exists and is not the ledger-recorded one. Resolve it through its own approved change; there is no acknowledgement path" % st["actionid"])
    ifa = interface_actions(api)
    chk("Interface Alerting action present and snapshotted", bool(ifa), "no NETOPS-IaC action found - the exclusion cannot be shown" if not ifa else "%d action(s)" % len(ifa))
    a, b = scope["_window"]
    in_window = a <= now <= b
    chk("INSIDE THE APPROVED WINDOW (mandatory to execute)", in_window or mode == "review",
        "" if in_window else "window %s .. %s, now %s%s" % (a.isoformat(), b.isoformat(), now.strftime("%Y-%m-%dT%H:%M:%SZ"), " - readiness review only; execution would be refused" if mode == "review" else ""))
    ready = all(c["ok"] for c in checks)
    return {"ok": ready, "checks": checks, "recipients": users, "in_window": in_window, "pre_existing_action": pre_existing, "mode": mode,
            "execution_allowed": ready and in_window}


def snapshot(api, scope, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    users, _ = recipients(api, scope)
    m = {"schema": 1, "taken_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "approval_reference": scope["approval_reference"],
         "interface_actions": interface_actions(api), "hardware_action": hardware_action_state(api),
         "synthetic_objects": synthetic_objects(api), "netops_hardware_trigger_count": len(hardware_triggers(api)), "recipients": users}
    m["manifest_sha256"] = hashlib.sha256(_canon(dict((k, v) for k, v in m.items() if k not in ("taken_utc", "manifest_sha256"))).encode()).hexdigest()
    return m


def diff(before, after):
    """Differences that matter after cleanup. Empty list = Zabbix is back to the 'before' state (event/alert history excepted)."""
    d = []
    bi = dict((a["actionid"], a) for a in before["interface_actions"])
    ai = dict((a["actionid"], a) for a in after["interface_actions"])
    if set(bi) != set(ai):
        d.append("Interface Alerting actions added/removed: %s" % sorted(set(bi) ^ set(ai)))
    for k in set(bi) & set(ai):
        if bi[k]["definition_sha256"] != ai[k]["definition_sha256"]:
            d.append("Interface Alerting action %s (%s) CHANGED" % (k, bi[k]["name"]))
    for k, v in after["synthetic_objects"].items():
        if v:
            d.append("synthetic %s still present: %s" % (k, v))
    bh, ah = before["hardware_action"], after["hardware_action"]
    if (bh["exists"], bh["status"]) != (ah["exists"], ah["status"]):
        d.append("hardware action state differs: before exists=%s status=%s, after exists=%s status=%s" % (bh["exists"], bh["status"], ah["exists"], ah["status"]))
    if bh["exists"] and ah["exists"]:
        if bh["actionid"] != ah["actionid"]:
            d.append("hardware action id changed (%s -> %s): it was deleted and recreated" % (bh["actionid"], ah["actionid"]))
        changed = sorted(k for k in set(bh["signature"]) | set(ah["signature"]) if bh["signature"].get(k) != ah["signature"].get(k))
        if changed:
            d.append("hardware action DEFINITION CHANGED (signature fields: %s)" % ", ".join(changed))
        elif bh.get("definition_sha256") != ah.get("definition_sha256"):
            d.append("hardware action definition hash differs although the signature is equal (an unexpected edit)")
    if after["hardware_action"]["exists"] and after["hardware_action"]["status"] != "1":
        d.append("hardware action is left ENABLED")
    if before["netops_hardware_trigger_count"] != after["netops_hardware_trigger_count"]:
        d.append("count of triggers carrying netops_hardware changed")
    return d


# ----------------------------------------------------------------------------------------------------------------- ledger / cleanup
class Ledger(object):
    """Exact ids created by THIS test. Cleanup operates on these ids only."""
    KINDS = ("hostgroup", "host", "item", "action")

    def __init__(self, path, data=None):
        self.path = path
        self.data = data or {"schema": 1, "hostgroup": None, "host": None, "item": None, "triggers": {}, "action": None, "action_created_by_test": False,
                             "enabled_at": None, "disabled_at": None, "observations": [], "sent": {}}

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(path, json.load(fh))

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def record(self, kind, zid, case=None):
        if kind == "trigger":
            if case not in CASE_TRIGGER:
                raise AuditError("unknown trigger case %r" % (case,))
            self.data["triggers"][case] = str(zid)
        elif kind in self.KINDS:
            self.data[kind] = str(zid)
        else:
            raise AuditError("unknown ledger kind " + kind)
        self.save()

    def ids(self):
        d = self.data
        return {"triggers": sorted(d["triggers"].values()), "item": d["item"], "host": d["host"], "hostgroup": d["hostgroup"], "action": d["action"]}


def verify_ownership(api, ledger):
    """Every recorded id must still be the synthetic object it was recorded as: right name/key/description, and (for item/triggers) on the recorded
    synthetic host. Returns a list of problems; empty = ownership verified. A mismatch means a wrong id was recorded: nothing may be deleted."""
    d, p = ledger.data, []
    if d["hostgroup"]:
        rows = api.call("hostgroup.get", {"output": ["groupid", "name"], "groupids": [d["hostgroup"]]})
        if rows and rows[0]["name"] != HOSTGROUP:
            p.append("recorded host group id %s is named %r, not %r" % (d["hostgroup"], rows[0]["name"], HOSTGROUP))
    if d["host"]:
        rows = api.call("host.get", {"output": ["hostid", "host"], "hostids": [d["host"]]})
        if rows and rows[0]["host"] != HOST:
            p.append("recorded host id %s is %r, not %r" % (d["host"], rows[0]["host"], HOST))
    if d["item"]:
        rows = api.call("item.get", {"output": ["itemid", "key_"], "itemids": [d["item"]], "selectHosts": ["hostid"]})
        if rows:
            if rows[0]["key_"] != ITEM_KEY:
                p.append("recorded item id %s has key %r, not %r" % (d["item"], rows[0]["key_"], ITEM_KEY))
            if d["host"] and [h["hostid"] for h in rows[0].get("hosts", [])] != [d["host"]]:
                p.append("recorded item id %s is not on the recorded synthetic host" % d["item"])
    for case, tid in sorted(d["triggers"].items()):
        rows = api.call("trigger.get", {"output": ["triggerid", "description"], "triggerids": [tid], "selectHosts": ["hostid"]})
        if rows:
            if rows[0]["description"] != CASE_TRIGGER[case]:
                p.append("recorded trigger id %s (case %s) is named %r, not %r" % (tid, case, rows[0]["description"], CASE_TRIGGER[case]))
            if d["host"] and [h["hostid"] for h in rows[0].get("hosts", [])] != [d["host"]]:
                p.append("recorded trigger id %s is not on the recorded synthetic host" % tid)
    return p


def _action_by_id(api, actionid):
    rows = api.call("action.get", {"output": "extend", "actionids": [actionid], "selectFilter": "extend", "selectOperations": "extend", "selectRecoveryOperations": "extend"})
    return rows[0] if rows else None


def emergency_disable_plan(api, ledger, base):
    """EMERGENCY path, independent of fixture cleanup. Returns the steps (possibly empty) that make the TEST-CREATED hardware action safe (disabled).
    It deliberately does not look at the synthetic namespace or at the completeness of the fixture ids, so a foreign or missing fixture can never
    leave an enabled action without a disable plan. It needs two things and nothing else: the exact action id in the ledger, and trustworthy evidence that
    this deployment owns that action. Without both it refuses and raises with the evidence a human needs for manual recovery. It never disables an action
    by name alone."""
    aid = ledger.data.get("action")
    rec = A.load_ownership(base, "lab")
    if not aid:
        live_any = A.get_action(api, A.ACTION_NAME)
        ev = A.ownership_evidence(live_any, rec)
        if live_any is not None and str(live_any.get("status")) != "1":
            raise AuditError("EMERGENCY: a hardware action named '%s' is ENABLED but the ledger has no action id, so this test cannot claim it. It is NOT being disabled by name. "
                             "Manual recovery evidence: %s" % (A.ACTION_NAME, json.dumps(ev, sort_keys=True)))
        return []
    if ledger.data.get("action_created_by_test") is not True:
        raise AuditError("EMERGENCY: the ledger does not say this test created action %s, so it is not treated as owned and will not be disabled by this tool. "
                         "Manual recovery evidence: %s" % (aid, json.dumps(A.ownership_evidence(A.get_action_by_id(api, aid), rec), sort_keys=True)))
    live = A.get_action_by_id(api, aid)
    if live is None:
        other = A.get_action(api, A.ACTION_NAME)
        if other is not None and str(other.get("status")) != "1":
            raise AuditError("EMERGENCY: the recorded action %s is gone but a different hardware action (id %s) is ENABLED. It is NOT being disabled by name. "
                             "Manual recovery evidence: %s" % (aid, other.get("actionid"), json.dumps(A.ownership_evidence(other, rec), sort_keys=True)))
        return []
    problems = A.verify_owned(live, rec, expect_actionid=aid)
    if problems:
        raise AuditError("EMERGENCY: ownership of action %s cannot be established (%s). It is NOT being disabled by this tool. Manual recovery evidence: %s"
                         % (aid, "; ".join(problems), json.dumps(A.ownership_evidence(live, rec), sort_keys=True)))
    if str(live["status"]) == "1":
        return []
    return [{"method": "action.update", "params": {"actionid": str(aid), "status": 1},
             "why": "EMERGENCY DISABLE: action %s is verifiably this deployment's own (id, nonce, definition hash) and is ENABLED right now" % aid,
             "preconditions": {"actionid": str(aid), "core_sha256": A.core_sha256(live)}}]


def cleanup_plan(api, ledger, base):
    """Destructive fixture cleanup, ledger ids only, ownership-verified. It is separate from the emergency disable: foreign, mismatched or incomplete
    fixtures block EVERY deletion here, while `emergency_disable_plan` still works. If the recorded action is owned and enabled its disable is
    the first step of this plan too."""
    ids = ledger.ids()
    if not (ids["host"] or ids["hostgroup"] or ids["item"] or ids["triggers"] or ids["action"]):
        raise AuditError("the ledger is empty: nothing to clean up (and nothing may be deleted by name)")
    plan = list(emergency_disable_plan(api, ledger, base))
    hw_now = hardware_action_state(api)
    if hw_now["exists"] and ids["action"] != hw_now["actionid"]:
        raise AuditError("a hardware action (id %s) exists that is not the one recorded in the ledger (%s): refusing to plan any deletion. Investigate." % (hw_now["actionid"], ids["action"]))
    own = verify_ownership(api, ledger)
    if own:
        raise AuditError("ownership verification failed - refusing to plan any deletion: " + "; ".join(own))
    live = synthetic_objects(api)
    known = {"triggers": set(ids["triggers"]), "items": {ids["item"]} - {None}, "hosts": {ids["host"]} - {None}, "hostgroups": {ids["hostgroup"]} - {None}}
    for kind in ("triggers", "items", "hosts", "hostgroups"):
        extra = [i for i, _ in live[kind] if i not in known[kind]]
        if extra:
            raise AuditError("the synthetic namespace contains %s %s that this test did not create: refusing to plan ANY deletion. Investigate." % (kind, extra))
    on_zabbix = dict((kind, set(i for i, _ in live[kind])) for kind in live)
    if ids["triggers"]:
        present = [i for i in ids["triggers"] if i in on_zabbix["triggers"]]
        if present:
            plan.append({"method": "trigger.delete", "params": present, "why": "test triggers created by this test (recorded ids)"})
    if ids["item"] and ids["item"] in on_zabbix["items"]:
        plan.append({"method": "item.delete", "params": [ids["item"]], "why": "synthetic trapper item (recorded id)"})
    if ids["host"] and ids["host"] in on_zabbix["hosts"]:
        plan.append({"method": "host.delete", "params": [ids["host"]], "why": "synthetic host (recorded id)"})
    if ids["hostgroup"] and ids["hostgroup"] in on_zabbix["hostgroups"]:
        plan.append({"method": "hostgroup.delete", "params": [ids["hostgroup"]], "why": "synthetic host group (recorded id)"})
    if ids["action"]:
        plan.append({"method": "(tool)", "params": "hardware_audit.py --env lab action rollback --backup <backup printed by 'action apply'>",
                     "why": "remove the action this test created: the tool re-verifies ownership and the exact id from the backup; it never deletes by name"})
    return plan


# ----------------------------------------------------------------------------------------------------------------- per-case action-state evidence
MAX_CASE_SECONDS = 900


def _epoch(v):
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v)
    if s.isdigit():
        return int(s)
    return int(datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp())


def record_observation(api, ledger, case, phase, base, now):
    """Read-only against Zabbix. Records a timestamped observation of the recorded hardware action (exact id, status, definition hash). Takes one
    'before' and one 'after' per case; a duplicate is refused because an ambiguous record is worthless as evidence. Refuses unless ownership holds."""
    if phase not in ("before", "after") or case not in ("A", "B", "C", "D"):
        raise AuditError("observe needs --case A|B|C|D and --phase before|after")
    aid = ledger.data.get("action")
    if not aid:
        raise AuditError("the ledger has no recorded hardware action id")
    live = A.get_action_by_id(api, aid)
    if live is None:
        raise AuditError("the recorded hardware action %s does not exist on Zabbix" % aid)
    own = A.verify_owned(live, A.load_ownership(base, "lab"), expect_actionid=aid)
    if own:
        raise AuditError("cannot record evidence for an action this deployment does not demonstrably own: " + "; ".join(own))
    obs = ledger.data.setdefault("observations", [])
    if any(o["case"] == case and o["phase"] == phase for o in obs):
        raise AuditError("an observation for case %s phase %s already exists; evidence is never overwritten or duplicated" % (case, phase))
    o = {"case": case, "phase": phase, "utc": int(now.timestamp()), "actionid": str(aid), "status": str(live["status"]), "core_sha256": A.core_sha256(live)}
    obs.append(o)
    ledger.save()
    return o


NEGATIVE_CASES = ("B", "C", "D")


def negative_case_evidence(api, ledger, case, live, scope=None):
    """LOCAL, tester-supplied evidence only. It can contradict (FAIL) or be missing (INCONCLUSIVE) but can never by itself establish a PASS:
    the authoritative server-side evidence in hwh/evidence.py is also required. Returns (fails, inconclusive, interval-or-None)."""
    f, inc = _negative_local(api, ledger, case, live, scope)
    d = ledger.data
    obs = [o for o in (d.get("observations") or []) if o["case"] == case]
    b = [o for o in obs if o["phase"] == "before"]
    a = [o for o in obs if o["phase"] == "after"]
    return f, inc, ((b[0]["utc"], a[0]["utc"]) if len(b) == 1 and len(a) == 1 else None)


def _negative_local(api, ledger, case, live, scope=None):
    """Independent evidence that the hardware action was ENABLED for the whole of this negative case. Zero alerts only mean something if the action
    was live: a missing, inconsistent or inconclusive record is a finding, and a clean zero is never enough on its own."""
    f, inc = [], []
    d = ledger.data
    aid = d.get("action")
    obs = d.get("observations") or []
    mine = [o for o in obs if o["case"] == case]
    before = [o for o in mine if o["phase"] == "before"]
    after = [o for o in mine if o["phase"] == "after"]
    if len(before) != 1 or len(after) != 1:
        return [], ["INCONCLUSIVE: no usable action-state evidence for case %s: need exactly one 'before' and one 'after' observation (found %d and %d). A zero-notification "
                    "result without proof that the action was enabled during the case is INCONCLUSIVE, not a pass" % (case, len(before), len(after))]
    b, a = before[0], after[0]
    for o in (b, a):
        if str(o["actionid"]) != str(aid):
            f.append("%s observation is for action %s, not the recorded %s" % (o["phase"], o["actionid"], aid))
        if str(o["status"]) != "0":
            f.append("%s observation shows the hardware action DISABLED" % o["phase"])
    live_core = A.core_sha256(live)
    if not (b["core_sha256"] == a["core_sha256"] == live_core):
        f.append("the action definition changed between the observations or since (core hash mismatch)")
    span = a["utc"] - b["utc"]
    if span <= 0:
        f.append("the 'after' observation is not later than the 'before' observation")
    elif span > MAX_CASE_SECONDS:
        f.append("the observed interval is %ds, longer than the %ds bound: the action could have been toggled unseen" % (span, MAX_CASE_SECONDS))
    sent = (d.get("sent") or {}).get(case) or []
    if not sent:
        inc.append("INCONCLUSIVE: no 'sent' mark for case %s: the time the value was sent is not tied to the observed interval" % case)
    for t in sent:
        if not b["utc"] <= _epoch(t) <= a["utc"]:
            f.append("a value was sent at %s, outside the observed interval %d..%d" % (t, b["utc"], a["utc"]))
    for o in obs:
        if o is not b and o is not a and b["utc"] < o["utc"] < a["utc"] and str(o["status"]) != "0":
            f.append("another observation inside the interval shows the action DISABLED")
    tid = d["triggers"].get(case)
    if tid:
        clocks = [int(e["clock"]) for e in _events(api, tid)]
        if not clocks:
            inc.append("INCONCLUSIVE: no event exists for the case trigger: the case is not shown to have run")
        for c in clocks:
            if not b["utc"] <= c <= a["utc"]:
                f.append("an event at %d is outside the observed interval %d..%d" % (c, b["utc"], a["utc"]))
    elif case != "C":
        inc.append("INCONCLUSIVE: no trigger recorded for case %s" % case)
    da = d.get("disabled_at")
    if da and _epoch(da) < a["utc"]:
        f.append("the ledger records the action as disabled at %s, before the end of the observed interval" % da)
    if scope is not None:
        w0, w1 = scope["_window"]
        for o in (b, a):
            t = datetime.datetime.fromtimestamp(o["utc"], datetime.timezone.utc)
            if not w0 <= t <= w1:
                f.append("the %s observation is outside the approved window" % o["phase"])
    return f, inc


# ----------------------------------------------------------------------------------------------------------------- verification
def _events(api, triggerid):
    return api.call("event.get", {"output": ["eventid", "r_eventid", "clock", "value"], "source": 0, "object": 0, "objectids": [triggerid]})


def _alerts(api, actionid, eventids):
    if not eventids:
        return []
    return api.call("alert.get", {"output": ["alertid", "actionid", "eventid", "p_eventid", "userid", "status", "retries", "error", "subject", "message", "alerttype"],
                                  "actionids": [actionid], "eventids": sorted(eventids)})


def _result(case, f, inc):
    verdict = "FAIL" if f else ("INCONCLUSIVE" if inc else "PASS")
    return {"case": case, "ok": verdict == "PASS", "verdict": verdict, "findings": list(f) + list(inc), "fail": list(f), "inconclusive": list(inc)}


def verify_case(api, case, ledger, recipients_expected, scope=None, now=None):
    """Read-only. Returns {"case", "verdict": PASS|FAIL|INCONCLUSIVE, "ok", "findings"}. Expectations PER APPROVED RECIPIENT: A = 1 Problem + 1 Recovery; B, C, D(hardware action) = 0.
    ACCEPTANCE RULE: PASS only when adequate authoritative evidence exists. Otherwise INCONCLUSIVE or FAIL - never an assumed PASS."""
    f, inc = [], []
    hw = hardware_action_state(api)
    if not hw["exists"] or hw["actionid"] != ledger.data.get("action"):
        return _result(case, ["the hardware action recorded in the ledger is not the one on Zabbix"], [])
    n = len(recipients_expected)
    if not ledger.data.get("enabled_at"):
        return _result(case, [], ["INCONCLUSIVE: no enabled_at mark: the hardware action is not recorded as enabled during the cases, so a zero-notification result proves nothing"])
    if case in NEGATIVE_CASES:
        from . import evidence as E
        live_action = A.get_action_by_id(api, hw["actionid"])
        lf, li, interval = negative_case_evidence(api, ledger, case, live_action, scope)
        f.extend(lf)
        inc.extend(li)
        if interval is not None:
            tid0 = ledger.data["triggers"].get(case)
            relevant = [int(t) for t in (ledger.data.get("sent") or {}).get(case, [])] + ([int(e["clock"]) for e in _events(api, tid0)] if tid0 else [])
            now_ts = int((now or datetime.datetime.now(datetime.timezone.utc)).timestamp())
            af, ai = E.audit_evidence(api, ledger, case, interval[0], interval[1], str(live_action["status"]), relevant, now_ts)
            f.extend(af)
            inc.extend(ai)
            hf, hi = E.history_evidence(api, ledger, case, interval[0], interval[1], (ledger.data.get("sent") or {}).get(case, []))
            f.extend(hf)
            inc.extend(hi)
    tid = ledger.data["triggers"].get(case)
    if case == "C":
        if tid:
            f.append("case C must not have a trigger")
        ev_ids = set()
    else:
        if not tid:
            return _result(case, ["no trigger id recorded for case %s" % case], [])
        events = _events(api, tid)
        problems = [e for e in events if str(e["value"]) == "1"]
        ev_ids = set()
        for e in problems:
            ev_ids.add(str(e["eventid"]))
            if str(e.get("r_eventid", "0")) != "0":
                ev_ids.add(str(e["r_eventid"]))
        if case in ("A", "B", "D") and len(problems) != 1:
            f.append("expected exactly one Problem event, found %d" % len(problems))
        if problems and str(problems[0].get("r_eventid", "0")) == "0":
            inc.append("INCONCLUSIVE: the Problem has not recovered yet (send the recovery value)")
    alerts = _alerts(api, hw["actionid"], ev_ids)
    prob = [a for a in alerts if str(a["p_eventid"]) == "0"]
    rec = [a for a in alerts if str(a["p_eventid"]) != "0"]
    if case == "A":
        for label, group in (("Problem", prob), ("Recovery", rec)):
            per_user = {}
            for a in group:
                per_user[str(a["userid"])] = per_user.get(str(a["userid"]), 0) + 1
            if sorted(per_user) != sorted(recipients_expected):
                f.append("%s alerts went to %s, expected exactly the approved recipients %s" % (label, sorted(per_user), sorted(recipients_expected)))
            if any(c != 1 for c in per_user.values()):
                f.append("%s: a recipient received more than one message" % label)
            if len(group) != n:
                f.append("%s: %d alert(s), expected %d (1 per approved recipient)" % (label, len(group), n))
        for a in alerts:
            if str(a["status"]) != SENT or str(a.get("error") or ""):
                f.append("alert %s not delivered cleanly (status %s, error %r)" % (a["alertid"], a["status"], a.get("error")))
            text = (a.get("subject") or "") + " " + (a.get("message") or "")
            if "*UNKNOWN*" in text or '{EVENT.TAGS' in text:
                f.append("alert %s has an unexpanded macro" % a["alertid"])
        for a in prob[:1]:
            for want in EXPECTED_TEXT:
                if want not in (a.get("message") or ""):
                    f.append("Problem message lacks the expanded value %r (macro expansion NOT verified)" % want)
        for a in rec[:1]:
            if "Resolved" not in (a.get("message") or "") and "RESOLVED" not in (a.get("subject") or ""):
                f.append("Recovery message lacks the recovery wording")
    else:
        if alerts:
            f.append("case %s must produce ZERO hardware-action notifications, found %d" % (case, len(alerts)))
        # a zero is only meaningful if the action was demonstrably live: Case A delivered through the same action
        ta0 = ledger.data["triggers"].get("A")
        a_ids = set()
        for e in (_events(api, ta0) if ta0 else []):
            a_ids |= {str(e["eventid"]), str(e.get("r_eventid", "0"))}
        if not _alerts(api, hw["actionid"], a_ids):
            inc.append("INCONCLUSIVE: no positive control: Case A produced no hardware-action alert, so a zero for case %s cannot show that filtering works" % case)
    # exclusion: the hardware action may only ever have acted on events of trigger A during the test
    allowed = set()
    ta = ledger.data["triggers"].get("A")
    if ta:
        for e in _events(api, ta):
            allowed |= {str(e["eventid"]), str(e.get("r_eventid", "0"))}
    all_hw = api.call("alert.get", {"output": ["alertid", "eventid"], "actionids": [hw["actionid"]]})
    stray = sorted(set(str(a["eventid"]) for a in all_hw) - allowed)
    if stray:
        f.append("the hardware action delivered for events that are not trigger A's: %s (exclusion violated)" % stray)
    # the Interface Alerting action must not have acted on any synthetic event (default cases carry no netops_alert)
    if case != "D" and ev_ids:
        for ia in interface_actions(api):
            leaked = _alerts(api, ia["actionid"], ev_ids)
            if leaked:
                f.append("Interface Alerting action %s delivered %d alert(s) for a synthetic event" % (ia["actionid"], len(leaked)))
    return _result(case, f, inc)
