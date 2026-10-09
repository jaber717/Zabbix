"""The separate NETOPS Hardware Health notification action - design, plan, guarded apply, rollback.

Design rules
  * Routing is a POSITIVE allowlist on a dedicated event tag: the action fires only for events whose tag `netops_hardware` equals `1`
    (Zabbix condition type 26, event tag value). Broad `scope` tags, host groups and trigger-name text are never used.
  * A second condition (type 25, event tag name `netops_alert` does-not-equal) guards against a trigger tagged for both families.
  * The Interface Alerting action (`NETOPS-IaC ...`, filter: event tag `netops_alert` present) is only READ, to prove offline that neither
    action can match the other's events. It is never modified.
  * The action is created DISABLED. This tool can only enable it when config/action-validation.yaml records independently verified Problem
    delivery, Recovery delivery and interface exclusion, and --enable is passed explicitly. Until then notifications are NOT operational.
  * Production is refused in this release.
The condition semantics modelled below are the documented Zabbix 7.0 ones; the live server is the authority (acceptance test HW-N4)."""
import datetime
import json
import os

import yaml

from .api import AuditError

ACTION_NAME = "NETOPS-HW Hardware Health"          # prefix NETOPS-HW is the ownership marker
OWNED_PREFIX = "NETOPS-HW "
INTERFACE_PREFIX = "NETOPS-IaC"
TAG_HW, TAG_INTERFACE = "netops_hardware", "netops_alert"
COND_TAG, COND_TAG_VALUE = 25, 26
OP_EQUALS, OP_NOT_EQUALS = 0, 1

def tag_macro(name):
    """{EVENT.TAGS."name"} - the documented Zabbix 7.0 form for an event-tag value. Tag names that contain anything other than letters and digits
    (every hardware_* name has an underscore) must be double-quoted; a quote or backslash inside the name is escaped with a backslash."""
    if not name or any(ord(c) < 32 for c in name):
        raise AuditError("invalid event tag name for a macro: %r" % (name,))
    return '{EVENT.TAGS."%s"}' % name.replace("\\", "\\\\").replace('"', '\\"')


TAG_MODEL, TAG_VENDOR, TAG_SITE, TAG_COMPONENT, TAG_SLOT = ("hardware_model", "hardware_vendor", "hardware_site", "hardware_component", "hardware_slot")
PAYLOAD_TAGS = (TAG_VENDOR, TAG_MODEL, TAG_SITE, TAG_COMPONENT, TAG_SLOT)

SUBJECT = "[HARDWARE {EVENT.STATUS}] {EVENT.NAME} on {HOST.NAME}"
MESSAGE = ("Status:      {EVENT.STATUS}\r\nSeverity:    {EVENT.SEVERITY}\r\nHost:        {HOST.NAME}\r\n"
           "Model:       " + tag_macro(TAG_MODEL) + "\r\nVendor:      " + tag_macro(TAG_VENDOR) + "\r\n"
           "Site:        " + tag_macro(TAG_SITE) + "\r\nComponent:   " + tag_macro(TAG_COMPONENT) + "  slot " + tag_macro(TAG_SLOT) + "\r\n"
           "Time:        {EVENT.DATE} {EVENT.TIME}\r\nEvent ID:    {EVENT.ID}\r\nTags:        {EVENT.TAGS}\r\n")
R_SUBJECT = "[HARDWARE RESOLVED] {EVENT.NAME} on {HOST.NAME}"
R_MESSAGE = "Resolved:    {EVENT.RECOVERY.DATE} {EVENT.RECOVERY.TIME}\r\nDuration:    {EVENT.DURATION}\r\n" + MESSAGE


def hardware_filter():
    return {"evaltype": 1, "conditions": [
        {"conditiontype": COND_TAG_VALUE, "operator": OP_EQUALS, "value": TAG_HW, "value2": "1"},
        {"conditiontype": COND_TAG, "operator": OP_NOT_EQUALS, "value": TAG_INTERFACE}]}


def load_spec(path):
    with open(path, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh) or {}
    if set(spec) - {"name", "media_type", "usergroups", "environment", "approved_by", "approval_reference"}:
        raise AuditError("notifications config: unknown keys")
    if spec.get("name", ACTION_NAME) != ACTION_NAME:
        raise AuditError("the action name is fixed to '%s' (ownership marker)" % ACTION_NAME)
    if not spec.get("media_type") or not isinstance(spec.get("usergroups"), list) or not spec["usergroups"]:
        raise AuditError("notifications config needs media_type and a non-empty usergroups list (operator-owned names)")
    for k in ("approved_by", "approval_reference"):
        if len(str(spec.get(k) or "").strip()) < 3:
            raise AuditError("notifications config: '%s' is required. The recipient group(s) must be explicitly approved by an operator; they are never defaulted or substituted (not even with the Zabbix administrators)" % k)
    if any(not isinstance(g, str) or not g.strip() for g in spec["usergroups"]):
        raise AuditError("notifications config: usergroups must be exact, non-empty group names")
    return spec


def build_params(mediatypeid, groupids, enabled):
    mt = str(mediatypeid)
    ops_grp = [{"usrgrpid": str(g)} for g in groupids]
    return {"name": ACTION_NAME, "eventsource": 0, "status": 0 if enabled else 1, "esc_period": "1h", "filter": hardware_filter(),
            "operations": [{"operationtype": 0, "esc_period": "0", "esc_step_from": 1, "esc_step_to": 1, "evaltype": 0,
                            "opmessage": {"default_msg": 0, "subject": SUBJECT, "message": MESSAGE, "mediatypeid": mt}, "opmessage_grp": ops_grp}],
            "recovery_operations": [{"operationtype": 0, "opmessage": {"default_msg": 0, "subject": R_SUBJECT, "message": R_MESSAGE, "mediatypeid": mt},
                                     "opmessage_grp": ops_grp}]}


def signature(a):
    ops, rops = a.get("operations") or [], a.get("recovery_operations") or []
    groups = sorted(str(g["usrgrpid"]) for o in ops for g in (o.get("opmessage_grp") or []))
    rgroups = sorted(str(g["usrgrpid"]) for o in rops for g in (o.get("opmessage_grp") or []))
    om = (ops[0].get("opmessage") or {}) if ops else {}
    rm = (rops[0].get("opmessage") or {}) if rops else {}
    f = a.get("filter") or {}
    conds = sorted((str(c["conditiontype"]), str(c["operator"]), c["value"], c.get("value2", "")) for c in f.get("conditions", []))
    return {"status": str(a["status"]), "evaltype": str(f.get("evaltype", "")), "conds": conds, "groups": groups, "r_groups": rgroups,
            "mediatype": str(om.get("mediatypeid", "")), "subject": om.get("subject", ""), "message": om.get("message", ""),
            "r_subject": rm.get("subject", ""), "r_message": rm.get("message", ""), "n_ops": len(ops), "n_rops": len(rops)}


def params_from_live(a):
    """action.get output -> action.create/update params (used by rollback)."""
    def op(o, recovery):
        d = {"operationtype": int(o.get("operationtype", 0)), "opmessage": dict((k, o["opmessage"][k]) for k in ("default_msg", "subject", "message", "mediatypeid") if k in o["opmessage"]),
             "opmessage_grp": [{"usrgrpid": str(g["usrgrpid"])} for g in o.get("opmessage_grp", [])]}
        if not recovery:
            for k in ("esc_period", "esc_step_from", "esc_step_to", "evaltype"):
                if k in o:
                    d[k] = o[k]
        return d
    f = a.get("filter") or {}
    return {"name": a["name"], "eventsource": int(a.get("eventsource", 0)), "status": int(a["status"]), "esc_period": a.get("esc_period", "1h"),
            "filter": {"evaltype": int(f.get("evaltype", 0)), "conditions": [dict((k, c[k]) for k in ("conditiontype", "operator", "value", "value2") if k in c) for c in f.get("conditions", [])]},
            "operations": [op(o, False) for o in a.get("operations", [])], "recovery_operations": [op(o, True) for o in a.get("recovery_operations", [])]}


# ----------------------------------------------------------------------------------------------------------------------- offline model
def event_matches(flt, event_tags):
    """Model of Zabbix trigger-action condition evaluation for the two condition types used here. event_tags: {name: value}."""
    res = []
    for c in flt.get("conditions", []):
        t, op = int(c["conditiontype"]), int(c["operator"])
        if t == COND_TAG:
            has = c["value"] in event_tags
            res.append(has if op == OP_EQUALS else (not has))
        elif t == COND_TAG_VALUE:
            ok = event_tags.get(c["value"]) == c.get("value2")
            res.append(ok if op == OP_EQUALS else (not ok))
        else:
            raise AuditError("event_matches does not model condition type %s" % t)
    if not res:
        return False
    return all(res) if int(flt.get("evaltype", 0)) == 1 else any(res)


def interface_filter():
    """The Interface Alerting action's documented filter: event tag `netops_alert` present."""
    return {"evaltype": 0, "conditions": [{"conditiontype": COND_TAG, "operator": OP_EQUALS, "value": TAG_INTERFACE}]}


SAMPLE_EVENTS = {
    "hardware fan event": ({TAG_HW: "1", "hardware_component": "fan"}, True, False),
    "hardware psu event": ({TAG_HW: "1", "hardware_component": "power"}, True, False),
    "interface link_down event": ({TAG_INTERFACE: "link_down", "link_id": "x"}, False, True),
    "interface util event": ({TAG_INTERFACE: "util_rx"}, False, True),
    "stock hardware trigger (scope only)": ({"scope": "availability", "component": "fan"}, False, False),
    "linux component=system notice": ({"scope": "notice", "component": "system"}, False, False),
    "mis-tagged trigger carrying both": ({TAG_HW: "1", TAG_INTERFACE: "link_down"}, False, True),
}


def crossover_report(live_interface_filters=None):
    """-> list of (event, hardware_action_fires, interface_action_fires, expected_hw, expected_if, ok)"""
    hw, ifs = hardware_filter(), interface_filter()
    out = []
    for name, (tags, want_hw, want_if) in SAMPLE_EVENTS.items():
        got_hw = event_matches(hw, tags)
        got_if = event_matches(ifs, tags)
        out.append({"event": name, "hardware_action": got_hw, "interface_action": got_if, "ok": got_hw == want_hw and got_if == want_if})
    for f in live_interface_filters or []:
        for name, (tags, _, _) in SAMPLE_EVENTS.items():
            if TAG_HW in tags and TAG_INTERFACE not in tags and event_matches(f, tags):
                out.append({"event": name + " vs live interface action", "hardware_action": None, "interface_action": True, "ok": False})
    return out


# ----------------------------------------------------------------------------------------------------------------------- live plan / apply
def load_validation(path):
    if not os.path.isfile(path):
        return {"ok": False, "why": "no validation evidence file"}
    with open(path, encoding="utf-8") as fh:
        v = yaml.safe_load(fh) or {}
    why = []
    for k in ("problem_delivery", "recovery_delivery", "interface_exclusion"):
        e = v.get(k) or {}
        if e.get("verified") is not True or len(str(e.get("evidence") or "").strip()) < 10:
            why.append(k + " not verified with evidence")
    if not str(v.get("validated_by") or "").strip():
        why.append("validated_by missing")
    return {"ok": not why, "why": "; ".join(why)}


def resolve(api, spec):
    mt = api.call("mediatype.get", {"output": ["mediatypeid", "name", "status"], "filter": {"name": [spec["media_type"]]}})
    ug = api.call("usergroup.get", {"output": ["usrgrpid", "name"], "filter": {"name": spec["usergroups"]}})
    problems = []
    if len(mt) != 1:
        problems.append("media type '%s' not found (it is never created by this tool)" % spec["media_type"])
    found = set(g["name"] for g in ug)
    for n in spec["usergroups"]:
        if n not in found:
            problems.append("user group '%s' not found (it is never created by this tool)" % n)
    return (mt[0] if mt else None), ug, problems


def get_action(api, name):
    rows = api.call("action.get", {"output": "extend", "filter": {"name": [name]}, "selectOperations": "extend", "selectRecoveryOperations": "extend", "selectFilter": "extend"})
    return rows[0] if rows else None


def plan(api, env, spec, enable_requested, validation_path):
    """Read-only. -> dict(changes, conflicts, notes, desired, live, enable_allowed, crossover)"""
    out = {"changes": [], "conflicts": [], "notes": [], "desired": None, "live": None, "crossover": []}
    if env != "lab":
        out["conflicts"].append("hardware action management is LAB only in this release (environment is %s)" % env)
        return out
    val = load_validation(validation_path)
    enable_ok = bool(enable_requested and val["ok"])
    if enable_requested and not val["ok"]:
        out["conflicts"].append("--enable refused: " + val["why"])
    mt, ug, problems = resolve(api, spec)
    out["conflicts"].extend(problems)
    live = get_action(api, ACTION_NAME)
    out["live"] = live
    if_actions = api.call("action.get", {"output": "extend", "search": {"name": INTERFACE_PREFIX}, "startSearch": True, "selectFilter": "extend"})
    out["crossover"] = crossover_report([a.get("filter") or {} for a in if_actions])
    if any(not c["ok"] for c in out["crossover"]):
        out["conflicts"].append("an event could reach the wrong action (see crossover report)")
    if out["conflicts"]:
        return out
    desired = build_params(mt["mediatypeid"], [g["usrgrpid"] for g in ug], enabled=enable_ok)
    out["desired"] = desired
    if live is None:
        out["changes"].append("CREATE action '%s' (%s)" % (ACTION_NAME, "ENABLED" if enable_ok else "disabled"))
    else:
        want, have = signature(desired), signature(live)
        diff = [k for k in want if want[k] != have[k]]
        if "status" in diff and have["status"] == "0" and not enable_ok:
            out["notes"].append("the live action is ENABLED without validation evidence: apply will disable it")
        if diff:
            out["changes"].append("UPDATE action '%s' [%s]" % (ACTION_NAME, ", ".join(diff)))
    return out


def readiness(api, validation_path, alert_pass_count):
    """Notification readiness, independent of telemetry and alert coverage. States: NOT_READY | VALIDATED. There is no 'delivery PASS' here:
    VALIDATED only means an independent tester recorded verified Problem+Recovery delivery and interface exclusion."""
    reasons = []
    if alert_pass_count == 0:
        reasons.append("no declared sensor has a routable hardware trigger (nothing can raise a hardware event)")
    live = get_action(api, ACTION_NAME)
    if live is None:
        reasons.append("action '%s' does not exist" % ACTION_NAME)
    elif str(live.get("status")) != "0":
        reasons.append("action '%s' is disabled" % ACTION_NAME)
    val = load_validation(validation_path)
    if not val["ok"]:
        reasons.append("delivery is not validated: " + val["why"])
    return {"state": "NOT_READY" if reasons else "VALIDATED", "reasons": reasons, "delivery_tested": val["ok"], "action_exists": live is not None}


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def apply(api, env, spec, enable_requested, validation_path, base):
    p = plan(api, env, spec, enable_requested, validation_path)
    if p["conflicts"]:
        raise AuditError("plan has conflicts: " + "; ".join(p["conflicts"]))
    if not p["changes"]:
        return {"plan": p, "backup": None}
    d = os.path.join(base, "state", "backups")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "hardware-action-%s-%s.json" % (env, _stamp()))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"environment": env, "action": ACTION_NAME, "existed": p["live"] is not None,
                   "previous": params_from_live(p["live"]) if p["live"] else None}, fh, indent=2, sort_keys=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if p["live"] is None:
        api.call("action.create", p["desired"])
    else:
        upd = dict(p["desired"])
        upd["actionid"] = p["live"]["actionid"]
        api.call("action.update", upd)
    again = plan(api, env, spec, enable_requested, validation_path)
    if again["changes"]:
        raise AuditError("readback verification failed: " + "; ".join(again["changes"]) + " (restore with rollback --backup %s)" % path)
    return {"plan": p, "backup": path}


def rollback(api, env, backup_path):
    if env != "lab":
        raise AuditError("hardware action management is LAB only in this release")
    with open(backup_path, encoding="utf-8") as fh:
        b = json.load(fh)
    if b.get("environment") != env or b.get("action") != ACTION_NAME:
        raise AuditError("backup is for a different environment/action - refusing")
    live = get_action(api, ACTION_NAME)
    if not b["existed"]:
        if live:
            api.call("action.delete", [live["actionid"]])
        return "removed action created by this tool" if live else "nothing to remove"
    prev = b["previous"]
    if live is None:
        api.call("action.create", prev)
    else:
        prev = dict(prev, actionid=live["actionid"])
        api.call("action.update", prev)
    return "restored previous definition"
