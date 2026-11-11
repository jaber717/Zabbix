"""MockZabbix extended with the read surface discovery uses: stock-style interface item sets with
freshness, triggers, host groups/tags, interface availability, users/media and permission denials.
Writes still go through MockZabbix (same enforcement), so the real apply path can run in the same test.
This is a model written from the Zabbix 7.0 API documentation, not a recording of a production server.
"""
import copy

from tests.fake_zabbix import Fail, MockZabbix, invalid

NOW = 1_800_000_000


class DiscoveryZabbix(MockZabbix):
    def __init__(self, **kw):
        MockZabbix.__init__(self, **kw)
        self.groups = {"2": "Network devices", "3": "Servers"}
        self.triggers = {}
        self.users = {}
        self.deny = set()          # methods that answer "No permissions" (least-privilege token)
        self.fail_on = {}          # method -> exception raised (unexpected API failure)
        self.events = []           # [{eventid, objectid, value, clock, alerts:[{actionid,status,alerttype,p_eventid}]}]

    # ------------------------------------------------------------------ builders
    def add_device(self, name, ports=(), snmp=True, status=0, available="1", groups=("2",), tags=(), templates=(),
                   error=""):
        hid = MockZabbix.add_host(self, name, interfaces=(), snmp=snmp, status=status, templates=templates)
        h = self.hosts[hid]
        h["interfaces"][0].update({"available": available if snmp else "0", "error": error})
        h["groupids"] = list(groups)
        h["tags"] = [{"tag": k, "value": v} for k, v in tags]
        for spec in ports:
            self.add_port(hid, **spec)
        return hid

    def add_port(self, hostid, name, index, alias="", oper="1", speed=10 ** 9, age=30, state="0", delay="1m",
                 status="0", error="", template="stock", kinds=("status", "in", "out", "speed")):
        keys = {"status": "net.if.status[ifOperStatus.%s]", "in": "net.if.in[ifHCInOctets.%s]",
                "out": "net.if.out[ifHCOutOctets.%s]", "speed": "net.if.speed[ifHighSpeed.%s]",
                "type": "net.if.type[ifType.%s]"}
        values = {"status": oper, "in": "1000", "out": "1000", "speed": str(speed), "type": "6"}
        ids = {}
        for k in kinds:
            iid = self.nid()
            tags = [{"tag": "component", "value": "network"}, {"tag": "interface", "value": name}]
            if alias:
                tags.append({"tag": "description", "value": alias})
            self.items[iid] = {"itemid": iid, "hostid": hostid, "key_": keys[k] % index,
                               "name": "Interface %s(%s): %s" % (name, alias, k), "tags": tags,
                               "lastvalue": values[k], "lastclock": str(NOW - age if age is not None else 0),
                               "state": state if k == "status" else "0", "status": status, "error": error,
                               "delay": delay, "value_type": "3"}
            ids[k] = iid
        return ids

    def add_netops_items(self, hostid, name, index):
        """What the NETOPS template's LLD creates on a host after deploy (the mock does not run LLD).
        Returns {kind: itemid} for oper/in/out/speed."""
        ids = {}
        for kind in ("oper", "in", "out", "speed"):
            iid = self.nid()
            self.items[iid] = {"itemid": iid, "hostid": hostid, "key_": "netops.if.%s[%s]" % (kind, index),
                               "name": "x", "tags": [{"tag": "interface", "value": name}], "lastvalue": "1",
                               "lastclock": str(NOW - 5), "state": "0", "status": "0", "error": "", "delay": "10s",
                               "value_type": "3"}
            ids[kind] = iid
        return ids

    def add_template(self, name, macros=None, tags=(), parents=()):
        tid = self.nid()
        self.templates[tid] = {"templateid": tid, "host": name, "description": "", "tags": [
            {"tag": k, "value": v} for k, v in tags], "parents": list(parents)}
        for m, v in (macros or {}).items():
            self.add_macro(tid, m, v)
        return tid

    def link(self, hostid, templateid):
        self.hosts[hostid]["templates"].append(templateid)

    def add_trigger(self, name, itemids, priority=4, enabled=True, tags=(), value="0", state="0", expression=""):
        tid = self.nid()
        self.triggers[tid] = {"triggerid": tid, "description": name, "event_name": "", "priority": str(priority),
                              "status": "0" if enabled else "1", "value": value, "state": state, "error": "",
                              "manual_close": "1", "itemids": list(itemids), "expression": expression,
                              "recovery_mode": "0", "recovery_expression": "",
                              "tags": [{"tag": k, "value": v} for k, v in tags]}
        return tid

    def add_delivery(self, triggerid, actionid, problem=True, recovery=True, status="1"):
        """Zabbix alert history: a problem event (and its recovery) with SENT messages from an action."""
        pe, re_ = self.nid(), self.nid()
        if problem:
            self.events.append({"eventid": pe, "objectid": triggerid, "value": "1", "clock": str(NOW - 3600), "alerts": [
                {"alertid": self.nid(), "actionid": actionid, "status": status, "alerttype": "0", "p_eventid": "0"}]})
        if recovery:
            self.events.append({"eventid": re_, "objectid": triggerid, "value": "0", "clock": str(NOW - 3000), "alerts": [
                {"alertid": self.nid(), "actionid": actionid, "status": status, "alerttype": "0", "p_eventid": pe}]})

    def add_user(self, username, groupids, medias=()):
        uid = self.nid()
        self.users[uid] = {"userid": uid, "username": username, "groups": list(groupids),
                           "medias": [dict(m) for m in medias]}
        return uid

    def add_action(self, name, conditions, groupid, mediatypeid="0", recovery=True, status="0", evaltype="0",
                   formula=""):
        aid = self.nid()
        op = {"operationtype": "0", "opmessage": {"default_msg": "1", "mediatypeid": str(mediatypeid)},
              "opmessage_grp": [{"usrgrpid": groupid}]}
        self.actions[aid] = {"actionid": aid, "name": name, "eventsource": "0", "status": status, "esc_period": "1h",
                             "filter": {"evaltype": evaltype, "formula": formula, "conditions": list(conditions)},
                             "operations": [op], "recovery_operations": [copy.deepcopy(op)] if recovery else []}
        return aid

    # ------------------------------------------------------------------ dispatch hooks
    def _dispatch(self, method, params, authenticated):
        if method in self.fail_on:
            raise self.fail_on[method]
        if method in self.deny:
            raise invalid("No permissions to call \"%s\"." % method)
        return MockZabbix._dispatch(self, method, params, authenticated)

    # ------------------------------------------------------------------ reads
    def m_hostgroup_get(self, p):
        names = (p.get("filter") or {}).get("name")
        return [{"groupid": g, "name": n} for g, n in self.groups.items() if names is None or n in names]

    def m_host_get(self, p):
        rows = MockZabbix.m_host_get(self, p)
        if p.get("groupids"):
            rows = [r for r in rows if set(self.hosts[r["hostid"]].get("groupids", [])) & set(p["groupids"])]
        for r in rows:
            h = self.hosts[r["hostid"]]
            if "selectHostGroups" in p:
                r["hostgroups"] = [{"groupid": g, "name": self.groups[g]} for g in h.get("groupids", [])]
            if "selectTags" in p:
                r["tags"] = copy.deepcopy(h.get("tags", []))
            if "selectInterfaces" in p:
                r["interfaces"] = [dict((k, i.get(k, "")) for k in p["selectInterfaces"]) for i in h["interfaces"]]
        return rows

    def m_item_get(self, p):
        out = []
        for it in self.items.values():
            if p.get("hostids") and it["hostid"] not in p["hostids"]:
                continue
            if p.get("itemids") and it["itemid"] not in p["itemids"]:
                continue
            s = (p.get("search") or {}).get("key_")
            if s and s.lower() not in it["key_"].lower():
                continue
            ok = True
            for t in p.get("tags") or []:
                has = [x for x in it["tags"] if x["tag"] == t["tag"]]
                if int(t.get("operator", 0)) == 4 and not has:
                    ok = False
            if not ok:
                continue
            r = self._out(dict((k, v) for k, v in it.items() if k != "tags"), p.get("output"))
            if p.get("selectTags"):
                r["tags"] = copy.deepcopy(it["tags"])
            out.append(r)
        return out

    def m_trigger_get(self, p):
        want = set(p.get("itemids") or [])
        out = []
        for t in self.triggers.values():
            if want and not want.intersection(t["itemids"]):
                continue
            r = self._out(dict((k, v) for k, v in t.items() if k not in ("itemids", "tags")), p.get("output"))
            if "selectItems" in p:
                r["items"] = [{"itemid": i} for i in t["itemids"]]
            if "selectTags" in p:
                r["tags"] = copy.deepcopy(t["tags"])
            out.append(r)
        return out

    def m_template_get(self, p):
        if "templateids" not in p:
            return MockZabbix.m_template_get(self, p)
        out = []
        for tid in p["templateids"]:
            t = self.templates.get(tid)
            if t is None:
                continue
            r = {"templateid": tid, "host": t["host"]}
            if "selectParentTemplates" in p:
                r["parentTemplates"] = [{"templateid": x} for x in t.get("parents", [])]
            if "selectMacros" in p:
                r["macros"] = [{"macro": m["macro"], "value": m["value"]} for m in self.macros.values() if m["hostid"] == tid]
            if "selectTags" in p:
                r["tags"] = copy.deepcopy(t.get("tags", []))
            out.append(r)
        return out

    def m_event_get(self, p):
        want = set(p.get("objectids") or [])
        out = []
        for e in self.events:
            if want and e["objectid"] not in want:
                continue
            if int(e["clock"]) < int(p.get("time_from", 0)):
                continue
            r = dict((k, v) for k, v in e.items() if k != "alerts")
            if "select_alerts" in p:
                r["alerts"] = copy.deepcopy(e["alerts"])
            out.append(r)
        return out

    def m_mediatype_get(self, p):
        flt = (p.get("filter") or {}).get("name")
        return [dict({"type": "0", "status": "0"}, **g) for g in self.mediatypes.values() if flt is None or g["name"] in flt]

    def m_usergroup_get(self, p):
        rows = MockZabbix.m_usergroup_get(self, p)
        for r in rows:
            g = self.usergroups[r["usrgrpid"]]
            r.setdefault("users_status", g.get("users_status", "0"))
            if "selectHostGroupRights" in p:
                r["hostgroup_rights"] = [{"id": k, "permission": str(v)} for k, v in g.get("rights", {}).items()]
        return rows

    def m_user_get(self, p):
        return [{"userid": u["userid"], "username": u["username"],
                 "usrgrps": [{"usrgrpid": g} for g in u["groups"]],
                 "medias": [dict(m) for m in u["medias"]]} for u in self.users.values()]

    def m_action_get(self, p):
        rows = MockZabbix.m_action_get(self, p)
        es = (p.get("filter") or {}).get("eventsource")
        return [r for r in rows if es is None or str(r.get("eventsource")) == str(es)]


def standard_world(z=None):
    """Two edge routers with an ISP each and one P2P link between them, a switch, a server without
    SNMP, an e-mail action that is READY for high/disaster, and the usual production noise."""
    z = z or DiscoveryZabbix(token="tok")
    email = z.add_mediatype("Email")
    noc = z.add_usergroup("NOC Network")
    z.usergroups[noc]["rights"] = {"2": 2}
    z.add_user("noc1", [noc], medias=[{"mediatypeid": email, "active": "0", "severity": "60",
                                       "period": "1-7,00:00-24:00"}])
    vendor = z.add_template("Cisco IOS by SNMP", macros={"{$IFCONTROL}": "1", "{$IF.UTIL.MAX}": "90"})
    r1 = z.add_device("EDGE-RTR-01", tags=[("site", "DC1")], templates=(vendor,), ports=[
        dict(name="Hu0/0/0/0", index="1", alias="STC INTERNET TRANSIT 10G", speed=10 ** 10),
        dict(name="Te0/0/0/1", index="2", alias="P2P TO EDGE-RTR-02 Te0/0/0/1"),
        dict(name="Gi0/0/0/9", index="9", alias="spare"),
        dict(name="Loopback0", index="20", alias="router-id"),
    ])
    r2 = z.add_device("EDGE-RTR-02", tags=[("site", "DC1")], templates=(vendor,), ports=[
        dict(name="Hu0/0/0/0", index="1", alias="MOBILY INTERNET TRANSIT 10G", speed=10 ** 10),
        dict(name="Te0/0/0/1", index="2", alias="P2P TO EDGE-RTR-01 Te0/0/0/1"),
    ])
    z.add_device("CORE-SW-01", ports=[dict(name="Eth1/1", index="1", alias="DCI to DC2 core")])
    z.add_device("APP-SRV-01", snmp=False, groups=("3",))
    st = [i for i, it in z.items.items() if it["hostid"] == r1 and it["key_"] == "net.if.status[ifOperStatus.1]"][0]
    z.add_trigger("EDGE-RTR-01 Hu0/0/0/0 link down (stock)", [st], priority=4, expression=stock_link("EDGE-RTR-01", "Hu0/0/0/0", "1"))
    act = z.add_action("Report network problems", [{"conditiontype": "0", "operator": "0", "value": "2", "formulaid": "A"}],
                       noc, mediatypeid=email)
    return z, {"r1": r1, "r2": r2, "email": email, "noc": noc, "vendor": vendor, "action": act}


def stock_link(host, port, idx):
    """Shape of the Zabbix 7.0 stock 'Link down' trigger expression (expanded)."""
    k = "/%s/net.if.status[ifOperStatus.%s]" % (host, idx)
    return ('{$IFCONTROL:"%s"}=1 and last(%s)=2 and (last(%s,#1)<>last(%s,#2))' % (port, k, k, k))


def stock_util(host, port, idx):
    """Shape of the stock 'High bandwidth usage' trigger expression (expanded)."""
    return ('(avg(/{h}/net.if.in[ifHCInOctets.{i}],15m)>({{$IF.UTIL.MAX:"{p}"}}/100)*last(/{h}/net.if.speed[ifHighSpeed.{i}]) '
            'or avg(/{h}/net.if.out[ifHCOutOctets.{i}],15m)>({{$IF.UTIL.MAX:"{p}"}}/100)*last(/{h}/net.if.speed[ifHighSpeed.{i}])) '
            'and last(/{h}/net.if.speed[ifHighSpeed.{i}])>0').format(h=host, i=idx, p=port)
