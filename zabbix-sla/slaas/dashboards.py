"""Native Zabbix dashboards from YAML specs (dashboards/*.yaml). No custom GUI: the output is ordinary dashboard.create/update objects.

Widget field `type` ids are the least certain part of the Zabbix dashboard API, so the defaults below are marked UNVERIFIED and
`apply` is refused until evidence/widget-field-types.json exists - written by scripts/accept_widget_fields.py from a dashboard that
a human built in the LAB GUI (evidence E-10). Planning and generation work without it (they are pure and tested offline).
"""
import glob
import json
import os

import yaml

from . import _compat
from . import tags as T

DEFAULT_FIELD_TYPES = {"int": 0, "str": 1, "service": 9, "sla": 10}      # UNVERIFIED until the evidence file exists
EVIDENCE_FILE = "evidence/widget-field-types.json"
DEFAULT_FIELD_NAMES = {"sla": "slaid.0", "service": "serviceid.0", "show_periods": "show_periods", "show_tags": "show_tags",
                       "tag": "tags.%d.tag", "operator": "tags.%d.operator", "value": "tags.%d.value"}      # UNVERIFIED too
LOGICAL_KEYS = ("sla", "service", "tags", "show_periods", "show_tags")


class DashboardError(Exception):
    pass


def load_specs(base):
    specs = []
    for path in sorted(glob.glob(os.path.join(base, "dashboards", "*.yaml"))):
        with open(path, "r", encoding="utf-8") as fh:
            spec = yaml.load(fh, Loader=_compat.UniqueKeyLoader) or {}
        for k in ("name", "pages"):
            if not spec.get(k):
                raise DashboardError("%s: '%s' is required" % (os.path.basename(path), k))
        spec["_file"] = os.path.basename(path)
        specs.append(spec)
    names = [T.NAME_PREFIX + s["name"] for s in specs]
    if len(names) != len(set(names)):
        raise DashboardError("duplicate dashboard names")
    return specs


def evidence(base):
    """-> (types, names, verified)"""
    path = os.path.join(base, EVIDENCE_FILE)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            ev = json.load(fh)
        if ev.get("verified") is True and ev.get("field_types"):
            return dict(DEFAULT_FIELD_TYPES, **ev["field_types"]), dict(DEFAULT_FIELD_NAMES, **ev.get("field_names", {})), True
    return dict(DEFAULT_FIELD_TYPES), dict(DEFAULT_FIELD_NAMES), False


def _fields(widget, ids, ft, fn, where):
    f = widget.get("fields") or {}
    unknown = set(f) - set(LOGICAL_KEYS)
    if unknown:
        raise DashboardError("%s: unknown field(s) %s" % (where, ", ".join(sorted(unknown))))
    out = []
    if "sla" in f:
        if f["sla"] not in ids["slas"]:
            raise DashboardError("%s: SLA class '%s' is not provisioned" % (where, f["sla"]))
        out.append({"type": ft["sla"], "name": fn["sla"], "value": str(ids["slas"][f["sla"]])})
    if "service" in f:
        if f["service"] not in ids["services"]:
            raise DashboardError("%s: service '%s' is not provisioned" % (where, f["service"]))
        out.append({"type": ft["service"], "name": fn["service"], "value": str(ids["services"][f["service"]])})
    if "show_periods" in f:
        out.append({"type": ft["int"], "name": fn["show_periods"], "value": str(int(f["show_periods"]))})
    if "show_tags" in f:
        out.append({"type": ft["int"], "name": fn["show_tags"], "value": str(int(f["show_tags"]))})
    for i, t in enumerate(f.get("tags") or []):
        out.append({"type": ft["str"], "name": fn["tag"] % i, "value": t["tag"]})
        out.append({"type": ft["int"], "name": fn["operator"] % i, "value": str(int(t.get("operator", 0)))})
        out.append({"type": ft["str"], "name": fn["value"] % i, "value": str(t.get("value", ""))})
    return sorted(out, key=lambda x: (x["name"], x["type"]))


def build(spec, ids, ft, fn=None):
    fn = fn or DEFAULT_FIELD_NAMES
    """spec + resolved ids -> normalised dashboard {name, display_period, pages:[{name, widgets:[...]}]}"""
    pages = []
    for pi, p in enumerate(spec["pages"]):
        ws = []
        for wi, w in enumerate(p.get("widgets") or []):
            where = "%s page %d widget %d" % (spec["_file"], pi + 1, wi + 1)
            for k in ("type", "name", "x", "y", "width", "height"):
                if k not in w:
                    raise DashboardError("%s: '%s' is required" % (where, k))
            ws.append({"type": w["type"], "name": w["name"], "x": int(w["x"]), "y": int(w["y"]), "width": int(w["width"]), "height": int(w["height"]),
                       "fields": _fields(w, ids, ft, fn, where)})
        pages.append({"name": p.get("name", ""), "widgets": sorted(ws, key=lambda x: (x["y"], x["x"], x["name"]))})
    return {"name": T.NAME_PREFIX + spec["name"], "display_period": int(spec.get("display_period", 30)), "pages": pages}


def to_params(d):
    return {"name": d["name"], "display_period": d["display_period"], "auto_start": 1,
            "pages": [{"name": p["name"], "widgets": [{"type": w["type"], "name": w["name"], "x": w["x"], "y": w["y"], "width": w["width"], "height": w["height"],
                                                          "view_mode": 0, "fields": [dict(f) for f in w["fields"]]} for w in p["widgets"]]} for p in d["pages"]]}


def _norm_live(row):
    pages = []
    for p in row.get("pages", []):
        ws = []
        for w in p.get("widgets", []):
            fields = sorted(({"type": int(f["type"]), "name": f["name"], "value": str(f["value"])} for f in w.get("fields", [])), key=lambda x: (x["name"], x["type"]))
            ws.append({"type": w["type"], "name": w.get("name", ""), "x": int(w["x"]), "y": int(w["y"]), "width": int(w["width"]), "height": int(w["height"]), "fields": fields})
        pages.append({"name": p.get("name", ""), "widgets": sorted(ws, key=lambda x: (x["y"], x["x"], x["name"]))})
    return {"name": row["name"], "display_period": int(row.get("display_period", 30)), "pages": pages}


def resolve_ids(client):
    from . import state as S
    live, _, _ = S.read_live(client)
    return {"slas": dict((k, v["_id"]) for k, v in live["slas"].items()), "services": dict((k, v["_id"]) for k, v in live["services"].items())}


def plan(client, base):
    """-> (changes [(action, name, params)], warnings, verified). Read-only."""
    specs = load_specs(base)
    ft, fn, verified = evidence(base)
    ids = resolve_ids(client)
    warnings = [] if verified else ["widget field type ids are UNVERIFIED defaults (%s missing): generation works, apply is refused" % EVIDENCE_FILE]
    rows = client.call("dashboard.get", {"output": ["dashboardid", "name", "display_period"], "selectPages": "extend",
                                         "search": {"name": T.NAME_PREFIX}, "startSearch": True})
    live = dict((r["name"], r) for r in rows)
    want, changes = {}, []
    for s in specs:
        try:
            d = build(s, ids, ft, fn)
        except DashboardError as exc:
            warnings.append(str(exc))
            continue
        want[d["name"]] = d
        have = live.get(d["name"])
        if have is None:
            changes.append(("create", d["name"], to_params(d)))
        elif _norm_live(have) != d:
            changes.append(("update", d["name"], dict(to_params(d), dashboardid=have["dashboardid"])))
    for name in live:
        if name not in want:
            warnings.append("dashboard '%s' carries the NETOPS-SLA prefix but has no spec (left in place)" % name)
    return changes, warnings, verified


def apply(client, base, log):
    changes, warnings, verified = plan(client, base)
    if not verified:
        raise DashboardError("refusing to write dashboards: widget field type ids are not verified "
                             "(run scripts/accept_widget_fields.py against a LAB dashboard first)")
    for action, name, params in changes:
        client.call("dashboard." + action, params)
        log("  ok  %s dashboard '%s'" % (action, name))
    return changes, warnings


def derive_evidence(row, slaid, serviceid, periods):
    """Learn field type ids and names from a dashboard a human built in the GUI (see scripts/accept_widget_fields.py).
    Matching is by the known VALUES the tester entered, so nothing is guessed."""
    import re
    types, names, seen = {}, {}, []
    for p in row.get("pages", []):
        for w in p.get("widgets", []):
            for f in w.get("fields", []):
                t, n, v = int(f["type"]), f["name"], str(f["value"])
                if w["type"] == "slareport":
                    if v == str(slaid):
                        types["sla"], names["sla"] = t, n
                    elif v == str(serviceid):
                        types["service"], names["service"] = t, n
                    elif v == str(periods):
                        types["int"], names["show_periods"] = t, n
                if w["type"] == "problems":
                    m = re.match(r"^tags\.(\d+)\.(tag|operator|value)$", n)
                    if m:
                        kind = m.group(2)
                        names[kind] = re.sub(r"\.\d+\.", ".%d.", n, count=1)
                        types["str" if kind in ("tag", "value") else "int"] = t
                    elif n == "show_tags":
                        names["show_tags"] = n
                seen.append("%s:%s=%s(type %s)" % (w["type"], n, v, t))
    missing = [k for k in ("sla", "service", "str", "int") if k not in types] + [k for k in ("tag", "operator", "value", "show_tags") if k not in names]
    if missing:
        raise DashboardError("could not identify %s from the dashboard; fields seen: %s" % (", ".join(missing), "; ".join(seen) or "none"))
    return {"verified": True, "field_types": types, "field_names": names, "fields_seen": seen}
