#!/usr/bin/env python3
"""Read-only freshness probe of the SNMP data behind a policy (dev tool; Grafana read proxy).

    GRAFANA_URL=... GRAFANA_USER=... GRAFANA_PASSWORD=... python3 scripts/live-snmp-state.py [policy.yaml]

For each host in the policy: SNMP interface availability/error, parent templates, age of the newest
value of each selected interface's status item, and the stock trigger prototypes' presence.
Prints 'Fresh SNMP validation: PASS' only when every selected status item is younger than --max-age
seconds; otherwise BLOCKED. It never writes and never touches credentials.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from devtools.grafana_proxy import GrafanaProxyTransport          # noqa: E402
from netalert import config, planner                                # noqa: E402
from netalert.zbx import ZabbixClient, ZabbixError                  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("policy", nargs="?", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                              "..", "config", "interfaces.yaml"))
    ap.add_argument("--max-age", type=int, default=300)
    a = ap.parse_args()
    c = ZabbixClient(GrafanaProxyTransport(os.environ["GRAFANA_URL"], os.environ["GRAFANA_USER"],
                                           os.environ["GRAFANA_PASSWORD"],
                                           os.environ.get("GRAFANA_DS", "zabbix-lab")), read_only=True)
    desired = config.load(a.policy)
    now = time.time()
    stale = 0
    total = 0
    for host in sorted(desired.hosts):
        rows = c.call("host.get", {"output": ["hostid", "host", "status"], "filter": {"host": [host]},
                                   "selectInterfaces": ["type", "available", "error"],
                                   "selectParentTemplates": ["host"]})
        if not rows:
            print("%s: NOT FOUND" % host)
            continue
        h = rows[0]
        snmp = [i for i in h["interfaces"] if str(i["type"]) == "2"]
        avail = {"0": "unknown", "1": "available", "2": "UNAVAILABLE"}.get(str(snmp[0]["available"]), "?") if snmp else "no SNMP if"
        err = (snmp[0].get("error") or "")[:90] if snmp else ""
        print("%s: SNMP %s %s | templates: %s" % (host, avail, ("(%s)" % err) if err else "",
                                                  ", ".join(t["host"] for t in h["parentTemplates"]) or "none"))
        items = c.call("item.get", {"output": ["key_", "lastclock", "lastvalue", "state", "error"],
                                    "hostids": [h["hostid"]], "search": {"key_": "net.if.status["},
                                    "selectTags": ["tag", "value"]})
        by_if = {}
        for it in items:
            for t in it.get("tags", []):
                if t["tag"] == "interface":
                    by_if[t["value"]] = it
        for ifname in sorted(desired.hosts[host]["interfaces"]):
            it = by_if.get(ifname)
            total += 1
            if not it:
                stale += 1
                print("  %-8s status item: MISSING" % ifname)
                continue
            age = now - int(it["lastclock"]) if it["lastclock"] != "0" else None
            fresh = age is not None and age <= a.max_age and it["state"] == "0"
            stale += 0 if fresh else 1
            print("  %-8s last value %s, age %s, state %s -> %s" % (
                ifname, it["lastvalue"], "never" if age is None else "%ds" % age, it["state"],
                "fresh" if fresh else "STALE"))
        try:
            trig = c.call("triggerprototype.get", {"output": ["description"], "hostids": [h["hostid"]]})
            print("  stock trigger prototypes visible: %d" % len(trig))
        except ZabbixError as exc:
            print("  stock trigger prototypes: not readable (%s)" % exc.message)
    ok = stale == 0 and total > 0
    print("Fresh SNMP validation: %s (%d/%d status items fresh within %ds)" % (
        "PASS" if ok else "BLOCKED", total - stale, total, a.max_age))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
