"""Live acceptance helpers, run by the independent tester against LAB. They are not part of the normal operator flow.

tag_semantics  Proves whether several service problem tags combine with AND or OR on THIS Zabbix (evidence E-01). It creates one
               always-firing trigger tagged only `acc_a=1`, a service that requires acc_a AND acc_b, and a control service that
               requires acc_a alone. AND is proven only if the control goes to problem and the two-tag service does not.
               It uses `acc_*` tags, never `netops_alert`, so no NETOPS notification can be triggered. Everything is deleted afterwards.
api_shapes     Read-only. Checks that the objects the planner reads have the fields it relies on (run after the first LAB apply).
"""
import time

from ._compat import ZabbixError

ACC_TAG_A, ACC_TAG_B = "acc_a", "acc_b"
OK_STATUS = "-1"


def _status(client, serviceid):
    row = client.call("service.get", {"output": ["serviceid", "status"], "serviceids": [serviceid]})
    return row[0]["status"] if row else None


def _wait(client, serviceid, want_problem, timeout, interval, sleep):
    waited, last = 0, None
    while True:
        last = _status(client, serviceid)
        if (last != OK_STATUS) == want_problem and last is not None:
            return last, waited
        if waited >= timeout:
            return last, waited
        sleep(interval)
        waited += interval


def tag_semantics(client, host, item_key, timeout=180, interval=10, sleep=time.sleep, log=print):
    created = {"triggers": [], "services": []}
    result = {"test": "tag_semantics", "host": host, "item_key": item_key, "outcome": "inconclusive", "detail": ""}
    try:
        hosts = client.call("host.get", {"output": ["hostid", "host"], "filter": {"host": [host]}})
        if not hosts:
            result["detail"] = "host '%s' not found" % host
            return result
        t = client.call("trigger.create", {"description": "[NETOPS-SLA-ACC] tag semantics probe (temporary)", "priority": 1,
                                           "expression": "nodata(/%s/%s,30)<2" % (host, item_key), "tags": [{"tag": ACC_TAG_A, "value": "1"}]})
        created["triggers"].append(t["triggerids"][0])
        log("  created always-firing trigger %s tagged %s=1" % (t["triggerids"][0], ACC_TAG_A))
        both = client.call("service.create", {"name": "NETOPS-SLA-ACC two tags", "algorithm": 2,
                                              "problem_tags": [{"tag": ACC_TAG_A, "operator": 0, "value": "1"}, {"tag": ACC_TAG_B, "operator": 0, "value": "1"}]})
        ctrl = client.call("service.create", {"name": "NETOPS-SLA-ACC control", "algorithm": 2,
                                              "problem_tags": [{"tag": ACC_TAG_A, "operator": 0, "value": "1"}]})
        created["services"] += [both["serviceids"][0], ctrl["serviceids"][0]]
        c_status, c_wait = _wait(client, ctrl["serviceids"][0], True, timeout, interval, sleep)
        result["control_status"], result["control_waited_s"] = c_status, c_wait
        if c_status == OK_STATUS or c_status is None:
            result["detail"] = ("the control service (acc_a only) never went to problem within %ss: the trigger did not fire or services are not being calculated. "
                                "Nothing can be concluded - fix the environment and rerun." % timeout)
            return result
        b_status = _status(client, both["serviceids"][0])
        result["two_tag_status"] = b_status
        if b_status == OK_STATUS:
            result["outcome"] = "and"
            result["detail"] = "the control service is in problem but the service requiring acc_a AND acc_b is OK: problem tags combine with AND"
        else:
            result["outcome"] = "or"
            result["detail"] = ("the service requiring acc_a and acc_b went to problem although the problem only carries acc_a: tags combine with OR. "
                                "Per-link services CANNOT use link_id + netops_alert; use the SLA-owned signal-trigger contingency (HLD section 5).")
        return result
    finally:
        result["cleanup"] = "ok"
        for method, key, ids in (("service.delete", "services", created["services"]), ("trigger.delete", "triggers", created["triggers"])):
            if ids:
                try:
                    client.call(method, ids)
                except ZabbixError as exc:
                    result["cleanup"] = "FAILED: delete %s %s manually (%s)" % (key, ids, str(exc)[:120])
        log("  cleanup: %s" % result["cleanup"])


EXPECTED = {
    "service.get": (["serviceid", "name", "algorithm", "status"], ["tags", "problem_tags", "children", "parents"]),
    "sla.get": (["slaid", "name", "slo", "period", "timezone", "effective_date", "status", "description"], ["service_tags", "schedule", "excluded_downtimes"]),
}


def api_shapes(client):
    """-> {"checks": [{"what", "ok", "detail"}], "samples": {...}}  (read-only)"""
    checks, samples = [], {}

    def check(what, ok, detail=""):
        checks.append({"what": what, "ok": bool(ok), "detail": detail})

    ver = client.call("apiinfo.version")
    check("API version is 7.0.x", ver.startswith("7.0."), ver)
    svc = client.call("service.get", {"output": "extend", "selectTags": "extend", "selectProblemTags": "extend", "selectChildren": ["serviceid"], "selectParents": ["serviceid"], "limit": 3})
    sla = client.call("sla.get", {"output": "extend", "selectServiceTags": "extend", "selectSchedule": "extend", "selectExcludedDowntimes": "extend", "limit": 3})
    for method, rows in (("service.get", svc), ("sla.get", sla)):
        if not rows:
            check("%s returns rows" % method, False, "nothing to inspect - apply the LAB inventory first")
            continue
        flat, nested = EXPECTED[method]
        row = rows[0]
        samples[method] = dict((k, (v if not isinstance(v, (list, dict)) else type(v).__name__)) for k, v in row.items())
        for k in flat + nested:
            check("%s has '%s'" % (method, k), k in row, "")
        check("%s ids are strings" % method, isinstance(row.get("serviceid", row.get("slaid")), str))
    if svc:
        pt = [p for s in svc for p in s.get("problem_tags", [])]
        if pt:
            check("problem_tags carry tag/operator/value", all(set(("tag", "operator", "value")) <= set(p) for p in pt))
    if sla:
        sid = sla[0]["slaid"]
        sids = [s["serviceid"] for s in svc][:2]
        try:
            res = client.call("sla.getsli", {"slaid": sid, "serviceids": sids, "periods": 1})
            samples["sla.getsli"] = dict((k, type(v).__name__) for k, v in res.items())
            check("sla.getsli returns periods/serviceids/sli", set(("periods", "serviceids", "sli")) <= set(res), str(sorted(res)))
            if res.get("sli") and res["sli"][0]:
                cell = res["sli"][0][0]
                check("sli cell has uptime/downtime/sli/error_budget/excluded_downtime",
                      set(("uptime", "downtime", "sli", "error_budget", "excluded_downtime")) <= set(cell), str(sorted(cell)))
                samples["sla.getsli.cell"] = cell
        except ZabbixError as exc:
            check("sla.getsli is callable", False, str(exc)[:160])
    try:
        d = client.call("dashboard.get", {"output": ["dashboardid", "name"], "selectPages": "extend", "limit": 1})
        check("dashboard.get with selectPages works", True)
        if d and d[0].get("pages") and d[0]["pages"][0].get("widgets"):
            samples["dashboard.widget"] = d[0]["pages"][0]["widgets"][0]
    except ZabbixError as exc:
        check("dashboard.get with selectPages works", False, str(exc)[:160])
    return {"checks": checks, "samples": samples, "ok": all(c["ok"] for c in checks)}
