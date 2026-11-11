#!/usr/bin/env python3
"""Read-only Zabbix 7.0 API contract probe for LAB (no names printed, nothing written anywhere).

    ./scripts/lab-contract-probe.py --env lab

Checks the response shapes discovery and coverage depend on, against the live server, and prints only field
names, types and counts (no host, user, action or item names). Identity check first; read-only client: any write
method raises before it is sent. Exit 0 = every REQUIRED check passed. INFO lines answer LAB questions that the
documentation does not settle (they are recorded, not judged).
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from netalert import envsafety                                  # noqa: E402
from netalert.onboard_cli import load_dotenv                    # noqa: E402
from netalert.zbx import HttpTransport, ZabbixClient, ZabbixError  # noqa: E402

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ALERT_FIELDS = ["alertid", "actionid", "eventid", "p_eventid", "userid", "mediatypeid", "status", "alerttype", "clock"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="lab")
    ap.add_argument("--days", type=int, default=30, help="event history window for the alert checks")
    a = ap.parse_args()
    environ = dict(os.environ)
    load_dotenv(BASE, environ)
    env = envsafety.load_env(BASE, a.env)
    url, token = envsafety.resolve_target(env, environ)
    client = ZabbixClient(HttpTransport(url, token, env["zabbix"].get("verify_tls", True)), read_only=True)
    ident = envsafety.verify(BASE, env, client, url, environ)
    if not ident.ok:
        print("environment safety check failed: %s" % "; ".join(ident.messages))
        return 3
    return probe(client, int(time.time()), a.days, print)


def probe(client, now, days, out):
    """Run the checks on a read-only client. Returns the exit code."""
    if not client.read_only:
        out("FAIL  the probe must run on a read-only client")
        return 4
    results = []

    def check(name, ok, detail, required=True):
        results.append((name, ok, required))
        out("%-5s %-34s %s" % ("PASS" if ok else ("FAIL" if required else "INFO"), name, detail))

    def call(method, params):
        try:
            return client.call(method, params), None
        except ZabbixError as exc:
            return None, str(exc)

    v = client.version()
    check("C1 version", str(v).startswith("7.0."), "apiinfo.version %s" % v)

    trig, err = call("trigger.get", {"output": ["triggerid", "expression", "recovery_expression", "recovery_mode"],
                                     "selectFunctions": ["functionid", "itemid", "function", "parameter"],
                                     "filter": {"value": 0}, "limit": 20})
    if err:
        check("C2 trigger functions", False, "trigger.get rejected: %s" % err)
    else:
        fkeys = set(tuple(sorted(f)) for t in trig for f in t.get("functions", []))
        params_ok = all(str(f.get("parameter", "")).startswith("$") for t in trig for f in t.get("functions", []))
        raw = all(re.search(r"\{\d+\}", t["expression"]) for t in trig)
        check("C2 trigger functions", bool(trig) and fkeys == {("function", "functionid", "itemid", "parameter")}
              and params_ok, "%d trigger(s); function keys %s; parameter starts with '$': %s" % (
                  len(trig), sorted(fkeys), params_ok))
        check("C3 raw expression form", bool(trig) and raw, "every unexpanded expression uses {functionid}: %s" % raw)
        withmacro = [t for t in trig if "{$" in t["expression"]]
        if withmacro:
            exp, _ = call("trigger.get", {"output": ["expression"], "triggerids": [withmacro[0]["triggerid"]],
                                          "expandExpression": True})
            still = bool(exp) and "{$" in exp[0]["expression"]
            check("C3b expandExpression and macros", True, "user macros %s by expandExpression" % (
                "NOT substituted" if still else "SUBSTITUTED"), required=False)

    ev, err = call("event.get", {"output": ["eventid", "objectid", "value", "clock", "r_eventid"], "source": 0,
                                 "object": 0, "time_from": now - days * 86400, "limit": 500,
                                 "selectAlerts": ALERT_FIELDS})
    if err:
        check("C4 event alerts", False, "event.get rejected: %s" % err)
    else:
        has_prop = bool(ev) and all("alerts" in e for e in ev)
        akeys = set(k for e in ev or [] for al in e.get("alerts", []) for k in al)
        check("C4 event alerts", has_prop and (not akeys or set(ALERT_FIELDS) <= akeys),
              "%d event(s); 'alerts' on every event: %s; alert fields %s" % (len(ev or []), has_prop, sorted(akeys)))
        probs = [e for e in ev if str(e.get("value")) == "1"]
        check("C5 r_eventid on problems", bool(probs) and all("r_eventid" in e for e in probs),
              "%d problem event(s), %d recovered" % (len(probs), sum(1 for e in probs if str(e.get("r_eventid")) != "0")))
        by_id = dict((e["eventid"], e) for e in ev)
        layout = {"on recovery event": 0, "on problem event": 0, "other": 0}
        for e in ev:
            for al in e.get("alerts", []):
                if str(al.get("p_eventid", "0")) not in ("0", ""):
                    pe = by_id.get(al["p_eventid"])
                    if pe and str(al["eventid"]) == str(pe.get("r_eventid")):
                        layout["on recovery event"] += 1
                    elif str(al["eventid"]) == str(al["p_eventid"]):
                        layout["on problem event"] += 1
                    else:
                        layout["other"] += 1
        seen = sum(layout.values())
        check("C6 recovery alert placement", seen > 0 and layout["other"] == 0,
              "recovery-message alerts: %s%s" % (layout, "" if seen else " - none in the window; repeat after the "
                                                 "Problem/Recovery e-mail test"), required=seen > 0)

    hosts, err = call("host.get", {"output": ["hostid"], "selectInterfaces": ["type", "main", "available", "error"],
                                   "limit": 20})
    ikeys = set(k for h in hosts or [] for i in h.get("interfaces", []) for k in i)
    check("C7 interface availability", not err and {"available", "error"} <= ikeys, err or "fields %s" % sorted(ikeys))

    ug, err = call("usergroup.get", {"output": ["usrgrpid", "users_status"],
                                     "selectHostGroupRights": ["id", "permission"]})
    rkeys = set(k for g in ug or [] for r in g.get("hostgroup_rights", []) for k in r)
    check("C8 host group rights", not err and {"id", "permission"} <= rkeys and all("users_status" in g for g in ug),
          err or "%d group(s); rights fields %s" % (len(ug), sorted(rkeys)))

    acts, err = call("action.get", {"output": ["actionid"], "filter": {"eventsource": "0"},
                                    "selectOperations": "extend", "selectRecoveryOperations": "extend"})
    shapes = set(type(o.get("opmessage")).__name__ for x in acts or []
                 for o in x.get("operations", []) + x.get("recovery_operations", []) if "opmessage" in o)
    check("C9 opmessage shape", not err and bool(shapes) and shapes <= {"dict"},
          err or "opmessage types %s (coverage also accepts a one-element list)" % sorted(shapes))

    us, err = call("user.get", {"output": ["userid"], "selectMedias": ["mediatypeid", "active", "severity", "period"],
                                "selectUsrgrps": ["usrgrpid"]})
    mkeys = set(k for u in us or [] for m in u.get("medias", []) for k in m)
    check("C10 user media", not err and {"mediatypeid", "active", "severity", "period"} <= mkeys,
          err or "%d user(s) visible to this token; media fields %s" % (len(us), sorted(mkeys)))

    items, err = call("item.get", {"output": ["key_", "type", "master_itemid", "state", "lastclock"],
                                   "tags": [{"tag": "interface", "operator": 4}], "limit": 2000})
    kinds = {}
    for it in items or []:
        k = it["key_"].split("[")[0]
        kinds[k] = kinds.get(k, 0) + 1
    check("C11 interface-tagged items", not err and kinds.get("net.if.status", 0) > 0,
          err or "item key families with tag 'interface': %s" % dict(sorted(kinds.items())[:12]))
    dep = [it for it in items or [] if str(it.get("type")) == "18"]
    check("C12 dependent items", not dep or all(str(it.get("master_itemid", "0")) != "0" for it in dep),
          "%d dependent item(s), all with master_itemid" % len(dep), required=bool(dep))

    if client.writes_made():
        out("FAIL  a write was attempted - aborting")
        return 4
    failed = [n for n, ok, req in results if req and not ok]
    out("RESULT: %s (%d required check(s) failed)" % ("PASS" if not failed else "FAIL", len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
