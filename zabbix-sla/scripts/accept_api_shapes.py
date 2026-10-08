#!/usr/bin/env python3
"""LIVE acceptance A-02 (read-only): the planner and report rely on specific fields of service.get / sla.get / sla.getsli / dashboard.get.

    python3 scripts/accept_api_shapes.py --env lab        (run after the first LAB apply)

Writes evidence/api-shapes-<env>.json with PASS/FAIL per check and one sample of each shape.
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
    a = ap.parse_args()
    client, env, url, ident = envmod.open_client(a.env, read_only=True)
    res = acceptance.api_shapes(client)
    res.update({"environment": a.env, "zabbix_version": ident.version})
    path = os.path.join(HERE, "..", "evidence", "api-shapes-%s.json" % a.env)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2, sort_keys=True)
    for c in res["checks"]:
        print("%-5s %s %s" % ("PASS" if c["ok"] else "FAIL", c["what"], ("- " + c["detail"]) if c["detail"] and not c["ok"] else ""))
    print("RESULT:", "PASS" if res["ok"] else "FAIL")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
