#!/usr/bin/env python3
"""Read-only probe: how does THIS Zabbix return the managed template's trigger prototypes? (dev tool)

    ZBX_URL=... ZBX_USER=... ZBX_PASSWORD=... python3 scripts/live-trigger-probe.py [--save fixture.json]

Logs in with the given account (session only; never printed), then reads: triggerprototype.get raw,
with expandExpression, with selectFunctions, and configuration.export. Prints shapes and, for a few
prototypes, the expression text each variant returns. Writes nothing to Zabbix.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from netalert import template as tpl  # noqa: E402


def rpc(url, method, params, auth=None):
    h = {"Content-Type": "application/json-rpc"}
    if auth:
        h["Authorization"] = "Bearer " + auth
    req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "method": method, "params": params,
                                                  "id": 1}).encode(), h)
    with urllib.request.urlopen(req, timeout=60, context=ssl._create_unverified_context()) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    a = ap.parse_args()
    url = os.environ["ZBX_URL"].rstrip("/") + "/api_jsonrpc.php"
    login = rpc(url, "user.login", {"username": os.environ["ZBX_USER"], "password": os.environ["ZBX_PASSWORD"]})
    if "error" in login:
        print("login failed:", login["error"].get("data"))
        return 2
    tok = login["result"]
    out = {}
    t = rpc(url, "template.get", {"output": ["templateid", "description"],
                                  "filter": {"host": [tpl.TEMPLATE_NAME]}}, tok)
    if "error" in t or not t["result"]:
        print("template.get:", t.get("error", "template not found"))
        return 1
    tid = t["result"][0]["templateid"]
    print("template id", tid, "|", t["result"][0]["description"][:80])
    variants = {
        "raw": {},
        "expandExpression": {"expandExpression": True},
        "selectFunctions": {"selectFunctions": "extend"},
    }
    for name, extra in variants.items():
        p = {"output": ["description", "expression", "recovery_expression", "priority"], "hostids": [tid],
             "limit": 3}
        p.update(extra)
        r = rpc(url, "triggerprototype.get", p, tok)
        print("\n== triggerprototype.get [%s]" % name)
        if "error" in r:
            print("  error:", r["error"].get("data"))
            continue
        out[name] = r["result"]
        for row in r["result"][:2]:
            print("  expr :", row["expression"][:230])
            print("  recov:", (row.get("recovery_expression") or "")[:230])
            if "functions" in row:
                print("  funcs:", json.dumps(row["functions"])[:230])
    r = rpc(url, "configuration.export", {"format": "json", "options": {"templates": [tid]}}, tok)
    print("\n== configuration.export")
    if "error" in r:
        print("  error:", r["error"].get("data"))
    else:
        doc = json.loads(r["result"])
        out["export"] = doc
        rule = doc["zabbix_export"]["templates"][0]["discovery_rules"][0]
        tp = rule["trigger_prototypes"]
        print("  trigger prototypes:", len(tp), "| item prototypes:", len(rule["item_prototypes"]))
        for row in tp[:2]:
            print("  expr :", row["expression"][:230])
            print("  recov:", row.get("recovery_expression", "")[:230])
            print("  keys :", sorted(row))
        print("  macros:", len(doc["zabbix_export"]["templates"][0].get("macros", [])),
              "| item keys:", sorted(rule["item_prototypes"][0]))
    rpc(url, "user.logout", {}, tok)
    if a.save:
        with open(a.save, "w") as fh:
            json.dump(out, fh, indent=1)
        os.chmod(a.save, 0o600)
        print("\nsaved", a.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
