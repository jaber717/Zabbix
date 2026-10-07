import json
import re
import unittest

from netalert import template as tpl
from tests.fake_zabbix import MockZabbix
from netalert.zbx import ZabbixClient, ZabbixError


class TemplateGeneration(unittest.TestCase):
    def test_deterministic(self):
        a = json.dumps(tpl.build(), sort_keys=True)
        b = json.dumps(tpl.build(), sort_keys=True)
        self.assertEqual(a, b)
        self.assertEqual(tpl.content_hash(), tpl.content_hash())

    def test_uuids_are_unique_v4(self):
        doc = tpl.build()
        found = []

        def walk(o):
            if isinstance(o, dict):
                if "uuid" in o:
                    found.append(o["uuid"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(doc)
        self.assertEqual(len(found), len(set(found)))
        for u in found:
            self.assertRegex(u, r"^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{3}[0-9a-f]{12}$")

    def test_no_hardcoded_environment_values(self):
        blob = json.dumps(tpl.build())
        for bad in ("PNET", "Gi0/", "HundredGig", "http://", "https://", "192.168.", "10.0."):
            self.assertNotIn(bad, blob, bad)

    def test_trigger_matrix(self):
        names = {}
        for t in tpl.trigger_prototypes():
            tags = dict((x["tag"], x["value"]) for x in t["tags"])
            names.setdefault(tags["netops_alert"], set()).add(tags["severity_label"])
        self.assertEqual(set(names), {"link_down", "util_rx", "util_tx", "errors", "discards",
                                      "flapping", "speed_degraded"})
        for alert, sevs in names.items():
            self.assertEqual(sevs, {"warning", "average", "high", "disaster"}, alert)

    def test_primary_threshold_has_no_averaging_window(self):
        for t in tpl.trigger_prototypes():
            tags = dict((x["tag"], x["value"]) for x in t["tags"])
            if tags["netops_alert"] in ("link_down", "util_rx", "util_tx"):
                self.assertNotRegex(t["expression"], r"avg\(|min\(|max\(|count\(|nodata\(")
                self.assertIn("last(", t["expression"])

    def test_utilization_has_recovery_hysteresis_expression(self):
        for t in tpl.trigger_prototypes():
            if t["name"].find("utilization") >= 0:
                self.assertEqual(t["recovery_mode"], "RECOVERY_EXPRESSION")
                self.assertIn("UTIL.RECOVER", t["recovery_expression"])
                self.assertIn("UTIL.MAX", t["expression"])

    def test_priorities_follow_variant(self):
        for t in tpl.trigger_prototypes():
            tags = dict((x["tag"], x["value"]) for x in t["tags"])
            self.assertEqual(t["priority"].lower(), tags["severity_label"])

    def test_every_trigger_prototype_carries_alert_tag_for_the_action_filter(self):
        for t in tpl.trigger_prototypes():
            self.assertIn(tpl.TAG_ALERT, [x["tag"] for x in t["tags"]])

    def test_item_prototypes_use_hc_counters_and_per_second_math(self):
        by = dict((i["key"], i) for i in tpl.item_prototypes())
        self.assertIn("1.3.6.1.2.1.31.1.1.1.6", by[tpl.K_IN]["snmp_oid"])      # ifHCInOctets
        self.assertIn("1.3.6.1.2.1.31.1.1.1.10", by[tpl.K_OUT]["snmp_oid"])    # ifHCOutOctets
        self.assertIn("1.3.6.1.2.1.31.1.1.1.15", by[tpl.K_HSPEED]["snmp_oid"])  # ifHighSpeed
        steps = [p["type"] for p in by[tpl.K_IN]["preprocessing"]]
        self.assertEqual(steps, ["CHANGE_PER_SECOND", "MULTIPLIER"])


class ImportIntoModel(unittest.TestCase):
    def setUp(self):
        self.z = MockZabbix()
        self.c = ZabbixClient(self.z.transport())

    def _import(self, doc=None, rules=None):
        return self.c.call("configuration.import", {"format": "json", "source": json.dumps(doc or tpl.build()),
                                                    "rules": rules or tpl.IMPORT_RULES})

    def test_import_succeeds_and_creates_objects(self):
        self.assertTrue(self._import())
        t = self.c.call("template.get", {"filter": {"host": [tpl.TEMPLATE_NAME]}, "output": "extend"})
        self.assertEqual(len(t), 1)
        self.assertEqual(len(self.z.itemprotos), 9)
        self.assertEqual(len(self.z.trigprotos), len(tpl.trigger_prototypes()))

    def test_reimport_is_in_place(self):
        self._import()
        before = (len(self.z.templates), len(self.z.itemprotos), len(self.z.trigprotos))
        self._import()
        self.assertEqual(before, (len(self.z.templates), len(self.z.itemprotos), len(self.z.trigprotos)))

    def test_delete_missing_removes_dropped_prototypes(self):
        self._import()
        doc = tpl.build()
        doc["zabbix_export"]["templates"][0]["discovery_rules"][0]["trigger_prototypes"].pop()
        # remove the dependency that pointed at nothing else; dropping the last (speed) is safe
        self._import(doc)
        self.assertEqual(len(self.z.trigprotos), len(tpl.trigger_prototypes()) - 1)

    def test_server_rejects_expression_with_unknown_item(self):
        doc = tpl.build()
        doc["zabbix_export"]["templates"][0]["discovery_rules"][0]["trigger_prototypes"][0]["expression"] = \
            "last(/%s/no.such.key[{#SNMPINDEX}])=1" % tpl.TEMPLATE_NAME
        with self.assertRaises(ZabbixError) as cm:
            self._import(doc)
        self.assertIn("does not exist", str(cm.exception))

    def test_server_rejects_bad_uuid_and_unknown_tag(self):
        doc = tpl.build()
        doc["zabbix_export"]["templates"][0]["uuid"] = "1234"
        with self.assertRaises(ZabbixError):
            self._import(doc)
        doc = tpl.build()
        doc["zabbix_export"]["templates"][0]["discovery_rules"][0]["bogus"] = 1
        with self.assertRaises(ZabbixError):
            self._import(doc)

    def test_readonly_user_cannot_import(self):
        z = MockZabbix(readonly=True)
        c = ZabbixClient(z.transport())
        with self.assertRaises(ZabbixError) as cm:
            c.call("configuration.import", {"format": "json", "source": json.dumps(tpl.build()),
                                            "rules": tpl.IMPORT_RULES})
        self.assertIn("No permissions", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class FingerprintTolerance(unittest.TestCase):
    def test_whitespace_reformatting_is_not_drift(self):
        doc = tpl.build()
        want = tpl.fingerprint_desired_numeric(doc)
        rows = [{"description": n, "expression": e.replace(" and ", "  and "), "recovery_expression": r.replace("*", " * "),
                 "priority": str(p)} for n, e, r, p in want["triggers"]]
        live = tpl.fingerprint_live(
            [{"key_": k, "snmp_oid": o, "delay": d} for k, o, d in want["items"]], rows,
            [{"macro": m, "value": v} for m, v in want["macros"]])
        self.assertEqual(live, want)
