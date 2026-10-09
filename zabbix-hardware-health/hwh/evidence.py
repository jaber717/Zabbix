"""Authoritative, server-side evidence for NEGATIVE synthetic cases (B, C, D). Read-only.

A negative case proves nothing by itself: zero notifications mean "the action filtered the event" only if the action was ENABLED for the whole time
the case ran. Snapshots taken by the tester (even honest ones) cannot show the absence of an unobserved disable/re-enable, and a local "sent" mark
cannot show a value reached Zabbix. This module therefore asks Zabbix:

  * auditlog.get   the action's own configuration-change history (needs Super Admin READ access - never requested, created or raised by this tool)
  * history.get    the samples actually received on the exact synthetic trapper item
  * settings.get   whether audit logging is switched on

Rule: PASS only when adequate authoritative evidence exists and is consistent. Anything unavailable, incomplete, truncated, too recent, ambiguous
under clock skew, or unparseable is INCONCLUSIVE; any contradiction is FAIL. An empty answer is never read as "nothing happened".

Returns (fails, inconclusive) - lists of messages; both empty means the evidence is adequate and consistent."""
import json

from . import action as A
from .api import AuditError

SKEW = 5                  # seconds of tolerated clock difference between this host and the Zabbix server
SETTLE = 60               # seconds the server needs to flush audit records before the log may be treated as complete
LIMIT = 1000              # a result of exactly this size is treated as possibly truncated
AUDIT_RESOURCE_ACTION = 5     # auditlog resourcetype of an action (checked empirically: the action's own 'add' record must be found, else INCONCLUSIVE)
STATUS_KEY = "action.status"
EXPECTED_VALUES = {"B": {"2", "0"}, "C": {"5"}, "D": {"3", "0"}}


class Unavailable(Exception):
    pass


def _call(api, method, params):
    try:
        return api.call(method, params)
    except AuditError as exc:
        raise Unavailable("%s is not available to this account (%s)" % (method, str(exc)[:160]))


def parse_details(d):
    """Audit `details` is a JSON object {"action.status": ["update", new, old], ...}. -> dict, {} for empty, None if unparseable."""
    if d is None or str(d).strip() == "":
        return {}
    try:
        o = json.loads(d)
    except (TypeError, ValueError):
        return None
    return o if isinstance(o, dict) else None


def _new(v):
    if isinstance(v, list):
        return str(v[1]) if len(v) >= 2 else None
    return None if v is None else str(v)


def _audit_query(api, extra, count=False):
    p = {"output": "extend", "sortfield": ["clock"], "sortorder": "ASC", "limit": LIMIT}
    p.update(extra)
    if count:
        p = dict((k, v) for k, v in p.items() if k not in ("output", "sortfield", "sortorder", "limit"))
        p["countOutput"] = True
    return _call(api, "auditlog.get", p)


def _complete(api, extra, rows, label, inc):
    if len(rows) >= LIMIT:
        inc.append("INCONCLUSIVE: the audit query for %s returned %d rows (the limit): the history may be truncated" % (label, len(rows)))
        return False
    total = _audit_query(api, extra, count=True)
    try:
        total = int(total)
    except (TypeError, ValueError):
        inc.append("INCONCLUSIVE: the audit row count for %s is unreadable" % label)
        return False
    if total != len(rows):
        inc.append("INCONCLUSIVE: the audit query for %s returned %d rows but the server counts %d: the history is incomplete" % (label, len(rows), total))
        return False
    return True


def audit_evidence(api, ledger, case, b, a, live_status, relevant_times, now_ts):
    """Authoritative check of the ACTION's configuration history around one case interval [b, a] (epoch seconds)."""
    fails, inc = [], []
    aid = str(ledger.data.get("action"))
    if now_ts < a + SETTLE:
        return fails, ["INCONCLUSIVE: audit records are written asynchronously; verify at least %ds after the 'after' observation (now is %ds after it)" % (SETTLE, now_ts - a)]
    try:
        st = _call(api, "settings.get", {"output": ["auditlog_enabled"]})
        st = st[0] if isinstance(st, list) and st else st
        if not isinstance(st, dict) or str(st.get("auditlog_enabled", "")) != "1":
            return fails, ["INCONCLUSIVE: audit logging is not enabled on this Zabbix (auditlog_enabled=%r): there is no configuration history to rely on" % (st.get("auditlog_enabled") if isinstance(st, dict) else st)]
        base = {"filter": {"resourcetype": [AUDIT_RESOURCE_ACTION], "resourceid": [aid]}}
        rows = _audit_query(api, base)
        if not _complete(api, base, rows, "action %s" % aid, inc):
            return fails, inc
        adds = [r for r in rows if str(r.get("action")) == "0"]
        if not adds:
            return fails, ["INCONCLUSIVE: the audit log holds no 'add' record for action %s: audit logging may not have been active when it was created, "
                           "the record may have been housekept, or the account cannot see it. Absence of change records is NOT evidence of no change" % aid]
        if len(adds) > 1:
            fails.append("the audit log records action %s as added %d times" % (aid, len(adds)))
        add = adds[0]
        add_clock = int(add["clock"])
        if add.get("resourcename") not in (None, "", A.ACTION_NAME):
            inc.append("INCONCLUSIVE: the 'add' record's resource name is %r, not the hardware action" % add.get("resourcename"))
        d0 = parse_details(add.get("details"))
        status0 = None if not d0 else _new(d0.get(STATUS_KEY))
        if status0 is None:
            inc.append("INCONCLUSIVE: the 'add' record does not state the initial action status")
        changes, other_updates = [], []
        for r in rows:
            act, clk = str(r.get("action")), int(r["clock"])
            if act == "2":
                fails.append("the audit log records DELETION of action %s at %d" % (aid, clk))
            elif act == "1":
                det = parse_details(r.get("details"))
                if det is None:
                    inc.append("INCONCLUSIVE: an update record of action %s at %d has unparseable details" % (aid, clk))
                    continue
                if STATUS_KEY in det:
                    v = _new(det[STATUS_KEY])
                    if v is None:
                        inc.append("INCONCLUSIVE: a status change at %d cannot be read" % clk)
                    else:
                        changes.append((clk, v))
                other = sorted(k for k in det if k != STATUS_KEY)
                if other:
                    other_updates.append((clk, other))
        for clk, keys in other_updates:
            msg = "the audit log records an update of the action DEFINITION at %d (%s)" % (clk, ", ".join(keys[:4]))
            if b - SKEW <= clk <= a + SKEW:
                fails.append(msg + " inside the case interval")
            else:
                inc.append("INCONCLUSIVE: " + msg + " outside the interval: the definition the case ran against cannot be established")
        changes.sort()

        def status_at(t):
            cur = status0
            for c, v in changes:
                if c <= t:
                    cur = v
            return cur
        first = min(relevant_times) if relevant_times else b
        if status_at(first - SKEW) != "0":
            if status_at(first + SKEW) == "0":
                inc.append("INCONCLUSIVE: the action was enabled within %ds of the first event/send of case %s; clock skew makes the order ambiguous (wait before sending)" % (SKEW, case))
            else:
                fails.append("the audit log shows the hardware action NOT enabled when case %s ran (status %r)" % (case, status_at(first - SKEW)))
        else:
            enable_clock = max([c for c, v in changes if c <= first - SKEW and v == "0"] + [add_clock])
            flips = [(c, v) for c, v in changes if enable_clock < c <= a + SKEW]
            if flips:
                fails.append("the audit log records the action status changing during case %s: %s" % (case, ", ".join("%d->%s" % (c, v) for c, v in flips)))
        final = status_at(10 ** 12)
        if final is not None and str(live_status) != final:
            fails.append("CONTRADICTION: the audit log says the action's status is %r but Zabbix reports %r" % (final, live_status))
        if not any(int(r["clock"]) > a + SKEW for r in rows):
            inc.append("INCONCLUSIVE: no audit record for the action exists after the interval (the final disable): continuity of audit logging after the case is not shown")
        # same-named actions, recreate, duplicates
        q2 = {"filter": {"resourcetype": [AUDIT_RESOURCE_ACTION]}, "search": {"resourcename": A.ACTION_NAME}, "time_from": add_clock}
        rows2 = _audit_query(api, q2)
        if _complete(api, q2, rows2, "actions named %s" % A.ACTION_NAME, inc):
            for r in rows2:
                if str(r.get("action")) == "0" and str(r.get("resourceid")) != aid:
                    fails.append("another action named %s was created at %s (id %s): recreate/duplicate" % (A.ACTION_NAME, r["clock"], r.get("resourceid")))
        # audit settings changes since creation (logging could have been switched off and on)
        # only auditlog_enabled gates the evidence. auditlog_mode (Zabbix 7.0) controls logging of LLD / network discovery / autoregistration by the
        # server (System user) - it does not affect logging of user changes to actions, so a mode change is irrelevant here (v0.3-rc2 correction).
        q3 = {"search": {"details": "auditlog_enabled"}, "time_from": add_clock}
        rows3 = _audit_query(api, q3)
        if _complete(api, q3, rows3, "audit-settings changes", inc) and rows3:
            inc.append("INCONCLUSIVE: audit logging settings were changed since the action was created (%d record(s)): continuity of the log is not established" % len(rows3))
    except Unavailable as exc:
        return [], ["INCONCLUSIVE: authoritative evidence source unavailable - %s. Reading the audit log requires Super Admin READ access; this tool never requests, "
                    "creates or raises privileges. Without it a negative case cannot be shown to have run against an enabled action." % exc]
    return fails, inc


def probe(api):
    """Read-only capability check for the authoritative evidence sources. Writes nothing, creates nothing, changes no setting."""
    out = {"settings_readable": False, "auditlog_enabled": None, "auditlog_readable": False, "history_readable": False, "detail": []}
    try:
        st = _call(api, "settings.get", {"output": ["auditlog_enabled"]})
        st = st[0] if isinstance(st, list) and st else st
        out["settings_readable"] = isinstance(st, dict)
        out["auditlog_enabled"] = str(st.get("auditlog_enabled")) == "1" if isinstance(st, dict) else None
    except Unavailable as exc:
        out["detail"].append(str(exc))
    try:
        _call(api, "auditlog.get", {"output": ["auditid", "clock"], "limit": 1, "sortfield": ["clock"], "sortorder": "DESC"})
        out["auditlog_readable"] = True
    except Unavailable as exc:
        out["detail"].append(str(exc) + " - needs Super Admin READ access, which this tool never requests or grants")
    try:
        _call(api, "history.get", {"output": "extend", "limit": 1, "history": 3, "itemids": ["0"]})
        out["history_readable"] = True
    except Unavailable as exc:
        out["detail"].append(str(exc))
    out["authoritative_evidence_available"] = bool(out["settings_readable"] and out["auditlog_readable"] and out["history_readable"] and out["auditlog_enabled"])
    return out


def history_evidence(api, ledger, case, b, a, sent_times):
    """The values the synthetic trapper item REALLY received (history.get) inside the interval; a local 'sent' mark is never enough."""
    fails, inc = [], []
    expected = EXPECTED_VALUES.get(case)
    iid = ledger.data.get("item")
    if not expected or not iid:
        return fails, ["INCONCLUSIVE: no recorded trapper item for case %s" % case]
    try:
        items = _call(api, "item.get", {"output": ["itemid", "key_", "value_type", "history"], "itemids": [iid]})
        if not items or items[0]["key_"] != "netops.hw.synthetic.state":
            return [], ["INCONCLUSIVE: the recorded item %s is not the synthetic trapper item" % iid]
        it = items[0]
        if str(it.get("history")) in ("0", "0s"):
            return [], ["INCONCLUSIVE: the item stores no history (history=%s): received values cannot be shown" % it.get("history")]
        rows = _call(api, "history.get", {"output": "extend", "itemids": [iid], "history": int(it["value_type"]), "time_from": b - SKEW, "time_till": a + SKEW,
                                          "sortfield": "clock", "sortorder": "ASC", "limit": LIMIT})
    except Unavailable as exc:
        return [], ["INCONCLUSIVE: %s" % exc]
    if len(rows) >= LIMIT:
        return [], ["INCONCLUSIVE: the history query returned the limit: truncated"]
    if not rows:
        return [], ["INCONCLUSIVE: no history sample exists for item %s in the interval %d..%d: the value is not shown to have reached Zabbix (history may be housekept, or it was never received)" % (iid, b, a)]
    vals = [str(r["value"]) for r in rows]
    unexpected = sorted(set(vals) - expected)
    if unexpected:
        fails.append("CONTRADICTION: the item received unexpected value(s) %s during case %s (expected only %s): the cases overlapped or another sender is active" % (unexpected, case, sorted(expected)))
    missing = sorted(expected - set(vals))
    if missing:
        inc.append("INCONCLUSIVE: expected value(s) %s were not found in the item history for case %s" % (missing, case))
    if sent_times:
        first_sent = min(int(t) for t in sent_times)
        good = [r for r in rows if str(r["value"]) in expected and int(r["clock"]) >= first_sent - SKEW]
        if not good:
            inc.append("INCONCLUSIVE: no expected sample was received at or after the recorded send time")
    return fails, inc
