#!/usr/bin/env python3
"""Validate interfaces.yaml against a LIVE Zabbix using READ-ONLY access (dev tool).

    GRAFANA_URL=... GRAFANA_USER=... GRAFANA_PASSWORD=... python3 scripts/live-readcheck.py [config.yaml]

Runs exactly the planner's per-interface checks (host exists/enabled/has SNMP interface/interface
name exists) plus the ownership scan, over the Grafana->Zabbix read proxy. It never writes.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from devtools.grafana_proxy import GrafanaProxyTransport          # noqa: E402
from netalert import config, planner                                # noqa: E402
from netalert.envsafety import read_identity                        # noqa: E402
from netalert.zbx import ZabbixClient                               # noqa: E402


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "config", "interfaces.yaml")
    t = GrafanaProxyTransport(os.environ["GRAFANA_URL"], os.environ["GRAFANA_USER"],
                              os.environ["GRAFANA_PASSWORD"], os.environ.get("GRAFANA_DS", "zabbix-lab"))
    c = ZabbixClient(t, read_only=True)
    print("Zabbix API version: %s" % c.version())
    ident = read_identity(c)
    print("identity macro: %s" % (ident["value"] if ident else "not set (uninitialised)"))
    desired = config.load(path)
    hosts = planner.get_hosts(c, list(desired.hosts))
    checks = planner.run_checks(c, desired, hosts)
    for ch in checks:
        print("  %s  %s / %s  %s" % ("PASS" if ch.ok else "FAIL", ch.host, ch.iface, ch.message))
    ns = c.call("usermacro.get", {"output": ["macro", "hostid", "description"], "search": {"macro": "{$NETOPS."}})
    print("existing {$NETOPS.*} host macros on this Zabbix: %d" % len(ns))
    for h in sorted(hosts):
        names = planner.interface_names(c, hosts[h]["hostid"])
        print("  %s: %d interface name(s) known, e.g. %s" % (h, len(names), ", ".join(sorted(names)[:6])))
    bad = [x for x in checks if not x.ok]
    print("RESULT: %s" % ("PASS" if not bad else "FAIL (%d)" % len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
