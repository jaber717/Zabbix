"""Phase B: the verified 18-interface LAB policy, link de-duplication and the Codex handover importer."""
import os
import unittest

import yaml

from netalert import config, handover, model, planner
from netalert import template as tpl
from netalert.zbx import ZabbixClient
from tests.fake_zabbix import MockZabbix
from tests.helpers import World
from tests.zsim import InterfaceSim, macros_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join(ROOT, "config", "interfaces.yaml")
REVIEW = ["SAIX-CORE", "PALO-LAB"]


def load_policy():
    d = config.load(POLICY)
    assert not d.problems, [p.message for p in d.problems]
    return d


class ShippedPolicy(unittest.TestCase):
    def setUp(self):
        self.d = load_policy()

    def test_exactly_18_interfaces_on_7_routers(self):
        self.assertEqual(sorted(self.d.hosts), ["PNET-INT-CORE", "PNET-MOBILY", "PNET-SAIX-A", "PNET-SAIX-B",
                                                "PNET-SITE-A", "PNET-SITE-B", "PNET-STC"])
        self.assertEqual(sum(len(h["interfaces"]) for h in self.d.hosts.values()), 18)

    def test_review_required_endpoints_are_not_enabled(self):
        for name in REVIEW:
            self.assertFalse([h for h in self.d.hosts if name in h], name)       # not a policy host
        for h in self.d.hosts.values():
            self.assertFalse([i for i in h["interfaces"] if i.startswith("ethernet")])
        with open(os.path.join(ROOT, "config", "REVIEW-REQUIRED.md"), encoding="utf-8") as fh:
            review = fh.read()
        for t in ("SAIX-CORE GigabitEthernet0/0", "SAIX-CORE GigabitEthernet0/1",
                  "PALO-LAB ethernet1/1", "PALO-LAB ethernet1/2"):
            self.assertIn(t, review)

    def test_policy_is_the_handover_requirement(self):
        for h in self.d.hosts.values():
            for name, c in h["interfaces"].items():
                self.assertTrue(c["link_alert"], name)
                self.assertTrue(c["utilization"]["enabled"], name)
                self.assertEqual((c["utilization"]["threshold"], c["utilization"]["recovery"]), (70, 65))
                self.assertEqual(c["utilization"]["poll_seconds"], 10)
                self.assertIn(c["severity"], ("disaster", "high"))
                self.assertEqual(c["expected_speed"], None)        # no nominal speed is invented

    def test_both_ends_of_every_link_notify_with_identical_link_id(self):
        ends = {}
        for h, hc in self.d.hosts.items():
            for n, c in hc["interfaces"].items():
                self.assertTrue(c["link_id"], "%s %s" % (h, n))
                self.assertTrue(c["notify"], "%s %s" % (h, n))
                ends.setdefault(c["link_id"], []).append((h, n))
        self.assertEqual(len(ends), 11)
        for lid, members in ends.items():
            self.assertEqual(len(members), 1 if ("palo" in lid or "saix-core" in lid) else 2, lid)

    def test_every_notifying_end_produces_event_tags_the_action_accepts(self):
        # per interface: macros say NOTIFY=yes and carry LINKID, so the action filter never skips either end
        for h, hc in self.d.hosts.items():
            m = model.host_macros(hc)
            for n, c in hc["interfaces"].items():
                self.assertEqual(m['{$NETOPS.NOTIFY:"%s"}' % n], "yes")
                self.assertEqual(m['{$NETOPS.LINKID:"%s"}' % n], c["link_id"])

    def test_stock_suppression_default_is_false(self):
        import yaml as _y
        with open(os.path.join(ROOT, "config", "environments", "lab.yaml"), encoding="utf-8") as fh:
            self.assertIs(_y.safe_load(fh)["suppress_stock"], False)
        with open(os.path.join(ROOT, "config", "environments", "production.yaml"), encoding="utf-8") as fh:
            self.assertIs(_y.safe_load(fh)["suppress_stock"], False)

    def test_fast_polling_footprint(self):
        count, values, gets = model.nvps_estimate(self.d)
        self.assertEqual(count, 18)
        self.assertAlmostEqual(values, 18 * (3 / 10.0 + 6 / 60.0))        # 7.2 values/s
        fast = [i for i in tpl.item_prototypes() if i.get("delay") == '{$NETOPS.POLL:"{#IFNAME}"}']
        slow = [i for i in tpl.item_prototypes() if i.get("delay") == '{$NETOPS.POLL.SLOW:"{#IFNAME}"}']
        self.assertEqual((len(fast), len(slow)), (3, 5))                  # +1 dependent item without own poll
        # every collected value is a targeted, indexed OID — no table walk is ever scheduled
        for i in tpl.item_prototypes():
            if i["type"] == "SNMP_AGENT":
                self.assertTrue(i["snmp_oid"].endswith(".{#SNMPINDEX}"), i["key"])
                self.assertNotIn("walk[", i["snmp_oid"])

    def test_end_to_end_on_the_model(self):
        z = MockZabbix(token="tok-lab")
        for h, hc in self.d.hosts.items():
            z.add_host(h, sorted(hc["interfaces"]) + ["Gi0/5"])
        with open(POLICY, encoding="utf-8") as fh:
            policy_text = fh.read()
        w = World(mock=z, yaml_text=policy_text,
                  lab_extra="suppress_stock: true\n")
        try:
            rc, out = w.run("--check")
            self.assertEqual(rc, 0, out)
            self.assertIn("PASS (18 interface(s))", out)
            self.assertEqual(w.run()[0], 0)
            self.assertIn("No changes required.", w.run("--dry-run")[1])
            m = z.host_macro_map("PNET-SITE-A")
            self.assertEqual(m["{$NETOPS.IF.MATCH}"], "^(?:Gi0/0|Gi0/1|Gi0/2|Gi0/3)$")
            self.assertEqual(m['{$NETOPS.SEV:"Gi0/3"}'], "4")
            self.assertEqual(m['{$IFCONTROL:"Gi0/0"}'], "0")           # stock duplicate suppressed
            self.assertNotIn('{$IFCONTROL:"Gi0/5"}', m)                # unselected interface untouched
            self.assertIn(m['{$NETOPS.NOTIFY:"Gi0/0"}'], ("yes", "no"))
        finally:
            w.close()


class FirstDownAndNotify(unittest.TestCase):
    def test_notify_and_link_id_become_macros_and_tags(self):
        c = {"hosts": {"R": {"interfaces": {"A": {"description": "a", "link_id": "x--y", "notify": False}}}}}
        d = config.parse(c)
        self.assertEqual(d.problems, [])
        m = model.host_macros(d.hosts["R"])
        self.assertEqual((m['{$NETOPS.NOTIFY:"A"}'], m['{$NETOPS.LINKID:"A"}']), ("no", "x--y"))
        tags = dict((t["tag"], t["value"]) for t in tpl.trigger_prototypes()[0]["tags"])
        self.assertIn("link_id", tags)
        self.assertIn("notify", tags)

    def test_action_skips_notify_no_events(self):
        spec = model.desired_action({"alert_action": {"name": "NETOPS-IaC x", "usergroups": ["g"]}})
        p = planner.action_params(spec, ["1"], 0)
        conds = [(c["conditiontype"], c["operator"], c["value"], c.get("value2")) for c in p["filter"]["conditions"]]
        self.assertIn((25, 0, tpl.TAG_ALERT, None), conds)
        self.assertIn((26, 1, "no", "notify"), conds)

    def test_first_down_alert_then_flapping_keeps_one_open_problem(self):
        macros = macros_for({"hosts": {"RTR-01": {"interfaces": {"Gi0/0": {
            "description": "x", "severity": "disaster"}}}}})
        s = InterfaceSim(macros, "Gi0/0")
        s.sample(10, oper=1)
        s.sample(10, oper=2)
        self.assertEqual(s.events[0][1:], ("link_down", "PROBLEM"))
        for i in range(12):
            s.sample(10, oper=1 if i % 2 == 0 else 2)
        self.assertTrue(s.problem("flapping"))
        self.assertTrue(s.problem("link_down"))


class CodexImporter(unittest.TestCase):
    RAW = {"selection_rules": {"utilization_threshold_pct": 70, "utilization_recovery_pct": 65},
           "hosts": {
               "RTR-01": {"zabbix_hostid": "H1", "site": "LAB", "interfaces": {
                   "Gi0/0": {"zabbix_ifname": "Gi0/0", "snmp_index": 1, "zabbix_status_itemid": "I1",
                             "description": "TO-B", "link_id": "a--b", "severity": "disaster",
                             "recommended_alerts": {"link": True, "utilization": True, "errors": True,
                                                    "discards": True, "flapping": True},
                             "speed_bps": 10 ** 9}}},
               "RTR-02": {"zabbix_hostid": "H2", "site": "LAB", "interfaces": {
                   "Gi0/0": {"zabbix_ifname": "Gi0/0", "snmp_index": 1, "zabbix_status_itemid": "I2",
                             "description": "TO-A", "link_id": "a--b", "severity": "disaster",
                             "recommended_alerts": {"link": True, "utilization": True}}}}}}

    def world(self):
        z = MockZabbix()
        h1 = z.add_host("RTR-01", ["Gi0/0"])
        h2 = z.add_host("RTR-02", ["Gi0/0"])
        self.ids = {}
        for hid, key in ((h1, "I1"), (h2, "I2")):
            iid = z.nid()
            z.items[iid] = {"itemid": iid, "hostid": hid, "key_": "net.if.status[ifOperStatus.1]",
                            "name": "status", "tags": [{"tag": "interface", "value": "Gi0/0"}]}
            self.ids[key] = iid
        return z, ZabbixClient(z.transport(), read_only=True)

    def raw_with_ids(self, z, h1id=None):
        raw = yaml.safe_load(yaml.safe_dump(self.RAW))
        raw["hosts"]["RTR-01"]["zabbix_hostid"] = z.host_id("RTR-01")
        raw["hosts"]["RTR-02"]["zabbix_hostid"] = z.host_id("RTR-02")
        raw["hosts"]["RTR-01"]["interfaces"]["Gi0/0"]["zabbix_status_itemid"] = self.ids["I1"]
        raw["hosts"]["RTR-02"]["interfaces"]["Gi0/0"]["zabbix_status_itemid"] = self.ids["I2"]
        return raw

    def test_conversion_keeps_every_end_notifying(self):
        self.assertTrue(handover.is_codex_format(self.RAW))
        policy, extras = handover.from_codex(self.RAW)
        self.assertEqual(config.parse(policy).problems, [])
        e1 = policy["hosts"]["RTR-01"]["interfaces"]["Gi0/0"]
        e2 = policy["hosts"]["RTR-02"]["interfaces"]["Gi0/0"]
        self.assertNotIn("expected_speed", e1)                       # nominal speeds are not copied
        self.assertEqual((e1.get("notify", True), e2.get("notify", True)), (True, True))
        self.assertEqual((e1["link_id"], e2["link_id"]), ("a--b", "a--b"))
        self.assertEqual(len(extras), 2)

    def test_all_verified(self):
        z, c = self.world()
        policy, extras = handover.from_codex(self.raw_with_ids(z))
        verified, review, _ = handover.verify(c, policy, extras)
        self.assertEqual(review, [])
        self.assertEqual(sum(len(h["interfaces"]) for h in verified["hosts"].values()), 2)

    def test_mismatches_are_excluded_not_guessed(self):
        z, c = self.world()
        raw = self.raw_with_ids(z)
        raw["hosts"]["RTR-01"]["zabbix_hostid"] = "99999"                      # wrong host id
        raw["hosts"]["RTR-02"]["interfaces"]["Gi0/0"]["snmp_index"] = 7        # index does not match item key
        policy, extras = handover.from_codex(raw)
        verified, review, _ = handover.verify(c, policy, extras)
        why = dict(((h, i), w) for h, i, w in review)
        self.assertIn("host id differs", why[("RTR-01", "Gi0/0")])
        self.assertIn("does not match snmp_index", why[("RTR-02", "Gi0/0")])
        self.assertEqual(verified["hosts"], {})

    def test_item_tagged_for_another_interface_is_excluded(self):
        z, c = self.world()
        z.items[self.ids["I1"]]["tags"] = [{"tag": "interface", "value": "Gi0/9"}]
        policy, extras = handover.from_codex(self.raw_with_ids(z))
        _, review, _ = handover.verify(c, policy, extras)
        self.assertTrue([r for r in review if r[0] == "RTR-01" and "tagged interface" in r[2]])

    def test_interface_that_no_longer_exists_is_excluded_and_rest_continue(self):
        z, c = self.world()
        raw = self.raw_with_ids(z)
        raw["hosts"]["RTR-01"]["interfaces"]["Gi0/0"]["zabbix_ifname"] = "Gi0/77"
        policy, extras = handover.from_codex(raw)
        verified, review, _ = handover.verify(c, policy, extras)
        self.assertEqual([(h, i) for h, i, _ in review][0], ("RTR-01", "Gi0/77"))
        self.assertIn("RTR-02", verified["hosts"])


if __name__ == "__main__":
    unittest.main()


class NoMissedAlertFailureMode(unittest.TestCase):
    """Each end alerts on its own host data; nothing lets one end's state suppress the other."""

    def test_no_trigger_references_another_host_or_dependency(self):
        for t in tpl.trigger_prototypes():
            self.assertNotIn("dependencies", t, t["name"])
            for expr in (t["expression"], t.get("recovery_expression", "")):
                for host in __import__("re").findall(r"/([^/(),]+)/", expr):
                    self.assertEqual(host, tpl.TEMPLATE_NAME)

    def test_action_filter_cannot_skip_a_notifying_end(self):
        spec = model.desired_action({"alert_action": {"name": "NETOPS-IaC x", "usergroups": ["g"]}})
        conds = planner.action_params(spec, ["1"], 0)["filter"]["conditions"]
        # only the alert tag and "notify != no" are filtered on: never link_id, never the peer
        self.assertEqual(sorted(c["conditiontype"] for c in conds), [25, 26])
        self.assertTrue(all(c["conditiontype"] == 25 or c["value2"] == "notify" for c in conds))

    def test_peer_alerts_alone_when_the_other_end_is_unreachable(self):
        d = load_policy()
        # INT-CORE Gi0/0 <-> STC Gi0/0 share a link_id; only the STC end ever sees data here
        stc = d.hosts["PNET-STC"]["interfaces"]["Gi0/0"]
        core = d.hosts["PNET-INT-CORE"]["interfaces"]["Gi0/0"]
        self.assertEqual(stc["link_id"], core["link_id"])
        self.assertTrue(stc["notify"] and core["notify"])
        m = model.host_macros(d.hosts["PNET-STC"])
        s = InterfaceSim(m, "Gi0/0")
        s.sample(10, oper=1)
        s.sample(10, oper=2)                      # the peer (INT-CORE) is silent/unreachable
        self.assertTrue(s.problem("link_down"))
        self.assertEqual(m['{$NETOPS.NOTIFY:"Gi0/0"}'], "yes")
        self.assertEqual(m['{$NETOPS.LINKID:"Gi0/0"}'], "int-core--stc")

    def test_both_ends_emit_same_link_id_tag(self):
        d = load_policy()
        ids = []
        for host in ("PNET-STC", "PNET-INT-CORE"):
            m = model.host_macros(d.hosts[host])
            ids.append(m['{$NETOPS.LINKID:"Gi0/0"}'])
        self.assertEqual(ids[0], ids[1])
        self.assertIn("link_id", [t["tag"] for t in tpl.trigger_prototypes()[0]["tags"]])
