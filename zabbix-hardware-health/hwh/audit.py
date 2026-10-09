"""Read-only hardware audit. Two modes:

discover_host  - what is there? Raw walk inputs and concrete CANDIDATE sensors with their real values, timestamps, units, OIDs, preprocessing,
                 value maps and model identity. Candidates are never coverage.
verify_host    - does each sensor the approved policy DECLARES really work end to end? A declared sensor is PASS only when its item is a concrete
                 sensor, collected, supported, fresh, its value is interpretable through a VERIFIED vendor mapping (or has a valid unit for
                 temperature) and an enabled trigger bound to THAT item carries the dedicated hardware event tags.
Verdicts: PASS, GAP (monitoring is missing/unusable), BLOCKED (cannot be judged: device unreachable, host missing), N/A (only with per-model evidence).
A name or keyword match is never a verdict."""
import datetime
import time

from . import items as I
from . import policy as P
from . import semantics as S

PASS, GAP, BLOCKED, NA = "PASS", "GAP", "BLOCKED", "N/A"
TAG_HW, TAG_COMPONENT, TAG_INTERFACE = "netops_hardware", "hardware_component", "netops_alert"
INVENTORY_FIELDS = ["model", "type", "vendor", "os", "os_full", "hardware", "software_full"]


def _host(api, name):
    rows = api.call("host.get", {"output": ["hostid", "host", "status"], "filter": {"host": [name]}, "selectParentTemplates": ["name"],
                                 "selectInventory": INVENTORY_FIELDS, "selectInterfaces": ["interfaceid", "type", "main", "available", "error"]})
    return rows[0] if len(rows) == 1 else None


def _triggers(api, hostid):
    return api.call("trigger.get", {"hostids": [hostid], "expandExpression": True,
                                    "output": ["triggerid", "description", "expression", "status", "priority", "value", "state", "error", "flags"],
                                    "selectTags": ["tag", "value"], "selectItems": ["itemid", "key_"]})


def monitoring_quality(host):
    ifs = [{"type": str(i.get("type")), "available": str(i.get("available")), "error": I._trunc(i.get("error"))} for i in host.get("interfaces", [])]
    snmp = [i for i in ifs if i["type"] == "2"]
    pool = snmp or ifs
    # available: 0 unknown, 1 available, 2 unavailable. Only when EVERY polling interface is unavailable is the device unreachable.
    return {"interfaces": ifs, "unreachable": bool(pool) and all(i["available"] == "2" for i in pool)}


def _identity(host, items, now, masters):
    inv = host.get("inventory") or {}
    inv = dict((k, inv[k]) for k in INVENTORY_FIELDS if isinstance(inv, dict) and inv.get(k))
    ids = [I.evidence(i, now, masters) for i in items if I.IDENTITY_KEY_RE.search(str(i.get("key_") or "")) and not I.raw_reason(i, masters)]
    return {"inventory": inv, "items": [{"key": e["key"], "value": e["lastvalue"], "lastclock_utc": e["lastclock_utc"]} for e in ids]}


def trigger_view(t, category=None):
    tags = dict((x.get("tag", ""), x.get("value", "")) for x in t.get("tags", []))
    enabled = str(t.get("status")) == "0"
    routable = tags.get(TAG_HW) == "1" and (category is None or tags.get(TAG_COMPONENT) == P.COMPONENT_TAG.get(category))
    return {"triggerid": str(t["triggerid"]), "description": I._trunc(t.get("description")), "priority": str(t.get("priority")),
            "enabled": enabled, "problem_now": str(t.get("value")) == "1", "error": I._trunc(t.get("error")),
            "tags": sorted([k, v] for k, v in tags.items()), "dedicated_tags": routable, "cross_tagged": TAG_INTERFACE in tags and TAG_HW in tags}


def discover_host(api, name, now=None):
    now = int(time.time()) if now is None else int(now)
    host = _host(api, name)
    if host is None:
        return {"host": name, "found": False}
    items = I.fetch_items(api, host["hostid"])
    masters = I.master_ids(items)
    ev = [I.evidence(i, now, masters) for i in items]
    raw = [e for e in ev if e["raw_input"]]
    concrete = [e for e in ev if not e["raw_input"]]
    cands = []
    for e in concrete:
        hint = I.classify(e["name"] + " " + e["key"])
        if hint:
            cands.append(dict(e, hint=hint, verdict="CANDIDATE_UNVERIFIED"))
    by_id = dict((e["itemid"], e) for e in concrete)
    trig = []
    for t in _triggers(api, host["hostid"]):
        bound = [str(x.get("itemid")) for x in t.get("items", []) if str(x.get("itemid")) in by_id and any(c["itemid"] == str(x.get("itemid")) for c in cands)]
        if bound:
            v = trigger_view(t)
            v["candidate_itemids"] = bound
            trig.append(v)
    counts = {}
    for c in cands:
        for h in c["hint"]:
            counts[h] = counts.get(h, 0) + 1
    return {"host": name, "found": True, "status": "MONITORED" if str(host["status"]) == "0" else "HOST_DISABLED",
            "templates": sorted(t["name"] for t in host.get("parentTemplates", [])), "identity": _identity(host, items, now, masters),
            "monitoring_quality": monitoring_quality(host),
            "raw_input_count": len(raw), "raw_inputs": [dict((k, e[k]) for k in ("itemid", "key", "snmp_oid", "lastclock", "lastclock_utc", "raw_input")) for e in raw],
            "candidate_sensor_count": len(cands), "candidate_counts": counts, "candidates": cands, "candidate_triggers": trig,
            "note": "Candidates are nominated from names/keys only. They are NOT coverage; declare verified sensors in the policy and run the audit."}


# ----------------------------------------------------------------------------------------------------------------------------- verification
def _norm_unit(u):
    u = str(u or "").strip().lower().replace("°", "")
    return "c" if u in ("c", "degc", "celsius", "deg c") else u


def verify_sensor(decl, cat, item, masters, triggers, unreachable, now, age_limit, reg, vendor, family):
    v = {"key": decl["key"], "category": cat, "slot": decl.get("slot", ""), "verdict": GAP, "reason": "", "detail": "", "current_state": None,
         "evidence": None, "triggers": []}

    def done(verdict, reason, detail=""):
        v.update(verdict=verdict, reason=reason, detail=detail)
        return v

    if item is None:
        return done(GAP, "ITEM_MISSING", "no item with this key on the host")
    ev = I.evidence(item, now, masters)
    v["evidence"] = ev
    if ev["raw_input"]:
        return done(GAP, "ITEM_IS_RAW_INPUT", "this is a raw SNMP walk/discovery input (%s), not one physical sensor" % ev["raw_input"])
    if not ev["enabled"]:
        return done(GAP, "ITEM_DISABLED")
    if unreachable:
        return done(BLOCKED, "HOST_UNREACHABLE", "every polling interface of the host is unavailable; stale/unsupported data cannot be attributed to the sensor")
    if not ev["supported"]:
        return done(GAP, "ITEM_UNSUPPORTED", ev["error"])
    if ev["lastclock"] == 0:
        return done(GAP, "NEVER_COLLECTED", "no value has ever been collected")
    if ev["age_seconds"] > age_limit:
        return done(GAP, "STALE", "last sample %ds ago (limit %ds)" % (ev["age_seconds"], age_limit))
    # --- interpret the value
    if cat in P.STATUS_CATEGORIES:
        entry, why = S.usable(reg, decl["semantics"], vendor, family)
        if entry is None:
            return done(GAP, "SEMANTICS_UNVERIFIED", why)
        state = S.interpret(entry, ev["lastvalue"])
        if state is None:
            return done(GAP, "VALUE_UNMAPPED", "value %r is not in the verified mapping %s" % (ev["lastvalue"], decl["semantics"]))
        v["current_state"] = state
    else:
        try:
            num = float(str(ev["lastvalue"]).strip())
        except ValueError:
            return done(GAP, "VALUE_NOT_NUMERIC", "lastvalue %r" % ev["lastvalue"])
        if _norm_unit(ev["units"]) != _norm_unit(decl["units"]):
            return done(GAP, "UNITS_MISMATCH", "item units %r, policy expects %r" % (ev["units"], decl["units"]))
        pr = decl.get("plausible_range")
        if pr and not pr[0] <= num <= pr[1]:
            return done(GAP, "VALUE_IMPLAUSIBLE", "%s outside the declared plausible range %s" % (num, pr))
        v["current_state"] = "%s %s" % (ev["lastvalue"], ev["units"])
    # --- a trigger bound to THIS item, with the dedicated tags
    bound = [trigger_view(t, cat) for t in triggers if any(str(x.get("itemid")) == ev["itemid"] for x in t.get("items", []))]
    v["triggers"] = bound
    enabled = [t for t in bound if t["enabled"]]
    if any(t["cross_tagged"] for t in enabled):
        return done(GAP, "TRIGGER_CROSS_TAGGED", "a trigger carries both netops_alert and netops_hardware: it could notify through the wrong action")
    if not enabled:
        return done(GAP, "NO_TRIGGER", "no enabled trigger references this item (a trigger whose NAME mentions the component does not count)")
    if not any(t["dedicated_tags"] for t in enabled):
        return done(GAP, "TRIGGER_NOT_ROUTABLE", "enabled trigger(s) exist but none carries %s=1 and %s=%s" % (TAG_HW, TAG_COMPONENT, P.COMPONENT_TAG[cat]))
    return done(PASS, "OK")


def _worst(verdicts):
    if GAP in verdicts:
        return GAP
    if BLOCKED in verdicts:
        return BLOCKED
    return PASS


def verify_host(api, name, settings, reg, now=None):
    now = int(time.time()) if now is None else int(now)
    base = {"host": name, "site": settings.get("site", ""), "vendor": settings["vendor"], "family": settings["family"], "model": settings["model"]}
    host = _host(api, name)
    if host is None:
        return dict(base, verdict=BLOCKED, host_status="HOST_NOT_FOUND", categories={})
    items = I.fetch_items(api, host["hostid"])
    masters = I.master_ids(items)
    triggers = _triggers(api, host["hostid"])
    mq = monitoring_quality(host)
    by_key = dict((str(i.get("key_")), i) for i in items)
    age_limit = settings.get("max_sensor_age_minutes", P.DEFAULT_AGE_MINUTES) * 60
    status = "MONITORED" if str(host["status"]) == "0" else "HOST_DISABLED"
    cats = {}
    for cat, na in (settings.get("not_applicable") or {}).items():
        cats[cat] = {"verdict": NA, "evidence": na["evidence"], "sensors": []}
    for cat in settings.get("expected", []):
        decls = [d for d in settings.get("sensors", []) if d["category"] == cat]
        if status != "MONITORED":
            cats[cat] = {"verdict": BLOCKED, "reason": "HOST_DISABLED", "sensors": []}
            continue
        if not decls:
            cats[cat] = {"verdict": GAP, "reason": "NO_DECLARED_SENSOR", "sensors": [],
                         "detail": "the policy declares no verified sensor for this category (use discover mode, then verify a real one)"}
            continue
        sv = [verify_sensor(d, cat, by_key.get(d["key"]), masters, triggers, mq["unreachable"], now, age_limit, reg, settings["vendor"], settings["family"]) for d in decls]
        cats[cat] = {"verdict": _worst([s["verdict"] for s in sv]), "sensors": sv}
    verdicts = [c["verdict"] for c in cats.values() if c["verdict"] != NA]
    overall = _worst(verdicts) if verdicts else NA
    ev_items = [I.evidence(i, now, masters) for i in items]
    return dict(base, verdict=overall, host_status=status, templates=sorted(t["name"] for t in host.get("parentTemplates", [])),
                identity=_identity(host, items, now, masters), monitoring_quality=mq, categories=cats,
                raw_input_count=sum(1 for e in ev_items if e["raw_input"]),
                concrete_sensor_count=sum(1 for c in cats.values() for s in c["sensors"] if s.get("evidence") and not s["evidence"]["raw_input"]))


def audit(api, config, reg, version, now=None):
    report = {"project": "NETOPS Hardware Health", "schema": 2, "environment": config["environment"], "zabbix_version": version,
              "identity_verified": True, "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "hosts": [],
              "summary": {PASS: 0, GAP: 0, BLOCKED: 0, NA: 0}}
    for name, settings in sorted(config["hosts"].items()):
        h = verify_host(api, name, settings, reg, now)
        report["hosts"].append(h)
        report["summary"][h["verdict"]] += 1
    return report
