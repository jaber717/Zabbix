"""Normalised, JSON-safe view of "the objects this project owns", from three sources: the inventory (desired), Zabbix (live), a backup.

One shape for all three is what makes semantic drift detection, readback verification and rollback the same diff.
Only JSON-native types are used (lists, never tuples) so a backup round-trips unchanged.

    {"services": {sla_id: {...}}, "slas": {class: {...}}, "items": {"host|key": {...}}, "triggers": {"host|description": {...}}}
Live-only bookkeeping lives under keys starting with "_" (ids, foreign children); it is ignored by the diff.
"""
import re

from . import tags as T
from .model import probe_objects

FORMAT = 1
_SLA_ID_RE = re.compile(r"sla_id=(\S+)")


def empty():
    return {"services": {}, "slas": {}, "items": {}, "triggers": {}}


def _tl(d):
    return sorted([k, str(v)] for k, v in d.items())


def _tags_from_api(rows):
    return sorted([r["tag"], r.get("value", "")] for r in (rows or []))


def _ptags_from_api(rows):
    return sorted([r["tag"], int(r.get("operator", 0)), r.get("value", "")] for r in (rows or []))


def is_managed_tags(rows):
    return any(r["tag"] == T.MANAGED_KEY and r.get("value") == T.MANAGED_VALUE for r in (rows or []))


# ------------------------------------------------------------------------------------------------ desired
def from_desired(desired, host_of_probe=None):
    """Desired (model.compile_inventory) -> normalised state. host_of_probe: {probe_id: runner host name} for active probes."""
    st = empty()
    for sid, s in desired.services.items():
        st["services"][sid] = {
            "name": s["name"], "algorithm": int(s["algorithm"]), "description": s.get("description", ""),
            "tags": _tl(s["tags"]), "problem_tags": sorted([t, int(o), v] for t, o, v in s["problem_tags"]),
            "children": sorted(s["children"]),
        }
    for cls, a in desired.slas.items():
        st["slas"][cls] = {
            "name": a["name"], "slo": round(float(a["slo"]), 4), "period": int(a["period"]), "timezone": a["timezone"], "status": int(a["status"]),
            "effective_date": int(a["effective_date"]), "description": a["description"],
            "service_tags": sorted([t["tag"], int(t["operator"]), t["value"]] for t in a["service_tags"]),
            "schedule": sorted([int(r["period_from"]), int(r["period_to"])] for r in a["schedule"]),
            "excluded_downtimes": sorted([e["name"], int(e["period_from"]), int(e["period_to"])] for e in a["excluded_downtimes"]),
            "_approved": bool(a.get("approved", False)),
        }
    for pid, p in desired.probes.items():
        host = p["runner"]
        objs = probe_objects(host, p)
        for it in objs["items"]:
            st["items"]["%s|%s" % (host, it["key"])] = {
                "name": it["name"], "type": int(it["type"]), "value_type": int(it["value_type"]), "delay": it["delay"],
                "params": it.get("params", ""), "tags": _tl(it["tags"]), "_host": host, "_probe": pid,
            }
        for tr in objs["triggers"]:
            st["triggers"]["%s|%s" % (host, tr["description"])] = {
                "expression": tr["expression"], "priority": int(tr["priority"]), "tags": _tl(tr["tags"]), "_host": host, "_probe": pid,
                "description": tr["description"],
            }
    return st


# ------------------------------------------------------------------------------------------------ live
def read_live(client):
    """-> (state of MANAGED objects, foreign: {"services": {name: id}, "slas": {name: id}}, anomalies [str])"""
    st, foreign, anomalies = empty(), {"services": {}, "slas": {}}, []

    svc = client.call("service.get", {"output": ["serviceid", "name", "algorithm", "description"], "selectTags": "extend",
                                      "selectProblemTags": "extend", "selectChildren": ["serviceid"]})
    id_to_sla = {}
    for s in svc:
        if is_managed_tags(s.get("tags")):
            tg = dict((t["tag"], t.get("value", "")) for t in s["tags"])
            if not tg.get(T.ID_KEY):
                anomalies.append("service %s '%s' carries managed_by but no sla_id tag - left untouched" % (s["serviceid"], s["name"]))
                continue
            id_to_sla[s["serviceid"]] = tg[T.ID_KEY]
        else:
            foreign["services"][s["name"]] = s["serviceid"]
    for s in svc:
        sid = id_to_sla.get(s["serviceid"])
        if sid is None:
            continue
        kids = [c["serviceid"] for c in s.get("children", [])]
        if sid in st["services"]:
            anomalies.append("two managed services share sla_id '%s' (ids %s and %s)" % (sid, st["services"][sid]["_id"], s["serviceid"]))
            continue
        st["services"][sid] = {
            "name": s["name"], "algorithm": int(s["algorithm"]), "description": s.get("description", ""),
            "tags": _tags_from_api(s["tags"]), "problem_tags": _ptags_from_api(s.get("problem_tags")),
            "children": sorted(id_to_sla[c] for c in kids if c in id_to_sla),
            "_id": s["serviceid"], "_foreign_children": [c for c in kids if c not in id_to_sla],
        }

    for a in client.call("sla.get", {"output": "extend", "selectServiceTags": "extend", "selectSchedule": "extend", "selectExcludedDowntimes": "extend"}):
        desc = a.get("description") or ""
        if T.SLA_DESC_MARKER not in desc:
            foreign["slas"][a["name"]] = a["slaid"]
            continue
        m = _SLA_ID_RE.search(desc)
        if not m:
            anomalies.append("sla %s '%s' carries the ownership marker but no sla_id - left untouched" % (a["slaid"], a["name"]))
            continue
        st["slas"][m.group(1)] = {
            "name": a["name"], "slo": round(float(a["slo"]), 4), "period": int(a["period"]), "timezone": a["timezone"], "status": int(a["status"]),
            "effective_date": int(a["effective_date"]), "description": desc,
            "service_tags": sorted([t["tag"], int(t.get("operator", 0)), t.get("value", "")] for t in a.get("service_tags", [])),
            "schedule": sorted([int(r["period_from"]), int(r["period_to"])] for r in a.get("schedule", [])),
            "excluded_downtimes": sorted([e["name"], int(e["period_from"]), int(e["period_to"])] for e in a.get("excluded_downtimes", [])),
            "_id": a["slaid"],
        }

    flt = [{"tag": T.MANAGED_KEY, "value": T.MANAGED_VALUE, "operator": 1}]
    for it in client.call("item.get", {"output": ["itemid", "key_", "name", "type", "value_type", "delay", "params"], "selectTags": "extend",
                                       "selectHosts": ["hostid", "host"], "tags": flt, "evaltype": 0}):
        host = it["hosts"][0]["host"]
        st["items"]["%s|%s" % (host, it["key_"])] = {
            "name": it["name"], "type": int(it["type"]), "value_type": int(it["value_type"]), "delay": it["delay"], "params": it.get("params", "") or "",
            "tags": _tags_from_api(it["tags"]), "_host": host, "_id": it["itemid"], "_hostid": it["hosts"][0]["hostid"],
        }
    for tr in client.call("trigger.get", {"output": ["triggerid", "description", "expression", "priority"], "selectTags": "extend", "selectHosts": ["hostid", "host"],
                                          "expandExpression": True, "tags": flt, "evaltype": 0}):
        host = tr["hosts"][0]["host"]
        st["triggers"]["%s|%s" % (host, tr["description"])] = {
            "expression": tr["expression"], "priority": int(tr["priority"]), "tags": _tags_from_api(tr["tags"]), "_host": host, "_id": tr["triggerid"],
            "description": tr["description"],
        }
    return st, foreign, anomalies


# ------------------------------------------------------------------------------------------------ comparison and (de)serialisation
COMPARED = {
    "services": ("name", "algorithm", "description", "tags", "problem_tags", "children"),
    "slas": ("name", "slo", "period", "timezone", "status", "effective_date", "description", "service_tags", "schedule", "excluded_downtimes"),
    "items": ("name", "type", "value_type", "delay", "params", "tags"),
    "triggers": ("expression", "priority", "tags"),
}


def differing_fields(kind, want, have):
    return [f for f in COMPARED[kind] if want.get(f) != have.get(f)]


def to_json(st):
    """Backup form: drops nothing (ids are kept for the audit record; they are ignored on restore)."""
    return {"format": FORMAT, "services": st["services"], "slas": st["slas"], "items": st["items"], "triggers": st["triggers"]}


def from_json(obj):
    if obj.get("format") != FORMAT:
        raise ValueError("unsupported backup state format %r" % (obj.get("format"),))
    st = empty()
    for k in st:
        st[k] = obj[k]
    return st


def counts(st):
    return dict((k, len(v)) for k, v in st.items())
