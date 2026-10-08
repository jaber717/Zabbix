#!/usr/bin/env python3
"""Read-only audit of the tags that already exist in a Zabbix (hosts, items, triggers, trigger prototypes, recent problems).

    # direct API (token from the environment named in the env file)      
    python3 scripts/audit_tags.py --env lab --out evidence/tag-audit-lab.json
    # dev-only: through the Grafana read proxy (GRAFANA_URL / GRAFANA_USER / GRAFANA_PASSWORD)
    python3 scripts/audit_tags.py --via-grafana-proxy --out evidence/tag-audit-lab.json

Nothing is written to Zabbix. Output: JSON with, per object type, tag name -> {count, distinct_values, samples}.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "zabbix-alerting"))
sys.path.insert(0, os.path.join(HERE, ".."))

from netalert.zbx import ApiUnavailable, ZabbixClient, ZabbixError   # noqa: E402


def summarize(rows):
    names = defaultdict(Counter)
    for r in rows:
        for t in r.get("tags", []) or []:
            names[t["tag"]][t.get("value", "")] += 1
    return dict((n, {"count": sum(c.values()), "distinct_values": len(c), "samples": [v for v, _ in c.most_common(5)]})
                for n, c in sorted(names.items()))


def safe(client, method, params, label, notes):
    try:
        return client.call(method, params)
    except (ZabbixError, ApiUnavailable) as exc:
        notes.append("%s: not readable with this account (%s)" % (label, str(exc)[:120]))
        return None


def audit(client, limit=5000):
    notes, out = [], {}
    out["api_version"] = client.version()
    hosts = safe(client, "host.get", {"output": ["host"], "selectTags": ["tag", "value"], "selectHostGroups": ["name"], "limit": limit}, "host.get", notes) or []
    out["hosts"] = {"count": len(hosts), "tags": summarize(hosts), "groups": dict(Counter(g["name"] for h in hosts for g in h.get("hostgroups", [])))}
    items = safe(client, "item.get", {"output": ["key_"], "selectTags": ["tag", "value"], "limit": limit, "monitored": True}, "item.get", notes) or []
    out["items"] = {"sampled": len(items), "tags": summarize(items)}
    trig = safe(client, "trigger.get", {"output": ["description", "priority"], "selectTags": ["tag", "value"], "limit": limit}, "trigger.get", notes) or []
    out["triggers"] = {"count": len(trig), "tags": summarize(trig), "without_tags": sum(1 for t in trig if not t.get("tags"))}
    tp = safe(client, "triggerprototype.get", {"output": ["description"], "selectTags": ["tag", "value"], "limit": limit}, "triggerprototype.get", notes)
    out["trigger_prototypes"] = None if tp is None else {"count": len(tp), "tags": summarize(tp)}
    ev = safe(client, "event.get", {"output": ["eventid", "name", "severity"], "source": 0, "object": 0, "value": 1, "selectTags": ["tag", "value"],
                                    "sortfield": ["clock"], "sortorder": "DESC", "limit": 1000}, "event.get", notes) or []
    out["recent_problem_events"] = {"sampled": len(ev), "tags": summarize(ev), "without_tags": sum(1 for e in ev if not e.get("tags"))}
    svc = safe(client, "service.get", {"output": "extend", "selectTags": "extend", "selectProblemTags": "extend", "selectParents": ["serviceid"], "selectChildren": ["serviceid"]}, "service.get", notes)
    out["services"] = None if svc is None else {"count": len(svc), "names": [s["name"] for s in svc][:50]}
    sla = safe(client, "sla.get", {"output": "extend", "selectServiceTags": "extend"}, "sla.get", notes)
    out["slas"] = None if sla is None else {"count": len(sla), "names": [s["name"] for s in sla][:50]}
    out["notes"] = notes
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="lab")
    ap.add_argument("--via-grafana-proxy", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.via_grafana_proxy:
        from devtools.grafana_proxy import GrafanaProxyTransport
        t = GrafanaProxyTransport(os.environ["GRAFANA_URL"], os.environ["GRAFANA_USER"], os.environ["GRAFANA_PASSWORD"], os.environ.get("GRAFANA_DS", "zabbix-lab"))
        client = ZabbixClient(t, read_only=True)
    else:
        from slaas.env import open_client
        client = open_client(a.env, read_only=True)[0]
    result = audit(client)
    text = json.dumps(result, indent=2, sort_keys=True)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
