#!/usr/bin/env python3
"""Capture sanitized, read-only Zabbix API responses from a LAB for regression fixtures.

    ./scripts/capture-api-fixtures.py --env lab [--group "Network devices"] [--host R1] \
        [--out ~/zabbix-captures/lab-$(date +%F).json]

Runs exactly the reads ./onboard.sh --report makes (identity check first, read-only client). The output is
sanitized with an allowlist (every free-text string becomes a pseudonym) and then checked: if any original string
that is not structural still appears, nothing is written. The file is written OUTSIDE the repository (this
repository is public): the script refuses an --out inside the Git work tree. Replay it with
NETALERT_RECORDED_DIR=<dir> python3 -m unittest tests.test_recorded_fixtures. Committing a capture requires an
independent confidentiality review first - it is never automatic. Never run against Production unless a sanitized
production recording is explicitly approved.
"""
import argparse
import json
import os
import subprocess
import sys
import time

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
    ap.add_argument("--out", default=os.path.join(os.path.expanduser("~"), "zabbix-captures",
                                                 "capture-%s.json" % time.strftime("%Y%m%dT%H%M%S")))
    a = ap.parse_args()
    top = subprocess.run(["git", "-C", BASE, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, universal_newlines=True).stdout.strip()
    out_abs = os.path.realpath(os.path.abspath(os.path.expanduser(a.out)))
    if top and (out_abs + os.sep).startswith(os.path.realpath(top) + os.sep):
        print("refused: --out %s is inside the Git work tree %s (public repository). Write it elsewhere; "
              "committing a capture needs an independent confidentiality review." % (out_abs, top))
        return 2
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
    left = apirecord.leaks(rec.calls, calls)
    if left:
        print("refused: %d original string(s) survived sanitizing, nothing written. First: %s" % (
            len(left), ", ".join(repr(x) for x in left[:5])))
        return 4
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    fd = os.open(out_abs, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"zabbix_version": snap["zabbix_version"], "environment": a.env, "taken_at": snap["taken_at"],
                   "pseudonymized": summary, "calls": calls}, fh, indent=1, sort_keys=True)
    print("recorded %d read call(s), %d host(s), %d port(s); writes made: %d -> %s" % (
        len(calls), len(snap["hosts"]), sum(len(h["ports"]) for h in snap["hosts"].values()),
        len(client.writes_made()), out_abs))
    print("Leak check passed. Do not commit captures to this public repository without an independent review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
