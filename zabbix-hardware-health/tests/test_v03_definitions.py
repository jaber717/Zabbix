import copy
import os
import unittest

from hwh import expr, importcheck, simulate, template, vendordefs
from hwh.api import AuditError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFS = vendordefs.load_dir(os.path.join(ROOT, "vendors"))


class Definitions(unittest.TestCase):
    def test_all_load_and_have_sources(self):
        self.assertGreaterEqual(len(DEFS), 7)
        for d in DEFS.values():
            self.assertTrue(d["sources"])

    def test_blocked_vendors_define_no_sensors(self):
        for k in ("cisco-asr8500", "fortinet-fortiproxy"):
            self.assertFalse(DEFS[k].get("sensors"))

    def test_reading_with_trigger_rejected(self):
        d = copy.deepcopy(DEFS["huawei-vrp"])
        r = [s for s in d["sensors"] if s["scope"] == "reading"][0]
        r["triggers"] = [{"id": "x", "severity": "high", "states": ["failed"], "confirm_samples": 2, "recover_samples": 2, "title": "t"}]
        with self.assertRaises(AuditError):
            vendordefs.validate(d)

    def test_missing_source_rejected(self):
        d = copy.deepcopy(DEFS["cisco-iosxe"])
        d["sources"] = []
        with self.assertRaises(AuditError):
            vendordefs.validate(d)

    def test_shared_state_triggers_rejected(self):
        d = copy.deepcopy(DEFS["cisco-iosxe"])
        sn = [s for s in d["sensors"] if s.get("triggers") and len(s["triggers"]) > 1][0]
        sn["triggers"][1]["states"] = list(sn["triggers"][0]["states"])
        with self.assertRaises(AuditError):
            vendordefs.validate(d)

    def test_registry_entries_not_device_verified(self):
        for e in vendordefs.registry_entries(DEFS).values():
            self.assertFalse(e["device_verified"])
            self.assertIn("NOT DEVICE-VERIFIED", e["evidence"])


class Expressions(unittest.TestCase):
    def test_roundtrip_parse(self):
        e = expr.problem_expression("T", "k[{#SNMPINDEX}]", ["3", "4"], 3)
        self.assertEqual(expr.references(expr.parse(e)), {("T", "k[{#SNMPINDEX}]")})

    def test_rejects_outside_subset(self):
        with self.assertRaises(AuditError):
            expr.parse("avg(/T/k,5m)>1")

    def test_unknown_leaves_state(self):
        p = expr.problem_expression("T", "k", ["3"], 2)
        r = expr.recovery_expression("T", "k", ["1"], 2)
        ser = {"k": [(1, 1), (2, 3), (3, 3)]}
        st = [s for _, s in expr.run_trigger(p, r, ser, [1, 2, 3])]
        self.assertEqual(st, ["OK", "OK", "PROBLEM"])


class Simulation(unittest.TestCase):
    def test_every_definition_passes(self):
        total = 0
        for did, s in simulate.summary(DEFS).items():
            self.assertEqual(s["failed"], [], did)
            total += s["cases"]
        self.assertGreater(total, 20)

    def test_glitch_and_flap_cases_present(self):
        names = {r["scenario"] for r in simulate.run_definition(DEFS["cisco-iosxe"])}
        self.assertTrue({"normal", "fault", "glitch", "recovery", "recovery-flap"} <= names)


class TemplateBuild(unittest.TestCase):
    def test_all_templates_structurally_sound(self):
        for did, d in DEFS.items():
            if not d.get("sensors"):
                continue
            self.assertEqual(importcheck.check(template.build(d)), [], did)

    def test_deterministic(self):
        d = DEFS["cisco-iosxe"]
        self.assertEqual(template.build(d), template.build(copy.deepcopy(d)))

    def test_no_netops_alert_tag_anywhere(self):
        for d in DEFS.values():
            if d.get("sensors"):
                self.assertNotIn('"netops_alert"', str(template.build(d)).replace("'", '"'))

    def test_importcheck_catches_defects(self):
        doc = template.build(DEFS["cisco-iosxe"])
        tr = doc["zabbix_export"]["templates"][0]["discovery_rules"][0]["item_prototypes"][0]["trigger_prototypes"][0]
        tr["tags"].append({"tag": "netops_alert", "value": "1"})
        self.assertTrue(any("netops_alert" in p for p in importcheck.check(doc)))
        doc = template.build(DEFS["cisco-iosxe"])
        doc["zabbix_export"]["templates"][0]["discovery_rules"][0]["item_prototypes"][0]["trigger_prototypes"][0].pop("recovery_expression")
        self.assertTrue(importcheck.check(doc))

    def test_palo_alto_password_is_secret(self):
        doc = template.build(DEFS["paloalto-panos"])
        pw = [m for m in doc["zabbix_export"]["templates"][0]["macros"] if "PASSWORD" in m["macro"]][0]
        self.assertEqual(pw["type"], "SECRET_TEXT")
        self.assertEqual(pw["value"], "")


if __name__ == "__main__":
    unittest.main()
