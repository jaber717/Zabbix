#!/usr/bin/env python3
"""LIVE acceptance A-01 (LAB only): do several service problem tags combine with AND or OR on this Zabbix?

    python3 scripts/accept_tag_semantics.py --env lab --host <any-monitored-host> --item-key <any-item-key-with-data>

Writes (and removes again): one trigger on the host, two services. Uses acc_a / acc_b tags only - no NETOPS notification can fire.
Result is written to evidence/tag-semantics-<env>.json. Then set `tag_semantics:` in inventory/<env>.yaml to the proven value.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from slaas import acceptance, env as envmod   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="lab")
    ap.add_argument("--host", required=True)
    ap.add_argument("--item-key", required=True)
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args()
    env = envmod.load(a.env)
    if env["is_production"]:
        print("REFUSED: this test creates a firing trigger; it is LAB only")
        return 1
    client, env, url, ident = envmod.open_client(a.env, read_only=False)
    print("environment %s at %s (API %s), identity %s" % (env["environment"], url, ident.version, ident.state))
    res = acceptance.tag_semantics(client, a.host, a.item_key, timeout=a.timeout)
    res.update({"environment": a.env, "zabbix_version": ident.version})
    path = os.path.join(HERE, "..", "evidence", "tag-semantics-%s.json" % a.env)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2, sort_keys=True)
    print(json.dumps(res, indent=2, sort_keys=True))
    print("RESULT:", res["outcome"].upper())
    return 0 if res["outcome"] in ("and", "or") and res["cleanup"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
