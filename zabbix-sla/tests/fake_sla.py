"""In-memory model of the Zabbix 7.0 service / SLA / item / trigger API, used as a *transport* in tests.

Built on the alerting project's MockZabbix (hosts, global macros, auth, read-only users, error shapes) which is loaded by path so
the two projects stay independent. Enforced here, because the real server enforces it: string ids, parameter validation, unknown
child ids, service cycles, SLO range, excluded-downtime ordering, calculated-item formula references, trigger expression references,
duplicate item keys per host, replace-semantics of tags / problem_tags / children on update.

It is an approximation written from the documentation, not a certified clone: every behaviour here that has not been observed on a
live 7.0.30 server is listed in docs/ACCEPTANCE-MATRIX.md as a live acceptance test.
"""
import copy
import importlib.util
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.normpath(os.path.join(_HERE, "..", "..", "zabbix-alerting", "tests", "fake_zabbix.py"))
_spec = importlib.util.spec_from_file_location("alerting_fake_zabbix", _SRC)
_fz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fz)
Fail, invalid, MockZabbix = _fz.Fail, _fz.invalid, _fz.MockZabbix

REF = re.compile(r"/([^/(),]+)/([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)")
SELF_REF = re.compile(r"//([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)")


class SlaMock(MockZabbix):
    def __init__(self, token="test-token", **kw):
        MockZabbix.__init__(self, token=token, **kw)
        self.services = {}
        self.slas = {}
        self.triggers = {}
        self.sli_data = {}          # (slaid, serviceid) -> [ {uptime, downtime, sli, error_budget, excluded_downtime} per period ]
        self.sli_periods = []       # [{"period_from","period_to"}]
        self.fail_on = {}           # method -> n : the n-th successful-looking call of that method fails (failure injection)
        self._counts = {}
        self.trigger_state = {}     # triggerid -> {"error": "", "state": "0"}
        self.ro_methods = set()

    def set_identity(self, env_name):
        gid = self.nid()
        self.gmacros[gid] = {"globalmacroid": gid, "macro": "{$NETOPS.ENVIRONMENT}", "value": env_name, "description": "managed_by=zabbix-alerting-as-code"}

    def _dispatch(self, method, params, authenticated):
        if method in self.fail_on:
            self._counts[method] = self._counts.get(method, 0) + 1
            if self._counts[method] == self.fail_on[method]:
                raise Fail("injected failure for %s" % method)
        return MockZabbix._dispatch(self, method, params, authenticated)

    @staticmethod
    def is_write(method):
        return MockZabbix.is_write(method)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _tagrows(rows, what="tags"):
        out = []
        for r in rows or []:
            if not isinstance(r, dict) or not r.get("tag"):
                raise invalid("Invalid parameter \"/1/%s\": a tag name is required." % what)
            out.append({"tag": str(r["tag"]), "value": str(r.get("value", ""))})
        keys = [(t["tag"], t["value"]) for t in out]
        if len(set(keys)) != len(keys):
            raise invalid("Invalid parameter \"/1/%s\": value (tag, value)=(%s) already exists." % (what, keys[0][0]))
        return out

    @staticmethod
    def _cond(rows, what):
        out = []
        for r in rows or []:
            if not r.get("tag"):
                raise invalid("Invalid parameter \"/1/%s\": a tag name is required." % what)
            op = int(r.get("operator", 0))
            if op not in (0, 2):
                raise invalid("Invalid parameter \"/1/%s/operator\": value must be one of 0, 2." % what)
            out.append({"tag": r["tag"], "operator": str(op), "value": str(r.get("value", ""))})
        return out

    # ------------------------------------------------------------------ services
    def _ancestors_would_cycle(self, sid, kids):
        # sid may not be reachable from any of its new children's descendants
        seen, stack = set(), list(kids)
        while stack:
            x = stack.pop()
            if x == sid:
                return True
            if x in seen:
                continue
            seen.add(x)
            stack.extend(self.services[x]["children"])
        return False

    def _check_service(self, p, creating):
        if creating and not p.get("name"):
            raise invalid("Invalid parameter \"/1\": the parameter \"name\" is missing.")
        if "algorithm" in p and int(p["algorithm"]) not in (0, 1, 2):
            raise invalid("Invalid parameter \"/1/algorithm\": value must be one of 0, 1, 2.")
        if creating and "algorithm" not in p:
            raise invalid("Invalid parameter \"/1\": the parameter \"algorithm\" is missing.")
        for c in p.get("children") or []:
            if c["serviceid"] not in self.services:
                raise invalid("No permissions to referred object or it does not exist!")

    def m_service_create(self, p):
        items = p if isinstance(p, list) else [p]
        ids = []
        for s in items:
            self._check_service(s, True)
            sid = self.nid()
            self.services[sid] = {"serviceid": sid, "name": s["name"], "algorithm": str(int(s["algorithm"])), "description": s.get("description", ""),
                                  "tags": self._tagrows(s.get("tags")), "problem_tags": self._cond(s.get("problem_tags"), "problem_tags"),
                                  "children": [c["serviceid"] for c in s.get("children") or []]}
            ids.append(sid)
        return {"serviceids": ids}

    def m_service_update(self, p):
        items = p if isinstance(p, list) else [p]
        for s in items:
            if s.get("serviceid") not in self.services:
                raise invalid("No permissions to referred object or it does not exist!")
            self._check_service(s, False)
            if "children" in s:
                kids = [c["serviceid"] for c in s["children"]]
                if len(set(kids)) != len(kids):
                    raise invalid("Invalid parameter \"/1/children\": duplicate service.")
                if self._ancestors_would_cycle(s["serviceid"], kids):
                    raise invalid("Cannot add dependency: service \"%s\" would become its own ancestor." % self.services[s["serviceid"]]["name"])
        for s in items:
            row = self.services[s["serviceid"]]
            for k in ("name", "description"):
                if k in s:
                    row[k] = s[k]
            if "algorithm" in s:
                row["algorithm"] = str(int(s["algorithm"]))
            if "tags" in s:
                row["tags"] = self._tagrows(s["tags"])
            if "problem_tags" in s:
                row["problem_tags"] = self._cond(s["problem_tags"], "problem_tags")
            if "children" in s:
                row["children"] = [c["serviceid"] for c in s["children"]]
        return {"serviceids": [s["serviceid"] for s in items]}

    def m_service_delete(self, p):
        ids = p if isinstance(p, list) else [p]
        for i in ids:
            if i not in self.services:
                raise invalid("No permissions to referred object or it does not exist!")
        for i in ids:
            del self.services[i]
        for s in self.services.values():
            s["children"] = [c for c in s["children"] if c in self.services]
        return {"serviceids": ids}

    def m_service_get(self, p):
        rows = []
        flt = p.get("filter") or {}
        for s in self.services.values():
            if p.get("serviceids") and s["serviceid"] not in p["serviceids"]:
                continue
            if "name" in flt and s["name"] not in (flt["name"] if isinstance(flt["name"], list) else [flt["name"]]):
                continue
            base = dict((k, v) for k, v in s.items() if k not in ("tags", "problem_tags", "children"))
            base["status"] = str(self._status(s["serviceid"]))
            r = self._out(base, p.get("output"))
            if p.get("selectTags"):
                r["tags"] = copy.deepcopy(s["tags"])
            if p.get("selectProblemTags"):
                r["problem_tags"] = copy.deepcopy(s["problem_tags"])
            if p.get("selectChildren"):
                r["children"] = [{"serviceid": c} for c in s["children"]]
            if p.get("selectParents"):
                r["parents"] = [{"serviceid": q["serviceid"]} for q in self.services.values() if s["serviceid"] in q["children"]]
            rows.append(r)
        return rows

    # ------------------------------------------------------------------ SLA
    def _check_sla(self, p, creating):
        if creating:
            for k in ("name", "period", "slo", "effective_date", "timezone"):
                if k not in p:
                    raise invalid("Invalid parameter \"/1\": the parameter \"%s\" is missing." % k)
        if "slo" in p and not (0 <= float(p["slo"]) <= 100):
            raise invalid("Invalid parameter \"/1/slo\": a number between 0 and 100 is expected.")
        if "period" in p and int(p["period"]) not in (0, 1, 2, 3, 4):
            raise invalid("Invalid parameter \"/1/period\": value must be one of 0, 1, 2, 3, 4.")
        if creating and not p.get("service_tags"):
            raise invalid("Invalid parameter \"/1/service_tags\": cannot be empty.")
        for e in p.get("excluded_downtimes") or []:
            if int(e["period_from"]) >= int(e["period_to"]):
                raise invalid("Invalid parameter \"/1/excluded_downtimes\": period_to must be greater than period_from.")
        for r in p.get("schedule") or []:
            if not (0 <= int(r["period_from"]) < int(r["period_to"]) <= 604800):
                raise invalid("Invalid parameter \"/1/schedule\": invalid period.")

    def _store_sla(self, row, p):
        for k in ("name", "description", "timezone"):
            if k in p:
                row[k] = p[k]
        for k in ("period", "status", "effective_date"):
            if k in p:
                row[k] = str(int(p[k]))
        if "slo" in p:
            row["slo"] = str(float(p["slo"]))
        if "service_tags" in p:
            row["service_tags"] = self._cond(p["service_tags"], "service_tags")
        if "schedule" in p:
            row["schedule"] = [{"period_from": str(int(r["period_from"])), "period_to": str(int(r["period_to"]))} for r in p["schedule"]]
        if "excluded_downtimes" in p:
            row["excluded_downtimes"] = [{"name": e["name"], "period_from": str(int(e["period_from"])), "period_to": str(int(e["period_to"]))} for e in p["excluded_downtimes"]]

    def m_sla_create(self, p):
        items = p if isinstance(p, list) else [p]
        ids = []
        for s in items:
            self._check_sla(s, True)
            if any(x["name"] == s["name"] for x in self.slas.values()):
                raise invalid("SLA \"%s\" already exists." % s["name"])
            sid = self.nid()
            row = {"slaid": sid, "status": "1", "description": "", "schedule": [], "excluded_downtimes": [], "service_tags": []}
            self._store_sla(row, s)
            self.slas[sid] = row
            ids.append(sid)
        return {"slaids": ids}

    def m_sla_update(self, p):
        items = p if isinstance(p, list) else [p]
        for s in items:
            if s.get("slaid") not in self.slas:
                raise invalid("No permissions to referred object or it does not exist!")
            self._check_sla(s, False)
        for s in items:
            self._store_sla(self.slas[s["slaid"]], s)
        return {"slaids": [s["slaid"] for s in items]}

    def m_sla_delete(self, p):
        ids = p if isinstance(p, list) else [p]
        for i in ids:
            if i not in self.slas:
                raise invalid("No permissions to referred object or it does not exist!")
        for i in ids:
            del self.slas[i]
        return {"slaids": ids}

    def m_sla_get(self, p):
        rows = []
        for s in self.slas.values():
            if p.get("slaids") and s["slaid"] not in p["slaids"]:
                continue
            base = dict((k, v) for k, v in s.items() if k not in ("service_tags", "schedule", "excluded_downtimes"))
            r = self._out(base, p.get("output"))
            if p.get("selectServiceTags"):
                r["service_tags"] = copy.deepcopy(s["service_tags"])
            if p.get("selectSchedule"):
                r["schedule"] = copy.deepcopy(s["schedule"])
            if p.get("selectExcludedDowntimes"):
                r["excluded_downtimes"] = copy.deepcopy(s["excluded_downtimes"])
            rows.append(r)
        return rows

    def m_sla_getsli(self, p):
        if p.get("slaid") not in self.slas:
            raise invalid("No permissions to referred object or it does not exist!")
        sids = p.get("serviceids") or sorted(k[1] for k in self.sli_data if k[0] == p["slaid"])
        periods = self.sli_periods
        sli = []
        for i in range(len(periods)):
            sli.append([copy.deepcopy(self.sli_data.get((p["slaid"], s), [{}] * len(periods))[i]) if (p["slaid"], s) in self.sli_data else
                        {"uptime": 0, "downtime": 0, "sli": -1, "error_budget": 0, "excluded_downtime": 0} for s in sids])
        return {"periods": copy.deepcopy(periods), "serviceids": list(sids), "sli": sli}

    # ------------------------------------------------------------------ items / triggers
    @staticmethod
    def _tag_match(tags, filters, evaltype=0):
        if not filters:
            return True
        res = []
        for f in filters:
            has = [t for t in tags if t["tag"] == f["tag"]]
            op = int(f.get("operator", 0))
            if op == 4:
                res.append(bool(has))
            elif op == 5:
                res.append(not has)
            elif op == 1:
                res.append(any(t["value"] == f.get("value", "") for t in has))
            elif op == 0:
                res.append(any(f.get("value", "") in t["value"] for t in has))
            elif op == 3:
                res.append(any(t["value"] != f.get("value", "") for t in has))
            else:
                res.append(any(f.get("value", "") not in t["value"] for t in has))
        return all(res) if int(evaltype) == 0 else any(res)

    def _host_of_item(self, iid):
        return self.hosts[self.items[iid]["hostid"]]

    def m_item_get(self, p):
        rows = []
        flt = p.get("filter") or {}
        for it in self.items.values():
            if p.get("hostids") and it["hostid"] not in p["hostids"]:
                continue
            if "key_" in flt and it["key_"] not in (flt["key_"] if isinstance(flt["key_"], list) else [flt["key_"]]):
                continue
            if not self._tag_match(it.get("tags", []), p.get("tags"), p.get("evaltype", 0)):
                continue
            r = self._out(dict((k, v) for k, v in it.items() if k != "tags"), p.get("output"))
            if p.get("selectTags"):
                r["tags"] = copy.deepcopy(it.get("tags", []))
            if p.get("selectHosts"):
                h = self.hosts[it["hostid"]]
                r["hosts"] = [{"hostid": h["hostid"], "host": h["host"]}]
            rows.append(r)
        return rows

    def _check_item(self, p, creating, existing=None):
        hostid = p.get("hostid") or (existing or {}).get("hostid")
        if hostid not in self.hosts:
            raise invalid("No permissions to referred object or it does not exist!")
        typ = int(p.get("type", (existing or {}).get("type", 0)))
        if creating:
            for k in ("name", "key_", "type", "value_type", "delay"):
                if k not in p:
                    raise invalid("Invalid parameter \"/1\": the parameter \"%s\" is missing." % k)
            if any(i["hostid"] == hostid and i["key_"] == p["key_"] for i in self.items.values()):
                raise invalid("Item with key \"%s\" already exists on \"%s\"." % (p["key_"], self.hosts[hostid]["host"]))
        if typ == 15:
            formula = p.get("params", (existing or {}).get("params", ""))
            if not formula:
                raise invalid("Invalid parameter \"/1/params\": cannot be empty.")
            keys = set(i["key_"] for i in self.items.values() if i["hostid"] == hostid)
            for m in SELF_REF.finditer(formula):
                if m.group(1) not in keys:
                    raise invalid("Invalid parameter \"/1/params\": item \"%s\" does not exist on host \"%s\"." % (m.group(1), self.hosts[hostid]["host"]))
        if typ == 3 and "interfaceid" in p:
            if not any(i.get("interfaceid") == p["interfaceid"] for i in self.hosts[hostid].get("interfaces", [])) and p["interfaceid"] not in ("1", "10001"):
                pass            # interface ids are not modelled for hosts seeded without them
        return typ

    def m_item_create(self, p):
        items = p if isinstance(p, list) else [p]
        ids = []
        for it in items:
            self._check_item(it, True)
            iid = self.nid()
            self.items[iid] = {"itemid": iid, "hostid": it["hostid"], "key_": it["key_"], "name": it["name"], "type": str(int(it["type"])),
                               "value_type": str(int(it["value_type"])), "delay": it["delay"], "params": it.get("params", ""),
                               "tags": self._tagrows(it.get("tags")), "status": "0"}
            ids.append(iid)
        return {"itemids": ids}

    def m_item_update(self, p):
        items = p if isinstance(p, list) else [p]
        for it in items:
            if it.get("itemid") not in self.items:
                raise invalid("No permissions to referred object or it does not exist!")
            self._check_item(it, False, self.items[it["itemid"]])
        for it in items:
            row = self.items[it["itemid"]]
            for k in ("name", "delay", "params"):
                if k in it:
                    row[k] = it[k]
            for k in ("type", "value_type"):
                if k in it:
                    row[k] = str(int(it[k]))
            if "tags" in it:
                row["tags"] = self._tagrows(it["tags"])
        return {"itemids": [i["itemid"] for i in items]}

    def m_item_delete(self, p):
        ids = p if isinstance(p, list) else [p]
        for i in ids:
            if i not in self.items:
                raise invalid("No permissions to referred object or it does not exist!")
        for t in self.triggers.values():
            used = set(m.group(2) for m in REF.finditer(t["expression"]))
            for i in ids:
                if self.items[i]["key_"] in used and self.hosts[self.items[i]["hostid"]]["host"] in [m.group(1) for m in REF.finditer(t["expression"])]:
                    raise invalid("Cannot delete item \"%s\": it is used in trigger \"%s\"." % (self.items[i]["key_"], t["description"]))
        for i in ids:
            del self.items[i]
        return {"itemids": ids}

    def _check_trigger_expression(self, expr):
        hosts = {}
        for m in REF.finditer(expr):
            host, key = m.group(1), m.group(2)
            hid = next((h["hostid"] for h in self.hosts.values() if h["host"] == host), None)
            if hid is None:
                raise invalid("Invalid parameter \"/1/expression\": host \"%s\" does not exist." % host)
            if not any(i["hostid"] == hid and i["key_"] == key for i in self.items.values()):
                raise invalid("Invalid parameter \"/1/expression\": item \"%s\" does not exist on host \"%s\"." % (key, host))
            hosts[host] = hid
        if not hosts:
            raise invalid("Invalid parameter \"/1/expression\": trigger expression must contain at least one /host/key reference.")
        return list(hosts.values())

    def m_trigger_create(self, p):
        items = p if isinstance(p, list) else [p]
        ids = []
        for t in items:
            for k in ("description", "expression"):
                if k not in t:
                    raise invalid("Invalid parameter \"/1\": the parameter \"%s\" is missing." % k)
            hostids = self._check_trigger_expression(t["expression"])
            if any(x["description"] == t["description"] and x["hostids"] == hostids for x in self.triggers.values()):
                raise invalid("Trigger \"%s\" already exists on the host." % t["description"])
            tid = self.nid()
            self.triggers[tid] = {"triggerid": tid, "description": t["description"], "expression": t["expression"], "priority": str(int(t.get("priority", 0))),
                                  "tags": self._tagrows(t.get("tags")), "hostids": hostids, "status": "0"}
            self.trigger_state[tid] = {"error": "", "state": "0"}
            ids.append(tid)
        return {"triggerids": ids}

    def m_trigger_update(self, p):
        items = p if isinstance(p, list) else [p]
        for t in items:
            if t.get("triggerid") not in self.triggers:
                raise invalid("No permissions to referred object or it does not exist!")
            if "expression" in t:
                self._check_trigger_expression(t["expression"])
        for t in items:
            row = self.triggers[t["triggerid"]]
            for k in ("description", "expression"):
                if k in t:
                    row[k] = t[k]
            if "priority" in t:
                row["priority"] = str(int(t["priority"]))
            if "tags" in t:
                row["tags"] = self._tagrows(t["tags"])
        return {"triggerids": [t["triggerid"] for t in items]}

    def m_trigger_delete(self, p):
        ids = p if isinstance(p, list) else [p]
        for i in ids:
            if i not in self.triggers:
                raise invalid("No permissions to referred object or it does not exist!")
        for i in ids:
            del self.triggers[i]
            self.trigger_state.pop(i, None)
        return {"triggerids": ids}

    def m_trigger_get(self, p):
        rows = []
        for t in self.triggers.values():
            if p.get("hostids") and not set(p["hostids"]) & set(t["hostids"]):
                continue
            if not self._tag_match(t["tags"], p.get("tags"), p.get("evaltype", 0)):
                continue
            base = dict((k, v) for k, v in t.items() if k not in ("tags", "hostids"))
            base.update(self.trigger_state.get(t["triggerid"], {}))
            r = self._out(base, p.get("output"))
            if p.get("selectTags"):
                r["tags"] = copy.deepcopy(t["tags"])
            if p.get("selectHosts"):
                r["hosts"] = [{"hostid": h, "host": self.hosts[h]["host"]} for h in t["hostids"]]
            rows.append(r)
        return rows

    # ------------------------------------------------------------------ snapshots for tests
    def sla_snapshot(self):
        return copy.deepcopy((self.services, self.slas, self.items, self.triggers))


def _add_host_with_interfaceid(self, *a, **k):
    hid = MockZabbix.add_host(self, *a, **k)
    for itf in self.hosts[hid]["interfaces"]:
        itf.setdefault("interfaceid", self.nid())
    return hid


SlaMock.add_host = _add_host_with_interfaceid


def _dash_mixin():
    def m_dashboard_create(self, p):
        for k in ("name", "pages"):
            if k not in p:
                raise invalid("Invalid parameter \"/1\": the parameter \"%s\" is missing." % k)
        if any(d["name"] == p["name"] for d in self.dashboards.values()):
            raise invalid("Dashboard \"%s\" already exists." % p["name"])
        for pg in p["pages"]:
            for w in pg.get("widgets", []):
                for k in ("type", "x", "y", "width", "height"):
                    if k not in w:
                        raise invalid("Invalid parameter \"/1/pages/1/widgets/1\": the parameter \"%s\" is missing." % k)
                if not (0 <= int(w["x"]) < 24 and 0 <= int(w["y"]) < 64 and 1 <= int(w["width"]) <= 24 and 1 <= int(w["height"]) <= 32 and int(w["x"]) + int(w["width"]) <= 24):
                    raise invalid("Invalid parameter \"/1/pages/1/widgets/1\": widget outside the dashboard grid.")
        did = self.nid()
        self.dashboards[did] = {"dashboardid": did, "name": p["name"], "display_period": str(p.get("display_period", 30)), "pages": copy.deepcopy(p["pages"])}
        return {"dashboardids": [did]}

    def m_dashboard_update(self, p):
        if p.get("dashboardid") not in self.dashboards:
            raise invalid("No permissions to referred object or it does not exist!")
        row = self.dashboards[p["dashboardid"]]
        for k in ("name", "pages"):
            if k in p:
                row[k] = copy.deepcopy(p[k])
        if "display_period" in p:
            row["display_period"] = str(p["display_period"])
        return {"dashboardids": [p["dashboardid"]]}

    def m_dashboard_delete(self, p):
        for i in p:
            self.dashboards.pop(i, None)
        return {"dashboardids": list(p)}

    def m_dashboard_get(self, p):
        rows = []
        s = (p.get("search") or {}).get("name")
        for d in self.dashboards.values():
            if s is not None and not d["name"].startswith(s):
                continue
            r = self._out(dict((k, v) for k, v in d.items() if k != "pages"), p.get("output"))
            if p.get("selectPages"):
                r["pages"] = copy.deepcopy(d["pages"])
            rows.append(r)
        return rows
    return m_dashboard_create, m_dashboard_update, m_dashboard_delete, m_dashboard_get


(SlaMock.m_dashboard_create, SlaMock.m_dashboard_update, SlaMock.m_dashboard_delete, SlaMock.m_dashboard_get) = _dash_mixin()
SlaMock.dashboards = None
_orig_init = SlaMock.__init__


def _init(self, *a, **k):
    _orig_init(self, *a, **k)
    self.dashboards = {}


SlaMock.__init__ = _init


def _status(self, sid, memo=None):
    """Service status from firing triggers (Zabbix documented algorithms); self.semantics decides how several problem tags combine."""
    from slaas import evaluator
    memo = {} if memo is None else memo
    if sid in memo:
        return memo[sid]
    s = self.services[sid]
    problems = [(dict((t["tag"], t["value"]) for t in tr["tags"]), int(tr["priority"])) for tr in self.triggers.values()
                if tr["description"].startswith("[NETOPS-SLA-ACC]") or tr["triggerid"] in self.firing]
    own = [sev for tags, sev in problems if evaluator.problem_matches([(t["tag"], int(t["operator"]), t["value"]) for t in s["problem_tags"]], tags, self.semantics)]
    kids = [self._status(c, memo) for c in s["children"] if c in self.services]
    algo = int(s["algorithm"])
    child = -1
    if kids and algo == 1:
        child = max(kids) if all(k != -1 for k in kids) else -1
    elif kids and algo == 2:
        child = max(kids)
    memo[sid] = max([child] + own) if own or child != -1 else -1
    return memo[sid]


SlaMock._status = _status
SlaMock.semantics = "and"
SlaMock.firing = frozenset()
