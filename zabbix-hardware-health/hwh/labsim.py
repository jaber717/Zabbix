"""READ-ONLY verification of the existing LAB simulator objects (host/items/triggers) and the isolation of their notification path.
Writes nothing. The tag change and the restore are PRINTED as plans (with preconditions) for explicit operator approval; they are never applied here."""
import json
import re

import yaml

from . import action as A
from .api import AuditError


def load(path):
    with open(path, encoding="utf-8") as fh:
        d = yaml.safe_load(fh)
    if d.get("schema") != 1 or d.get("environment") != "lab":
        raise AuditError("lab-sim.yaml must be schema 1, environment lab")
    return d


def snapshot(api, cfg):
    """Everything about the three objects that a later restore/diff needs. Read-only."""
    hid = cfg["host"]["hostid"]
    host = api.call("host.get", {"hostids": [hid], "output": ["hostid", "host", "name", "status"], "selectTags": "extend"})
    items = api.call("item.get", {"itemids": [s["itemid"] for s in cfg["sensors"]], "output": ["itemid", "hostid", "name", "key_", "status", "lastvalue", "lastclock", "state", "value_type"],
                                  "selectTags": "extend"})
    trig = api.call("trigger.get", {"triggerids": [s["triggerid"] for s in cfg["sensors"]], "output": ["triggerid", "description", "expression", "status", "value", "priority"],
                                    "selectTags": "extend", "expandExpression": True})
    return {"host": host, "items": sorted(items, key=lambda x: x["itemid"]), "triggers": sorted(trig, key=lambda x: x["triggerid"])}


def verify(api, cfg):
    """-> {'checks': [(name, ok, detail)], 'ok': bool, 'snapshot': ...}. Nothing is written."""
    snap = snapshot(api, cfg)
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    chk("host exists", len(snap["host"]) == 1 and snap["host"][0]["host"] == cfg["host"]["name"], cfg["host"]["name"])
    chk("three items found", len(snap["items"]) == 3)
    chk("three triggers found", len(snap["triggers"]) == 3)
    by_item = dict((i["itemid"], i) for i in snap["items"])
    for s in cfg["sensors"]:
        i, t = by_item.get(s["itemid"]), next((x for x in snap["triggers"] if x["triggerid"] == s["triggerid"]), None)
        chk("%s: item on the sim host and enabled" % s["component"], i is not None and i["hostid"] == cfg["host"]["hostid"] and i["status"] == "0")
        chk("%s: item is delivering data" % s["component"], i is not None and i.get("state") == "0" and i.get("lastclock", "0") not in ("", "0"))
        chk("%s: trigger references its item" % s["component"], t is not None and i is not None and i["key_"] in t["expression"])
        tags = dict((x["tag"], x["value"]) for x in (t or {}).get("tags", []))
        chk("%s: trigger does not carry netops_alert" % s["component"], t is not None and A.TAG_INTERFACE not in tags)
    # notification isolation: no ENABLED action may match these triggers' tags
    actions = api.call("action.get", {"output": ["actionid", "name", "status", "eventsource"], "selectFilter": "extend", "filter": {"eventsource": 0}})
    for s in cfg["sensors"]:
        t = next((x for x in snap["triggers"] if x["triggerid"] == s["triggerid"]), None)
        ev = dict((x["tag"], x["value"]) for x in (t or {}).get("tags", []))
        hit = [a["name"] for a in actions if a["status"] == "0" and may_match(a.get("filter") or {}, ev)]
        chk("%s: no ENABLED action matches the trigger's tags" % s["component"], not hit, ", ".join(hit))
    return {"checks": checks, "ok": all(c[1] for c in checks), "snapshot": snap}


def may_match(flt, event_tags):
    """FAIL-CLOSED model: an action with no conditions matches every event; a condition type this tool does not model is assumed to match."""
    conds = flt.get("conditions") or []
    if not conds:
        return True
    if any(int(c["conditiontype"]) not in (A.COND_TAG, A.COND_TAG_VALUE) for c in conds):
        flt = dict(flt, conditions=[c for c in conds if int(c["conditiontype"]) in (A.COND_TAG, A.COND_TAG_VALUE)])
        return True if not flt["conditions"] else (A.event_matches(flt, event_tags) if int(flt.get("evaltype", 0)) == 1 else True)
    return A.event_matches(flt, event_tags)


def tag_plan(cfg, snap):
    """PRINT-ONLY plan: the tags to ADD to each trigger (existing tags are kept) so it routes like a hardware trigger."""
    plan = []
    for s in cfg["sensors"]:
        t = next(x for x in snap["triggers"] if x["triggerid"] == s["triggerid"])
        have = dict((x["tag"], x["value"]) for x in t.get("tags", []))
        want = dict(cfg["proposed_tags"], hardware_component=s["component"], hardware_slot="sim-" + s["component"])
        add = [{"tag": k, "value": v} for k, v in sorted(want.items()) if have.get(k) != v]
        plan.append({"triggerid": t["triggerid"], "existing_tags": t.get("tags", []), "tags_after": t.get("tags", []) + add, "adds": add})
    return plan


def restore_plan(snap):
    """PRINT-ONLY: the exact tag lists to put back (trigger.update tags) to undo a tag change."""
    return [{"triggerid": t["triggerid"], "restore_tags": t.get("tags", [])} for t in snap["triggers"]]


def render(result, cfg):
    lines = ["LAB simulator objects - READ-ONLY verification (nothing written)"]
    for name, ok, detail in result["checks"]:
        lines.append("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" - " + detail) if detail else ""))
    lines.append("Overall: %s" % ("PASS" if result["ok"] else "FAIL"))
    lines.append("\nPROPOSED tag addition (NOT APPLIED; needs operator approval):")
    lines.append(json.dumps(tag_plan(cfg, result["snapshot"]), indent=2, sort_keys=True))
    lines.append("\nRESTORE plan (exact pre-change tags):")
    lines.append(json.dumps(restore_plan(result["snapshot"]), indent=2, sort_keys=True))
    return "\n".join(lines)


def evidence(api, cfg, since):
    """READ-ONLY event / alert evidence for the three simulator triggers since `since` (epoch seconds).
    -> {'triggers': {triggerid: {'problems': n, 'recovered': n, 'alerts_by_action': {name: n}}}, 'findings': [...], 'ok': bool}
    ok means: every Problem has a linked Recovery, and every alert came from the hardware action (nothing from any other action)."""
    out, findings = {}, []
    for s in cfg["sensors"]:
        tid = s["triggerid"]
        ev = api.call("event.get", {"objectids": [tid], "source": 0, "object": 0, "time_from": int(since), "output": ["eventid", "value", "r_eventid", "clock"],
                                    "sortfield": ["clock"], "sortorder": "ASC"})
        problems = [e for e in ev if str(e["value"]) == "1"]
        recovered = [e for e in problems if str(e.get("r_eventid", "0")) not in ("", "0")]
        by_action = {}
        if ev:
            # a Recovery notification is attached to the RECOVERY event id, so query both ids
            ids = [e["eventid"] for e in ev] + [e["r_eventid"] for e in recovered]
            al = api.call("alert.get", {"eventids": ids, "output": ["alertid", "actionid", "status", "error", "eventid"]})
            for a in al:
                by_action[str(a["actionid"])] = by_action.get(str(a["actionid"]), 0) + 1
        out[tid] = {"component": s["component"], "problems": len(problems), "recovered": len(recovered), "alerts_by_actionid": by_action}
        if len(problems) != len(recovered):
            findings.append("trigger %s (%s): %d Problem(s) but %d linked Recovery(ies)" % (tid, s["component"], len(problems), len(recovered)))
    names = dict((str(a["actionid"]), a["name"]) for a in api.call("action.get", {"output": ["actionid", "name"]}))
    for tid, r in out.items():
        r["alerts_by_action"] = dict((names.get(k, k), v) for k, v in r.pop("alerts_by_actionid").items())
        for name in r["alerts_by_action"]:
            if name != A.ACTION_NAME:
                findings.append("trigger %s: alert(s) from action %r (only %r may notify for hardware events)" % (tid, name, A.ACTION_NAME))
    return {"triggers": out, "findings": findings, "ok": not findings}
