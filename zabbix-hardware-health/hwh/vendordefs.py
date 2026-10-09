"""Vendor sensor definitions (vendors/*.yaml): what to read, where it is documented, what each raw value means and when to alert.

A definition is the SINGLE source for (a) the status-semantics registry used by the audit, (b) the generated Zabbix template and (c) the coverage
matrix. Nothing here is invented: every OID / API path / enumeration carries a source (a vendor MIB object or the official Zabbix 7.0 template
that cites it, with commit and tested platform). Evidence levels are kept apart:

  IMPLEMENTED          the definition exists and validates; a template can be generated from it
  SIMULATED_TESTED     the generated trigger expressions were actually evaluated against simulated normal / fault / glitch / recovery / stale series
  REAL_DEVICE_VERIFIED recorded device evidence exists (config/device-evidence.yaml). Empty in this release.
  UNVERIFIED_BLOCKED   not defined, undocumented, or model dependent
"""
import glob
import os
import re

import yaml

from .api import AuditError
from .policy import CATEGORIES, VENDORS
from .semantics import STATE_NAMES

SEVERITIES = {"information": 1, "warning": 2, "average": 3, "high": 4, "disaster": 5}
SCOPES = ("status", "reading", "sensor-health")
SUPPORT = ("documented-tested", "documented-unverified", "unsupported", "unknown")
OID_RE = re.compile(r"^[0-9]+(\.[0-9]+)+$")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
TOP = {"schema", "id", "vendor", "families", "title", "kind", "sources", "platforms", "semantics", "sensors", "unsupported", "api"}
SENSOR_KEYS = {"id", "category", "scope", "title", "table", "value", "triggers", "note", "api"}
TRIGGER_KEYS = {"id", "severity", "states", "confirm_samples", "recover_samples", "title"}


def load_dir(path):
    defs = {}
    for f in sorted(glob.glob(os.path.join(path, "*.yaml"))):
        with open(f, encoding="utf-8") as fh:
            d = yaml.safe_load(fh)
        validate(d, os.path.basename(f))
        if d["id"] in defs:
            raise AuditError("duplicate vendor definition id " + d["id"])
        defs[d["id"]] = d
    return defs


def validate(d, where="definition"):
    def bad(msg):
        raise AuditError("%s: %s" % (where, msg))

    if not isinstance(d, dict) or set(d) - TOP:
        bad("unknown top-level keys: %s" % sorted(set(d) - TOP if isinstance(d, dict) else []))
    if d.get("schema") != 1 or not ID_RE.match(str(d.get("id", ""))):
        bad("schema must be 1 and id a slug")
    if d.get("vendor") not in VENDORS:
        bad("vendor must be one of %s" % ", ".join(VENDORS))
    if not d.get("families") or not isinstance(d["families"], list):
        bad("families is required")
    if d.get("kind") not in ("snmp", "http-api"):
        bad("kind must be snmp or http-api")
    srcs = d.get("sources")
    if not isinstance(srcs, list) or not srcs:
        bad("at least one source is required (a definition without a source is a guess)")
    for s in srcs:
        if not s.get("kind") or not s.get("ref"):
            bad("every source needs kind and ref")
        if s["kind"] == "zabbix-template" and not (s.get("url") and re.match(r"^[0-9a-f]{40}$", str(s.get("commit", "")))):
            bad("a zabbix-template source needs url and the 40-hex commit it was read from")
    for p in d.get("platforms") or []:
        if p.get("support") not in SUPPORT or not p.get("name"):
            bad("platform entries need name and support in %s" % (SUPPORT,))
    sem = d.get("semantics") or {}
    for sid, s in sem.items():
        states = s.get("states")
        if not isinstance(states, dict) or not states:
            bad("semantics %s has no states" % sid)
        for raw, v in states.items():
            if not str(raw).lstrip("-").isdigit() or v.get("state") not in STATE_NAMES or not str(v.get("meaning", "")).strip():
                bad("semantics %s value %s needs a numeric raw value, a state in %s and its documented meaning" % (sid, raw, STATE_NAMES))
        if not any(v["state"] == "normal" for v in states.values()):
            bad("semantics %s has no normal value" % sid)
        if not str(s.get("object", "")).strip() or not str(s.get("classification_source", "")).strip():
            bad("semantics %s needs the documented object and where the classification comes from" % sid)
    seen = set()
    for sn in d.get("sensors") or []:
        if set(sn) - SENSOR_KEYS:
            bad("sensor %s: unknown keys %s" % (sn.get("id"), sorted(set(sn) - SENSOR_KEYS)))
        if not ID_RE.match(str(sn.get("id", ""))) or sn["id"] in seen:
            bad("sensor id missing, malformed or duplicated: %r" % sn.get("id"))
        seen.add(sn["id"])
        if sn.get("category") not in CATEGORIES or sn.get("scope") not in SCOPES:
            bad("sensor %s: category/scope invalid" % sn["id"])
        v = sn.get("value") or {}
        if d["kind"] == "snmp":
            t = sn.get("table") or {}
            if not OID_RE.match(str(t.get("name_oid", ""))) or not OID_RE.match(str(v.get("oid", ""))):
                bad("sensor %s: table.name_oid and value.oid must be dotted numeric OIDs" % sn["id"])
            if not str(v.get("object", "")).strip():
                bad("sensor %s: value.object (the MIB object name) is required" % sn["id"])
        else:
            a = sn.get("api") or {}
            if not a.get("command") or not a.get("json_path"):
                bad("sensor %s: api.command and api.json_path are required" % sn["id"])
            g = a.get("gate")
            if g is not None and (not isinstance(g, dict) or set(g) != {"path", "equals"} or not isinstance(g["path"], list) or not g["path"]
                                  or not all(isinstance(k, str) and re.match(r"^[A-Za-z0-9_-]+$", k) for k in g["path"]) or not isinstance(g["equals"], str)):
                bad("sensor %s: api.gate must be {path: [keys...], equals: text}" % sn["id"])
        if v.get("type") not in ("unsigned", "float"):
            bad("sensor %s: value.type must be unsigned or float" % sn["id"])
        trig = sn.get("triggers") or []
        if sn["scope"] == "reading" and trig:
            bad("sensor %s: a reading carries no trigger (no invented thresholds)" % sn["id"])
        if sn["scope"] != "reading":
            if v.get("semantics") not in sem:
                bad("sensor %s: semantics %r is not defined in this file" % (sn["id"], v.get("semantics")))
        tids = set()
        for t in trig:
            if set(t) - TRIGGER_KEYS or t.get("id") in tids:
                bad("sensor %s: bad or duplicate trigger" % sn["id"])
            tids.add(t["id"])
            if t.get("severity") not in SEVERITIES:
                bad("sensor %s trigger %s: severity must be one of %s" % (sn["id"], t["id"], sorted(SEVERITIES)))
            used = {x["state"] for x in sem[v["semantics"]]["states"].values()}
            if not t.get("states") or any(s_ not in used or s_ == "normal" for s_ in t["states"]):
                bad("sensor %s trigger %s: states must be non-normal states that the semantics defines" % (sn["id"], t["id"]))
            for k in ("confirm_samples", "recover_samples"):
                if type(t.get(k)) is not int or not 1 <= t[k] <= 10:
                    bad("sensor %s trigger %s: %s must be 1..10" % (sn["id"], t["id"], k))
        sets = [set(t["states"]) for t in trig]
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                if sets[i] & sets[j]:
                    bad("sensor %s: two triggers share a state (they would both fire)" % sn["id"])
    for u in d.get("unsupported") or []:
        if u.get("category") not in CATEGORIES or not str(u.get("reason", "")).strip():
            bad("unsupported entries need a category and a reason")
    return d


def registry_entries(defs):
    """Documented status semantics as audit-registry entries: verified against the DOCUMENTATION, never against a device."""
    out = {}
    for d in defs.values():
        for sid, s in d.get("semantics", {}).items():
            if sid in out:
                raise AuditError("semantics id %s is defined twice" % sid)
            out[sid] = {"vendor": d["vendor"], "families": list(d["families"]), "description": s.get("description", ""),
                        "evidence": "%s | %s | source: %s | DOCUMENTATION-DERIVED, NOT DEVICE-VERIFIED" % (
                            s["object"], s["classification_source"][:160], "; ".join(x["ref"][:80] for x in d["sources"])),
                        "verified": True, "device_verified": False, "origin": "vendor-definition:" + d["id"],
                        "states": dict((str(k), v["state"]) for k, v in s["states"].items())}
    return out


def raw_values_for(defn, sem_id, states):
    """Raw values (as strings) whose classification is in `states`."""
    return sorted((k for k, v in defn["semantics"][sem_id]["states"].items() if v["state"] in states), key=int)


def family_report(defs, family):
    """What exists for a catalogue family. -> {'definitions': [...], 'implemented': {cat: [titles]}, 'unsupported': {cat: [reasons]}, 'platforms': [...]}"""
    out = {"definitions": [], "implemented": {}, "readings": {}, "unsupported": {}, "platforms": []}
    for d in defs.values():
        if family not in d["families"]:
            continue
        out["definitions"].append(d["id"])
        out["platforms"].extend(d.get("platforms") or [])
        for sn in d.get("sensors") or []:
            bucket = "readings" if sn["scope"] == "reading" else "implemented"
            out[bucket].setdefault(sn["category"], []).append("%s (%s)" % (sn["title"], sn["scope"]))
        for u in d.get("unsupported") or []:
            out["unsupported"].setdefault(u["category"], []).append(u["reason"])
    return out
