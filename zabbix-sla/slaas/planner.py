"""Diff desired state against live state. Pure given its inputs; `build` does the (read-only) API reads.

Ownership rules (never relaxed):
  * only objects carrying managed_by=zabbix-sla (services/items/triggers) or the description marker (SLAs) are ever updated or deleted;
  * an unmanaged object with the same name as one we need is a CONFLICT - it is never adopted or overwritten;
  * deletions happen only with prune=True, so a removed inventory entry is reported as an orphan until an operator opts in.
Drift is semantic: it compares meaning (algorithm, problem-tag conditions, child sla_ids, SLO ...), not object ids or ordering.
"""
import datetime
import zoneinfo

from . import state as S
from . import tags as T

KINDS = ("services", "slas", "items", "triggers")


class Change(object):
    def __init__(self, kind, action, key, fields=(), want=None, have=None):
        self.kind, self.action, self.key = kind, action, key
        self.fields = list(fields)
        self.want, self.have = want, have

    def line(self):
        extra = (" [%s]" % ", ".join(self.fields)) if self.fields else ""
        return "%-6s %-9s %s%s" % (self.action.upper(), self.kind[:-1], self.key, extra)


class Plan(object):
    def __init__(self):
        self.changes = []
        self.conflicts = []
        self.warnings = []
        self.orphans = []        # managed objects not in the inventory (kept unless prune)
        self.hosts = {}          # runner host name -> {"hostid", "interfaceid"}

    @property
    def ok(self):
        return not self.conflicts

    def counts(self):
        c = {}
        for ch in self.changes:
            c[ch.action] = c.get(ch.action, 0) + 1
        return c

    def lines(self):
        return [c.line() for c in self.changes]


def read_hosts(client, names):
    if not names:
        return {}
    rows = client.call("host.get", {"output": ["hostid", "host"], "filter": {"host": sorted(names)}, "selectInterfaces": ["interfaceid", "main", "type"]})
    out = {}
    for h in rows:
        itf = sorted(h.get("interfaces", []), key=lambda i: (str(i.get("main")) != "1", i["interfaceid"]))
        out[h["host"]] = {"hostid": h["hostid"], "interfaceid": itf[0]["interfaceid"] if itf else None}
    return out


def _month_start(now, tz):
    n = now.astimezone(zoneinfo.ZoneInfo(tz))
    return int(datetime.datetime(n.year, n.month, 1, tzinfo=zoneinfo.ZoneInfo(tz)).timestamp())


def _history_conflict(key, want, have, now):
    """Closed-month history of an SLA is immutable: excluded downtimes that ended before this month, and a reached effective_date, never change."""
    cut = _month_start(now, have["timezone"])
    old = set(map(tuple, have["excluded_downtimes"]))
    new = set(map(tuple, want["excluded_downtimes"]))
    changed = [e for e in old ^ new if e[2] <= cut]
    if changed:
        return "sla %s: excluded downtime in a closed month would change (%s) - closed periods are immutable" % (key, ", ".join(sorted(e[0] for e in changed)))
    if want["effective_date"] != have["effective_date"] and have["effective_date"] <= int(now.timestamp()):
        return "sla %s: effective_date has already been reached and cannot be changed (it would rewrite history) - create a new SLA class instead" % key
    return None


def diff(desired, live, foreign, anomalies, hosts, env, prune=False, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    plan = Plan()
    plan.hosts = hosts
    plan.warnings.extend(anomalies)
    prod = bool(env.get("is_production"))

    for kind in KINDS:
        want_all, have_all = desired[kind], live[kind]
        for key in sorted(want_all):
            want = want_all[key]
            have = have_all.get(key)
            if kind in ("items", "triggers") and want["_host"] not in hosts:
                plan.conflicts.append("%s %s: runner host '%s' does not exist in this Zabbix" % (kind[:-1], key, want["_host"]))
                continue
            if kind == "slas" and prod and not want.get("_approved", True):
                plan.conflicts.append("sla %s: the SLO is not approved; unapproved SLOs are never applied to production" % key)
                continue
            if have is None:
                clash = None
                if kind in ("services", "slas") and want["name"] in foreign[kind]:
                    clash = foreign[kind][want["name"]]
                if clash:
                    plan.conflicts.append("%s %s: an unmanaged %s named '%s' already exists (id %s); it is never adopted - rename or remove it"
                                          % (kind[:-1], key, kind[:-1], want["name"], clash))
                    continue
                plan.changes.append(Change(kind, "create", key, want=want))
                continue
            fields = S.differing_fields(kind, want, have)
            if fields and kind == "slas":
                hc = _history_conflict(key, want, have, now)
                if hc:
                    plan.conflicts.append(hc)
                    continue
            if fields:
                plan.changes.append(Change(kind, "update", key, fields, want=want, have=have))
        for key in sorted(set(have_all) - set(want_all)):
            plan.orphans.append("%s %s" % (kind[:-1], key))
            if prune:
                plan.changes.append(Change(kind, "delete", key, have=have_all[key]))
    if plan.orphans and not prune:
        plan.warnings.append("%d managed object(s) are no longer in the inventory and were left in place (use --prune to remove them)" % len(plan.orphans))
    return plan


def build(client, desired, env, prune=False, hosts_extra=(), now=None):
    """Read live state (read-only calls) and diff. `desired` is a normalised state."""
    live, foreign, anomalies = S.read_live(client)
    names = set(v["_host"] for k in ("items", "triggers") for v in desired[k].values())
    names |= set(v["_host"] for k in ("items", "triggers") for v in live[k].values())
    names |= set(hosts_extra)
    hosts = read_hosts(client, names)
    return diff(desired, live, foreign, anomalies, hosts, env, prune, now), live
