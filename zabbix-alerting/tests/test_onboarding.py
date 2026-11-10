"""Discovery-assisted onboarding: read-only discovery, review, generation, coverage audit, deploy gate.

All against tests/discovery_fixture.py (an in-memory Zabbix 7.0 model) - not a production server.
"""
import json
import os
import shutil
import stat
import tempfile
import unittest

import yaml

from netalert import cli as icli
from netalert import coverage, discovery, onboard_cli
from netalert import onboarding as ob
from netalert.zbx import ApiUnavailable, ZabbixClient
from tests.discovery_fixture import NOW, DiscoveryZabbix, standard_world
from tests.helpers import LAB_YAML, PROD_YAML, write

IDENT = {"globalmacroid": "1", "macro": "{$NETOPS.ENVIRONMENT}", "value": "production",
         "description": "managed_by=zabbix-alerting-as-code"}
READ_METHODS = ("apiinfo.version",)


class World(object):
    def __init__(self, z=None, iface="hosts: {}\n", health="devices: {}\n", prod_extra="", claim=True):
        self.base = tempfile.mkdtemp(prefix="onboard-test-")
        write(os.path.join(self.base, "config/environments/lab.yaml"), LAB_YAML)
        write(os.path.join(self.base, "config/environments/production.yaml"), PROD_YAML + prod_extra)
        write(os.path.join(self.base, "config/interfaces.production.yaml"), iface)
        write(os.path.join(self.base, "config/network-health.production.yaml"), health)
        if z is None:
            z, self.ids = standard_world()
        self.z = z
        if claim:
            z.gmacros["1"] = dict(IDENT)
        self.env = {"ZABBIX_URL_PRODUCTION": "https://zbx.prod.example", "ZABBIX_TOKEN_PRODUCTION": "tok"}
        self.netbox_opener = None

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def run(self, *argv, lines=None, environ=None):
        out = []
        rc = onboard_cli.run(["--env", "production"] + list(argv), environ=dict(self.env if environ is None else environ), out=out.append,
                             lines=lines, base=self.base, transport_factory=lambda u, t, v: self.z.transport(t),
                             netbox_opener=self.netbox_opener, now=NOW)
        return rc, "\n".join(out)

    def apply(self, *argv):
        out = []
        rc = icli.run(["--env", "production"] + list(argv), environ=dict(self.env), out=out.append, base=self.base,
                      transport_factory=lambda u, t, v: self.z.transport(t))
        return rc, "\n".join(out)

    def path(self, rel):
        return os.path.join(self.base, rel)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def yaml(self, rel):
        return yaml.safe_load(self.read(rel))

    def snapshot(self):
        return discovery.discover(ZabbixClient(self.z.transport("tok"), read_only=True), now=NOW)

    def model(self):
        b = self.base
        p = ob.paths(b, "production")
        return ob.build(self.snapshot(), ob.load_rules(b), ob.read_yaml(p["interfaces"]), ob.read_yaml(p["health"]),
                        ob.load_decisions(p["decisions"]), NOW)


def row_no(out, host, port):
    """Row number in the LAST listing printed (the one the following commands refer to)."""
    for line in reversed(out.splitlines()):
        parts = line.split()
        if len(parts) > 4 and parts[0].isdigit() and parts[2] == host and parts[3] == port:
            return parts[0]
    raise AssertionError("%s %s not listed:\n%s" % (host, port, out))


class Base(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()


# ------------------------------------------------------------------------------------------- read-only

class ReadOnly(Base):
    def test_report_and_review_never_write_to_zabbix(self):
        rc, out = self.w.run("--report")
        self.assertEqual(rc, 0, out)
        rc, out = self.w.run(lines=["l all", "a all", "h", "a all", "w", "q"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.z.writes(), [])
        called = set(m for m, _ in self.w.z.calls)
        self.assertTrue(all(m.endswith(".get") or m in READ_METHODS for m in called), called)
        self.assertIn("0 writes", out)

    def test_discovery_refuses_a_write_capable_client(self):
        with self.assertRaises(discovery.DiscoveryError):
            discovery.discover(ZabbixClient(self.w.z.transport("tok"), read_only=False))

    def test_netbox_is_read_only(self):
        calls = []

        def opener(url):
            calls.append(url)
            return {"results": [], "next": None}
        self.w.netbox_opener = opener
        env = dict(self.w.env, NETBOX_URL="https://netbox.example", NETBOX_TOKEN="x")
        rc, out = self.w.run("--report", environ=env)
        self.assertEqual(rc, 0, out)
        self.assertTrue(calls and all("/api/dcim/" in c for c in calls))


# ------------------------------------------------------------------------------------------- inventory scope

class Scope(Base):
    def test_empty_zabbix(self):
        self.w.close()
        self.w = World(z=DiscoveryZabbix(token="tok"))
        rc, out = self.w.run("--report")
        self.assertEqual(rc, 0, out)
        self.assertIn("discovered 0 host(s), 0 port(s)", out)
        self.assertIn("no enabled trigger action", self.w.read("state/onboarding/production/coverage-latest.md"))
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("never written", out)

    def test_hosts_without_ports_or_snmp_are_reported_blind_spots(self):
        self.w.z.add_device("NEW-RTR-09")                         # SNMP, but no interface items yet
        rc, out = self.w.run("--report")
        rep = self.w.read("state/onboarding/production/coverage-latest.md")
        self.assertIn("no discovered interface items (blind spot): NEW-RTR-09", rep)
        self.assertIn("without SNMP interface (ports not discoverable): APP-SRV-01", rep)

    def test_management_interfaces_are_not_ports_and_loopbacks_not_candidates(self):
        m = self.w.model()
        ids = [r.id for r in m["ports"] if r.candidate]
        self.assertNotIn("EDGE-RTR-01|Loopback0", ids)
        self.assertNotIn("EDGE-RTR-01|Gi0/0/0/9", ids)              # "spare": no role evidence
        self.assertFalse(any(r.host == "APP-SRV-01" for r in m["ports"]))

    def test_group_scope(self):
        rc, out = self.w.run("--report", "--group", "Servers")
        self.assertIn("discovered 1 host(s), 0 port(s)", out)
        rc, out = self.w.run("--report", "--group", "No Such Group")
        self.assertEqual(rc, icli.EXIT_API)
        self.assertIn("host group(s) not found", out)


# ------------------------------------------------------------------------------------------- data quality

class DataQuality(Base):
    def _port(self, **kw):
        hid = self.w.z.add_device("RTR-Q", ports=[dict(dict(name="Te1/1", index="5", alias="ISP transit"), **kw)])
        return hid

    def approve_one(self, host, port):
        rc, out = self.w.run(lines=["l all"])
        return self.w.run(lines=["l all", "a %s" % row_no(out, host, port), "w", "q"])

    def test_missing_snmp_data_blocks_approval_and_is_stale(self):
        self._port(age=None)                                       # never received a value
        rc, out = self.approve_one("RTR-Q", "Te1/1")
        self.assertIn("refused RTR-Q|Te1/1: status item never", out)
        r = self.w.model()["by_id"]["RTR-Q|Te1/1"]
        self.assertEqual(coverage.port_coverage(self.w.snapshot(), r)[0], coverage.REVIEW if r.review else coverage.STALE)

    def test_stale_and_snmp_unavailable(self):
        self._port(age=7200)
        r = self.w.model()["by_id"]["RTR-Q|Te1/1"]
        self.assertIn("status item stale", r.blockers)
        self.w.z.hosts[self.w.z.host_id("RTR-Q")]["interfaces"][0]["available"] = "2"
        snap = self.w.snapshot()
        cls, why, _ = coverage.port_coverage(snap, self.w.model()["by_id"]["RTR-Q|Te1/1"])
        self.assertEqual(cls, coverage.STALE)

    def test_unsupported_item_blocks_approval(self):
        self._port(state="1", error="Timeout while connecting")
        rc, out = self.approve_one("RTR-Q", "Te1/1")
        self.assertIn("unsupported: Timeout while connecting", out)
        self.assertEqual(self.w.yaml("config/interfaces.production.yaml")["hosts"], {})

    def test_duplicate_interface_names_are_ambiguous(self):
        hid = self._port()
        self.w.z.add_port(hid, name="Te1/1", index="77", alias="ISP transit")   # second ifIndex, same name
        r = self.w.model()["by_id"]["RTR-Q|Te1/1"]
        self.assertTrue(any("ambiguous" in b for b in r.blockers))
        rc, out = self.approve_one("RTR-Q", "Te1/1")
        self.assertIn("refused", out)
        self.assertEqual(coverage.port_coverage(self.w.snapshot(), r)[0], coverage.REVIEW)

    def test_changed_index_fails_gate_until_reapproved(self):
        hid = self._port()
        self.approve_one("RTR-Q", "Te1/1")
        self.assertEqual(self.w.run("--verify")[0], 0)
        for iid in [i for i, it in self.w.z.items.items() if it["hostid"] == hid]:
            del self.w.z.items[iid]
        self.w.z.add_port(hid, name="Te1/1", index="31", alias="ISP transit")   # reboot without ifindex persist
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("SNMP index changed 5 -> 31", out)
        self.assertIn("identity drift", out)
        rc, out = self.approve_one("RTR-Q", "Te1/1")             # operator checked the port: re-approve
        self.assertEqual(self.w.run("--verify")[0], 0, self.w.run("--verify")[1])


# ------------------------------------------------------------------------------------------- pairing

class Pairing(Base):
    def test_suggested_pair_needs_operator_confirmation(self):
        rc, out = self.w.run(lines=["l"])
        a, b = row_no(out, "EDGE-RTR-01", "Te0/0/0/1"), row_no(out, "EDGE-RTR-02", "Te0/0/0/1")
        self.assertIn("suggested peer: EDGE-RTR-02|Te0/0/0/1", out)
        self.w.run(lines=["l", "a %s,%s" % (a, b), "w", "q"])
        doc = self.w.yaml("config/interfaces.production.yaml")
        self.assertNotIn("link_id", doc["hosts"]["EDGE-RTR-01"]["interfaces"]["Te0/0/0/1"])   # hint is not proof
        self.w.run(lines=["l", "p %s" % a, "w", "q"])
        doc = self.w.yaml("config/interfaces.production.yaml")
        l1 = doc["hosts"]["EDGE-RTR-01"]["interfaces"]["Te0/0/0/1"]["link_id"]
        self.assertEqual(l1, doc["hosts"]["EDGE-RTR-02"]["interfaces"]["Te0/0/0/1"]["link_id"])
        self.assertEqual(l1, "edge-rtr-01-te0-0-0-1--edge-rtr-02-te0-0-0-1")

    def test_unmatched_p2p_endpoint_is_a_warning_not_a_guess(self):
        rc, out = self.w.run(lines=["l"])
        self.w.run(lines=["l", "a %s" % row_no(out, "EDGE-RTR-01", "Te0/0/0/1"), "w", "q"])
        entry = self.w.yaml("config/interfaces.production.yaml")["hosts"]["EDGE-RTR-01"]["interfaces"]["Te0/0/0/1"]
        self.assertNotIn("link_id", entry)
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 0, out)
        self.assertIn("WARN  EDGE-RTR-01 / Te0/0/0/1: P2P port has no verified or operator-confirmed peer", out)

    def test_similar_names_are_never_paired(self):
        z = DiscoveryZabbix(token="tok")
        z.add_device("A-RTR", ports=[dict(name="Te0/1", index="1", alias="P2P link")])
        z.add_device("B-RTR", ports=[dict(name="Te0/1", index="1", alias="P2P link")])
        self.w.close()
        self.w = World(z=z)
        m = self.w.model()
        self.assertTrue(all(not r.pair and not r.pair_hints for r in m["ports"]))

    def test_netbox_cable_is_verified_pairing(self):
        def opener(url):
            if "dcim/devices" in url:
                return {"results": [{"id": 1, "name": "EDGE-RTR-01", "site": {"name": "DC1"}},
                                    {"id": 2, "name": "EDGE-RTR-02", "site": {"name": "DC1"}}], "next": None}
            dev, peer = ("EDGE-RTR-01", "EDGE-RTR-02") if "device_id=1" in url else ("EDGE-RTR-02", "EDGE-RTR-01")
            return {"results": [{"name": "TenGigE0/0/0/1", "cable": {"id": 9},
                                 "link_peers": [{"device": {"name": peer}, "name": "TenGigE0/0/0/1"}]}], "next": None}
        self.w.netbox_opener = opener
        env = dict(self.w.env, NETBOX_URL="https://netbox.example", NETBOX_TOKEN="x")
        rc, out = self.w.run(lines=["l"], environ=env)
        a, b = row_no(out, "EDGE-RTR-01", "Te0/0/0/1"), row_no(out, "EDGE-RTR-02", "Te0/0/0/1")
        self.assertIn("(netbox-cable)", out)
        self.w.run(lines=["l", "a %s,%s" % (a, b), "w", "q"], environ=env)
        doc = self.w.yaml("config/interfaces.production.yaml")
        self.assertEqual(doc["hosts"]["EDGE-RTR-01"]["interfaces"]["Te0/0/0/1"]["link_id"],
                         doc["hosts"]["EDGE-RTR-02"]["interfaces"]["Te0/0/0/1"]["link_id"])


# ------------------------------------------------------------------------------------------- generation

EXISTING = """\
# hand-written before onboarding existed
defaults:
  flapping: {enabled: true, transitions: 5, window: 15m}
hosts:
  EDGE-RTR-01:
    site: DC1-HALL-A
    interfaces:
      Hu0/0/0/0:
        description: STC 10G (contract 123)
        role: ISP
        severity: disaster
        link_id: STC-CIRCUIT-77
        expected_speed: 5G
        utilization: {enabled: true, threshold: 85, recovery: 80}
"""


class Generation(Base):
    def test_existing_entries_are_preserved_verbatim(self):
        self.w.close()
        self.w = World(iface=EXISTING)
        before = yaml.safe_load(EXISTING)
        rc, out = self.w.run(lines=["l"])
        self.assertIn("A EDGE-RTR-01", out)                       # already approved through the inventory
        self.w.run(lines=["l", "a %s" % row_no(out, "EDGE-RTR-02", "Hu0/0/0/0"), "w", "q"])
        doc = self.w.yaml("config/interfaces.production.yaml")
        self.assertEqual(doc["defaults"], before["defaults"])
        self.assertEqual(doc["hosts"]["EDGE-RTR-01"]["interfaces"], before["hosts"]["EDGE-RTR-01"]["interfaces"])
        self.assertEqual(doc["hosts"]["EDGE-RTR-01"]["site"], "DC1-HALL-A")
        self.assertIn("Hu0/0/0/0", doc["hosts"]["EDGE-RTR-02"]["interfaces"])

    def test_repeat_runs_are_idempotent_and_keep_approvals(self):
        rc, out = self.w.run(lines=["l"])
        self.w.run(lines=["l", "a %s" % row_no(out, "EDGE-RTR-01", "Hu0/0/0/0"), "w", "q"])
        first, dec1 = self.w.read("config/interfaces.production.yaml"), self.w.yaml("config/onboarding.production.yaml")
        rc, out = self.w.run(lines=["w", "w", "q"])                # new session, rewrite twice
        self.assertEqual(self.w.read("config/interfaces.production.yaml"), first)
        dec2 = self.w.yaml("config/onboarding.production.yaml")
        self.assertEqual(dec1["ports"], dec2["ports"])
        rc, out = self.w.run(lines=["l approved"])
        self.assertRegex(out, r"1  A EDGE-RTR-01 +Hu0/0/0/0")
        self.assertEqual(self.w.read("config/interfaces.production.yaml").count("Hu0/0/0/0"), 1)

    def test_exclusions_persist_and_removal_is_explicit(self):
        self.w.close()
        self.w = World(iface=EXISTING)
        rc, out = self.w.run(lines=["l"])
        n = row_no(out, "CORE-SW-01", "Eth1/1")
        self.w.run(lines=["l", "x %s" % n, "q"])
        rc, out = self.w.run(lines=["l"])
        self.assertNotIn("CORE-SW-01", out)                       # excluded stays out of the default list
        rc, out = self.w.run(lines=["l approved", "x 1", "w", "q"])
        self.assertIn("will be REMOVED on write", out)
        self.assertEqual(self.w.yaml("config/interfaces.production.yaml")["hosts"], {})

    def test_severity_never_raised_to_disaster_without_policy(self):
        m = self.w.model()
        self.assertTrue(all(r.severity == "high" for r in m["ports"] if r.candidate))
        write(self.w.path("config/onboarding-rules.yaml"), "severity: {ISP: disaster}\n")
        self.assertEqual(self.w.model()["by_id"]["EDGE-RTR-01|Hu0/0/0/0"].severity, "disaster")

    def test_shipped_example_rules_load_and_unknown_keys_fail(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copy(os.path.join(here, "examples", "onboarding-rules.example.yaml"),
                    self.w.path("config/onboarding-rules.yaml"))
        rules = ob.load_rules(self.w.base)
        self.assertEqual(rules["interface_policy"]["utilization"], {"enabled": True, "threshold": 70, "recovery": 65})
        write(self.w.path("config/onboarding-rules.yaml"), "severty: {ISP: high}\n")
        with self.assertRaises(ob.OnboardError):
            ob.load_rules(self.w.base)

    def test_role_required_before_approval_and_description_fallback(self):
        rc, out = self.w.run(lines=["l all"])
        n = row_no(out, "EDGE-RTR-01", "Gi0/0/0/9")
        rc, out = self.w.run(lines=["l all", "a %s" % n, "r WAN %s" % n, "d %s Branch WAN to Jeddah" % n, "a %s" % n,
                                    "w", "q"])
        self.assertIn("no role suggested", out)
        e = self.w.yaml("config/interfaces.production.yaml")["hosts"]["EDGE-RTR-01"]["interfaces"]["Gi0/0/0/9"]
        self.assertEqual((e["role"], e["description"]), ("WAN", "Branch WAN to Jeddah"))

    def test_health_inventory_only_supported_approved_features(self):
        rc, out = self.w.run(lines=["l"])
        self.w.run(lines=["l", "a %s" % row_no(out, "EDGE-RTR-01", "Hu0/0/0/0"), "h", "f 1 +cpu +ospf",
                          "a 1", "w", "q"])
        doc = self.w.yaml("config/network-health.production.yaml")["devices"]["EDGE-RTR-01"]
        self.assertEqual(sorted(k for k in doc if k != "site"), ["device_unreachable", "ospf", "snmp_stale"])
        self.assertEqual(doc["device_unreachable"], {"severity": "high"})     # never the module's 'disaster' default
        rc, out = self.w.run("--verify")
        self.assertIn("ospf enabled although UNVERIFIED", out)

    def test_invalid_existing_inventory_is_never_rewritten(self):
        bad = EXISTING.replace("        severity: disaster\n", "        severity: disaster\n        notify: false\n")
        self.w.close()
        self.w = World(iface=bad)
        rc, out = self.w.run(lines=["l", "a %s" % "1", "w", "q"])
        self.assertIn("WRITE REFUSED", out)
        self.assertIn("notify=false is not supported", out)
        self.assertEqual(self.w.read("config/interfaces.production.yaml"), bad)

    def test_unusable_interface_name_cannot_be_approved(self):
        self.w.z.add_device("RTR-Z", ports=[dict(name='Gi0/1"x', index="3", alias="ISP uplink")])
        r = self.w.model()["by_id"]['RTR-Z|Gi0/1"x']
        self.assertTrue(any("quote or backslash" in b for b in r.blockers))

    def test_generated_files_pass_strict_validation(self):
        rc, out = self.w.run(lines=["l", "a all", "h", "a all", "w", "q"])
        from netalert import config
        from nethealth import config as hc
        self.assertEqual(config.load(self.w.path("config/interfaces.production.yaml")).problems, [])
        self.assertEqual(hc.load(self.w.path("config/network-health.production.yaml")).problems, [])
        self.assertIn("--- validation: ./apply.sh --dry-run", out)


# ------------------------------------------------------------------------------------------- coverage

class Coverage(Base):
    def _cls(self, rid):
        snap = self.w.snapshot()
        m = self.w.model()
        return coverage.port_coverage(snap, m["by_id"][rid])

    def _util_trigger(self, host, index):
        hid = self.w.z.host_id(host)
        ids = [i for i, it in self.w.z.items.items() if it["hostid"] == hid and it["key_"] in (
            "net.if.in[ifHCInOctets.%s]" % index, "net.if.out[ifHCOutOctets.%s]" % index)]
        return self.w.z.add_trigger("%s high bandwidth" % host, ids)

    def test_stock_link_trigger_without_utilization_is_partial(self):
        cls, why, ev = self._cls("EDGE-RTR-01|Hu0/0/0/0")
        self.assertEqual(cls, coverage.PART)
        self.assertIn("no utilization alert", " ".join(why))

    def test_protected_requires_link_util_fresh_and_ready_notification(self):
        self._util_trigger("EDGE-RTR-01", "1")
        self.assertEqual(self._cls("EDGE-RTR-01|Hu0/0/0/0")[0], coverage.PROT)

    def test_not_protected_when_recovery_missing(self):
        self._util_trigger("EDGE-RTR-01", "1")
        for a in self.w.z.actions.values():
            a["recovery_operations"] = []
        cls, why, _ = self._cls("EDGE-RTR-01|Hu0/0/0/0")
        self.assertEqual(cls, coverage.PART)
        self.assertIn("no recovery operation", " ".join(why))

    def test_not_protected_when_recipients_unreadable(self):
        self._util_trigger("EDGE-RTR-01", "1")
        self.w.z.deny.add("user.get")
        cls, why, _ = self._cls("EDGE-RTR-01|Hu0/0/0/0")
        self.assertEqual(cls, coverage.PART)
        self.assertIn("recipients not readable", " ".join(why))

    def test_not_protected_when_recipient_lacks_host_permission_or_severity(self):
        self._util_trigger("EDGE-RTR-01", "1")
        self.w.z.usergroups[self.w.ids["noc"]]["rights"] = {"3": 3}
        self.assertEqual(self._cls("EDGE-RTR-01|Hu0/0/0/0")[0], coverage.PART)
        self.w.z.usergroups[self.w.ids["noc"]]["rights"] = {"2": 2}
        for u in self.w.z.users.values():
            u["medias"][0]["severity"] = str(1 << 5)                # disaster only; trigger is high
        self.assertEqual(self._cls("EDGE-RTR-01|Hu0/0/0/0")[0], coverage.PART)

    def test_deny_in_any_user_group_wins(self):
        self._util_trigger("EDGE-RTR-01", "1")
        self.assertEqual(self._cls("EDGE-RTR-01|Hu0/0/0/0")[0], coverage.PROT)
        deny = self.w.z.add_usergroup("Deny network")
        self.w.z.usergroups[deny]["rights"] = {"2": 0}
        for u in self.w.z.users.values():
            u["groups"] = [deny] + u["groups"]                        # deny listed first, read-write after it
        self.assertEqual(self._cls("EDGE-RTR-01|Hu0/0/0/0")[0], coverage.PART)

    def test_disabled_or_gated_stock_trigger_is_not_coverage(self):
        for t in self.w.z.triggers.values():
            t["status"] = "1"
        self.assertEqual(self._cls("EDGE-RTR-01|Hu0/0/0/0")[0], coverage.NOTC)
        for t in self.w.z.triggers.values():
            t["status"] = "0"
        self.w.z.add_macro(self.w.ids["r1"], '{$IFCONTROL:"Hu0/0/0/0"}', "0")
        self.assertEqual(self._cls("EDGE-RTR-01|Hu0/0/0/0")[0], coverage.NOTC)

    def test_action_filter_evaluation(self):
        host = {"groupids": ["2"], "hostid": "9", "templateids": [], "tags": [("site", "DC1")]}
        trig = {"triggerid": "1", "name": "x link down", "priority": 4, "tags": [("netops_alert", "link_down")]}
        c = lambda t, op, v, **kw: dict({"conditiontype": str(t), "operator": str(op), "value": v}, **kw)
        self.assertTrue(coverage.eval_filter({"evaltype": "0", "conditions": [c(25, 0, "netops_alert")]}, host, trig))
        self.assertFalse(coverage.eval_filter({"evaltype": "0", "conditions": [c(4, 5, "5")]}, host, trig))
        f = {"evaltype": "3", "formula": "(A or B) and not C", "conditions": [
            c(0, 0, "7", formulaid="A"), c(26, 0, "DC1", value2="site", formulaid="B"), c(4, 0, "2", formulaid="C")]}
        self.assertTrue(coverage.eval_filter(f, host, trig))
        f["formula"] = "A and __import__"
        self.assertIsNone(coverage.eval_filter(f, host, trig))
        self.assertIsNone(coverage.eval_filter({"evaltype": "0", "conditions": [c(6, 4, "1-7,00:00-24:00")]}, host, trig))

    def test_report_sections_and_preserved_alerts(self):
        self.w.run("--report")
        rep = self.w.read("state/onboarding/production/coverage-latest.md")
        for s in ("| PROTECTED / VERIFIED |", "## Existing alerts that are preserved", "EDGE-RTR-01 Hu0/0/0/0 link down (stock)",
                  "## ISP / P2P endpoint relationships", "SUGGESTED (description cross-reference only, NOT verified)",
                  "## Findings, blind spots and limits"):
            self.assertIn(s, rep)


# ------------------------------------------------------------------------------------------- safety gates

ACTION = """
alert_action:
  name: "NETOPS-IaC Interface Alerts"
  enabled: true
  usergroups: ["NOC Network"]
  media_type: "Email"
"""


class Gates(Base):
    def approve_isp(self):
        rc, out = self.w.run(lines=["l"])
        self.w.run(lines=["l", "a %s" % row_no(out, "EDGE-RTR-01", "Hu0/0/0/0"), "w", "q"])

    def test_identity_mismatch_stops_before_discovery(self):
        self.w.z.gmacros["1"]["value"] = "lab"
        rc, out = self.w.run("--report")
        self.assertEqual(rc, icli.EXIT_SAFETY)
        self.assertIn("IDENTITY MISMATCH", out)
        self.assertNotIn("host.get", [m for m, _ in self.w.z.calls])

    def test_unclaimed_server_can_be_audited_but_not_deployed(self):
        self.w.z.gmacros.clear()
        self.assertEqual(self.w.run("--report")[0], 0)
        self.approve_isp()
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("not claimed", out)

    def test_api_failure_aborts_without_writing_files(self):
        before = self.w.read("config/interfaces.production.yaml")
        self.w.z.fail_on["trigger.get"] = ApiUnavailable("connection reset")
        rc, out = self.w.run(lines=["a all", "w"])
        self.assertEqual(rc, icli.EXIT_API)
        self.assertIn("discovery aborted", out)
        self.assertEqual(self.w.read("config/interfaces.production.yaml"), before)
        self.assertFalse(os.path.exists(self.w.path("config/onboarding.production.yaml")))

    def test_permission_gaps_are_reported_not_fatal(self):
        self.w.z.deny.update(["user.get", "usergroup.get"])
        rc, out = self.w.run("--report")
        self.assertEqual(rc, 0, out)
        rep = self.w.read("state/onboarding/production/coverage-latest.md")
        self.assertIn("users and their media not readable with this token", rep)

    def test_hand_edit_blocks_deploy(self):
        self.approve_isp()
        p = self.w.path("config/interfaces.production.yaml")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("# edited\n")
        rc, out = self.w.run("--deploy", "--confirm", "production")
        self.assertEqual(rc, 1)
        self.assertIn("changed since the last reviewed write", out)
        self.assertEqual(self.w.z.writes(), [])

    def test_vanished_approved_port_blocks_deploy(self):
        self.approve_isp()
        hid = self.w.ids["r1"]
        for iid in [i for i, it in self.w.z.items.items() if it["hostid"] == hid and it["key_"].endswith(".1]")]:
            del self.w.z.items[iid]
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("port no longer discovered on host", out)

    def test_production_deploy_requires_confirm(self):
        self.approve_isp()
        rc, out = self.w.run("--deploy")
        self.assertEqual(rc, icli.EXIT_SAFETY)
        self.assertIn("--confirm production", out)
        self.assertEqual(self.w.z.writes(), [])

    def test_deploy_then_reconcile_with_existing_managed_objects(self):
        self.w.close()
        self.w = World(prod_extra=ACTION)
        self.approve_isp()
        rc, out = self.w.run("--deploy", "--confirm", "production")
        self.assertEqual(rc, 0, out)
        self.assertIn("verification plan is empty", out)
        self.assertEqual(self.w.apply("--dry-run")[1].splitlines()[-1], "No changes required.")
        # what the template's LLD would create on the host, gated by the macros apply.sh just wrote
        z, hid = self.w.z, self.w.ids["r1"]
        own = z.add_netops_items(hid, "Hu0/0/0/0", "1")
        for alert in ("link_down", "util_rx", "util_tx"):
            for prio in (2, 3, 4, 5):                              # four severity variants; macros pick one
                z.add_trigger("NETOPS %s" % alert, [own], priority=prio,
                              tags=[("netops_alert", alert), ("if_name", "Hu0/0/0/0")])
        for t in list(z.triggers.values()):                        # remove the stock trigger: project coverage only
            if "(stock)" in t["description"]:
                t["status"] = "1"
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 0, out)
        for a in z.actions.values():                               # only the NETOPS-IaC e-mail action may count
            if not a["name"].startswith("NETOPS-IaC"):
                a["status"] = "1"
        snap = self.w.snapshot()
        cls, why, ev = coverage.port_coverage(snap, self.w.model()["by_id"]["EDGE-RTR-01|Hu0/0/0/0"])
        self.assertEqual(cls, coverage.PROT, why)
        self.assertIn("NETOPS-IaC Interface Alerts", " ".join(ev["notify"]))
        # a second onboarding run over the deployed state changes nothing
        before = self.w.read("config/interfaces.production.yaml")
        self.w.run(lines=["w", "q"])
        self.assertEqual(self.w.read("config/interfaces.production.yaml"), before)
        self.assertEqual(self.w.apply("--dry-run")[1].splitlines()[-1], "No changes required.")

    def test_empty_inventory_deploy_never_removes_everything(self):
        self.w.close()
        self.w = World(prod_extra=ACTION)
        self.approve_isp()
        self.assertEqual(self.w.run("--deploy", "--confirm", "production")[0], 0)
        rc, out = self.w.run(lines=["l approved", "x 1", "w", "q"])
        rc, out = self.w.run("--deploy", "--confirm", "production")
        self.assertIn("deliberately not automated", out)
        self.assertIn('{$NETOPS.IF.MATCH}', self.w.z.host_macro_map("EDGE-RTR-01"))


# ------------------------------------------------------------------------------------------- setup

class Setup(Base):
    def test_first_run_setup_writes_private_env_and_url_guard(self):
        write(self.w.path("config/environments/production.yaml"),
              PROD_YAML.replace(r"'^https://zbx\.prod\.example$'", "'^CHANGE-ME-TO-YOUR-PRODUCTION-URL-REGEX$'"))
        answers = iter(["https://zbx.prod.example", "", "y"])
        out = []
        rc = onboard_cli.run(["--env", "production", "--setup"], environ={}, out=out.append, lines=[], base=self.w.base,
                             transport_factory=lambda u, t, v: self.w.z.transport(t), now=NOW,
                             ask=lambda q: next(answers), secret=lambda q: "tok")
        self.assertEqual(rc, 0, out)
        envf = self.w.path(".env")
        self.assertEqual(stat.S_IMODE(os.stat(envf).st_mode), 0o600)
        self.assertIn("ZABBIX_TOKEN_PRODUCTION=tok", self.w.read(".env"))
        self.assertIn(r"url_regex: '^https://zbx\.prod\.example/?$'", self.w.read("config/environments/production.yaml"))
        rc, text = self.w.run("--report", environ={})               # .env is picked up on the next run
        self.assertEqual(rc, 0, text)

    def test_missing_settings_without_terminal_is_a_clear_error(self):
        rc, out = self.w.run("--report", environ={}, lines=[])
        self.assertEqual(rc, icli.EXIT_USAGE)
        self.assertIn("--setup", out)


if __name__ == "__main__":
    unittest.main()
