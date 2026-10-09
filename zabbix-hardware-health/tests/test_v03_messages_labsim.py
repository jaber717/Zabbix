import io
import json
import os
import unittest

from hwh import labsim, messages
from hwh.api import ZabbixAPI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = labsim.load(os.path.join(ROOT, "config", "lab-sim.yaml"))


class _R(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_api(tags=None, enabled_action_filter=None, delivering=True):
    tags = tags if tags is not None else {"26409": [{"tag": "scenario", "value": "fan"}], "26410": [], "26411": []}
    keys = {"52108": "sim.fan", "52109": "sim.psu", "52110": "sim.temp"}
    calls = []

    def transport(req, timeout=0):
        body = json.loads(req.data)
        m, p = body["method"], body.get("params", {})
        calls.append(m)
        if m == "host.get":
            r = [{"hostid": "10696", "host": "LAB-SNMPSIM-HW-01", "name": "x", "status": "0", "tags": []}]
        elif m == "item.get":
            r = [{"itemid": i, "hostid": "10696", "name": i, "key_": keys[i], "status": "0", "state": "0" if delivering else "1",
                  "lastvalue": "1", "lastclock": "100" if delivering else "0", "value_type": "3", "tags": []} for i in p["itemids"]]
        elif m == "trigger.get":
            inv = dict((v, k) for k, v in {"52108": "26409", "52109": "26410", "52110": "26411"}.items())
            r = [{"triggerid": t, "description": t, "expression": "last(/h/%s)=3" % keys[inv[t]], "status": "0", "value": "0", "priority": "4", "tags": tags[t]}
                 for t in p["triggerids"]]
        elif m == "action.get":
            r = [] if enabled_action_filter is None else [{"actionid": "9", "name": "x", "status": "0", "eventsource": "0", "filter": enabled_action_filter}]
        else:
            raise AssertionError(m)
        return _R(json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": r}).encode())

    api = ZabbixAPI("http://z", "t", transport=transport)
    return api, calls


class LabSim(unittest.TestCase):
    def test_verify_passes_and_writes_nothing(self):
        api, calls = make_api()
        r = labsim.verify(api, CFG)
        self.assertTrue(r["ok"], r["checks"])
        self.assertEqual(api.writes_made(), [])
        self.assertTrue(all(c.endswith(".get") for c in calls))

    def test_enabled_matching_action_fails_isolation(self):
        flt = {"evaltype": 0, "conditions": [{"conditiontype": 25, "operator": 0, "value": "scenario"}]}
        api, _ = make_api(enabled_action_filter=flt)
        r = labsim.verify(api, CFG)
        self.assertFalse(r["ok"])

    def test_netops_alert_tag_fails(self):
        api, _ = make_api(tags={"26409": [{"tag": "netops_alert", "value": "1"}], "26410": [], "26411": []})
        self.assertFalse(labsim.verify(api, CFG)["ok"])

    def test_not_delivering_fails(self):
        api, _ = make_api(delivering=False)
        self.assertFalse(labsim.verify(api, CFG)["ok"])

    def test_plans_keep_existing_tags_and_restore_exact(self):
        api, _ = make_api()
        r = labsim.verify(api, CFG)
        plan = labsim.tag_plan(CFG, r["snapshot"])
        self.assertIn({"tag": "scenario", "value": "fan"}, plan[0]["tags_after"])
        self.assertIn({"tag": "netops_hardware", "value": "1"}, plan[0]["adds"])
        rp = labsim.restore_plan(r["snapshot"])
        self.assertEqual(rp[0]["restore_tags"], [{"tag": "scenario", "value": "fan"}])
        self.assertIn("NOT APPLIED", labsim.render(r, CFG))


class Messages(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(messages.check(), [])

    def test_examples_render(self):
        t = messages.render_examples()
        self.assertIn("Catalyst 9300-48P", t)
        self.assertIn("Resolved:", t)
        self.assertNotIn("{EVENT", t)


if __name__ == "__main__":
    unittest.main()


class IsolationFailsClosed(unittest.TestCase):
    def test_unconditioned_enabled_action_matches_everything(self):
        api, _ = make_api(enabled_action_filter={"evaltype": 0, "conditions": []})
        self.assertFalse(labsim.verify(api, CFG)["ok"])

    def test_unmodelled_condition_only_is_assumed_to_match(self):
        flt = {"evaltype": 0, "conditions": [{"conditiontype": 4, "operator": 5, "value": "3"}]}
        api, _ = make_api(enabled_action_filter=flt)
        self.assertFalse(labsim.verify(api, CFG)["ok"])

    def test_and_with_unmodelled_condition_still_excluded_by_tag_condition(self):
        flt = {"evaltype": 1, "conditions": [{"conditiontype": 25, "operator": 0, "value": "netops_hardware"}, {"conditiontype": 4, "operator": 5, "value": "3"}]}
        api, _ = make_api(enabled_action_filter=flt)
        self.assertTrue(labsim.verify(api, CFG)["ok"])


def make_evidence_api(events, alerts, actions):
    calls = []

    def transport(req, timeout=0):
        body = json.loads(req.data)
        m, p = body["method"], body.get("params", {})
        calls.append((m, p))
        if m == "event.get":
            r = events.get(p["objectids"][0], [])
        elif m == "alert.get":
            r = [a for a in alerts if a["eventid"] in p["eventids"]]
        elif m == "action.get":
            r = actions
        else:
            raise AssertionError(m)
        return _R(json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": r}).encode())

    return ZabbixAPI("http://z", "t", transport=transport), calls


class Evidence(unittest.TestCase):
    ACTIONS = [{"actionid": "9", "name": "NETOPS-HW Hardware Health"}, {"actionid": "3", "name": "NETOPS-IaC Interface Alerting"}]

    def test_problem_and_recovery_alerts_counted_from_hardware_action(self):
        ev = {"26409": [{"eventid": "10", "value": "1", "r_eventid": "11", "clock": "1"}]}
        al = [{"alertid": "1", "actionid": "9", "eventid": "10", "status": "1"}, {"alertid": "2", "actionid": "9", "eventid": "11", "status": "1"}]
        api, calls = make_evidence_api(ev, al, self.ACTIONS)
        r = labsim.evidence(api, CFG, 0)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["triggers"]["26409"]["alerts_by_action"], {"NETOPS-HW Hardware Health": 2})
        self.assertEqual(api.writes_made(), [])

    def test_unrecovered_problem_is_reported(self):
        ev = {"26410": [{"eventid": "20", "value": "1", "r_eventid": "0", "clock": "1"}]}
        api, _ = make_evidence_api(ev, [], self.ACTIONS)
        self.assertFalse(labsim.evidence(api, CFG, 0)["ok"])

    def test_alert_from_another_action_is_a_finding(self):
        ev = {"26411": [{"eventid": "30", "value": "1", "r_eventid": "31", "clock": "1"}]}
        al = [{"alertid": "5", "actionid": "3", "eventid": "30", "status": "1"}]
        api, _ = make_evidence_api(ev, al, self.ACTIONS)
        r = labsim.evidence(api, CFG, 0)
        self.assertFalse(r["ok"])
        self.assertTrue(any("Interface" in f for f in r["findings"]))
