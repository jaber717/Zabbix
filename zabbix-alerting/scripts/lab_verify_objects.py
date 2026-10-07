#!/usr/bin/env python3
"""Check, through the real API, that what apply created is really working in Zabbix (LAB).

    ./scripts/lab_verify_objects.py --env lab --config examples/lab-validation.yaml [--wait 420]

Read-only. Confirms: template present and equal to the repository, template linked, host macros
equal the YAML, and, once the LLD rule has run, that discovered items exist for exactly the
selected interfaces with values arriving and no unsupported items.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from netalert import config, envsafety, model, planner, template as tpl   # noqa: E402
from netalert.zbx import HttpTransport, ZabbixClient                       # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def discovered_interfaces(c, hostid):
    rows = c.call("item.get", {"output": ["itemid", "key_", "lastclock", "state"], "hostids": [hostid],
                               "search": {"key_": "netops.if."}, "selectTags": ["tag", "value"]})
    names = set()
    for r in rows:
        for t in r.get("tags", []):
            if t["tag"] == "interface":
                names.add(t["value"])
    return names, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="lab")
    ap.add_argument("--config", default=os.path.join(BASE, "config", "interfaces.yaml"))
    ap.add_argument("--wait", type=int, default=420, help="seconds to wait for discovery and first values")
    a = ap.parse_args()
    env = envsafety.load_env(BASE, a.env)
    url, token = envsafety.resolve_target(env)
    c = ZabbixClient(HttpTransport(url, token, env["zabbix"].get("verify_tls", True)), read_only=True)
    ident = envsafety.verify(BASE, env, c, url)
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print("%s  %s %s" % ("PASS" if ok else "FAIL", name, detail))

    check("identity matches --env", ident.ok and ident.state == "ok", ident.state)
    desired = config.load(a.config)
    tp = planner.get_template(c)
    check("template exists and is ours", bool(tp) and tpl.MARKER in tp["description"])
    if tp:
        live_fp = planner.live_fingerprint(c, tp["templateid"])
        diff = (["template content unreadable with this account"] if live_fp is None else
                planner.diff_fingerprint(tpl.fingerprint_doc(tpl.build()), live_fp))
        check("template content equals repository", not diff, "; ".join(diff))
    hosts = planner.get_hosts(c, list(desired.hosts))
    for h, hc in sorted(desired.hosts.items()):
        live = hosts.get(h)
        check("%s exists" % h, live)
        if not live:
            continue
        check("%s has template linked" % h, any(t["host"] == tpl.TEMPLATE_NAME for t in live["parentTemplates"]))
        want = model.host_macros(hc, bool(env.get("suppress_stock")))
        have = dict((m["macro"], m["value"]) for m in live["macros"])
        missing = [m for m, v in want.items() if have.get(m) != v]
        check("%s macros equal YAML" % h, not missing, ", ".join(missing[:3]))
        names = set(hc["interfaces"])
        deadline = time.time() + a.wait
        while True:
            found, rows = discovered_interfaces(c, live["hostid"])
            oper = [r for r in rows if r["key_"].startswith("netops.if.oper[")]
            if (found == names and oper and all(r["lastclock"] != "0" for r in oper)) or time.time() > deadline:
                break
            time.sleep(15)
        check("%s discovered interfaces == YAML" % h, found == names,
              "discovered=%s expected=%s" % (sorted(found), sorted(names)))
        check("%s link-status values are arriving" % h, oper and all(r["lastclock"] != "0" for r in oper))
        bad = [r["key_"] for r in rows if r["state"] == "1"]
        check("%s no unsupported items" % h, not bad, ", ".join(bad[:3]))
        trig = c.call("trigger.get", {"output": ["description"], "hostids": [live["hostid"]],
                                       "filter": {"status": "0"}, "search": {"description": "Interface"}})
        check("%s trigger instances exist" % h, trig, "%d trigger(s)" % len(trig))
    print("RESULT: %s" % ("PASS" if all(results) else "FAIL"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
