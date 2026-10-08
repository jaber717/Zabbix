"""Offline evaluation of the compiled service tree with Zabbix 7.0 status semantics.

Used for (a) tests that prove the redundancy modelling, (b) the operator what-if command `sla.sh simulate`.
The semantics implemented here are the documented ones; whether the live server behaves identically is acceptance
test A-05..A-08 (a model of Zabbix is not Zabbix).

Status values: -1 OK, 0..5 = problem severity (Not classified .. Disaster).
"""
from . import tags as T

OK = -1


def problem_matches(service_problem_tags, problem_tags, semantics="and"):
    """service_problem_tags: [(tag, op, value)] ; problem_tags: {tag: value}. Empty condition list never matches."""
    if not service_problem_tags:
        return False
    results = []
    for tag, op, value in service_problem_tags:
        have = problem_tags.get(tag)
        results.append(have is not None and (have == value if op == T.OP_EQUALS else value in have))
    return all(results) if semantics == "and" else any(results)


def evaluate(desired, problems, semantics="and"):
    """problems: [{"tags": {...}, "severity": 0..5}] -> {sla_id: status}"""
    memo = {}

    def status(sid):
        if sid in memo:
            return memo[sid]
        s = desired.services[sid]
        own = [p["severity"] for p in problems if problem_matches(s["problem_tags"], p["tags"], semantics)]
        kids = [status(c) for c in s["children"]]
        if s["children"]:
            if s["algorithm"] == 1:                    # most critical if all children have problems
                child = max(kids) if all(k != OK for k in kids) else OK
            elif s["algorithm"] == 2:                  # most critical of children
                child = max(kids)
            else:
                child = OK
        else:
            child = OK
        memo[sid] = max([child] + own) if (own or child != OK) else OK
        return memo[sid]
    for sid in desired.services:
        status(sid)
    return memo


def netops_link_down(link_id, severity=5):
    return {"tags": {T.NETOPS_LINK_ID: link_id, T.NETOPS_ALERT: "link_down", "severity_label": "disaster", "site": "WAN-LAB"}, "severity": severity}


def netops_alert(link_id, alert, severity=5):
    """Any non-availability NETOPS alert (util_rx, util_tx, errors, discards, flapping...)"""
    return {"tags": {T.NETOPS_LINK_ID: link_id, T.NETOPS_ALERT: alert, "severity_label": "disaster", "site": "WAN-LAB"}, "severity": severity}


def probe_down(pid, severity=5):
    return {"tags": {T.PROBE_DOWN: pid}, "severity": severity}


def probe_stale(pid):
    return {"tags": {T.PROBE_STALE: pid}, "severity": 2}


def down_services(desired, problems, semantics="and"):
    st = evaluate(desired, problems, semantics)
    return sorted(s for s, v in st.items() if v != OK)
