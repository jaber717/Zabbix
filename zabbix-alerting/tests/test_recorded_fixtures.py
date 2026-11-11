"""Replay sanitized recordings of a REAL Zabbix 7.0 (tests/fixtures/recorded/*.json, made with
scripts/capture-api-fixtures.py). With no recordings present the replay test reports NOT RUN (skip) - it never
passes on its own. The record/sanitize/replay machinery itself is proven offline below.
"""
import glob
import json
import os
import unittest

from netalert import apirecord, coverage, discovery
from netalert import onboarding as ob
from netalert.zbx import ZabbixClient
from tests.discovery_fixture import NOW, standard_world

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDED = sorted(glob.glob(os.path.join(HERE, "fixtures", "recorded", "*.json")))


class RecordedRealZabbix(unittest.TestCase):
    def test_replay_real_recordings(self):
        if not RECORDED:
            self.skipTest("NOT RUN: no recorded real-Zabbix fixtures in tests/fixtures/recorded/ "
                          "(capture them in LAB with scripts/capture-api-fixtures.py)")
        for path in RECORDED:
            with self.subTest(fixture=os.path.basename(path)):
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                client = ZabbixClient(apirecord.ReplayTransport(data["calls"]), read_only=True)
                snap = discovery.discover(client, now=data["taken_at"])
                self.assertEqual(client.writes_made(), [])
                model = ob.build(snap, ob.load_rules("/nonexistent"), {}, {}, ob.load_decisions("/nonexistent"), snap["taken_at"])
                coverage.audit(snap, model)
                with_items = [h for h in snap["hosts"].values() if h["ports"]]
                self.assertTrue(with_items, "no interface items recognised in a real recording: stock key/tag "
                                            "conventions differ from what discovery expects")
                for h in with_items:
                    for p in h["ports"].values():
                        self.assertIn("status", p["items"], "%s/%s: no net.if.status item" % (h["host"], p["name"]))


class RecorderMachinery(unittest.TestCase):
    def test_record_sanitize_replay_round_trip(self):
        z, _ = standard_world()
        z.add_device("CUSTOMER-RTR", ports=[dict(name="Gi0/1", index="1", alias="ACME BANK internet uplink")])
        z.gmacros["1"] = {"globalmacroid": "1", "macro": "{$SNMP_COMMUNITY}", "value": "s3cret", "description": ""}
        rec = apirecord.RecordingTransport(z.transport("tok"))
        live = discovery.discover(ZabbixClient(rec, read_only=True), now=NOW)
        calls, summary = apirecord.sanitize(rec.calls)
        text = json.dumps(calls)
        for leak in ("EDGE-RTR-01", "CUSTOMER-RTR", "noc1", "10.0.0.1", "s3cret", "ACME", "BANK", "Network devices"):
            self.assertNotIn(leak, text)
        self.assertIn("HOST-", text)
        self.assertGreater(summary["hosts"], 0)
        replayed = discovery.discover(ZabbixClient(apirecord.ReplayTransport(calls), read_only=True), now=NOW)
        self.assertEqual(sorted(len(h["ports"]) for h in replayed["hosts"].values()),
                         sorted(len(h["ports"]) for h in live["hosts"].values()))
        exprs = [t["expression"] for h in replayed["hosts"].values() for t in h["triggers"]]
        self.assertTrue(exprs and all("EDGE-RTR" not in e for e in exprs))   # pseudonyms inside expressions too


if __name__ == "__main__":
    unittest.main()
