"""Template drift detection against Zabbix-shaped responses (internal `{functionid}` expressions)."""
import re
import unittest

from netalert import planner, template as tpl
from netalert.zbx import ZabbixClient
from tests.fake_zabbix import MockZabbix
from tests.helpers import World


def applied_world(**kw):
    w = World(**kw)
    assert w.run()[0] == 0
    return w


class InternalIds(unittest.TestCase):
    def setUp(self):
        self.w = applied_world()
        self.z = self.w.mock

    def tearDown(self):
        self.w.close()

    def tid(self):
        return [t for t, v in self.z.templates.items() if v["host"] == tpl.TEMPLATE_NAME][0]

    def test_the_model_really_returns_internal_ids(self):
        c = ZabbixClient(self.z.transport(), read_only=True)
        raw = c.call("triggerprototype.get", {"output": ["expression", "recovery_expression"],
                                              "hostids": [self.tid()]})
        self.assertTrue(all(re.search(r"\{\d+\}", r["expression"]) for r in raw))
        self.assertFalse(any("last(" in r["expression"] for r in raw))
        full = c.call("triggerprototype.get", {"output": ["expression"], "hostids": [self.tid()],
                                               "expandExpression": True})
        self.assertTrue(any("last(/" in r["expression"] for r in full))

    def test_clean_via_export(self):
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_clean_via_function_resolution_when_export_is_denied(self):
        self.z.deny_export = True
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_different_function_ids_are_not_drift(self):
        self.z.deny_export = True
        for t in self.z.trigprotos.values():           # renumber every function id consistently
            for f in t["functions"]:
                old, new = f["functionid"], str(int(f["functionid"]) + 500000)
                t["expression"] = t["expression"].replace("{%s}" % old, "{%s}" % new)
                t["recovery_expression"] = t["recovery_expression"].replace("{%s}" % old, "{%s}" % new)
                f["functionid"] = new
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_28_triggers_are_never_reported_missing_and_unexpected(self):
        for deny in (False, True):
            self.z.deny_export = deny
            out = self.w.run("--dry-run")[1]
            self.assertNotIn("28 missing", out)
            self.assertNotIn("unexpected", out)

    def test_genuine_expression_change_is_detected_via_export(self):
        victim = next(t for t in self.z.trigprotos.values() if t["_expr"].endswith("<>1"))
        victim["_expr"] = victim["_expr"].replace("<>1", "<>2")
        rc, out = self.w.run("--dry-run")
        self.assertIn("CHANGE template", out)
        self.assertIn("triggers: 1 missing, 1 unexpected", out)

    def test_genuine_expression_change_is_detected_via_resolution(self):
        self.z.deny_export = True
        victim = next(t for t in self.z.trigprotos.values() if t["_expr"].endswith("<>1"))
        victim["expression"] = victim["expression"].replace("<>1", "<>2")
        self.assertIn("triggers: 1 missing, 1 unexpected", self.w.run("--dry-run")[1])

    def test_recovery_expression_change_is_detected_both_ways(self):
        victim = next(t for t in self.z.trigprotos.values() if t["_rec"] and "UTIL.RECOVER" in t["_rec"])
        victim["_rec"] = victim["_rec"].replace("UTIL.RECOVER", "UTIL.MAX")
        self.assertIn("triggers: 1 missing, 1 unexpected", self.w.run("--dry-run")[1])
        self.z.deny_export = True
        victim["recovery_expression"] = victim["recovery_expression"] + "+0"
        self.assertIn("triggers: 1 missing, 1 unexpected", self.w.run("--dry-run")[1])

    def test_priority_change_is_detected(self):
        victim = next(iter(self.z.trigprotos.values()))
        victim["_priority"] = "INFO"
        self.assertIn("CHANGE template", self.w.run("--dry-run")[1])

    def test_apply_repairs_genuine_drift_in_place(self):
        victim = next(t for t in self.z.trigprotos.values() if t["_expr"].endswith("<>1"))
        victim["_expr"] = victim["_expr"].replace("<>1", "<>2")
        self.assertEqual(self.w.run()[0], 0)
        self.assertIn("No changes required.", self.w.run("--dry-run")[1])

    def test_unreadable_template_does_not_invent_drift(self):
        self.z.deny_export = True
        self.z.deny_triggerprototype = True
        rc, out = self.w.run("--dry-run")
        self.assertIn("No changes required.", out)
        self.assertIn("could not be read", out)

    def test_unreadable_template_still_catches_version_change(self):
        self.z.deny_export = True
        self.z.deny_triggerprototype = True
        for t in self.z.templates.values():
            t["description"] = t["description"].replace("hash=", "hash=dead")
        self.assertIn("template version differs", self.w.run("--dry-run")[1])


class ResolveFunctionIds(unittest.TestCase):
    def test_reconstruction(self):
        funcs = [{"functionid": "7", "itemid": "1", "function": "last", "parameter": "$"},
                 {"functionid": "8", "itemid": "1", "function": "changecount", "parameter": "$,10m"}]
        out = planner.resolve_function_ids("{7}<>1 and {8}>=3", funcs, {"1": "k[{#SNMPINDEX}]"}, "T")
        self.assertEqual(out, "last(/T/k[{#SNMPINDEX}])<>1 and changecount(/T/k[{#SNMPINDEX}],10m)>=3")

    def test_unknown_shapes_raise_instead_of_guessing(self):
        with self.assertRaises(KeyError):
            planner.resolve_function_ids("{9}", [], {}, "T")
        with self.assertRaises(ValueError):
            planner.resolve_function_ids("{7}", [{"functionid": "7", "itemid": "1", "function": "last",
                                                  "parameter": "weird"}], {"1": "k"}, "T")


class Whitespace(unittest.TestCase):
    def test_whitespace_reformatting_is_not_drift(self):
        want = tpl.fingerprint_doc(tpl.build())
        rows = [{"description": n, "expression": e.replace("and", " and "), "recovery_expression": r,
                 "priority": {v: k for k, v in tpl.PRIORITY_NAME.items()}[p]} for n, e, r, p in want["triggers"]]
        live = tpl.fingerprint_from_api([{"key_": k, "snmp_oid": o, "delay": d, "type": "20"}
                                         for k, o, d in want["items"]], rows,
                                        [{"macro": m, "value": v} for m, v in want["macros"]])
        live["items"] = want["items"]            # dependent-item delay is exercised in the model tests
        self.assertEqual(live, want)


if __name__ == "__main__":
    unittest.main()
