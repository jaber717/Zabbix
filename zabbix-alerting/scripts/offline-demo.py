#!/usr/bin/env python3
"""Run the real operator workflow against the in-memory Zabbix 7.0 model (no network, no credentials).

    python3 scripts/offline-demo.py            # uses config/interfaces.yaml

Shows --check, --dry-run, apply and the idempotent second run exactly as an operator would see
them. It is a rehearsal, NOT validation against a real Zabbix.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from netalert import cli, config                       # noqa: E402
from tests.fake_zabbix import MockZabbix               # noqa: E402


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "config", "interfaces.yaml")
    desired = config.load(cfg_path)
    z = MockZabbix(token="demo")
    for host in desired.hosts:
        z.add_host(host, sorted(desired.hosts[host]["interfaces"]) + ["Gi0/1", "Gi0/5"])
    base = tempfile.mkdtemp(prefix="netalert-demo-")
    shutil.copytree(os.path.join(ROOT, "config", "environments"), os.path.join(base, "config", "environments"))
    env = {"ZABBIX_URL_LAB": "https://zabbix.demo.invalid", "ZABBIX_TOKEN_LAB": "demo"}
    try:
        for args in (["--check"], ["--dry-run"], [], ["--dry-run"]):
            print("\n$ ./apply.sh --env lab %s" % " ".join(args))
            cli.run(["--env", "lab", "--config", cfg_path] + args, environ=env, out=print, base=base,
                    transport_factory=lambda u, t, v: z.transport(t))
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
