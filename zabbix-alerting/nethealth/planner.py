"""Plan and apply Network Health. Owns ONLY: the NETOPS Health templates, their links, and host macros
{$NHEALTH.*} marked managed_by=network-health-as-code. Never touches Interface Alerting objects
({$NETOPS.*}, template 'NETOPS Interface Alerting', the alert action) or anything stock. UNTESTED.
"""
import datetime
import json
import os

from netalert.planner import ADD, CHANGE, REMOVE, Change, Check, Plan, get_hosts
from netalert.zbx import ZabbixError

from . import templates as T

SNMP_FEATURES = ("snmp_stale", "cpu", "memory", "ospf", "bgp")


def host_macros(dev):
    """{macro: value} written on one host. Alerts not selected stay at the template default (off)."""
    f = dev["features"]
    sev = dict((n, str(p)) for n, p, _ in T.SEVS)
    m = {"{$NHEALTH.SITE}": dev["site"]}
    if "device_unreachable" in f:
        s = f["device_unreachable"]
        m.update({"{$NHEALTH.UNREACH.ON}": "1", "{$NHEALTH.UNREACH.SEV}": sev[s["severity"]],
                  "{$NHEALTH.UNREACH.WINDOW}": str(s["window"])})
    if "snmp_stale" in f:
        s = f["snmp_stale"]
        m.update({"{$NHEALTH.STALE.ON}": "1", "{$NHEALTH.STALE.SEV}": sev[s["severity"]],
                  "{$NHEALTH.STALE.TIMEOUT}": str(s["timeout"])})
    for feat, p in (("cpu", "CPU"), ("memory", "MEM")):
        if feat in f:
            s = f[feat]
            m.update({"{$NHEALTH.%s.ON}" % p: "1", "{$NHEALTH.%s.SEV}" % p: sev[s["severity"]],
                      "{$NHEALTH.%s.MAX}" % p: _num(s["threshold"]), "{$NHEALTH.%s.RECOVER}" % p: _num(s["recovery"]),
                      "{$NHEALTH.%s.WINDOW}" % p: str(s["window"])})
    for feat, p in (("ospf", "OSPF"), ("bgp", "BGP")):
        if feat in f:
            m["{$NHEALTH.%s.SEV}" % p] = sev[f[feat]["severity"]]
            for x in f[feat]["exclude"]:
                m['{$NHEALTH.%s.ALERT:"%s"}' % (p, x)] = "0"
    return m


def _num(v):
    return str(int(v)) if isinstance(v, float) and v == int(v) else str(v)


def _owned(row):
    return T.MARKER in (row.get("description") or "")


def build_plan(client, desired):
    plan = Plan()
    for dev, feat, msg in desired.problems:
        plan.checks.append(Check(dev, feat, False, msg))
    if desired.problems:
        plan.notes.append("configuration errors: changes are not computed")
        return plan

    live = get_hosts(client, list(desired.devices))
    for name in sorted(desired.devices):
        dev, h = desired.devices[name], live.get(name)
        if h is None:
            plan.checks.append(Check(name, "-", False, "host '%s' not found in Zabbix (use the technical Host name)" % name))
        elif str(h["status"]) != "0":
            plan.checks.append(Check(name, "-", False, "host is disabled in Zabbix"))
        elif any(f in dev["features"] for f in SNMP_FEATURES) and \
                not any(str(i["type"]) == "2" for i in h.get("interfaces", [])):
            plan.checks.append(Check(name, "-", False, "host has no SNMP interface"))
        elif not h.get("interfaces"):
            plan.checks.append(Check(name, "-", False, "host has no interface (needed for ICMP)"))
        else:
            plan.checks.append(Check(name, ",".join(sorted(dev["features"])), True,
                                     "templates: %s" % ", ".join(sorted(T.templates_for(dev)))))

    # ---- templates: import only what the inventory needs; never touch a same-named foreign template
    needed = set()
    for dev in desired.devices.values():
        needed |= T.templates_for(dev)
    rows = client.call("template.get", {"output": ["templateid", "host", "description"],
                                        "filter": {"host": list(T.ALL)}})
    tids = {}
    for r in rows:
        if not _owned(r):
            plan.conflicts.append("template '%s' exists but is not managed by Network Health — REVIEW REQUIRED" % r["host"])
            continue
        tids[r["host"]] = r["templateid"]
        if r["host"] in needed and ("hash=%s" % T.content_hash(r["host"])) not in r["description"]:
            plan.changes.append(Change(CHANGE, "template", r["host"], "re-import (version differs from repository)",
                                       "import_template", {"name": r["host"]}))
    for name in sorted(needed - set(r["host"] for r in rows)):
        plan.changes.append(Change(ADD, "template", name, "import", "import_template", {"name": name}))

    # ---- links -----------------------------------------------------------------------------------
    linked, names_by_id = {}, {}
    for tname, tid in tids.items():
        for h in client.call("host.get", {"output": ["hostid", "host"], "templateids": [tid]}):
            linked.setdefault(h["hostid"], set()).add(tname)
            names_by_id[h["hostid"]] = h["host"]
    for name in sorted(desired.devices):
        h = live.get(name)
        if h is None:
            continue
        want, have = T.templates_for(desired.devices[name]), linked.get(h["hostid"], set())
        for tname in sorted(want - have):
            plan.changes.append(Change(ADD, "link", name, "link template '%s'" % tname, "link_template",
                                       {"host": name, "hostid": h["hostid"], "name": tname}))
        for tname in sorted(have - want):
            plan.changes.append(Change(REMOVE, "link", name, "unlink + clear template '%s'" % tname, "unlink_template",
                                       {"host": name, "hostid": h["hostid"], "name": tname}))
    live_ids = set(h["hostid"] for h in live.values())
    for hid in sorted(set(linked) - live_ids):
        for tname in sorted(linked[hid]):
            plan.changes.append(Change(REMOVE, "link", names_by_id[hid], "unlink + clear template '%s'" % tname,
                                       "unlink_template", {"host": names_by_id[hid], "hostid": hid, "name": tname}))

    # ---- host macros {$NHEALTH.*} ------------------------------------------------------------------
    for name in sorted(desired.devices):
        h = live.get(name)
        if h is None:
            continue
        want = host_macros(desired.devices[name])
        have = dict((m["macro"], m) for m in h.get("macros", []))
        for mac in sorted(want):
            cur = have.get(mac)
            if cur is None:
                plan.changes.append(Change(ADD, "macro", "%s %s" % (name, mac), "= %s" % want[mac], "macro_create",
                                           {"hostid": h["hostid"], "macro": mac, "value": want[mac]}))
            elif not _owned(cur):
                plan.conflicts.append("%s: macro %s exists but is not managed by Network Health — REVIEW REQUIRED" %
                                      (name, mac))
            elif cur.get("value", "") != want[mac]:
                plan.changes.append(Change(CHANGE, "macro", "%s %s" % (name, mac),
                                           "live '%s' -> git '%s'" % (cur.get("value", ""), want[mac]), "macro_update",
                                           {"hostmacroid": cur["hostmacroid"], "value": want[mac]}))
        for mac, cur in sorted(have.items()):
            if mac.startswith(T.MACRO_PREFIX) and _owned(cur) and mac not in want:
                plan.changes.append(Change(REMOVE, "macro", "%s %s" % (name, mac), "was '%s'" % cur.get("value", ""),
                                           "macro_delete", {"hostmacroid": cur["hostmacroid"]}))
    rows = client.call("usermacro.get", {"output": ["hostmacroid", "hostid", "macro", "value", "description"],
                                         "search": {"macro": T.MACRO_PREFIX}})
    orphans = [r for r in rows if _owned(r) and r["hostid"] not in live_ids and r["hostid"] not in tids.values()]
    if orphans:
        ids = sorted(set(r["hostid"] for r in orphans) - set(names_by_id))
        if ids:
            for h in client.call("host.get", {"output": ["hostid", "host"], "hostids": ids}):
                names_by_id[h["hostid"]] = h["host"]
        for r in orphans:
            plan.changes.append(Change(REMOVE, "macro", "%s %s" % (names_by_id.get(r["hostid"], r["hostid"]), r["macro"]),
                                       "was '%s'" % r.get("value", ""), "macro_delete", {"hostmacroid": r["hostmacroid"]}))
    plan.conflicts = sorted(set(plan.conflicts))
    return plan


class ApplyError(Exception):
    def __init__(self, message, done):
        Exception.__init__(self, message)
        self.done = done


ORDER = ["import_template", "link_template", "macro_create", "macro_update", "unlink_template", "macro_delete"]


def execute(client, plan, log):
    by = {}
    for ch in plan.changes:
        by.setdefault(ch.action, []).append(ch)
    done = [0]

    def step(label, method, params):
        try:
            res = client.call(method, params)
        except ZabbixError as exc:
            raise ApplyError("%s failed: %s" % (label, exc), done[0])
        log("  ok  %s" % label)
        return res

    def tid(name):
        rows = client.call("template.get", {"output": ["templateid"], "filter": {"host": [name]}})
        if not rows:
            raise ApplyError("template '%s' not found after import" % name, done[0])
        return rows[0]["templateid"]

    for action in ORDER:
        chs = by.get(action) or []
        if not chs:
            continue
        if action == "import_template":
            for ch in chs:
                step("import template '%s'" % ch.args["name"], "configuration.import",
                     {"format": "json", "source": json.dumps(T.build(ch.args["name"])), "rules": T.IMPORT_RULES})
                done[0] += 1
        elif action in ("link_template", "unlink_template"):
            for ch in chs:
                if action == "link_template":
                    step("link '%s' to %s" % (ch.args["name"], ch.args["host"]), "host.massadd",
                         {"hosts": [{"hostid": ch.args["hostid"]}], "templates": [{"templateid": tid(ch.args["name"])}]})
                else:
                    step("unlink '%s' from %s" % (ch.args["name"], ch.args["host"]), "host.massremove",
                         {"hostids": [ch.args["hostid"]], "templateids_clear": [tid(ch.args["name"])]})
                done[0] += 1
        elif action == "macro_create":
            step("create %d macro(s)" % len(chs), "usermacro.create",
                 [{"hostid": c.args["hostid"], "macro": c.args["macro"], "value": c.args["value"],
                   "description": T.MARKER} for c in chs])
            done[0] += len(chs)
        elif action == "macro_update":
            step("update %d macro(s)" % len(chs), "usermacro.update",
                 [{"hostmacroid": c.args["hostmacroid"], "value": c.args["value"], "description": T.MARKER}
                  for c in chs])
            done[0] += len(chs)
        elif action == "macro_delete":
            step("delete %d macro(s)" % len(chs), "usermacro.delete", [c.args["hostmacroid"] for c in chs])
            done[0] += len(chs)
    return done[0]


def write_backup(base, client, env_name, cfg_path):
    """Audit record of every Network Health object before an apply (owned macros, links, templates)."""
    rows = client.call("usermacro.get", {"output": ["hostmacroid", "hostid", "macro", "value", "description"],
                                         "search": {"macro": T.MACRO_PREFIX}})
    tpls = client.call("template.get", {"output": ["templateid", "host", "description"], "filter": {"host": list(T.ALL)}})
    links = {}
    for t in tpls:
        links[t["host"]] = [h["host"] for h in client.call("host.get", {"output": ["host"], "templateids": [t["templateid"]]})]
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    d = os.path.join(base, "state", "backups")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "network-health-%s-%s.json" % (env_name, stamp))
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, "network-health-%s-%s_%d.json" % (env_name, stamp, n))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"format": 1, "tool_version": T.TOOL_VERSION, "config": os.path.relpath(cfg_path, base),
                   "macros": [r for r in rows if _owned(r)], "templates": tpls, "links": links}, fh, indent=1)
    return path
