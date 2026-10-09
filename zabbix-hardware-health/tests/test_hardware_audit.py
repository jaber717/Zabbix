import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hardware_audit", ROOT / "hardware_audit.py")
auditmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditmod)


class FakeAPI:
    def __init__(self, triggers=True, freshness=True):
        self.calls = []
        self.triggers = triggers
        self.freshness = freshness

    def call(self, method, params=None):
        self.calls.append(method)
        if method == "apiinfo.version":
            return "7.0.30"
        if method == "host.get":
            return [{"hostid": "4", "host": "NEXUS-01", "status": "0",
                     "parentTemplates": [{"name": "Cisco Nexus 9000 Series by SNMP"}]}]
        if method == "item.get":
            value = "9900" if self.freshness else "1"
            return [{"itemid": "1", "name": "Fan 1: Fan operational status",
                     "key_": "sensor.fan.status[1]", "status": "0", "state": "0",
                     "lastclock": value},
                    {"itemid": "2", "name": "Power supply 1: PSU status",
                     "key_": "sensor.psu.status[1]", "status": "0", "state": "0",
                     "lastclock": value}]
        if method == "trigger.get":
            if not self.triggers:
                return []
            return [{"triggerid": "10", "description": "Fan 1: Fan is down",
                     "status": "0", "priority": "3", "items": [{"itemid": "1"}],
                     "tags": [{"tag": "component", "value": "fans"}]},
                    {"triggerid": "11", "description": "Power supply 1 failed",
                     "status": "0", "priority": "4", "items": [{"itemid": "2"}],
                     "tags": [{"tag": "component", "value": "power"}]}]
        raise AssertionError("Unexpected API method " + method)


POLICY = {"environment": "lab",
          "hosts": {"NEXUS-01": {"expected": ["fan", "power"],
                                 "max_sensor_age_minutes": 10}}}


class HardwareTests(unittest.TestCase):
    def test_healthy_host_covered(self):
        api = FakeAPI()
        h = auditmod.scan_host(api, "NEXUS-01", POLICY["hosts"]["NEXUS-01"],
                               now=10000)
        self.assertEqual(h["status"], "COVERED")
        self.assertEqual(h["coverage"]["fan"]["enabled_trigger_count"], 1)
        self.assertEqual(h["coverage"]["power"]["state"], "COVERED")

    def test_missing_triggers_is_gap(self):
        h = auditmod.scan_host(FakeAPI(triggers=False), "NEXUS-01",
                               POLICY["hosts"]["NEXUS-01"], now=10000)
        self.assertEqual(h["coverage"]["fan"]["state"], "NO_ENABLED_TRIGGERS")
        self.assertEqual(h["status"], "REVIEW_REQUIRED")

    def test_stale_sensor_fails_coverage(self):
        h = auditmod.scan_host(FakeAPI(freshness=False), "NEXUS-01",
                               POLICY["hosts"]["NEXUS-01"], now=10000)
        self.assertEqual(h["coverage"]["power"]["state"], "STALE_OR_UNSUPPORTED")

    def test_fan_on_psu_not_misreported_as_power(self):
        self.assertEqual(auditmod.classify("PowerSupply-2 Fan operational status"), ["fan"])

    def test_empty_inventory_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "inventory.yaml"
            f.write_text("environment: production\nhosts: {}\n", encoding="utf-8")
            self.assertEqual(auditmod.load_config(f, "production")["hosts"], {})

    def test_environment_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "policy.yaml"
            f.write_text("environment: lab\nhosts: {}\n", encoding="utf-8")
            with self.assertRaises(auditmod.AuditError):
                auditmod.load_config(f, "production")

    def test_duplicate_or_invalid_expected_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "policy.yaml"
            f.write_text("environment: lab\nhosts:\n  R1:\n    expected: [fan, fan]\n",
                         encoding="utf-8")
            with self.assertRaises(auditmod.AuditError):
                auditmod.load_config(f, "lab")

    def test_version_check(self):
        report = auditmod.audit(FakeAPI(), POLICY)
        self.assertEqual(report["summary"]["covered"], 0)
        self.assertEqual(report["summary"]["review_required"], 1)
        # Fixture lastclock is old relative to actual now.

    def test_api_allowlist_prevents_mutation(self):
        api = auditmod.ZabbixAPI("https://zabbix.example", "placeholder")
        with self.assertRaises(auditmod.AuditError):
            api.call("trigger.update", {"triggerid": "1"})


if __name__ == "__main__":
    unittest.main()
