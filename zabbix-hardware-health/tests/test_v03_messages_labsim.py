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
