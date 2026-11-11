"""Zabbix 7.0 API contract regression tests (rc3 review, 64387e7).

Two kinds of evidence, both independent of the offline mock's own conventions:
  1. every request discovery makes is checked against the 7.0 method reference (tests/zabbix70_contract.py):
     no undocumented parameter, no deprecated parameter, no undocumented sub-select field;
  2. discovery and delivery correlation run against hand-written responses in the shape the 7.0 docs show
     (function objects {functionid, itemid, function, parameter}; raw '{functionid}' expressions; alert objects
     with eventid / p_eventid / userid / status / alerttype; problem events with r_eventid).
Run against 64387e7 both fail: selectFunctions asks for "name" and rebuild() reads f["name"]; event.get uses the
deprecated select_alerts. These are offline proofs of the request/response contract only - LAB still decides.
"""
import copy
import unittest

from netalert import coverage, discovery
from netalert.zbx import ZabbixClient, ZabbixError
from tests import zabbix70_contract as contract
from tests.test_onboarding import World

NOW = 1_800_000_000


class CapturingTransport(object):
    """Records every request BEFORE it is sent, so a request that the server rejects is still examined."""

    def __init__(self, inner):
        self.inner, self.requests = inner, []

    def send(self, payload, authenticated=True):
        self.requests.append((payload["method"], copy.deepcopy(payload.get("params"))))
        return self.inner.send(payload, authenticated)


class Doc70Transport(object):
    """A tiny Zabbix 7.0 stand-in answering with literal, documentation-shaped responses. It enforces the request
    contract like the server's validator (undocumented parameters/fields -> error; deprecated ones still work)."""

    def __init__(self, recovery_alert_on="recovery"):
        self.requests = []
        problem_alert = {"alertid": "901", "actionid": "7", "eventid": "5001", "userid": "5", "clock": "1799996400",
                         "mediatypeid": "1", "sendto": "noc@example", "subject": "Problem", "message": "m",
                         "status": "1", "retries": "0", "error": "", "esc_step": "1", "alerttype": "0",
                         "p_eventid": "0", "acknowledgeid": "0"}
        recovery_alert = dict(problem_alert, alertid="902", eventid="5002" if recovery_alert_on == "recovery" else "5001",
                              clock="1799997000", subject="Resolved", p_eventid="5001")
        problem = {"eventid": "5001", "source": "0", "object": "0", "objectid": "3001", "clock": "1799996400",
                   "value": "1", "acknowledged": "0", "ns": "0", "name": "Gi0/1 down", "severity": "4",
                   "r_eventid": "5002", "c_eventid": "0", "correlationid": "0", "userid": "0", "cause_eventid": "0",
                   "alerts": [problem_alert] + ([recovery_alert] if recovery_alert_on == "problem" else [])}
        recovery = dict(problem, eventid="5002", clock="1799997000", value="0", r_eventid="0",
                        alerts=[recovery_alert] if recovery_alert_on == "recovery" else [])
        self.data = {
            "apiinfo.version": "7.0.5",
            "host.get": [{"hostid": "10501", "host": "R1", "name": "R1", "status": "0", "maintenance_status": "0",
                          "interfaces": [{"type": "2", "main": "1", "ip": "192.0.2.1", "dns": "", "available": "1",
                                          "error": ""}],
                          "hostgroups": [{"groupid": "2", "name": "Network devices"}], "tags": [],
                          "parentTemplates": [], "macros": [
                              {"hostmacroid": "1", "macro": "{$IFCONTROL}", "value": "1", "description": ""}]}],
            "item.get": [{"itemid": "24350", "hostid": "10501", "key_": "net.if.status[ifOperStatus.1]",
                          "name": "Interface Gi0/1(): Operational status", "lastvalue": "1",
                          "lastclock": str(NOW - 30), "state": "0", "status": "0", "error": "", "delay": "1m",
                          "value_type": "3", "type": "20", "master_itemid": "0",
                          "tags": [{"tag": "interface", "value": "Gi0/1"}]}],
            "trigger.get": [{"triggerid": "3001", "description": "Gi0/1 link down", "event_name": "",
                             "priority": "4", "status": "0", "value": "0", "state": "0", "error": "",
                             "manual_close": "1", "expression": '{$IFCONTROL}=1 and {13513}=2',
                             "recovery_mode": "0", "recovery_expression": "",
                             "items": [{"itemid": "24350"}], "tags": [],
                             "functions": [{"functionid": "13513", "itemid": "24350", "parameter": "$",
                                            "function": "last"}]}],
            "template.get": [], "usermacro.get": [], "hostgroup.get": [{"groupid": "2", "name": "Network devices"}],
            "action.get": [{"actionid": "7", "name": "Report problems", "eventsource": "0", "status": "0",
                            "esc_period": "1h", "filter": {"evaltype": "0", "formula": "", "conditions": []},
                            "operations": [{"operationtype": "0", "esc_step_from": "1", "esc_step_to": "1",
                                            "opmessage": {"default_msg": "1", "mediatypeid": "1"},
                                            "opmessage_grp": [{"usrgrpid": "8"}], "opmessage_usr": []}],
                            "recovery_operations": [{"operationtype": "11",
                                                     "opmessage": {"default_msg": "1", "mediatypeid": "0"}}]}],
            "mediatype.get": [{"mediatypeid": "1", "name": "Email", "type": "0", "status": "0"}],
            "usergroup.get": [{"usrgrpid": "8", "name": "NOC", "users_status": "0",
                               "hostgroup_rights": [{"id": "2", "permission": "2"}]}],
            "user.get": [{"userid": "5", "username": "noc1", "usrgrps": [{"usrgrpid": "8"}],
                          "medias": [{"mediatypeid": "1", "active": "0", "severity": "60",
                                      "period": "1-7,00:00-24:00"}]}],
            "event.get": [problem, recovery],
        }

    def send(self, payload, authenticated=True):
        m, p = payload["method"], payload.get("params") or {}
        self.requests.append((m, copy.deepcopy(p)))
        bad = [v for v in contract.violations(m, p) if "deprecated" not in v]
        if bad:
            return {"jsonrpc": "2.0", "id": payload["id"],
                    "error": {"code": -32602, "message": "Invalid params.", "data": bad[0]}}
        res = copy.deepcopy(self.data.get(m, []))
        if m == "item.get" and "search" in p:
            res = []
        if m == "event.get":
            sel = p.get("selectAlerts", p.get("select_alerts"))
            for e in res:
                if sel is None:
                    e.pop("alerts")
                elif sel != "extend":
                    e["alerts"] = [dict((k, a[k]) for k in sel if k in a) for a in e["alerts"]]
        if m == "trigger.get":
            sel = p.get("selectFunctions")
            for t in res:
                if sel is None:
                    t.pop("functions")
                elif sel != "extend":
                    t["functions"] = [dict((k, f[k]) for k in sel if k in f) for f in t["functions"]]
        return {"jsonrpc": "2.0", "id": payload["id"], "result": res}


class RequestContract(unittest.TestCase):
    def test_every_discovery_request_is_documented_and_not_deprecated(self):
        w = World()
        try:
            cap = CapturingTransport(w.z.transport("tok"))
            try:
                discovery.discover(ZabbixClient(cap, read_only=True), now=NOW)
            except ZabbixError:
                pass                                         # examined below either way
            problems = [v for m, p in cap.requests for v in contract.violations(m, p)]
            self.assertEqual(problems, [])
            methods = set(m for m, _ in cap.requests)
            self.assertTrue({"trigger.get", "event.get", "host.get", "item.get", "user.get"} <= methods, methods)
        finally:
            w.close()

    def test_trigger_functions_requested_with_7_0_field_names(self):
        t = Doc70Transport()
        discovery.discover(ZabbixClient(t, read_only=True), now=NOW)
        sel = [p["selectFunctions"] for m, p in t.requests if m == "trigger.get"]
        self.assertEqual(sel, [["functionid", "itemid", "function", "parameter"]])

    def test_event_alerts_requested_with_selectAlerts(self):
        t = Doc70Transport()
        discovery.discover(ZabbixClient(t, read_only=True), now=NOW)
        ev = [p for m, p in t.requests if m == "event.get"]
        self.assertTrue(ev)
        for p in ev:
            self.assertIn("selectAlerts", p)
            self.assertNotIn("select_alerts", p)
            self.assertTrue({"eventid", "p_eventid", "userid", "status", "alerttype", "actionid"} <= set(p["selectAlerts"]))


class DocumentShapedResponses(unittest.TestCase):
    def snap(self, **kw):
        return discovery.discover(ZabbixClient(Doc70Transport(**kw), read_only=True), now=NOW)

    def test_expression_rebuilt_from_7_0_function_objects(self):
        trig = self.snap()["hosts"]["R1"]["triggers"][0]
        self.assertEqual(trig["expression"], "{$IFCONTROL}=1 and last(/R1/net.if.status[ifOperStatus.1])=2")

    def test_problem_recovery_pair_correlated_from_7_0_alert_objects(self):
        for layout in ("recovery", "problem"):     # which event a recovery alert hangs on is a LAB question
            with self.subTest(recovery_alert_on=layout):
                snap = self.snap(recovery_alert_on=layout)
                trig = snap["hosts"]["R1"]["triggers"][0]
                pairs = coverage.correlated_pairs(snap, trig, "7", ["5"])
                self.assertEqual([(x["problem"], x["recovery"], x["users"]) for x in pairs], [("5001", "5002", ["5"])])
                self.assertEqual(coverage.correlated_pairs(snap, trig, "7", ["6"]), [])   # not a current recipient
                self.assertEqual(coverage.correlated_pairs(snap, trig, "99", ["5"]), [])  # another action

    def test_unsent_or_uncorrelated_alerts_never_pair(self):
        t = Doc70Transport()
        t.data["event.get"][1]["alerts"][0]["p_eventid"] = "4999"      # recovery of a different problem
        snap = discovery.discover(ZabbixClient(t, read_only=True), now=NOW)
        trig = snap["hosts"]["R1"]["triggers"][0]
        self.assertEqual(coverage.correlated_pairs(snap, trig, "7", ["5"]), [])
        t = Doc70Transport()
        t.data["event.get"][0]["alerts"][0]["status"] = "2"            # problem message failed
        snap = discovery.discover(ZabbixClient(t, read_only=True), now=NOW)
        self.assertEqual(coverage.correlated_pairs(snap, snap["hosts"]["R1"]["triggers"][0], "7", ["5"]), [])

    def test_missing_alerts_property_is_unreadable_history(self):
        t = Doc70Transport()
        orig = t.send

        def no_alerts(payload, authenticated=True):
            r = orig(payload, authenticated)
            if payload["method"] == "event.get":
                for e in r.get("result", []):
                    e.pop("alerts", None)
            return r
        t.send = no_alerts
        snap = discovery.discover(ZabbixClient(t, read_only=True), now=NOW)
        self.assertIsNone(snap["events"])
        self.assertIn("no 'alerts' property", " ".join(snap["limits"]))

    def test_opmessage_shapes(self):
        self.assertEqual(coverage.opmessage({"opmessage": {"mediatypeid": "1"}}), {"mediatypeid": "1"})
        self.assertEqual(coverage.opmessage({"opmessage": [{"mediatypeid": "1"}]}), {"mediatypeid": "1"})
        self.assertIsNone(coverage.opmessage({"opmessage": [{"a": 1}, {"b": 2}]}))
        self.assertIsNone(coverage.opmessage({"opmessage": "x"}))


if __name__ == "__main__":
    unittest.main()


class LabProbe(unittest.TestCase):
    """The LAB probe itself: read-only, and it passes on documentation-shaped responses."""

    def load(self):
        import importlib.util
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts",
                            "lab-contract-probe.py")
        spec = importlib.util.spec_from_file_location("lab_contract_probe", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_probe_on_document_shaped_server(self):
        out = []
        t = Doc70Transport()
        rc = self.load().probe(ZabbixClient(t, read_only=True), NOW, 30, out.append)
        text = "\n".join(out)
        self.assertEqual(rc, 0, text)
        self.assertIn("RESULT: PASS", text)
        self.assertNotIn("R1", text)                                 # prints no names
        self.assertNotIn("noc1", text)
        for m, p in t.requests:
            self.assertEqual([v for v in contract.violations(m, p) if "deprecated" not in v], [], (m, p))
            self.assertTrue(m.endswith(".get") or m == "apiinfo.version", m)

    def test_probe_refuses_write_capable_client(self):
        out = []
        self.assertEqual(self.load().probe(ZabbixClient(Doc70Transport(), read_only=False), NOW, 30, out.append), 4)
