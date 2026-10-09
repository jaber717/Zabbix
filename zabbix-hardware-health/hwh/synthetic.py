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
    allowed = {"approved_by", "approval_reference", "window_start", "window_end", "media_type", "usergroups", "test_scope", "case_d", "existing_hardware_action"}
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
    eh = s.get("existing_hardware_action")
    if eh is not None and (not isinstance(eh, dict) or eh.get("acknowledged") is not True or len(str(eh.get("note") or "").strip()) < 3 or set(eh) - {"acknowledged", "note"}):
        raise AuditError("synthetic scope: existing_hardware_action needs acknowledged: true and a note")
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
def preflight(api, scope, notif_spec, now=None, mode="execute"):
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
    if pre_existing:
        chk("hardware action is DISABLED before the test", st["status"] == "1", "action %s is enabled" % st["actionid"] if st["status"] != "1" else "")
        ack = (scope.get("existing_hardware_action") or {}).get("acknowledged") is True
        chk("a PRE-EXISTING hardware action is explicitly acknowledged (it is never adopted, modified or deleted by the test)", ack,
            "" if ack else "action %s already exists. Add existing_hardware_action: {acknowledged: true, note: ...} to the approval, or remove it through its own approved change" % st["actionid"])
    else:
        chk("hardware action absent (will be created disabled by 'action apply')", True)
        chk("no existing_hardware_action acknowledgement without an existing action", "existing_hardware_action" not in scope, "")
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
                             "enabled_at": None, "disabled_at": None}

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


def cleanup_plan(api, ledger):
    """Exact cleanup calls, ledger ids only, ownership-verified. Refuses (stop and investigate, never delete) if: the ledger is empty; a recorded id is
    not the synthetic object it claims to be; the namespace holds anything the ledger does not know; or an ENABLED hardware action is not in the ledger.
    The hardware action is inspected LIVE by its recorded id: if it is enabled, disabling it is always the first step, whatever enabled_at/disabled_at say."""
    ids = ledger.ids()
    if not (ids["host"] or ids["hostgroup"] or ids["item"] or ids["triggers"] or ids["action"]):
        raise AuditError("the ledger is empty: nothing to clean up (and nothing may be deleted by name)")
    own = verify_ownership(api, ledger)
    if own:
        raise AuditError("ownership verification failed - refusing to plan any deletion: " + "; ".join(own))
    live = synthetic_objects(api)
    known = {"triggers": set(ids["triggers"]), "items": {ids["item"]} - {None}, "hosts": {ids["host"]} - {None}, "hostgroups": {ids["hostgroup"]} - {None}}
    for kind in ("triggers", "items", "hosts", "hostgroups"):
        extra = [i for i, _ in live[kind] if i not in known[kind]]
        if extra:
            raise AuditError("the synthetic namespace contains %s %s that this test did not create: refusing to clean up. Investigate." % (kind, extra))
    on_zabbix = dict((kind, set(i for i, _ in live[kind])) for kind in live)
    plan = []
    hw = hardware_action_state(api)
    if ids["action"]:
        rec = _action_by_id(api, ids["action"])
        if rec is not None and rec["name"] != A.ACTION_NAME:
            raise AuditError("recorded action id %s is named %r, not the hardware action: refusing" % (ids["action"], rec["name"]))
        if rec is not None and str(rec["status"]) != "1":
            plan.append({"method": "action.update", "params": {"actionid": ids["action"], "status": 1}, "why": "FIRST STEP: the recorded hardware action is ENABLED on Zabbix right now - disable it"})
        if hw["exists"] and hw["actionid"] != ids["action"]:
            raise AuditError("a hardware action (id %s) exists that is not the recorded one (%s): refusing. Investigate." % (hw["actionid"], ids["action"]))
    elif hw["exists"] and hw["status"] != "1":
        raise AuditError("the hardware action (id %s) is ENABLED but is not in the ledger, so this test cannot claim it. Disable it through its own approved change and "
                         "investigate; nothing was planned." % hw["actionid"])
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
    if ids["action"] and ledger.data.get("action_created_by_test") is True:
        plan.append({"method": "(tool)", "params": "hardware_audit.py --env lab action rollback --backup <backup printed by action apply>",
                     "why": "remove the action created by this test, using its backup (not by name)"})
    elif ids["action"]:
        plan.append({"method": "(none)", "params": None, "why": "the hardware action PRE-EXISTED: it is left in place, disabled, and must be byte-identical in the after-manifest"})
    return plan


# ----------------------------------------------------------------------------------------------------------------- verification
def _events(api, triggerid):
    return api.call("event.get", {"output": ["eventid", "r_eventid", "clock", "value"], "source": 0, "object": 0, "objectids": [triggerid]})


def _alerts(api, actionid, eventids):
    if not eventids:
        return []
    return api.call("alert.get", {"output": ["alertid", "actionid", "eventid", "p_eventid", "userid", "status", "retries", "error", "subject", "message", "alerttype"],
                                  "actionids": [actionid], "eventids": sorted(eventids)})


def verify_case(api, case, ledger, recipients_expected):
    """Read-only. Returns {"case", "ok", "findings": [...]}. Expectations PER APPROVED RECIPIENT: A = 1 Problem + 1 Recovery; B, C, D(hardware action) = 0."""
    f = []
    hw = hardware_action_state(api)
    if not hw["exists"] or hw["actionid"] != ledger.data.get("action"):
        return {"case": case, "ok": False, "findings": ["the hardware action recorded in the ledger is not the one on Zabbix"]}
    n = len(recipients_expected)
    if not ledger.data.get("enabled_at"):
        return {"case": case, "ok": False, "findings": ["no enabled_at mark: the hardware action is not recorded as enabled during the cases, so a zero-notification result proves nothing"]}
    tid = ledger.data["triggers"].get(case)
    if case == "C":
        if tid:
            f.append("case C must not have a trigger")
        ev_ids = set()
    else:
        if not tid:
            return {"case": case, "ok": False, "findings": ["no trigger id recorded for case %s" % case]}
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
            f.append("the Problem has not recovered yet (send the recovery value)")
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
            f.append("no positive control: Case A produced no hardware-action alert, so a zero for case %s cannot show that filtering works" % case)
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
    return {"case": case, "ok": not f, "findings": f}
