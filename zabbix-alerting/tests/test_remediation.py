"""Regression tests for the v1.1.0 independent review (CONDITIONAL NO-GO on 98bd925).

Each test asserts the SAFE behaviour. Run against 98bd925 they fail (see docs/REMEDIATION-v1.1.md), which is the
evidence that the defect existed and is fixed. Offline only: an in-memory Zabbix 7.0 model, not a real server.
"""
import http.server
import os
import threading
import unittest

from netalert import coverage, netbox
from netalert import onboarding as ob
from netalert.zbx import ApiUnavailable, HttpTransport, ZabbixClient
from tests.discovery_fixture import DiscoveryZabbix, add_netops, stock_link, stock_util
from tests.helpers import write
from tests.test_onboarding import World, row_no


def util(w, host="EDGE-RTR-01", port="Hu0/0/0/0", idx="1", **kw):
    """Utilization alerts of the approved policy (70%/65%, RX and TX) - only the NETOPS template implements it."""
    return add_netops(w.z, host, port, idx, **kw)


def stock_bw(w, host="EDGE-RTR-01", port="Hu0/0/0/0", idx="1"):
    hid = w.z.host_id(host)
    ids = [i for i, it in w.z.items.items() if it["hostid"] == hid and it["key_"] in (
        "net.if.in[ifHCInOctets.%s]" % idx, "net.if.out[ifHCOutOctets.%s]" % idx, "net.if.speed[ifHighSpeed.%s]" % idx)]
    return w.z.add_trigger("%s bandwidth" % port, ids, expression=stock_util(host, port, idx))


def cls(w, rid="EDGE-RTR-01|Hu0/0/0/0"):
    return coverage.port_coverage(w.snapshot(), w.model()["by_id"][rid])


class Base(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def assertNotProtected(self, rid="EDGE-RTR-01|Hu0/0/0/0"):
        c, why, _ = cls(self.w, rid)
        self.assertNotIn(c, coverage.PROTECTED_CLASSES, why)
        return c, why


# =========================================================================================== P0-1 coverage

class CoverageNeverOverclaims(Base):
    def setUp(self):
        Base.setUp(self)
        util(self.w)                                   # baseline: CONFIG VERIFIED, so each test removes ONE proof
        self.assertEqual(cls(self.w)[0], coverage.CONFIG)

    def test_managed_port_without_utilization_alert(self):                       # R1
        z = self.w.z
        z.add_netops_items(self.w.ids["r1"], "Gi0/0/0/9", "9")
        st = [i for i, it in z.items.items() if it["hostid"] == self.w.ids["r1"] and it["key_"] == "net.if.status[ifOperStatus.9]"][0]
        z.add_trigger("Gi0/0/0/9 down", [st], expression=stock_link("EDGE-RTR-01", "Gi0/0/0/9", "9"))
        c, why = self.assertNotProtected("EDGE-RTR-01|Gi0/0/0/9")
        self.assertIn("no proven RX utilization alert at the approved policy 70%/65%", " ".join(why))

    def test_trigger_on_status_item_must_test_link_down(self):                   # R2
        for t in self.w.z.triggers.values():
            if "(stock)" in t["description"]:
                t["expression"] = "nodata(/EDGE-RTR-01/net.if.status[ifOperStatus.1],30m)=1"
        c, why = self.assertNotProtected()
        self.assertIn("does not prove a link-down", " ".join(why))
        for t in self.w.z.triggers.values():
            if "(stock)" in t["description"]:
                t["expression"] = "last(/EDGE-RTR-01/net.if.status[ifOperStatus.1])=7"   # lowerLayerDown only
        self.assertNotProtected()

    def test_recovery_recipients_verified_separately(self):                     # R3
        nobody = self.w.z.add_usergroup("Nobody")
        for a in self.w.z.actions.values():
            a["recovery_operations"][0]["opmessage_grp"] = [{"usrgrpid": nobody}]
        c, why = self.assertNotProtected()
        self.assertIn("no eligible recovery recipient", " ".join(why))

    def test_recovery_media_type_disabled(self):
        sms = self.w.z.add_mediatype("SMS")
        self.w.z.mediatypes[sms]["status"] = "1"
        for a in self.w.z.actions.values():
            a["recovery_operations"][0]["opmessage"]["mediatypeid"] = sms
        self.assertNotProtected()

    def test_media_active_period_restricted(self):                              # R4
        for u in self.w.z.users.values():
            u["medias"][0]["period"] = "7,09:00-10:00"
        c, why = self.assertNotProtected()
        self.assertIn("media active only 7,09:00-10:00", " ".join(why))

    def test_nested_host_group_negative_condition(self):                        # R5
        z = self.w.z
        z.groups["8"], z.groups["9"] = "Network devices/DC", "Network devices/DC/Edge"
        z.hosts[self.w.ids["r1"]]["groupids"] = ["9"]
        z.usergroups[self.w.ids["noc"]]["rights"] = {"9": 2}
        for a in z.actions.values():
            a["filter"]["conditions"] = [{"conditiontype": "0", "operator": "1", "value": "8", "formulaid": "A"}]
        self.assertNotProtected()

    def test_template_level_tag_negative_condition(self):                       # R6
        z = self.w.z
        z.templates[self.w.ids["vendor"]]["tags"] = [{"tag": "noalert", "value": ""}]
        for a in z.actions.values():
            a["filter"]["conditions"].append({"conditiontype": "25", "operator": "1", "value": "noalert", "formulaid": "B"})
        self.assertNotProtected()

    def test_template_condition_respects_inheritance(self):
        z = self.w.z
        parent = z.add_template("Interfaces SNMP")
        z.templates[self.w.ids["vendor"]]["parents"] = [parent]
        for a in z.actions.values():                     # "not from template Interfaces SNMP": inherited -> no match
            a["filter"]["conditions"].append({"conditiontype": "13", "operator": "1", "value": parent, "formulaid": "B"})
        self.assertNotProtected()

    def test_unresolvable_gate_macro_fails_closed(self):
        self.w.z.deny.add("template.get")                # {$IFCONTROL} lives on the template: cannot be resolved
        c, why = self.assertNotProtected()
        self.assertIn("cannot be resolved", " ".join(why))

    def test_gate_closed_at_template_level(self):
        for m in self.w.z.macros.values():
            if m["macro"] == "{$IFCONTROL}":
                m["value"] = "0"
        c, why = self.assertNotProtected()
        self.assertEqual(c, coverage.NOTC)

    def test_only_delayed_problem_operation(self):
        for a in self.w.z.actions.values():
            a["operations"][0]["esc_step_from"] = "3"
        c, why = self.assertNotProtected()
        self.assertIn("no immediate (step 1) problem operation", " ".join(why))

    def test_time_period_condition_fails_closed(self):
        for a in self.w.z.actions.values():
            a["filter"]["conditions"].append({"conditiontype": "6", "operator": "4", "value": "1-5,08:00-17:00",
                                              "formulaid": "B"})
        self.assertNotProtected()

    def test_host_in_maintenance(self):
        self.w.z.hosts[self.w.ids["r1"]]["maintenance_status"] = "1"
        self.assertNotProtected()

    def test_delivery_tested_requires_sent_problem_and_recovery(self):
        stock = [t for t in self.w.z.triggers.values() if "(stock)" in t["description"]][0]["triggerid"]
        act = self.w.ids["action"]
        self.w.z.add_delivery(stock, act, recovery=False)
        self.assertEqual(cls(self.w)[0], coverage.CONFIG)              # problem only: not delivery tested
        self.w.z.add_delivery(stock, act, status="2")                  # failed sends do not count
        self.assertEqual(cls(self.w)[0], coverage.CONFIG)
        self.w.z.add_delivery(stock, act)
        c, why, _ = cls(self.w)
        self.assertEqual(c, coverage.CONFIG)                           # correlated, but only historical evidence
        self.assertIn("historical delivery evidence only", " ".join(why))
        rc, out = self.w.run("--record-fault-test", "EDGE-RTR-01|Hu0/0/0/0")
        self.assertEqual(rc, 0, out)
        self.assertEqual(cls(self.w)[0], coverage.PROT)
        self.w.z.deny.add("event.get")                                 # history unreadable: never DELIVERY TESTED
        c, why, _ = cls(self.w)
        self.assertEqual(c, coverage.CONFIG)
        self.assertIn("alert history not readable", " ".join(why))


# =========================================================================================== P0-2 pairing

class Pairing(Base):
    def setUp(self):
        Base.setUp(self)
        self.w.z.add_device("EDGE-RTR-03", templates=(self.w.ids["vendor"],),
                            ports=[dict(name="Te0/0/0/1", index="2", alias="P2P TO EDGE-RTR-01")])
        rc, out = self.w.run(lines=["l"])
        self.a, self.b, self.c = (row_no(out, h, "Te0/0/0/1") for h in ("EDGE-RTR-01", "EDGE-RTR-02", "EDGE-RTR-03"))

    def doc(self):
        d = self.w.yaml("config/interfaces.production.yaml")["hosts"]
        return dict((h, d[h]["interfaces"]["Te0/0/0/1"].get("link_id")) for h in d if "Te0/0/0/1" in d[h]["interfaces"])

    def test_repair_releases_old_partner_and_never_reuses_link_id(self):       # R7
        self.w.run(lines=["l", "a %s,%s,%s" % (self.a, self.b, self.c), "p %s %s" % (self.a, self.b), "w", "q"])
        old = self.doc()
        self.assertEqual(old["EDGE-RTR-01"], old["EDGE-RTR-02"])
        self.w.run(lines=["l", "p %s %s" % (self.a, self.c), "w", "q"])
        new = self.doc()
        self.assertEqual(new["EDGE-RTR-01"], new["EDGE-RTR-03"])
        self.assertNotEqual(new["EDGE-RTR-01"], old["EDGE-RTR-01"])
        self.assertIsNone(new.get("EDGE-RTR-02"))                   # stale id removed from the released end
        dec = self.w.yaml("config/onboarding.production.yaml")["ports"]
        self.assertIsNone(dec["EDGE-RTR-02|Te0/0/0/1"].get("pair"))
        rc, out = self.w.run("--verify")                            # B is a P2P with no peer now: must be resolved
        self.assertIn("EDGE-RTR-02 / Te0/0/0/1: P2P peer unresolved", out)
        self.assertEqual(rc, 1)

    def test_single_ended_releases_partner(self):
        self.w.run(lines=["l", "a %s,%s" % (self.a, self.b), "p %s %s" % (self.a, self.b), "w", "q"])
        self.w.run(lines=["l", "p %s -" % self.a, "w", "q"])
        self.assertEqual(self.doc(), {"EDGE-RTR-01": None, "EDGE-RTR-02": None})
        rc, out = self.w.run("--verify")
        self.assertIn("EDGE-RTR-02 / Te0/0/0/1: P2P peer unresolved", out)
        self.assertNotIn("EDGE-RTR-01 / Te0/0/0/1: P2P", out)

    def test_endpoint_removal_drops_link_id_and_blocks_until_resolved(self):
        self.w.run(lines=["l", "a %s,%s" % (self.a, self.b), "p %s %s" % (self.a, self.b), "w", "q"])
        self.w.run(lines=["l approved", "x 2", "w", "q"])            # remove EDGE-RTR-02 Te0/0/0/1
        self.assertEqual(self.doc(), {"EDGE-RTR-01": None})
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("is not approved", out)

    def test_netbox_topology_change_is_a_blocker(self):
        peers = {"EDGE-RTR-01": "EDGE-RTR-02", "EDGE-RTR-02": "EDGE-RTR-01"}

        def opener(url):
            if "dcim/devices" in url:
                return {"results": [{"id": i, "name": n} for i, n in enumerate(sorted(peers), 1)], "next": None}
            dev = sorted(peers)[int(url.split("device_id=")[1].split("&")[0]) - 1]
            return {"results": [{"name": "TenGigE0/0/0/1", "cable": {"id": 9},
                                 "link_peers": [{"device": {"name": peers[dev]}, "name": "TenGigE0/0/0/1"}]}], "next": None}
        env = dict(self.w.env, NETBOX_URL="https://netbox.example", NETBOX_TOKEN="x")
        self.w.netbox_opener = opener
        self.w.run(lines=["l", "a %s,%s,%s" % (self.a, self.b, self.c), "p %s -" % self.c, "w", "q"], environ=env)
        dec = self.w.yaml("config/onboarding.production.yaml")["ports"]
        self.assertEqual(dec["EDGE-RTR-01|Te0/0/0/1"]["pair_source"], "netbox-cable")      # persisted, auditable
        peers.update({"EDGE-RTR-01": "EDGE-RTR-03", "EDGE-RTR-03": "EDGE-RTR-01"})       # re-cabled in NetBox
        peers.pop("EDGE-RTR-02")
        rc, out = self.w.run("--verify", environ=env)
        self.assertEqual(rc, 1)
        self.assertIn("NetBox now shows a cable to EDGE-RTR-03|Te0/0/0/1", out)

    def test_inconsistent_existing_inventory_is_blocked(self):
        inv = """hosts:
  EDGE-RTR-01: {interfaces: {Te0/0/0/1: {description: x, role: P2P, link_id: L1}}}
  EDGE-RTR-02: {interfaces: {Te0/0/0/1: {description: x, role: P2P, link_id: L1}}}
  EDGE-RTR-03: {interfaces: {Te0/0/0/1: {description: x, role: P2P, link_id: L1}}}
"""
        self.w.close()
        self.w = World(iface=inv)
        self.w.z.add_device("EDGE-RTR-03", ports=[dict(name="Te0/0/0/1", index="2", alias="x")])
        m = self.w.model()
        self.assertTrue(all(any("used by 3 entries" in i for i in m["by_id"]["%s|Te0/0/0/1" % h].issues)
                            for h in ("EDGE-RTR-01", "EDGE-RTR-02", "EDGE-RTR-03")))
        before = self.w.read("config/interfaces.production.yaml")
        rc, out = self.w.run(lines=["w", "q"])
        self.assertIn("WRITE REFUSED", out)                        # never repaired silently
        self.assertEqual(self.w.read("config/interfaces.production.yaml"), before)
        self.assertEqual(self.w.run("--verify")[0], 1)
        rc, out = self.w.run(lines=["l approved"])                 # operator decides every end, then it can be written
        a, b, c = (row_no(out, h, "Te0/0/0/1") for h in ("EDGE-RTR-01", "EDGE-RTR-02", "EDGE-RTR-03"))
        rc, out = self.w.run(lines=["l approved", "p %s %s" % (a, b), "p %s -" % c, "w", "q"])
        self.assertNotIn("WRITE REFUSED", out)
        d = self.w.yaml("config/interfaces.production.yaml")["hosts"]
        la, lb = d["EDGE-RTR-01"]["interfaces"]["Te0/0/0/1"]["link_id"], d["EDGE-RTR-02"]["interfaces"]["Te0/0/0/1"]["link_id"]
        self.assertEqual(la, lb)
        self.assertNotEqual(la, "L1")
        self.assertNotIn("link_id", d["EDGE-RTR-03"]["interfaces"]["Te0/0/0/1"])

    def test_unchanged_relationship_keeps_historical_link_id(self):
        inv = """hosts:
  EDGE-RTR-01: {interfaces: {Te0/0/0/1: {description: x, role: P2P, link_id: CIRCUIT-P2P-77}}}
  EDGE-RTR-02: {interfaces: {Te0/0/0/1: {description: x, role: P2P, link_id: CIRCUIT-P2P-77}}}
"""
        self.w.close()
        self.w = World(iface=inv)
        self.w.run(lines=["w", "q"])
        d = self.w.yaml("config/interfaces.production.yaml")["hosts"]
        self.assertEqual(d["EDGE-RTR-01"]["interfaces"]["Te0/0/0/1"]["link_id"], "CIRCUIT-P2P-77")
        self.assertEqual(d["EDGE-RTR-02"]["interfaces"]["Te0/0/0/1"]["link_id"], "CIRCUIT-P2P-77")
        dec = self.w.yaml("config/onboarding.production.yaml")["ports"]
        self.assertEqual(dec["EDGE-RTR-01|Te0/0/0/1"]["pair_source"], "inventory link_id")
        self.assertEqual(self.w.run("--verify")[0], 0)

    def test_non_reciprocal_decisions_are_blocked(self):
        self.w.run(lines=["l", "a %s,%s" % (self.a, self.b), "p %s %s" % (self.a, self.b), "w", "q"])
        p = self.w.path("config/onboarding.production.yaml")
        dec = ob.load_decisions(p)
        dec["ports"]["EDGE-RTR-02|Te0/0/0/1"]["pair"] = "EDGE-RTR-03|Te0/0/0/1"    # hand edit / corruption
        ob.save_decisions(p, dec)
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("not reciprocal", out)

    def test_link_id_checker(self):
        m = self.w.model()
        doc = {"hosts": {"A": {"interfaces": {"x": {"link_id": "L"}}}, "B": {"interfaces": {"y": {"link_id": "L"}}}}}
        self.assertIn("not a resolved pair", ob.check_link_ids(doc, m)[0])


# =========================================================================================== P0-3 gate

class Gate(Base):
    def approve(self, *ports):
        rc, out = self.w.run(lines=["l"])
        rows = ",".join(row_no(out, h, p) for h, p in ports)
        return self.w.run(lines=["l", "a %s" % rows, "w", "q"])

    def test_decisions_changed_after_write_block_deploy(self):                  # R8
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        self.w.run(lines=["l approved", "x 1", "q"])                    # excluded, not written
        tok, rc, out = self.w.token()
        self.assertEqual(rc, 1)
        self.assertIn("decisions changed after the last write", out)
        rc, out = self.w.run("--deploy", "--approve", "anything", "--confirm", "production")
        self.assertEqual(self.w.z.writes(), [])

    def test_inventory_must_equal_regenerated_inventory(self):
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        p = self.w.path("config/interfaces.production.yaml")
        text = self.w.read("config/interfaces.production.yaml").replace("severity: high", "severity: warning")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        dpath = self.w.path("config/onboarding.production.yaml")
        dec = ob.load_decisions(dpath)                                  # another tool also "fixes" the recorded hash
        dec["written"]["interfaces_sha256"] = ob.file_sha(p)
        ob.save_decisions(dpath, dec)
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("differs from what the approved decisions", out)

    def test_approval_token_binds_the_reviewed_state(self):
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        tok, rc, out = self.w.token()
        self.assertEqual(rc, 0, out)
        self.approve(("EDGE-RTR-02", "Hu0/0/0/0"))                      # state changes after the review
        rc, out = self.w.run("--deploy", "--approve", tok, "--confirm", "production")
        self.assertEqual(rc, 3)
        self.assertIn("does not match the current approval token", out)
        self.assertEqual(self.w.z.writes(), [])

    def test_missing_identity_evidence_blocks(self):
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        dpath = self.w.path("config/onboarding.production.yaml")
        dec = ob.load_decisions(dpath)
        dec["ports"]["EDGE-RTR-01|Hu0/0/0/0"].pop("itemid")
        dec["written"]["decisions_sha256"] = ob.decisions_sha(dec)
        ob.save_decisions(dpath, dec)
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("no recorded identity evidence", out)

    def test_production_code_must_be_clean_and_pinned(self):
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        self.w.code = ("c0ffee", ["code differs from commit c0ffee (local modifications: M netalert/coverage.py)"])
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        self.assertIn("local modifications", out)
        self.w.close()
        self.w = World(pin="")
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        rc, out = self.w.run("--verify")
        self.assertIn("production deployments must be pinned", out)

    def test_unverified_health_blocks_until_evidence_expected_and_acceptance(self):   # R9
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        self.w.run(lines=["h", "f 1 +ospf", "a 1", "w", "q"])
        rc, out = self.w.run("--verify")
        self.assertEqual(rc, 1)
        for msg in ("ospf UNVERIFIED", "no expected-neighbor list", "Network Health is not accepted for production"):
            self.assertIn(msg, out)
        self.w.run(lines=["h", "ev 1 ospf snmpwalk CHG-1234", "ex 1 ospf 10.0.0.2,10.0.0.3", "w", "q"])
        rc, out = self.w.run("--verify")
        self.assertNotIn("ospf UNVERIFIED", out)
        self.assertNotIn("expected-neighbor", out)
        self.assertIn("Network Health is not accepted for production", out)
        doc = self.w.yaml("config/network-health.production.yaml")["devices"]["EDGE-RTR-01"]["ospf"]
        self.assertEqual(doc["expected"], ["10.0.0.2", "10.0.0.3"])

    def test_preflight_runs_before_the_first_write_and_partial_apply_is_reported(self):
        self.w.close()
        self.w = World(prod_extra="network_health_lab_acceptance: 'LAB-ACC-42'\n")
        self.approve(("EDGE-RTR-01", "Hu0/0/0/0"))
        self.w.run(lines=["h", "f 1 +ospf", "ev 1 ospf CHG-1", "ex 1 ospf 10.0.0.2", "a 1", "w", "q"])
        rc, out = self.w.deploy()
        self.assertIn("PARTIAL APPLY: completed = Interface Alerting", out)   # the mock rejects the health import
        self.assertNotEqual(rc, 0)


# =========================================================================================== P1 network safety

class _Sink(http.server.BaseHTTPRequestHandler):
    got = {}

    def do_GET(self):
        _Sink.got[self.path] = self.headers.get("Authorization")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"jsonrpc":"2.0","result":"7.0.30","id":1,"results":[],"next":null}')

    do_POST = do_GET

    def log_message(self, *a):
        pass


class Credentials(unittest.TestCase):
    def setUp(self):
        _Sink.got = {}
        self.sink = http.server.HTTPServer(("127.0.0.1", 0), _Sink)
        port = self.sink.server_port

        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:%d/leak%s" % (port, self.path))
                self.end_headers()
            do_POST = do_GET

            def log_message(self, *a):
                pass
        self.red = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
        for s in (self.sink, self.red):
            threading.Thread(target=s.serve_forever, daemon=True).start()

    def tearDown(self):
        for s in (self.sink, self.red):
            s.shutdown()
            s.server_close()

    def test_zabbix_transport_refuses_redirects(self):                          # R11 (also in v1.0.2 code)
        c = ZabbixClient(HttpTransport("http://127.0.0.1:%d" % self.red.server_port, "ZBXTOKEN"))
        with self.assertRaises(ApiUnavailable) as ctx:
            c.call("host.get", {})
        self.assertIn("redirect", str(ctx.exception))
        self.assertEqual(_Sink.got, {})

    def test_netbox_refuses_redirects(self):
        with self.assertRaises(netbox.NetBoxError):
            netbox.NetBox("http://127.0.0.1:%d" % self.red.server_port, "NBTOKEN").get_all("dcim/devices", {})
        self.assertEqual(_Sink.got, {})

    def test_netbox_pagination_stays_on_origin_and_api_path(self):              # R10
        seen = []

        def opener(url):                       # one foreign hop only: the original code would loop forever
            seen.append(url)
            return {"results": [], "next": nxt[0] if len(seen) == 1 else None}
        for bad in ("https://evil.example/api/dcim/devices/?offset=50", "http://netbox.example/api/dcim/devices/",
                    "https://netbox.example/admin/", "https://netbox.example:8443/api/dcim/devices/"):
            nxt, seen[:] = [bad], []
            with self.assertRaises(netbox.NetBoxError):
                netbox.NetBox("https://netbox.example", "T", opener=opener).get_all("dcim/devices", {})
            self.assertEqual(len(seen), 1, bad)
        good = ["https://netbox.example/api/dcim/devices/?offset=50"]

        def opener2(url):
            seen.append(url)
            return {"results": [1], "next": good.pop() if good else None}
        seen[:] = []
        self.assertEqual(netbox.NetBox("https://netbox.example", "T", opener=opener2).get_all("dcim/devices", {}), [1, 1])


# =========================================================================================== P1 network health

class NetworkHealth(unittest.TestCase):
    def test_expected_lists_validated_and_written_as_macro(self):
        from nethealth import config as hc, planner as hp
        d = hc.parse({"devices": {"R1": {"ospf": {"expected": ["10.0.0.2", "bad"]}}}})
        self.assertTrue(any("IPv4" in m for _, _, m in d.problems))
        d = hc.parse({"devices": {"R1": {"ospf": {"expected": ["10.0.0.3", "10.0.0.2"]}, "bgp": True}}})
        self.assertEqual(d.problems, [])
        m = hp.host_macros(d.devices["R1"])
        self.assertEqual(m["{$NHEALTH.OSPF.EXPECTED}"], "10.0.0.2,10.0.0.3")
        self.assertNotIn("{$NHEALTH.BGP.EXPECTED}", m)

    def test_templates_detect_blindness_and_never_delete_lost_neighbors(self):
        from nethealth import templates as T
        for name, feat in ((T.OSPF, "ospf"), (T.BGP, "bgp")):
            doc = T.build(name)["zabbix_export"]
            rule = doc["templates"][0]["discovery_rules"][0]
            self.assertEqual(rule["lifetime_type"], "DELETE_NEVER")
            self.assertEqual(rule["enabled_lifetime_type"], "DISABLE_NEVER")
            exprs = [t["expression"] for t in doc["triggers"]]
            self.assertTrue(any("nodata(/%s/nhealth.%s.alive," % (name, feat) in e for e in exprs))
            self.assertTrue(any("last(/%s/nhealth.%s.expected.missing)>0" % (name, feat) in e for e in exprs))
            items = dict((i["key"], i) for i in doc["templates"][0]["items"])
            self.assertNotEqual(items["nhealth.%s.alive" % feat].get("history"), "0")    # nodata needs stored values
            self.assertNotIn("trends", items["nhealth.%s.expected.names" % feat])

    def test_production_health_apply_blocked_without_lab_acceptance(self):
        from nethealth import cli as hcli
        from tests.helpers import PROD_YAML
        w = World()
        try:
            write(w.path("config/network-health.production.yaml"),
                  "devices:\n  EDGE-RTR-01:\n    device_unreachable: {severity: high}\n")
            out = []
            rc = hcli.run(["--env", "production", "--confirm", "production"], environ=dict(w.env), out=out.append,
                          base=w.base, transport_factory=lambda u, t, v: w.z.transport(t))
            self.assertEqual(rc, 3, out)
            self.assertIn("not accepted for production", "\n".join(out))
            self.assertEqual(w.z.writes(), [])
        finally:
            w.close()


if __name__ == "__main__":
    unittest.main()
