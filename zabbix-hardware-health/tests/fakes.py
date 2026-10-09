"""In-memory Zabbix 7.0 JSON-RPC server used as the urllib transport. Only what the hardware tool calls; every call is logged."""
import copy
import io
import json

NOW = 1_000_000


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeZabbix(object):
    def __init__(self, version="7.0.30", identity="lab"):
        self.version = version
        self.identity = identity
        self.hosts = {}          # hostid -> dict(host, status, templates, inventory, interfaces)
        self.items = {}          # hostid -> [item dicts]
        self.triggers = {}       # hostid -> [trigger dicts]
        self.actions = {}        # actionid -> dict
        self.usergroups = [{"usrgrpid": "7", "name": "Network Operations"}]
        self.mediatypes = [{"mediatypeid": "3", "name": "Telegram", "status": "0"}]
        self.calls = []
        self.hostgroups = {}     # groupid -> name
        self.users = []          # {"userid", "usrgrpids": [...], "medias": [...]}
        self.events = []         # {"eventid","r_eventid","objectid","value","clock"}
        self.alerts = []         # alert.get rows
        self._n = 100

    # ---------------------------------------------------------------- seeding
    def nid(self):
        self._n += 1
        return str(self._n)

    def add_host(self, name, templates=(), inventory=None, interfaces=None, status="0"):
        hid = self.nid()
        self.hosts[hid] = {"hostid": hid, "host": name, "status": status, "templates": list(templates), "inventory": inventory or {},
                           "interfaces": interfaces if interfaces is not None else [{"interfaceid": self.nid(), "type": "2", "main": "1", "available": "1", "error": ""}]}
        self.items[hid] = []
        self.triggers[hid] = []
        return hid

    def add_item(self, hostid, key, name=None, lastvalue="", lastclock=NOW - 60, status="0", state="0", snmp_oid="", units="", valuemap=None,
                 preprocessing=(), master=None, flags="0", error="", value_type="3"):
        iid = self.nid()
        self.items[hostid].append({"itemid": iid, "name": name or key, "key_": key, "type": "20", "value_type": value_type, "units": units,
                                   "snmp_oid": snmp_oid, "lastvalue": lastvalue, "lastclock": str(lastclock), "delay": "1m", "status": status,
                                   "state": state, "error": error, "flags": flags, "master_itemid": master or "0", "valuemapid": "0",
                                   "valuemap": valuemap or [], "preprocessing": list(preprocessing), "tags": []})
        return iid

    def add_trigger(self, hostid, description, itemids, tags=(), status="0", priority="4", value="0"):
        tid = self.nid()
        self.triggers[hostid].append({"triggerid": tid, "description": description, "expression": "last(/h/x)=1", "status": status, "priority": priority,
                                      "value": value, "state": "0", "error": "", "flags": "0", "tags": [{"tag": k, "value": v} for k, v in tags],
                                      "items": [{"itemid": i, "key_": "k"} for i in itemids]})
        return tid

    def add_action(self, name, flt, status="0"):
        aid = self.nid()
        self.actions[aid] = {"actionid": aid, "name": name, "eventsource": "0", "status": status, "esc_period": "1h", "filter": flt,
                             "operations": [], "recovery_operations": []}
        return aid

    # ---------------------------------------------------------------- transport
    def __call__(self, req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        method, params = payload["method"], payload.get("params") or {}
        self.calls.append((method, "Authorization" in req.headers or "authorization" in req.headers))
        try:
            result = self.dispatch(method, params)
            body = {"jsonrpc": "2.0", "result": result, "id": payload["id"]}
        except KeyError as exc:
            body = {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found.", "data": str(exc)}, "id": payload["id"]}
        return _Resp(json.dumps(body).encode("utf-8"))

    def methods(self):
        return [m for m, _ in self.calls]

    def writes(self):
        return [m for m in self.methods() if m.endswith((".create", ".update", ".delete"))]

    def dispatch(self, method, p):
        if method == "apiinfo.version":
            return self.version
        if method == "usermacro.get":
            return [] if self.identity is None else [{"macro": "{$NETOPS.ENVIRONMENT}", "value": self.identity}]
        if method == "host.get":
            flt = (p.get("filter") or {}).get("host")
            rows = []
            for h in self.hosts.values():
                if flt and h["host"] not in flt:
                    continue
                r = {"hostid": h["hostid"], "host": h["host"], "status": h["status"]}
                if "selectParentTemplates" in p:
                    r["parentTemplates"] = [{"name": t} for t in h["templates"]]
                if "selectInventory" in p:
                    r["inventory"] = dict(h["inventory"]) if h["inventory"] else []
                if "selectInterfaces" in p:
                    r["interfaces"] = copy.deepcopy(h["interfaces"])
                rows.append(r)
            return rows
        if method == "item.get":
            rows = []
            for hid in (p.get("hostids") or list(self.items)):
                if not p.get("hostids") and not (p.get("filter") or {}).get("key_"):
                    continue
                flt = (p.get("filter") or {}).get("key_")
                for it in self.items.get(hid, []):
                    if flt and it["key_"] != flt:
                        continue
                    r = dict((k, v) for k, v in it.items() if k in (p.get("output") or it) or k in ("valuemap", "preprocessing", "tags"))
                    if "selectValueMap" not in p:
                        r.pop("valuemap", None)
                    if "selectPreprocessing" not in p:
                        r.pop("preprocessing", None)
                    if "selectTags" not in p:
                        r.pop("tags", None)
                    rows.append(copy.deepcopy(r))
            return rows
        if method == "trigger.get":
            rows = []
            for hid in (p.get("hostids") or list(self.triggers)):
                rows += copy.deepcopy(self.triggers.get(hid, []))
            sr = (p.get("search") or {}).get("description")
            if sr:
                rows = [t for t in rows if t["description"].startswith(sr)]
            for tg in p.get("tags") or []:
                if int(tg.get("operator", 0)) == 4:
                    rows = [t for t in rows if any(x["tag"] == tg["tag"] for x in t.get("tags", []))]
            return rows
        if method == "hostgroup.get":
            names = (p.get("filter") or {}).get("name")
            return [{"groupid": g, "name": n} for g, n in self.hostgroups.items() if not names or n in names]
        if method == "user.get":
            return [dict(userid=u["userid"], medias=copy.deepcopy(u["medias"])) for u in self.users if set(u["usrgrpids"]) & set(p.get("usrgrpids", []))]
        if method == "event.get":
            ids = p.get("objectids") or []
            return [dict(e) for e in self.events if e["objectid"] in ids]
        if method == "alert.get":
            rows = [dict(a) for a in self.alerts if a["actionid"] in p.get("actionids", [a["actionid"]])]
            if p.get("eventids"):
                rows = [a for a in rows if a["eventid"] in p["eventids"]]
            return rows
        if method == "mediatype.get":
            names = (p.get("filter") or {}).get("name")
            return [m for m in self.mediatypes if not names or m["name"] in names]
        if method == "usergroup.get":
            names = (p.get("filter") or {}).get("name")
            return [g for g in self.usergroups if not names or g["name"] in names]
        if method == "action.get":
            rows = list(self.actions.values())
            nm = (p.get("filter") or {}).get("name")
            if nm:
                rows = [a for a in rows if a["name"] in nm]
            sr = (p.get("search") or {}).get("name")
            if sr:
                rows = [a for a in rows if a["name"].startswith(sr)]
            return copy.deepcopy(rows)
        if method == "action.create":
            aid = self.nid()
            a = copy.deepcopy(p)
            a["actionid"] = aid
            self.actions[aid] = self._norm_action(a)
            return {"actionids": [aid]}
        if method == "action.update":
            a = self.actions[p["actionid"]]
            a.update(self._norm_action(copy.deepcopy(p)))
            return {"actionids": [p["actionid"]]}
        if method == "action.delete":
            for i in p:
                self.actions.pop(i, None)
            return {"actionids": list(p)}
        raise KeyError(method)

    @staticmethod
    def _norm_action(a):
        a["status"] = str(a.get("status", 0))
        return a
