"""PAN-OS authentication is checked against an extract of the EXACT official Zabbix 7.0 template cited by the definition
(docs/sources/pan-pa440-http-extract.json, produced from commit 4a89781 by docs/sources/extract-pan-auth.py)."""
import json
import os
import unittest

from hwh import template, vendordefs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF = vendordefs.load_dir(os.path.join(ROOT, "vendors"))["paloalto-panos"]
with open(os.path.join(ROOT, "docs", "sources", "pan-pa440-http-extract.json"), encoding="utf-8") as fh:
    REF = json.load(fh)
RENAME = {"{$PAN.PA440.API.URL}": "{$NETOPS.HW.API.URL}", "{$PAN.PA440.USER}": "{$NETOPS.HW.API.USER}", "{$PAN.PA440.PASSWORD}": "{$NETOPS.HW.API.PASSWORD}",
          "{$PAN.PA440.TIMEOUT}": "{$NETOPS.HW.API.TIMEOUT}", "{$PAN.PA440.HTTP_PROXY}": "{$NETOPS.HW.API.HTTP_PROXY}"}
FIELDS = ("type", "authtype", "username", "password", "url", "timeout", "status_codes", "http_proxy")


def generated():
    t = template.build(DEF)["zabbix_export"]["templates"][0]
    return t, dict((i["query_fields"][-1]["value"], i) for i in t["items"] if i["type"] == "HTTP_AGENT")


class PanAuth(unittest.TestCase):
    def test_extract_is_from_the_cited_commit(self):
        src = [s for s in DEF["sources"] if s["kind"] == "zabbix-template"][0]
        self.assertEqual(REF["source"]["commit"], src["commit"])
        self.assertEqual(len(REF["source"]["sha256_of_file"]), 64)

    def test_every_generated_api_item_matches_the_reference_authentication(self):
        t, by_cmd = generated()
        seen = 0
        for key, ref in REF["items"].items():
            cmd = [q["value"] for q in ref["query_fields"] if q["name"] == "cmd"][0]
            ours = by_cmd.get(cmd)
            self.assertIsNotNone(ours, "no generated item for the reference command of " + key)
            seen += 1
            for f in FIELDS:
                want = RENAME.get(ref[f], ref[f])
                self.assertEqual(ours[f], want, "%s differs from the reference template (%s)" % (f, key))
            self.assertEqual(ours["preprocessing"], ref["preprocessing"])
            self.assertEqual(sorted((q["name"], q["value"]) for q in ours["query_fields"]), sorted((q["name"], q["value"]) for q in ref["query_fields"]))
        self.assertEqual(seen, 2)

    def test_password_macro_is_secret_and_empty_like_the_reference(self):
        t, _ = generated()
        ref = REF["macros"]["{$PAN.PA440.PASSWORD}"]
        ours = [m for m in t["macros"] if m["macro"] == "{$NETOPS.HW.API.PASSWORD}"][0]
        self.assertEqual(ours["type"], ref["type"])
        self.assertEqual(ours["value"], "")

    def test_timeout_default_matches_reference(self):
        t, _ = generated()
        self.assertEqual([m["value"] for m in t["macros"] if m["macro"] == "{$NETOPS.HW.API.TIMEOUT}"], [REF["macros"]["{$PAN.PA440.TIMEOUT}"]["value"]])

    def test_ha_item_is_gated_like_the_reference_singleton(self):
        t, _ = generated()
        rules = [r for r in t["discovery_rules"] if "ha-state" in r["key"]]
        self.assertEqual(len(rules), 1)
        self.assertIn("\"enabled\"", rules[0]["preprocessing"][0]["parameters"][0])
        self.assertNotIn("=>", rules[0]["preprocessing"][0]["parameters"][0])           # Duktape / ES5
        self.assertNotIn(" of ", rules[0]["preprocessing"][0]["parameters"][0])
        plain = [i for i in t["items"] if i["type"] == "DEPENDENT" and "ha-state" in i["key"]]
        self.assertEqual(plain, [])

    def test_suspended_is_not_failed(self):
        self.assertEqual(DEF["semantics"]["paloalto-ha-state"]["states"]["7"]["state"], "degraded")


if __name__ == "__main__":
    unittest.main()
