import json
import pathlib
import os
import pathlib
import tempfile
import unittest

import yaml

from hwh import identity, policy
from hwh.api import AuditError, ZabbixAPI
from tests.fakes import NOW, FakeZabbix
from tests.helpers import CATALOGUE, ROOT, Project, TAGS_FAN, good_fake

HOST_YAML = """\
hosts:
  NX-01:
    site: SITE-A
    vendor: cisco
    family: cisco-nxos
    model: TEST-MODEL-1
    expected: [fan]
    max_sensor_age_minutes: 10
    sensors:
      - {category: fan, key: "sensor.fan.status[1]", slot: "Fan tray 1", semantics: test-status}
"""
SEMANTICS_YAML = """\
semantics:
  test-status:
    vendor: cisco
    evidence: "synthetic test fixture - not vendor data"
    verified: true
    states: {"10": normal, "30": failed}
"""


def write_cfg(text):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "p.yaml")
    with open(p, "w") as fh:
        fh.write(text)
    return p


def load(text, env="lab"):
    return policy.load_config(write_cfg("environment: %s\n%s" % (env, text)), env, CATALOGUE)


class TestPolicyValidation(unittest.TestCase):
    def test_valid(self):
        self.assertIn("NX-01", load(HOST_YAML)["hosts"])

    def test_shipped_policies_are_empty(self):
        for env in ("lab", "production"):
            cfg = policy.load_config(str(ROOT / "config" / ("hardware.%s.yaml" % env)), env, CATALOGUE)
            self.assertEqual(cfg["hosts"], {}, "the approved %s hardware inventory must stay empty until real sensors are verified" % env)

    def test_environment_mismatch(self):
        with self.assertRaises(AuditError):
            policy.load_config(write_cfg("environment: lab\nhosts: {}\n"), "production", CATALOGUE)

    def test_old_redundancy_name_is_rejected_because_it_conflated_ha_and_hardware(self):
        with self.assertRaises(AuditError) as cm:
            load(HOST_YAML.replace("expected: [fan]", "expected: [fan, redundancy]"))
        self.assertIn("'ha' and 'hw_redundancy' are different", str(cm.exception))

    def test_na_needs_model_specific_evidence_and_cannot_overlap_expected(self):
        base = HOST_YAML.replace("    expected: [fan]\n", "    expected: [fan]\n    not_applicable:\n      power: {evidence: %s}\n")
        self.assertIn("NX-01", load(base % '"Fixed-power model per datasheet DS-123 section 4"')["hosts"])
        with self.assertRaises(AuditError):
            load(base % '""')
        with self.assertRaises(AuditError):
            load(base % "short")
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace("    expected: [fan]\n", "    expected: [fan]\n    not_applicable:\n      fan: {evidence: 'a long enough evidence statement'}\n"))

    def test_status_sensor_needs_semantics_and_temperature_needs_units(self):
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace(", semantics: test-status", ""))
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace("[fan]", "[temperature]").replace("category: fan", "category: temperature").replace(", semantics: test-status", ""))

    def test_family_must_exist_and_match_vendor_and_model_is_required(self):
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace("cisco-nxos", "cisco-nope"))
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace("vendor: cisco", "vendor: huawei"))
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace("    model: TEST-MODEL-1\n", ""))

    def test_only_the_four_mandatory_vendors(self):
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace("vendor: cisco", "vendor: f5").replace("family: cisco-nxos", "family: x"))

    def test_duplicate_sensor_keys_and_unknown_keys(self):
        dup = HOST_YAML + '      - {category: fan, key: "sensor.fan.status[1]", semantics: test-status}\n'
        with self.assertRaises(AuditError):
            load(dup)
        with self.assertRaises(AuditError):
            load(HOST_YAML.replace("site: SITE-A", "colour: red"))

    def test_catalogue_covers_all_four_mandatory_vendors_and_models(self):
        self.assertEqual({f["vendor"] for f in CATALOGUE.values()}, {"cisco", "paloalto", "fortinet", "huawei"})
        for fid in ("cisco-iosxe", "cisco-nxos", "cisco-asr8500", "paloalto-panos", "fortinet-fortigate", "fortinet-fortiproxy", "huawei-vrp-switch", "huawei-ar8140"):
            self.assertIn(fid, CATALOGUE)
        self.assertIn("ha", CATALOGUE["fortinet-fortigate"]["categories"])
        self.assertIn("ha", CATALOGUE["paloalto-panos"]["categories"])


class TestIsolation(unittest.TestCase):
    """Defect 5: the audit never compared the server-side {$NETOPS.ENVIRONMENT} with --env."""

    def api(self, fz):
        return ZabbixAPI("https://zbx.lab.example", "t", transport=fz)

    def test_matching_identity_passes(self):
        self.assertEqual(identity.verify(self.api(FakeZabbix(identity="lab")), "lab", "https://zbx.lab.example", {}), "7.0.30")

    def test_mismatch_is_refused(self):
        with self.assertRaises(AuditError) as cm:
            identity.verify(self.api(FakeZabbix(identity="production")), "lab", "https://zbx.lab.example", {})
        self.assertIn("IDENTITY MISMATCH", str(cm.exception))

    def test_missing_identity_is_refused(self):
        with self.assertRaises(AuditError) as cm:
            identity.verify(self.api(FakeZabbix(identity=None)), "lab", "https://zbx.lab.example", {})
        self.assertIn("identity unknown", str(cm.exception))

    def test_wrong_major_version_is_refused(self):
        with self.assertRaises(AuditError):
            identity.verify(self.api(FakeZabbix(version="6.0.5")), "lab", "https://zbx.lab.example", {})

    def test_production_policy_requires_a_url_regex(self):
        with self.assertRaises(AuditError):
            identity.verify(self.api(FakeZabbix(identity="production")), "production", "https://zbx.prod.example", {})
        ok = {"zabbix": {"url_regex": r"^https://zbx\.prod\.example$", "forbid_url_regex": "(lab|test)"}}
        self.assertEqual(identity.verify(self.api(FakeZabbix(identity="production")), "production", "https://zbx.prod.example", ok), "7.0.30")
        with self.assertRaises(AuditError):
            identity.verify(self.api(FakeZabbix(identity="production")), "production", "https://zbx.lab.example", ok)

    def test_same_url_or_token_for_both_environments_is_refused(self):
        env = {"ZABBIX_HARDWARE_URL_LAB": "https://z.example/", "ZABBIX_HARDWARE_TOKEN_LAB": "a",
               "ZABBIX_HARDWARE_URL_PRODUCTION": "https://z.example/api_jsonrpc.php", "ZABBIX_HARDWARE_TOKEN_PRODUCTION": "b"}
        with self.assertRaises(AuditError):
            identity.resolve_target("lab", env)
        env["ZABBIX_HARDWARE_URL_PRODUCTION"] = "https://other.example"
        env["ZABBIX_HARDWARE_TOKEN_PRODUCTION"] = "a"
        with self.assertRaises(AuditError):
            identity.resolve_target("lab", env)

    def test_missing_credentials(self):
        with self.assertRaises(AuditError):
            identity.resolve_target("lab", {})

    def test_cli_refuses_a_mispointed_server_before_reading_any_item(self):
        p = Project(hosts_yaml=HOST_YAML, semantics_yaml=SEMANTICS_YAML, identity="production")
        try:
            rc, out, err = p.run("--env", "lab", "audit")
            self.assertEqual(rc, 3)
            self.assertIn("IDENTITY MISMATCH", err)
            self.assertNotIn("item.get", p.fake.methods())
            self.assertNotIn("host.get", p.fake.methods())
        finally:
            p.close()

    def test_cli_refuses_an_uninitialised_server(self):
        p = Project(hosts_yaml=HOST_YAML, semantics_yaml=SEMANTICS_YAML, identity=None)
        try:
            rc, out, err = p.run("--env", "lab", "audit")
            self.assertEqual(rc, 3)
            self.assertNotIn("item.get", p.fake.methods())
        finally:
            p.close()


class TestCli(unittest.TestCase):
    def test_empty_inventory_fails_closed_without_contacting_zabbix(self):
        p = Project()
        try:
            rc, out, err = p.run("--env", "lab", "audit")
            self.assertEqual(rc, 3)
            self.assertIn("No approved hosts", err)
            self.assertEqual(p.fake.calls, [])
        finally:
            p.close()

    def test_audit_pass_exit_0_and_report_schema(self):
        fz, hid, iid = good_fake()
        fz.identity = "lab"
        p = Project(hosts_yaml=HOST_YAML, semantics_yaml=SEMANTICS_YAML, fake=fz)
        try:
            outfile = os.path.join(p.base, "r.json")
            rc, out, err = p.run("--env", "lab", "audit", "--output", outfile)
            self.assertEqual(rc, 0, err + out)
            rep = json.loads(pathlib.Path(outfile).read_text(encoding="utf-8"))
            self.assertEqual(rep["schema"], 2)
            self.assertTrue(rep["identity_verified"])
            self.assertEqual(rep["summary"]["PASS"], 1)
            self.assertEqual(fz.writes(), [])
            self.assertNotIn("lab-token-aaa", out)
        finally:
            p.close()

    def test_audit_gap_exit_2(self):
        fz, hid, iid = good_fake()
        fz.triggers[hid] = []
        p = Project(hosts_yaml=HOST_YAML, semantics_yaml=SEMANTICS_YAML, fake=fz)
        try:
            rc, out, err = p.run("--env", "lab", "audit")
            self.assertEqual(rc, 2)
            self.assertIn("NO_TRIGGER", out)
        finally:
            p.close()

    def test_default_registry_means_every_status_sensor_is_a_gap_via_the_cli(self):
        fz, hid, iid = good_fake()
        p = Project(hosts_yaml=HOST_YAML, fake=fz)                      # shipped (empty) registry
        try:
            rc, out, err = p.run("--env", "lab", "audit")
            self.assertEqual(rc, 2)
            self.assertIn("SEMANTICS_UNVERIFIED", out)
        finally:
            p.close()

    def test_discover_is_read_only_and_works_for_hosts_outside_the_inventory(self):
        fz, hid, iid = good_fake()
        p = Project(fake=fz)
        try:
            rc, out, err = p.run("--env", "lab", "discover", "--host", "NX-01")
            self.assertEqual(rc, 0, err)
            d = json.loads(out)["hosts"][0]
            self.assertEqual(d["candidate_sensor_count"], 1)
            self.assertEqual(fz.writes(), [])
        finally:
            p.close()

    def test_env_is_required(self):
        p = Project()
        try:
            rc, out, err = p.run("audit")
            self.assertEqual(rc, 3)
        finally:
            p.close()


if __name__ == "__main__":
    unittest.main()
