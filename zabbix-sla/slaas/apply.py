"""Safe apply: backup -> ordered writes (journalled) -> readback verification; and rollback to a backup.

Rollback is not a separate mechanism: a backup holds the normalised pre-apply state of every object this project owns, and
restoring it is the same diff-and-apply run with that state as the target (prune on). Objects are matched by their stable
identity (sla_id / class / host+key), never by Zabbix id, so a service deleted and recreated by a rollback is still the same service.
Note: Zabbix ids of recreated objects change, so anything that stores ids (dashboards, saved links) must be re-pointed.
"""
import datetime
import json
import os

from . import planner
from . import state as S
from ._compat import ZabbixError

BACKUP_FORMAT = 1


class ApplyError(Exception):
    def __init__(self, message, done, backup=None, journal=None):
        Exception.__init__(self, message)
        self.done, self.backup, self.journal = done, backup, journal


def _tags(rows):
    return [{"tag": t, "value": v} for t, v in rows]


def service_params(w):
    return {"name": w["name"], "algorithm": w["algorithm"], "description": w["description"], "tags": _tags(w["tags"]),
            "problem_tags": [{"tag": t, "operator": o, "value": v} for t, o, v in w["problem_tags"]]}


def sla_params(w):
    return {"name": w["name"], "period": w["period"], "slo": w["slo"], "effective_date": w["effective_date"], "timezone": w["timezone"],
            "status": w["status"], "description": w["description"], "service_tags": [{"tag": t, "operator": o, "value": v} for t, o, v in w["service_tags"]],
            "schedule": [{"period_from": a, "period_to": b} for a, b in w["schedule"]],
            "excluded_downtimes": [{"name": n, "period_from": a, "period_to": b} for n, a, b in w["excluded_downtimes"]]}


def item_params(key, w, host):
    p = {"hostid": host["hostid"], "name": w["name"], "key_": key.split("|", 1)[1], "type": w["type"], "value_type": w["value_type"],
         "delay": w["delay"], "tags": _tags(w["tags"])}
    if w["params"]:
        p["params"] = w["params"]
    if w["type"] == 3 and host.get("interfaceid"):
        p["interfaceid"] = host["interfaceid"]
    return p


def trigger_params(w):
    return {"description": w["description"], "expression": w["expression"], "priority": w["priority"], "tags": _tags(w["tags"])}


def _stamp(now=None):
    return (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def state_dir(base, sub):
    d = os.path.join(base, "state", sub)
    os.makedirs(d, exist_ok=True)
    return d


def write_backup(base, env, live, plan, version, label, now=None):
    data = {"format": BACKUP_FORMAT, "label": label, "environment": env["environment"], "taken_utc": _stamp(now), "zabbix_version": version,
            "planned": plan.lines(), "state": S.to_json(live)}
    d = state_dir(base, "backups")
    path = os.path.join(d, "%s-%s.json" % (env["environment"], data["taken_utc"]))
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, "%s-%s_%d.json" % (env["environment"], data["taken_utc"], n))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def read_backup(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("format") != BACKUP_FORMAT:
        raise ValueError("%s is not a supported backup (format %r)" % (path, data.get("format")))
    return data


class Journal(object):
    def __init__(self, base, env, stamp):
        self.path = os.path.join(state_dir(base, "journal"), "%s-%s.jsonl" % (env["environment"], stamp))
        self.n = 0

    def add(self, label, ok=True, detail=""):
        self.n += 1
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"seq": self.n, "label": label, "ok": ok, "detail": detail}) + "\n")


def execute(client, plan, live, journal, log):
    """Run plan.changes in dependency order. Returns the number of API steps done."""
    done = [0]
    by = {}
    for ch in plan.changes:
        by.setdefault((ch.kind, ch.action), []).append(ch)

    def step(label, method, params):
        try:
            res = client.call(method, params)
        except ZabbixError as exc:
            journal.add(label, ok=False, detail=str(exc)[:300])
            raise ApplyError("%s failed: %s" % (label, exc), done[0])
        journal.add(label)
        done[0] += 1
        log("  ok  %s" % label)
        return res

    # 1. probe items (calculated item after the items it reads), then probe triggers
    items = sorted(by.get(("items", "create"), []) + by.get(("items", "update"), []), key=lambda c: (c.want["type"] == 15, c.key))
    for ch in items:
        h = plan.hosts[ch.want["_host"]]
        if ch.action == "create":
            step("create item %s" % ch.key, "item.create", item_params(ch.key, ch.want, h))
        else:
            p = item_params(ch.key, ch.want, h)
            p = dict((k, v) for k, v in p.items() if k not in ("hostid", "interfaceid", "key_"))
            p["itemid"] = ch.have["_id"]
            step("update item %s [%s]" % (ch.key, ", ".join(ch.fields)), "item.update", p)
    for ch in sorted(by.get(("triggers", "create"), []) + by.get(("triggers", "update"), []), key=lambda c: c.key):
        if ch.action == "create":
            step("create trigger %s" % ch.key, "trigger.create", trigger_params(ch.want))
        else:
            p = trigger_params(ch.want)
            p.pop("description")
            p["triggerid"] = ch.have["_id"]
            step("update trigger %s [%s]" % (ch.key, ", ".join(ch.fields)), "trigger.update", p)

    # 2. services: create bare, update fields, then (re)link children once every id is known
    ids = dict((sid, v["_id"]) for sid, v in live["services"].items())
    for ch in sorted(by.get(("services", "create"), []), key=lambda c: c.key):
        res = step("create service %s" % ch.key, "service.create", service_params(ch.want))
        ids[ch.key] = res["serviceids"][0]
    for ch in sorted(by.get(("services", "update"), []), key=lambda c: c.key):
        fields = [f for f in ch.fields if f != "children"]
        if fields:
            p = dict((k, v) for k, v in service_params(ch.want).items() if k in fields)
            p["serviceid"] = ch.have["_id"]
            step("update service %s [%s]" % (ch.key, ", ".join(fields)), "service.update", p)
    for ch in sorted(by.get(("services", "create"), []) + by.get(("services", "update"), []), key=lambda c: c.key):
        if ch.action == "update" and "children" not in ch.fields:
            continue
        if not ch.want["children"] and ch.action == "create":
            continue
        kids = [{"serviceid": ids[c]} for c in ch.want["children"]]
        kids += [{"serviceid": f} for f in (ch.have or {}).get("_foreign_children", [])]       # operator-added children of someone else's are preserved
        step("link %d child(ren) of service %s" % (len(ch.want["children"]), ch.key), "service.update", {"serviceid": ids[ch.key], "children": kids})

    # 3. SLAs
    for ch in sorted(by.get(("slas", "create"), []) + by.get(("slas", "update"), []), key=lambda c: c.key):
        if ch.action == "create":
            step("create sla %s" % ch.key, "sla.create", sla_params(ch.want))
        else:
            p = sla_params(ch.want)
            p["slaid"] = ch.have["_id"]
            step("update sla %s [%s]" % (ch.key, ", ".join(ch.fields)), "sla.update", p)

    # 4. deletions (prune only): SLAs first, then triggers/items, services last
    for kind, method, idkey in (("slas", "sla.delete", "_id"), ("triggers", "trigger.delete", "_id"), ("items", "item.delete", "_id"), ("services", "service.delete", "_id")):
        chs = by.get((kind, "delete"), [])
        if chs:
            step("delete %d %s" % (len(chs), kind), method, [c.have[idkey] for c in sorted(chs, key=lambda c: c.key)])
    return done[0]


def apply(client, env, desired, base, version, log, prune=False, label="apply", now=None, allow_empty=False):
    """Plan, back up, write, verify. Returns dict(plan, backup, journal, steps, verify_changes)."""
    if not any(desired[k] for k in S.COMPARED) and not allow_empty:
        raise ApplyError("the desired state is empty: refusing to apply (this would manage nothing, or remove everything with --prune). "
                         "Use --allow-empty only when that is really intended.", 0)
    plan, live = planner.build(client, desired, env, prune=prune, now=now)
    if not plan.ok:
        raise ApplyError("plan has conflicts: " + "; ".join(plan.conflicts), 0)
    if not plan.changes:
        return {"plan": plan, "backup": None, "journal": None, "steps": 0, "verify_changes": []}
    backup = write_backup(base, env, live, plan, version, label, now)
    log("backup written: %s" % backup)
    journal = Journal(base, env, _stamp(now))
    try:
        steps = execute(client, plan, live, journal, log)
    except ApplyError as exc:
        exc.backup, exc.journal = backup, journal.path
        raise
    after, _ = planner.build(client, desired, env, prune=prune, now=now)
    return {"plan": plan, "backup": backup, "journal": journal.path, "steps": steps, "verify_changes": after.lines()}


def verify(client, env, desired, prune=False, now=None):
    """Readback: live state must equal the desired state. Returns the list of remaining differences (empty = verified)."""
    plan, _ = planner.build(client, desired, env, prune=prune, now=now)
    return plan.lines() + ["CONFLICT " + c for c in plan.conflicts]


def rollback(client, env, backup_path, base, version, log, now=None):
    data = read_backup(backup_path)
    if data["environment"] != env["environment"]:
        raise ApplyError("backup %s is for environment '%s', not '%s' - refusing" % (os.path.basename(backup_path), data["environment"], env["environment"]), 0)
    target = S.from_json(data["state"])
    return_plan, live = planner.build(client, target, env, prune=True, now=now)
    if not return_plan.ok:
        raise ApplyError("rollback has conflicts: " + "; ".join(return_plan.conflicts), 0)
    if not return_plan.changes:
        return {"plan": return_plan, "backup": None, "journal": None, "steps": 0, "verify_changes": []}
    safety = write_backup(base, env, live, return_plan, version, "pre-rollback of " + os.path.basename(backup_path), now)
    log("pre-rollback backup written: %s" % safety)
    journal = Journal(base, env, _stamp(now) + "-rollback")
    try:
        steps = execute(client, return_plan, live, journal, log)
    except ApplyError as exc:
        exc.backup, exc.journal = safety, journal.path
        raise
    after, _ = planner.build(client, target, env, prune=True, now=now)
    return {"plan": return_plan, "backup": safety, "journal": journal.path, "steps": steps, "verify_changes": after.lines()}
