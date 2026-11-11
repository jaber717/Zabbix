#!/usr/bin/env python3
"""Capture sanitized, read-only Zabbix API responses from a LAB for regression fixtures.

    ./scripts/capture-api-fixtures.py --env lab [--group "Network devices"] [--host R1] \
        --out tests/fixtures/recorded/lab-$(date +%F).json

Runs exactly the reads ./onboard.sh --report makes (identity check first, read-only client). Review the output
file before committing it: it is sanitized, but you are responsible for what goes into Git. Never run against
Production unless a sanitized production recording is explicitly approved.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from netalert import apirecord, discovery, envsafety          # noqa: E402
from netalert.onboard_cli import load_dotenv                    # noqa: E402
from netalert.zbx import HttpTransport, ZabbixClient            # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="lab")
    ap.add_argument("--group", action="append", default=[])
    ap.add_argument("--host", action="append", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    environ = dict(os.environ)
    load_dotenv(BASE, environ)
    env = envsafety.load_env(BASE, a.env)
    url, token = envsafety.resolve_target(env, environ)
    rec = apirecord.RecordingTransport(HttpTransport(url, token, env["zabbix"].get("verify_tls", True)))
    client = ZabbixClient(rec, read_only=True)
    ident = envsafety.verify(BASE, env, client, url, environ)
    if not ident.ok:
        print("environment safety check failed: %s" % "; ".join(ident.messages))
        return 3
    snap = discovery.discover(client, a.group, a.host)
    calls, summary = apirecord.sanitize(rec.calls)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"zabbix_version": snap["zabbix_version"], "environment": a.env, "taken_at": snap["taken_at"],
                   "pseudonymized": summary, "calls": calls}, fh, indent=1, sort_keys=True)
    print("recorded %d read call(s), %d host(s), %d port(s); writes made: %d -> %s" % (
        len(calls), len(snap["hosts"]), sum(len(h["ports"]) for h in snap["hosts"].values()),
        len(client.writes_made()), a.out))
    print("Review the file before committing it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
