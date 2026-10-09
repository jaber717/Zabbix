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
        hit = [a["name"] for a in actions if a["status"] == "0" and A.event_matches(a.get("filter") or {}, ev)]
        chk("%s: no ENABLED action matches the trigger's tags" % s["component"], not hit, ", ".join(hit))
    return {"checks": checks, "ok": all(c[1] for c in checks), "snapshot": snap}


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
