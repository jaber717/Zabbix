"""An in-memory model of the Zabbix 7.0 JSON-RPC API, used as a *transport* in tests.

It enforces the rules the real server enforces on the calls this tool makes —
auth and read-only users, macro name/value limits, duplicate macros, template
linking, configuration.import validation (schema keys, uuid format, expression
references, trigger-prototype-needs-item-prototype, dependencies, deleteMissing),
action structure, task.create — and answers with Zabbix-shaped result and error
objects (string ids, JSON-RPC error codes and messages).

It is an approximation, not a certified clone: every behaviour here that was
written from documentation rather than observed on a live server is the
reason the final status stays PASS WITH LIMITATIONS until a write-capable LAB
run is done.
"""
import copy
import json
import re

MACRO_RE = re.compile(r'^\{\$[A-Z0-9_.]+(?::.+)?\}$')
UUID_RE = re.compile(r'^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{3}[0-9a-f]{12}$')
REF_RE = re.compile(r'/([^/(),]+)/([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)')
FUNC_RE = re.compile(r'([a-z_]+)\(')
FUNCTIONS = {"last", "avg", "min", "max", "count", "changecount", "find", "nodata", "sum", "abs", "delta"}
PRIORITIES = {"NOT_CLASSIFIED": 0, "INFO": 1, "WARNING": 2, "AVERAGE": 3, "HIGH": 4, "DISASTER": 5}
VALUE_TYPES = {"FLOAT": 0, "CHAR": 1, "LOG": 2, "UNSIGNED": 3, "TEXT": 4}
ITEM_TYPES = {"SNMP_AGENT", "DEPENDENT", "ZABBIX_PASSIVE", "CALCULATED", "SNMP_TRAP", "TRAP", "SIMPLE"}
PREPROC = {"MULTIPLIER", "CHANGE_PER_SECOND", "JAVASCRIPT", "REGEX", "DELTA_VALUE", "TRIM",
           "SNMP_WALK_VALUE", "SNMP_WALK_TO_JSON", "JSONPATH"}
WRITE_SUFFIXES = (".create", ".update", ".delete", ".massadd", ".massremove", ".massupdate",
                  ".createglobal", ".updateglobal", ".deleteglobal")
ALLOWED = {
    "template": {"uuid", "template", "name", "description", "groups", "discovery_rules", "macros",
                 "items", "tags", "templates"},
    "rule": {"uuid", "name", "type", "snmp_oid", "key", "delay", "filter", "lifetime_type", "lifetime",
             "description", "item_prototypes", "trigger_prototypes", "status", "enabled_lifetime_type"},
    "item": {"uuid", "name", "type", "snmp_oid", "key", "delay", "history", "trends", "value_type",
             "units", "tags", "preprocessing", "master_item", "description", "status"},
    "trigger": {"uuid", "name", "event_name", "opdata", "expression", "recovery_mode",
                "recovery_expression", "priority", "description", "manual_close", "tags", "dependencies",
                "status", "url", "correlation_mode", "correlation_tag"},
}


class _Transport(object):
    def __init__(self, server, token):
        self.server, self.token = server, token

    def send(self, payload, authenticated=True):
        return self.server.send(payload, authenticated, self.token)


def err(code, message, data=""):
    return {"error": {"code": code, "message": message, "data": data}}


class Fail(Exception):
    def __init__(self, data, code=-32500, message="Application error."):
        Exception.__init__(self, data)
        self.payload = err(code, message, data)["error"]


def invalid(data):
    return Fail(data, -32602, "Invalid params.")


class MockZabbix(object):
    VERSION = "7.0.30"

    def __init__(self, token="test-token", readonly=False, version=None):
        self.token = token
        self.readonly = readonly
        self.VERSION = version or self.VERSION
        self._n = 10000
        self.hosts = {}          # hostid -> dict
        self.templates = {}      # templateid -> dict (also in hosts-like macros store)
        self.macros = {}         # hostmacroid -> {hostid,macro,value,description,type}
        self.gmacros = {}        # globalmacroid -> dict
        self.items = {}          # itemid -> {hostid,key_,name,tags:[{tag,value}]}
        self.itemprotos = {}     # id -> dict (hostid=template id)
        self.trigprotos = {}
        self.rules = {}          # itemid -> {hostid,key_, ...}
        self.usergroups = {}
        self.mediatypes = {}
        self.actions = {}
        self.tasks = []
        self.calls = []          # [(method, ok)]
        self.template_groups = {"1": "Templates/Network devices"}
        self.last_import = None

    # ---------------------------------------------------------------- seeding
    def nid(self):
        self._n += 1
        return str(self._n)

    def add_host(self, name, interfaces=("Gi0/0", "Gi0/1"), snmp=True, status=0, tag_name="interface",
                 templates=()):
        hid = self.nid()
        self.hosts[hid] = {"hostid": hid, "host": name, "name": name, "status": str(status),
                           "interfaces": [{"type": "2" if snmp else "1", "main": "1", "ip": "10.0.0.1",
                                           "dns": ""}], "templates": list(templates)}
        for itf in interfaces:
            for key in ("net.if.in", "net.if.out"):
                iid = self.nid()
                self.items[iid] = {"itemid": iid, "hostid": hid, "key_": "%s[%s]" % (key, itf),
                                   "name": "Interface %s: bits" % itf,
                                   "tags": [{"tag": tag_name, "value": itf}, {"tag": "component", "value": "network"}]}
        return hid

    def add_usergroup(self, name):
        gid = self.nid()
        self.usergroups[gid] = {"usrgrpid": gid, "name": name}
        return gid

    def add_mediatype(self, name):
        mid = self.nid()
        self.mediatypes[mid] = {"mediatypeid": mid, "name": name}
        return mid

    def add_macro(self, hostid, macro, value, description=""):
        mid = self.nid()
        self.macros[mid] = {"hostmacroid": mid, "hostid": hostid, "macro": macro, "value": value,
                            "description": description, "type": "0"}
        return mid

    def host_id(self, name):
        for h in self.hosts.values():
            if h["host"] == name:
                return h["hostid"]

    def host_macro_map(self, name):
        hid = self.host_id(name)
        return dict((m["macro"], m["value"]) for m in self.macros.values() if m["hostid"] == hid)

    # -------------------------------------------------------------- transport
    def transport(self, token=None):
        """What ZabbixClient talks to. `token` is what the client presents (default: the valid one)."""
        return _Transport(self, self.token if token is None else token)

    def send(self, payload, authenticated=True, presented_token=None):
        method = payload["method"]
        try:
            if authenticated and method != "apiinfo.version" and presented_token != self.token:
                raise invalid("Not authorized.")
            result = self._dispatch(method, payload.get("params"), authenticated)
            self.calls.append((method, True))
            return {"jsonrpc": "2.0", "result": result, "id": payload["id"]}
        except Fail as exc:
            self.calls.append((method, False))
            return {"jsonrpc": "2.0", "error": exc.payload, "id": payload["id"]}

    @staticmethod
    def is_write(method):
        return method.endswith(WRITE_SUFFIXES) or method in ("configuration.import", "task.create")

    def writes(self):
        return [m for m, ok in self.calls if ok and self.is_write(m)]

    def snapshot(self):
        return copy.deepcopy((self.hosts, self.templates, self.macros, self.gmacros, self.items,
                              self.itemprotos, self.trigprotos, self.rules, self.actions, self.tasks))

    def _dispatch(self, method, params, authenticated):
        if method == "apiinfo.version":
            return self.VERSION
        if not authenticated or params is None:
            raise invalid("Not authorized.")
        fn = getattr(self, "m_" + method.replace(".", "_"), None)
        if fn is None:
            raise Fail("Method \"%s\" not found" % method.split(".")[-1], -32601, "Method not found.")
        if self.is_write(method) and self.readonly:
            raise invalid("No permissions to call \"%s\"." % method)
        return fn(params)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _out(row, output):
        if output in (None, "extend"):
            return dict(row)
        return dict((k, row[k]) for k in output if k in row)

    # ------------------------------------------------------------------ reads
    def m_host_get(self, p):
        rows = []
        flt = (p.get("filter") or {}).get("host")
        for h in self.hosts.values():
            if flt is not None and h["host"] not in (flt if isinstance(flt, list) else [flt]):
                continue
            if p.get("hostids") and h["hostid"] not in p["hostids"]:
                continue
            if p.get("templateids") and not any(t in h["templates"] for t in p["templateids"]):
                continue
            public = dict((k, v) for k, v in h.items() if k not in ("interfaces", "templates"))
            r = self._out(public, p.get("output"))
            if "selectInterfaces" in p:
                r["interfaces"] = [dict((k, i[k]) for k in (p["selectInterfaces"] if isinstance(
                    p["selectInterfaces"], list) else i)) for i in h["interfaces"]]
            if "selectMacros" in p:
                r["macros"] = [self._out(m, p["selectMacros"]) for m in self.macros.values()
                               if m["hostid"] == h["hostid"]]
            if "selectParentTemplates" in p:
                r["parentTemplates"] = [{"templateid": t, "host": self.templates[t]["host"]}
                                        for t in h["templates"] if t in self.templates]
            rows.append(r)
        return rows

    def m_item_get(self, p):
        rows = []
        for it in self.items.values():
            if p.get("hostids") and it["hostid"] not in p["hostids"]:
                continue
            ok = True
            for t in p.get("tags") or []:
                has = [x for x in it["tags"] if x["tag"] == t["tag"]]
                op = int(t.get("operator", 0))
                if op == 4 and not has:
                    ok = False
                elif op == 5 and has:
                    ok = False
            if not ok:
                continue
            r = self._out(it, p.get("output"))
            if p.get("selectTags"):
                r["tags"] = [dict(x) for x in it["tags"]]
            else:
                r.pop("tags", None)
            r.pop("hostid", None) if "hostid" not in (p.get("output") or []) else None
            rows.append(r)
        return rows

    def m_template_get(self, p):
        flt = (p.get("filter") or {}).get("host")
        return [self._out(t, p.get("output")) for t in self.templates.values()
                if flt is None or t["host"] in flt]

    def m_itemprototype_get(self, p):
        return [self._out(i, p.get("output")) for i in self.itemprotos.values()
                if not p.get("hostids") or i["hostid"] in p["hostids"]]

    def m_triggerprototype_get(self, p):
        return [self._out(i, p.get("output")) for i in self.trigprotos.values()
                if not p.get("hostids") or i["hostid"] in p["hostids"]]

    def m_discoveryrule_get(self, p):
        flt = (p.get("filter") or {}).get("key_")
        return [self._out(r, p.get("output")) for r in self.rules.values()
                if (not p.get("hostids") or r["hostid"] in p["hostids"]) and (flt is None or r["key_"] == flt)]

    def m_usergroup_get(self, p):
        flt = (p.get("filter") or {}).get("name")
        return [dict(g) for g in self.usergroups.values() if flt is None or g["name"] in flt]

    def m_mediatype_get(self, p):
        flt = (p.get("filter") or {}).get("name")
        return [dict(g) for g in self.mediatypes.values() if flt is None or g["name"] in flt]

    def m_usermacro_get(self, p):
        rows = []
        if p.get("globalmacro"):
            src = [dict(globalmacroid=g["globalmacroid"], macro=g["macro"], value=g["value"],
                        description=g.get("description", "")) for g in self.gmacros.values()]
        else:
            src = list(self.macros.values())
        for m in src:
            if p.get("hostids") and m.get("hostid") not in p["hostids"]:
                continue
            f = (p.get("filter") or {}).get("macro")
            if f is not None and m["macro"] != f:
                continue
            s = (p.get("search") or {}).get("macro")
            if s is not None and s.lower() not in m["macro"].lower():
                continue
            if (p.get("search") or {}).get("description") is not None:
                raise invalid("Invalid parameter \"/search\": unsupported field \"description\".")
            rows.append(self._out(m, p.get("output")))
        return rows

    # ----------------------------------------------------------------- macros
    def _check_macro(self, m, host_or_global):
        if not isinstance(m.get("macro"), str) or not MACRO_RE.match(m["macro"]):
            raise invalid("Invalid parameter \"/1/macro\": a user macro is expected.")
        if len(m["macro"]) > 255:
            raise invalid("Invalid parameter \"/1/macro\": value is too long.")
        if len(m.get("value", "")) > 2048:
            raise invalid("Invalid parameter \"/1/value\": value is too long.")

    def m_usermacro_create(self, p):
        items = p if isinstance(p, list) else [p]
        ids = []
        seen = set()
        for m in items:
            if m["hostid"] not in self.hosts and m["hostid"] not in self.templates:
                raise invalid("No permissions to referred object or it does not exist!")
            self._check_macro(m, m["hostid"])
            key = (m["hostid"], m["macro"])
            if key in seen or any(x["hostid"] == m["hostid"] and x["macro"] == m["macro"]
                                  for x in self.macros.values()):
                raise invalid("Macro \"%s\" already exists on \"%s\"." % (
                    m["macro"], (self.hosts.get(m["hostid"]) or self.templates[m["hostid"]])["host"]))
            seen.add(key)
        for m in items:
            ids.append(self.add_macro(m["hostid"], m["macro"], m.get("value", ""), m.get("description", "")))
        return {"hostmacroids": ids}

    def m_usermacro_update(self, p):
        items = p if isinstance(p, list) else [p]
        for m in items:
            if m.get("hostmacroid") not in self.macros:
                raise invalid("No permissions to referred object or it does not exist!")
            if len(m.get("value", "")) > 2048:
                raise invalid("Invalid parameter \"/1/value\": value is too long.")
        for m in items:
            row = self.macros[m["hostmacroid"]]
            for k in ("value", "description"):
                if k in m:
                    row[k] = m[k]
        return {"hostmacroids": [m["hostmacroid"] for m in items]}

    def m_usermacro_delete(self, p):
        for i in p:
            if i not in self.macros:
                raise invalid("No permissions to referred object or it does not exist!")
        for i in p:
            del self.macros[i]
        return {"hostmacroids": list(p)}

    def m_usermacro_createglobal(self, p):
        items = p if isinstance(p, list) else [p]
        for m in items:
            self._check_macro(m, None)
            if any(g["macro"] == m["macro"] for g in self.gmacros.values()):
                raise invalid("Macro \"%s\" already exists." % m["macro"])
        ids = []
        for m in items:
            gid = self.nid()
            self.gmacros[gid] = {"globalmacroid": gid, "macro": m["macro"], "value": m.get("value", ""),
                                 "description": m.get("description", "")}
            ids.append(gid)
        return {"globalmacroids": ids}

    # ------------------------------------------------------------------ links
    def m_host_massadd(self, p):
        for h in p["hosts"]:
            if h["hostid"] not in self.hosts:
                raise invalid("No permissions to referred object or it does not exist!")
        for t in p.get("templates", []):
            if t["templateid"] not in self.templates:
                raise invalid("No permissions to referred object or it does not exist!")
        for h in p["hosts"]:
            for t in p.get("templates", []):
                if t["templateid"] not in self.hosts[h["hostid"]]["templates"]:
                    self.hosts[h["hostid"]]["templates"].append(t["templateid"])
                    self._inherit_rules(h["hostid"], t["templateid"])
        return {"hostids": [h["hostid"] for h in p["hosts"]]}

    def _inherit_rules(self, hostid, templateid):
        """Linking a template gives the host its own copy of every discovery rule (real Zabbix does too)."""
        for rid, r in list(self.rules.items()):
            if r["hostid"] == templateid:
                nid = self.nid()
                self.rules[nid] = dict(r, itemid=nid, hostid=hostid, templateid=rid)

    def m_host_massremove(self, p):
        for hid in p["hostids"]:
            if hid not in self.hosts:
                raise invalid("No permissions to referred object or it does not exist!")
        for hid in p["hostids"]:
            for tid in p.get("templateids_clear", []) + p.get("templateids", []):
                if tid in self.hosts[hid]["templates"]:
                    self.hosts[hid]["templates"].remove(tid)
                    parents = set(r_id for r_id, r in self.rules.items() if r["hostid"] == tid)
                    for r_id, r in list(self.rules.items()):
                        if r["hostid"] == hid and r.get("templateid") in parents:
                            del self.rules[r_id]
        return {"hostids": p["hostids"]}

    # ------------------------------------------------------------ import/export
    def _check_expression(self, expr, tpl_name, keys, where):
        if expr.count("(") != expr.count(")"):
            raise Fail("Invalid parameter \"%s\": unbalanced parentheses in \"%s\"." % (where, expr))
        for fn in FUNC_RE.findall(re.sub(r'\{[^{}]*\}', '', expr)):
            if fn not in FUNCTIONS:
                raise Fail("Invalid parameter \"%s\": unknown function \"%s\"." % (where, fn))
        refs = REF_RE.findall(re.sub(r'"[^"]*"', '', expr.replace('"{#IFNAME}"', '')))
        for host, key in refs:
            if host.startswith("{") or host == "{HOST.HOST}":
                continue
            if host != tpl_name:
                raise Fail("Invalid parameter \"%s\": host \"%s\" does not exist." % (where, host))
            if key not in keys:
                raise Fail("Invalid parameter \"%s\": item \"%s\" does not exist in \"%s\"." % (
                    where, key, tpl_name))
        return [k for h, k in refs if h == tpl_name]

    def _unknown_keys(self, obj, kind, where):
        for k in obj:
            if k not in ALLOWED[kind]:
                raise Fail("Invalid tag \"%s\": unexpected tag \"%s\"." % (where, k))

    def m_configuration_import(self, p):
        if p.get("format") != "json":
            raise invalid("Invalid parameter \"/format\": value must be one of json, xml, yaml.")
        try:
            doc = json.loads(p["source"])["zabbix_export"]
        except (ValueError, KeyError, TypeError):
            raise Fail("Cannot parse import source: invalid JSON or missing zabbix_export.")
        if doc.get("version") != "7.0":
            raise Fail("Invalid tag \"/zabbix_export/version\": unsupported version number.")
        rules = p.get("rules") or {}
        for g in doc.get("template_groups", []):
            if not UUID_RE.match(g["uuid"]):
                raise Fail("Invalid tag \"/zabbix_export/template_groups\": invalid uuid.")
            if g["name"] not in self.template_groups.values():
                if not (rules.get("template_groups") or {}).get("createMissing"):
                    raise Fail("Template group \"%s\" does not exist." % g["name"])
                self.template_groups[self.nid()] = g["name"]
        staged = []
        seen_uuid = set()
        for ti, t in enumerate(doc.get("templates", [])):
            w = "/zabbix_export/templates/%d" % (ti + 1)
            self._unknown_keys(t, "template", w)
            for need in ("uuid", "template", "groups"):
                if need not in t:
                    raise Fail("Invalid tag \"%s\": the tag \"%s\" is missing." % (w, need))
            self._uuid(t["uuid"], w, seen_uuid)
            for g in t["groups"]:
                if g["name"] not in self.template_groups.values():
                    raise Fail("Invalid tag \"%s/groups\": template group \"%s\" not found." % (w, g["name"]))
            for mi, m in enumerate(t.get("macros", [])):
                if not MACRO_RE.match(m["macro"]):
                    raise Fail("Invalid tag \"%s/macros/%d\": a user macro is expected." % (w, mi + 1))
            ips, tps, rl = [], [], []
            for ri, r in enumerate(t.get("discovery_rules", [])):
                rw = "%s/discovery_rules/%d" % (w, ri + 1)
                self._unknown_keys(r, "rule", rw)
                self._uuid(r["uuid"], rw, seen_uuid)
                if r["type"] not in ITEM_TYPES:
                    raise Fail("Invalid tag \"%s/type\": unexpected value." % rw)
                if r["type"] == "SNMP_AGENT" and not r.get("snmp_oid", "").startswith("discovery["):
                    raise Fail("Invalid tag \"%s/snmp_oid\": discovery[] expected for SNMP discovery." % rw)
                keys = set()
                for ii, i in enumerate(r.get("item_prototypes", [])):
                    iw = "%s/item_prototypes/%d" % (rw, ii + 1)
                    self._unknown_keys(i, "item", iw)
                    self._uuid(i["uuid"], iw, seen_uuid)
                    if "{#" not in i["key"]:
                        raise Fail("Invalid tag \"%s/key\": an LLD macro is required in an item prototype key." % iw)
                    if i["key"] in keys:
                        raise Fail("Invalid tag \"%s\": item prototype \"%s\" already exists." % (iw, i["key"]))
                    keys.add(i["key"])
                    if i["value_type"] not in VALUE_TYPES:
                        raise Fail("Invalid tag \"%s/value_type\": unexpected value." % iw)
                    if i["type"] not in ITEM_TYPES:
                        raise Fail("Invalid tag \"%s/type\": unexpected value." % iw)
                    if i["type"] == "SNMP_AGENT":
                        if not i.get("snmp_oid"):
                            raise Fail("Invalid tag \"%s/snmp_oid\": cannot be empty." % iw)
                        d = i.get("delay", "")
                        if not (d.startswith("{$") or re.match(r'^\d+[smhdw]?$', d)):
                            raise Fail("Invalid tag \"%s/delay\": a time unit is expected." % iw)
                    if i["type"] == "DEPENDENT" and (not i.get("master_item") or "delay" in i):
                        raise Fail("Invalid tag \"%s\": dependent item needs master_item and no delay." % iw)
                    for pi, pre in enumerate(i.get("preprocessing", [])):
                        if pre["type"] not in PREPROC:
                            raise Fail("Invalid tag \"%s/preprocessing/%d/type\": unexpected value." % (iw, pi + 1))
                    ips.append(i)
                for i in r.get("item_prototypes", []):
                    if i["type"] == "DEPENDENT" and i["master_item"]["key"] not in keys:
                        raise Fail("Invalid tag \"%s\": master item \"%s\" does not exist." % (
                            rw, i["master_item"]["key"]))
                tnames = set()
                for ki, tg in enumerate(r.get("trigger_prototypes", [])):
                    kw = "%s/trigger_prototypes/%d" % (rw, ki + 1)
                    self._unknown_keys(tg, "trigger", kw)
                    self._uuid(tg["uuid"], kw, seen_uuid)
                    if tg["priority"] not in PRIORITIES:
                        raise Fail("Invalid tag \"%s/priority\": unexpected value." % kw)
                    refs = self._check_expression(tg["expression"], t["template"], keys, kw + "/expression")
                    if not any("{#" in k for k in refs):
                        raise Fail("Invalid tag \"%s\": trigger prototype must contain at least one item "
                                   "prototype." % kw)
                    if tg.get("recovery_mode") == "RECOVERY_EXPRESSION":
                        if not tg.get("recovery_expression"):
                            raise Fail("Invalid tag \"%s\": recovery_expression required." % kw)
                        self._check_expression(tg["recovery_expression"], t["template"], keys,
                                               kw + "/recovery_expression")
                    elif tg.get("recovery_expression"):
                        raise Fail("Invalid tag \"%s\": recovery_expression without RECOVERY_EXPRESSION mode." % kw)
                    ident = (tg["name"], tg["expression"], tg.get("recovery_expression", ""))
                    if ident in tnames:
                        raise Fail("Invalid tag \"%s\": trigger prototype already exists." % kw)
                    tnames.add(ident)
                    tps.append(tg)
                known = set((x["name"], x["expression"]) for x in r.get("trigger_prototypes", []))
                for tg in r.get("trigger_prototypes", []):
                    for d in tg.get("dependencies", []):
                        if (d["name"], d["expression"]) not in known:
                            raise Fail("Invalid tag \"trigger dependency\": trigger \"%s\" does not exist." % d["name"])
                rl.append(r)
            staged.append((t, rl))
        # ------- commit
        for t, rl in staged:
            tid = next((i for i, x in self.templates.items() if x["host"] == t["template"]), None)
            if tid is None:
                if not (rules.get("templates") or {}).get("createMissing"):
                    continue
                tid = self.nid()
                self.templates[tid] = {"templateid": tid, "hostid": tid, "host": t["template"],
                                       "description": t.get("description", "")}
            elif (rules.get("templates") or {}).get("updateExisting"):
                self.templates[tid]["description"] = t.get("description", "")
            else:
                continue
            self._replace_macros(tid, t.get("macros", []))
            self._sync(tid, t, rl, rules)
        self.last_import = doc
        return True

    def _uuid(self, u, where, seen):
        if not UUID_RE.match(u):
            raise Fail("Invalid tag \"%s/uuid\": must be a version 4 uuid in hex form." % where)
        if u in seen:
            raise Fail("Invalid tag \"%s/uuid\": uuid \"%s\" already used." % (where, u))
        seen.add(u)

    def _replace_macros(self, tid, macros):
        have = dict((m["macro"], k) for k, m in self.macros.items() if m["hostid"] == tid)
        for m in macros:
            if m["macro"] in have:
                self.macros[have[m["macro"]]]["value"] = m.get("value", "")
                self.macros[have[m["macro"]]]["description"] = m.get("description", "")
            else:
                self.add_macro(tid, m["macro"], m.get("value", ""), m.get("description", ""))

    def _sync(self, tid, t, rules_in, import_rules):
        delete_missing = (import_rules.get("discoveryRules") or {}).get("deleteMissing")
        want_rule_keys = set(r["key"] for r in rules_in)
        for rid, r in list(self.rules.items()):
            if r["hostid"] == tid and r["key_"] not in want_rule_keys and delete_missing:
                del self.rules[rid]
        for r in rules_in:
            rid = next((i for i, x in self.rules.items() if x["hostid"] == tid and x["key_"] == r["key"]), None)
            if rid is None:
                rid = self.nid()
            self.rules[rid] = {"itemid": rid, "hostid": tid, "key_": r["key"], "name": r["name"],
                               "delay": r["delay"], "snmp_oid": r.get("snmp_oid", ""),
                               "filter": copy.deepcopy(r.get("filter"))}
            for store, objs, ident in ((self.itemprotos, r.get("item_prototypes", []), "key"),
                                       (self.trigprotos, r.get("trigger_prototypes", []), "uuid")):
                want = set(o[ident] for o in objs)
                for oid, o in list(store.items()):
                    if o["hostid"] == tid and o["ruleid"] == rid:
                        marker = o["key_"] if store is self.itemprotos else o["uuid"]
                        if marker not in want:
                            del store[oid]
                for o in objs:
                    existing = next((i for i, x in store.items() if x["hostid"] == tid and x["ruleid"] == rid and
                                     (x["key_"] if store is self.itemprotos else x["uuid"]) == o[ident]), None)
                    oid = existing or self.nid()
                    if store is self.itemprotos:
                        store[oid] = {"itemid": oid, "hostid": tid, "ruleid": rid, "key_": o["key"],
                                      "name": o["name"], "snmp_oid": o.get("snmp_oid", ""),
                                      "delay": o.get("delay", "0"), "uuid": o["uuid"]}
                    else:
                        store[oid] = {"triggerid": oid, "hostid": tid, "ruleid": rid, "uuid": o["uuid"],
                                      "description": o["name"], "expression": o["expression"],
                                      "recovery_expression": o.get("recovery_expression", ""),
                                      "priority": str(PRIORITIES[o["priority"]]), "key_": o["uuid"]}

    def m_configuration_export(self, p):
        ids = (p.get("options") or {}).get("templates") or []
        for i in ids:
            if i not in self.templates:
                raise invalid("No permissions to referred object or it does not exist!")
        return json.dumps({"zabbix_export": {"version": "7.0", "templates": [
            {"template": self.templates[i]["host"], "description": self.templates[i]["description"]} for i in ids]}})

    # ---------------------------------------------------------------- actions
    def m_action_get(self, p):
        flt = (p.get("filter") or {}).get("name")
        out = []
        for a in self.actions.values():
            if flt is not None and a["name"] not in flt:
                continue
            r = {"actionid": a["actionid"], "name": a["name"], "eventsource": a["eventsource"],
                 "status": a["status"], "esc_period": a["esc_period"]}
            r["operations"] = copy.deepcopy(a["operations"]) if p.get("selectOperations") else None
            r["recovery_operations"] = copy.deepcopy(a["recovery_operations"]) if p.get(
                "selectRecoveryOperations") else None
            r["filter"] = copy.deepcopy(a["filter"]) if p.get("selectFilter") else None
            out.append(dict((k, v) for k, v in r.items() if v is not None))
        return out

    def _validate_action(self, a, creating):
        if creating:
            for need in ("name", "eventsource", "esc_period"):
                if need not in a:
                    raise invalid("Invalid parameter \"/\": the parameter \"%s\" is missing." % need)
        if "esc_period" in a and not re.match(r'^(\d+[smhdw]?|\{\$.+\})$', str(a["esc_period"])):
            raise invalid("Invalid parameter \"/esc_period\": a time unit is expected.")
        for c in (a.get("filter") or {}).get("conditions", []):
            if int(c["conditiontype"]) not in (0, 1, 2, 3, 4, 6, 13, 16, 25, 26, 27, 28):
                raise invalid("Invalid parameter \"/filter/conditions\": unexpected condition type.")
        for o in a.get("operations", []):
            if int(o["operationtype"]) != 0:
                continue
            if not o.get("opmessage") or not (o.get("opmessage_grp") or o.get("opmessage_usr")):
                raise invalid("Invalid parameter \"/operations\": no recipients for message operation.")
            for g in o.get("opmessage_grp", []):
                if g["usrgrpid"] not in self.usergroups:
                    raise invalid("No permissions to referred object or it does not exist!")
            mt = str(o["opmessage"].get("mediatypeid", "0"))
            if mt != "0" and mt not in self.mediatypes:
                raise invalid("No permissions to referred object or it does not exist!")
        for o in a.get("recovery_operations", []):
            if int(o["operationtype"]) not in (0, 1, 11):
                raise invalid("Invalid parameter \"/recovery_operations\": unexpected operation type.")

    def m_action_create(self, p):
        if any(a["name"] == p["name"] for a in self.actions.values()):
            raise invalid("Action \"%s\" already exists." % p["name"])
        self._validate_action(p, True)
        aid = self.nid()
        self.actions[aid] = dict(copy.deepcopy(p), actionid=aid, status=str(p.get("status", 0)),
                                 eventsource=str(p["eventsource"]),
                                 operations=copy.deepcopy(p.get("operations", [])),
                                 recovery_operations=copy.deepcopy(p.get("recovery_operations", [])),
                                 filter=copy.deepcopy(p.get("filter", {"conditions": []})))
        return {"actionids": [aid]}

    def m_action_update(self, p):
        if p.get("actionid") not in self.actions:
            raise invalid("No permissions to referred object or it does not exist!")
        self._validate_action(p, False)
        a = self.actions[p["actionid"]]
        for k, v in p.items():
            if k in ("actionid",):
                continue
            a[k] = str(v) if k == "status" else copy.deepcopy(v)
        return {"actionids": [p["actionid"]]}

    def m_action_delete(self, p):
        for i in p:
            self.actions.pop(i, None)
        return {"actionids": list(p)}

    def m_task_create(self, p):
        for t in p:
            if int(t["type"]) != 6 or t["request"]["itemid"] not in self.rules and \
                    t["request"]["itemid"] not in self.items:
                raise invalid("Invalid parameter \"/1/request/itemid\": object does not exist or is not a "
                              "discovery rule.")
            self.tasks.append(t)
        return {"taskids": [self.nid() for _ in p]}
