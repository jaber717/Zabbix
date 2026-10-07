"""Read the live Zabbix, compare with the desired state, and produce a plan.

Reading only. Nothing in here can write: the plan is data (Change objects) that
apply.py executes through the same ZabbixClient.
"""
import difflib

from . import model
from . import template as tpl
from .envsafety import IDENTITY_MACRO, IDENTITY_MARKER

ADD, CHANGE, REMOVE = "ADD", "CHANGE", "REMOVE"


class Check(object):
    def __init__(self, host, iface, ok, message):
        self.host, self.iface, self.ok, self.message = host, iface, ok, message


class Change(object):
    def __init__(self, kind, obj, target, detail, action, args=None):
        self.kind, self.obj, self.target, self.detail = kind, obj, target, detail
        self.action, self.args = action, args or {}

    def line(self):
        return "%-6s %-10s %s  %s" % (self.kind, self.obj, self.target, self.detail)


class Plan(object):
    def __init__(self):
        self.checks = []
        self.changes = []
        self.conflicts = []     # foreign objects we refuse to touch: REVIEW REQUIRED
        self.notes = []

    @property
    def failed(self):
        return [c for c in self.checks if not c.ok]

    @property
    def empty(self):
        return not self.changes

    def counts(self):
        n = {ADD: 0, CHANGE: 0, REMOVE: 0}
        for c in self.changes:
            n[c.kind] += 1
        return "%d ADD, %d CHANGE, %d REMOVE" % (n[ADD], n[CHANGE], n[REMOVE])


# ----------------------------------------------------------------------- reads

def get_hosts(client, names):
    if not names:
        return {}
    rows = client.call("host.get", {
        "output": ["hostid", "host", "name", "status"], "filter": {"host": sorted(names)},
        "selectInterfaces": ["type", "main", "ip", "dns"],
        "selectMacros": ["hostmacroid", "macro", "value", "description", "type"],
        "selectParentTemplates": ["templateid", "host"]})
    return dict((r["host"], r) for r in rows)


def interface_names(client, hostid):
    """Interface names the host already monitors, from the stock templates' `interface` item tag."""
    rows = client.call("item.get", {
        "output": ["itemid"], "hostids": [hostid], "selectTags": ["tag", "value"],
        "tags": [{"tag": "interface", "operator": 4}]})
    names = set()
    for r in rows:
        for t in r.get("tags", []):
            if t["tag"] == "interface" and t["value"]:
                names.add(t["value"])
    return names


def get_template(client):
    rows = client.call("template.get", {"output": ["templateid", "host", "description"],
                                         "filter": {"host": [tpl.TEMPLATE_NAME]}})
    return rows[0] if rows else None


def live_fingerprint(client, templateid):
    items = client.call("itemprototype.get", {"output": ["key_", "snmp_oid", "delay"],
                                               "hostids": [templateid]})
    trigs = client.call("triggerprototype.get", {
        "output": ["description", "expression", "recovery_expression", "priority"],
        "hostids": [templateid]})
    macros = client.call("usermacro.get", {"output": ["macro", "value"], "hostids": [templateid]})
    return tpl.fingerprint_live(items, trigs, macros)


def diff_fingerprint(want, have):
    out = []
    for part in ("items", "triggers", "macros"):
        w, h = set(map(tuple, want[part])), set(map(tuple, have[part]))
        if w != h:
            out.append("%s: %d missing, %d unexpected" % (part, len(w - h), len(h - w)))
    return out


def get_action(client, name):
    rows = client.call("action.get", {
        "output": "extend", "filter": {"name": [name]}, "selectOperations": "extend",
        "selectRecoveryOperations": "extend", "selectFilter": "extend"})
    return rows[0] if rows else None


def resolve_names(client, method, key, names):
    rows = client.call(method, {"output": "extend", "filter": {"name": sorted(names)}}) if names else []
    return dict((r["name"], r[key]) for r in rows)


def action_params(spec, groupids, mediatypeid):
    mt = str(mediatypeid)
    return {
        "name": spec["name"], "eventsource": 0, "status": 0 if spec["enabled"] else 1,
        "esc_period": "1h",
        "filter": {"evaltype": 0, "conditions": [
            {"conditiontype": 25, "operator": 0, "value": tpl.TAG_ALERT}]},
        "operations": [{
            "operationtype": 0, "esc_period": "0", "esc_step_from": 1, "esc_step_to": 1, "evaltype": 0,
            "opmessage": {"default_msg": 0, "subject": spec["subject"], "message": spec["message"],
                          "mediatypeid": mt},
            "opmessage_grp": [{"usrgrpid": g} for g in groupids]}],
        "recovery_operations": [{
            "operationtype": 11,
            "opmessage": {"default_msg": 0, "subject": spec["r_subject"], "message": spec["r_message"],
                          "mediatypeid": mt}}],
    }


def action_signature(a):
    """Comparable essentials of an action, from desired params or from action.get output."""
    ops = a.get("operations") or []
    rops = a.get("recovery_operations") or []
    groups = sorted(str(g["usrgrpid"]) for o in ops for g in (o.get("opmessage_grp") or []))
    om = (ops[0].get("opmessage") or {}) if ops else {}
    rm = (rops[0].get("opmessage") or {}) if rops else {}
    conds = sorted((str(c["conditiontype"]), str(c["operator"]), c["value"])
                   for c in (a.get("filter") or {}).get("conditions", []))
    return {"status": str(a["status"]), "groups": groups, "mediatype": str(om.get("mediatypeid", "")),
            "subject": om.get("subject", ""), "message": om.get("message", ""),
            "r_subject": rm.get("subject", ""), "r_message": rm.get("message", ""), "conds": conds}


# ------------------------------------------------------------------------ plan

def run_checks(client, desired, hosts_live):
    """PASS/FAIL per selected interface (reads only). Config problems come first."""
    checks = []
    for p in desired.problems:
        checks.append(Check(p.host or "-", p.iface or "-", False, p.message))

    # ---- per-interface checks ------------------------------------------------
    for hname in sorted(desired.hosts):
        hcfg = desired.hosts[hname]
        live = hosts_live.get(hname)
        seen = {}
        for iname in sorted(hcfg["interfaces"]):
            key = " ".join(iname.lower().split())
            if key in seen:
                checks.append(Check(hname, iname, False,
                                         "duplicate of '%s' (names differ only by case/spacing)" % seen[key]))
            seen[key] = iname
        if live is None:
            for iname in sorted(hcfg["interfaces"]):
                checks.append(Check(hname, iname, False, "host '%s' not found in Zabbix" % hname))
            continue
        if str(live["status"]) != "0":
            for iname in sorted(hcfg["interfaces"]):
                checks.append(Check(hname, iname, False, "host is disabled in Zabbix (not monitored)"))
            continue
        if not any(str(i["type"]) == "2" for i in live.get("interfaces", [])):
            for iname in sorted(hcfg["interfaces"]):
                checks.append(Check(hname, iname, False, "host has no SNMP interface"))
            continue
        known = interface_names(client, live["hostid"])
        if not known:
            for iname in sorted(hcfg["interfaces"]):
                checks.append(Check(hname, iname, False,
                                         "cannot verify: host has no items tagged interface=<name>"))
            continue
        for iname in sorted(hcfg["interfaces"]):
            if any(c.host == hname and c.iface == iname and not c.ok for c in checks):
                continue
            if iname in known:
                checks.append(Check(hname, iname, True, "interface exists on host"))
            else:
                hint = [k for k in known if k.lower() == iname.lower()] or \
                    difflib.get_close_matches(iname, sorted(known), n=2, cutoff=0.6)
                checks.append(Check(hname, iname, False,
                                         "interface not found on host" +
                                         (" (did you mean %s?)" % ", ".join("'%s'" % h for h in hint)
                                          if hint else "")))
    return checks


def build_plan(client, env, desired, identity_state="ok", allow_init=False):
    plan = Plan()
    hosts_live = get_hosts(client, list(desired.hosts))
    plan.checks = run_checks(client, desired, hosts_live)
    if desired.problems:
        plan.notes.append("configuration errors: macros and changes are not computed")
        return plan

    # ---- macros need to be computed even when checks fail (for dry-run info) ----
    suppress = bool(env.get("suppress_stock"))
    try:
        desired_macros = dict((h, model.host_macros(c, suppress)) for h, c in desired.hosts.items())
    except model.ModelError as exc:
        plan.checks.append(Check("-", "-", False, str(exc)))
        return plan

    # ---- template -----------------------------------------------------------
    tp = get_template(client)
    want_doc = tpl.build()
    if tp is None:
        plan.changes.append(Change(ADD, "template", tpl.TEMPLATE_NAME,
                                   "import generated template (1 LLD rule, 9 item prototypes, "
                                   "%d trigger prototypes)" % len(tpl.trigger_prototypes()),
                                   "import_template"))
        tplid = None
    elif tpl.MARKER not in (tp.get("description") or ""):
        plan.conflicts.append("template '%s' exists but is not managed by this tool "
                              "(no '%s' marker) — REVIEW REQUIRED" % (tpl.TEMPLATE_NAME, tpl.MARKER))
        tplid = tp["templateid"]
    else:
        tplid = tp["templateid"]
        problems = diff_fingerprint(tpl.fingerprint_desired_numeric(want_doc), live_fingerprint(client, tplid))
        hash_now = "hash=" + tpl.content_hash()
        if hash_now not in tp["description"]:
            problems.append("template version differs from this repository")
        if problems:
            plan.changes.append(Change(CHANGE, "template", tpl.TEMPLATE_NAME,
                                       "re-import (%s)" % "; ".join(problems), "import_template"))

    # ---- owned / foreign macros across the whole server ---------------------------
    # `search` is only reliable on the (varchar) macro name, so ownership is decided locally
    # from the description marker.
    cols = ["hostmacroid", "hostid", "macro", "value", "description"]
    ns_rows = client.call("usermacro.get", {"output": cols, "search": {"macro": tpl.MACRO_PREFIX}})
    ifc_rows = client.call("usermacro.get", {"output": cols, "search": {"macro": model.IFCONTROL + ":"}})
    owned_rows = [r for r in ns_rows + ifc_rows if tpl.MARKER in (r.get("description") or "")]
    owned_by_host = {}
    for r in owned_rows:
        if r["hostid"] != tplid:
            owned_by_host.setdefault(r["hostid"], []).append(r)
    foreign_ns = [r for r in ns_rows if r["hostid"] != tplid and tpl.MARKER not in (r.get("description") or "")]

    linked = {}
    if tplid:
        for h in client.call("host.get", {"output": ["hostid", "host"], "templateids": [tplid]}):
            linked[h["hostid"]] = h["host"]
    live_by_id = dict((h["hostid"], h) for h in hosts_live.values())
    extra_ids = (set(owned_by_host) | set(linked) | set(r["hostid"] for r in foreign_ns)) - set(live_by_id)
    names_by_id = dict((h["hostid"], h["host"]) for h in hosts_live.values())
    if extra_ids:
        for h in client.call("host.get", {"output": ["hostid", "host"], "hostids": sorted(extra_ids)}):
            names_by_id[h["hostid"]] = h["host"]

    # ---- hosts in YAML --------------------------------------------------------------
    for hname in sorted(desired.hosts):
        live = hosts_live.get(hname)
        if live is None:
            continue
        want = desired_macros[hname]
        have = dict((m["macro"], m) for m in live.get("macros", []))
        if not any(t["host"] == tpl.TEMPLATE_NAME for t in live.get("parentTemplates", [])):
            plan.changes.append(Change(ADD, "link", hname, "link template '%s'" % tpl.TEMPLATE_NAME,
                                       "link_template", {"host": hname, "hostid": live["hostid"]}))
        for macro in sorted(want):
            cur = have.get(macro)
            if cur is None:
                plan.changes.append(Change(ADD, "macro", "%s %s" % (hname, macro), "= %s" % want[macro],
                                           "macro_create", {"hostid": live["hostid"], "macro": macro,
                                                            "value": want[macro]}))
            elif model.is_owned(cur):
                if cur["value"] != want[macro]:
                    plan.changes.append(Change(CHANGE, "macro", "%s %s" % (hname, macro),
                                               "live '%s' -> git '%s'" % (cur["value"], want[macro]),
                                               "macro_update", {"hostmacroid": cur["hostmacroid"],
                                                                "macro": macro, "value": want[macro]}))
            else:
                plan.conflicts.append("%s: macro %s exists but is not managed by this tool — "
                                      "REVIEW REQUIRED" % (hname, macro))
        for macro, cur in sorted(have.items()):
            if macro in want or not model.is_owned(cur):
                continue
            plan.changes.append(Change(REMOVE, "macro", "%s %s" % (hname, macro), "was '%s'" % cur["value"],
                                       "macro_delete", {"hostmacroid": cur["hostmacroid"]}))
        for cur in [m for m in live.get("macros", []) if model.in_namespace(m["macro"])
                    and not model.is_owned(m) and m["macro"] not in want]:
            plan.conflicts.append("%s: unmanaged macro %s is in the reserved {$NETOPS.*} namespace — "
                                  "REVIEW REQUIRED" % (hname, cur["macro"]))

    # ---- hosts no longer in YAML: remove what we own ---------------------------------
    for hid in sorted(set(owned_by_host) | set(linked)):
        name = names_by_id.get(hid, hid)
        if name in desired.hosts:
            continue
        if hid in linked:
            plan.changes.append(Change(REMOVE, "link", name, "unlink + clear template '%s'" % tpl.TEMPLATE_NAME,
                                       "unlink_template", {"host": name, "hostid": hid}))
        for r in owned_by_host.get(hid, []):
            plan.changes.append(Change(REMOVE, "macro", "%s %s" % (name, r["macro"]), "was '%s'" % r["value"],
                                       "macro_delete", {"hostmacroid": r["hostmacroid"]}))
    for r in foreign_ns:
        nm = names_by_id.get(r["hostid"])
        if nm is None:
            continue
        if nm not in desired.hosts:
            plan.conflicts.append("%s: unmanaged macro %s is in the reserved {$NETOPS.*} namespace — "
                                  "REVIEW REQUIRED" % (nm, r["macro"]))

    # ---- alert action ---------------------------------------------------------------------
    spec = model.desired_action(env)
    if spec:
        groups = resolve_names(client, "usergroup.get", "usrgrpid", spec["usergroups"])
        missing = [g for g in spec["usergroups"] if g not in groups]
        mt = 0
        if spec["media_type"]:
            found = resolve_names(client, "mediatype.get", "mediatypeid", [spec["media_type"]])
            if spec["media_type"] not in found:
                missing.append("media type '%s'" % spec["media_type"])
            else:
                mt = found[spec["media_type"]]
        if missing:
            plan.checks.append(Check("-", "alert_action", False,
                                     "not found in Zabbix: %s" % ", ".join(missing)))
        else:
            want = action_params(spec, [groups[g] for g in spec["usergroups"]], mt)
            cur = get_action(client, spec["name"])
            if cur is None:
                plan.changes.append(Change(ADD, "action", spec["name"],
                                           "notify %s, %s" % (", ".join(spec["usergroups"]),
                                                              "ENABLED" if spec["enabled"] else "disabled"),
                                           "action_create", {"params": want}))
            elif action_signature(cur) != action_signature(want):
                diff = sorted(k for k, v in action_signature(want).items()
                              if action_signature(cur).get(k) != v)
                plan.changes.append(Change(CHANGE, "action", spec["name"], "differs: %s" % ", ".join(diff),
                                           "action_update", {"params": dict(want, actionid=cur["actionid"])}))

    # ---- identity ---------------------------------------------------------------------------------
    if identity_state == "uninitialised":
        if allow_init:
            plan.changes.insert(0, Change(ADD, "identity", IDENTITY_MACRO, "= %s" % env["environment"],
                                          "init_identity", {"value": env["environment"]}))
        else:
            plan.notes.append("identity not initialised on this Zabbix: apply needs --init-identity")

    # ---- final: honour blockers ------------------------------------------------------------------------
    plan.conflicts = sorted(set(plan.conflicts))
    return plan
