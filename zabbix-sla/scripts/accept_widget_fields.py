#!/usr/bin/env python3
"""LIVE acceptance A-20 (read-only): learn the dashboard widget field type ids and names from a dashboard built by hand in the LAB GUI.

Build a LAB dashboard containing:
  * an "SLA report" widget with SLA = 'NETOPS-SLA: <title of a class>' and Service = '<a NETOPS-SLA service>' and "number of periods" = 7
  * a "Problems" widget with Tags filter: tag 'netops_alert' operator 'Equals' value 'link_down', and "Show tags" = 3
then:  python3 scripts/accept_widget_fields.py --env lab --dashboard "<name>" --sla <class id> --service <sla_id>

Writes evidence/widget-field-types.json (verified: true) which the dashboard generator then uses; until it exists `dashboards apply` is refused.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from slaas import dashboards, env as envmod   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="lab")
    ap.add_argument("--dashboard", required=True)
    ap.add_argument("--sla", required=True, help="SLA class id used in the SLA report widget")
    ap.add_argument("--service", required=True, help="sla_id of the service used in the SLA report widget")
    ap.add_argument("--periods", type=int, default=7)
    a = ap.parse_args()
    client, env, url, ident = envmod.open_client(a.env, read_only=True)
    rows = client.call("dashboard.get", {"output": ["dashboardid", "name", "display_period"], "selectPages": "extend", "filter": {"name": [a.dashboard]}})
    if not rows:
        print("dashboard '%s' not found" % a.dashboard)
        return 1
    ids = dashboards.resolve_ids(client)
    try:
        ev = dashboards.derive_evidence(rows[0], ids["slas"][a.sla], ids["services"][a.service], a.periods)
    except (KeyError, dashboards.DashboardError) as exc:
        print("FAILED: %s" % exc)
        return 1
    ev.update({"environment": a.env, "zabbix_version": ident.version, "source_dashboard": a.dashboard})
    path = os.path.join(HERE, "..", dashboards.EVIDENCE_FILE)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, indent=2, sort_keys=True)
    print(json.dumps(ev, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
