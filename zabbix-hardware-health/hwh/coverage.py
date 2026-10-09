"""Vendor coverage matrix with FOUR separate evidence levels, generated from the definitions (never hand-edited):

  IMPLEMENTED          a validated definition and a generated template exist
  SIMULATED TESTED     the generated trigger expressions passed the simulated scenarios (hwh/simulate.py)
  REAL DEVICE VERIFIED recorded device evidence exists in config/device-evidence.yaml (empty in this release)
  UNVERIFIED / BLOCKED not defined, undocumented, or model dependent
"""
import yaml

from . import simulate
from .api import AuditError


def load_device_evidence(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = yaml.safe_load(fh) or {}
    except OSError:
        return {}
    if d.get("schema") != 1 or not isinstance(d.get("verified") or {}, dict):
        raise AuditError("device-evidence.yaml: schema 1 with a 'verified' mapping is required")
    for key, ev in (d.get("verified") or {}).items():
        if len(str(ev.get("device", "")).strip()) < 3 or len(str(ev.get("recorded_by", "")).strip()) < 3 or not ev.get("raw_capture"):
            raise AuditError("device-evidence.yaml: %s needs device, recorded_by and a raw_capture reference" % key)
    return d.get("verified") or {}


def build(defs, catalogue, evidence=None):
    evidence = evidence or {}
    sim = simulate.summary(defs)
    rows = []
    for fid, fam in sorted(catalogue.items()):
        for cat in fam["categories"]:
            cell = {"family": fid, "title": fam["title"], "category": cat, "implemented": [], "simulated": False, "device": False, "blocked": [], "readings": []}
            sim_ok = True
            for d in defs.values():
                if fid not in d["families"]:
                    continue
                for sn in d.get("sensors") or []:
                    if sn["category"] != cat:
                        continue
                    if sn["scope"] == "reading":
                        cell["readings"].append(sn["title"])
                        continue
                    cell["implemented"].append("%s [%s]" % (sn["title"], sn["scope"]))
                    if not sim[d["id"]]["cases"] or sim[d["id"]]["failed"]:
                        sim_ok = False
                    if "%s:%s" % (d["id"], sn["id"]) in evidence:
                        cell["device"] = True
                for u in d.get("unsupported") or []:
                    if u["category"] == cat:
                        cell["blocked"].append(u["reason"])
            cell["simulated"] = bool(cell["implemented"]) and sim_ok
            rows.append(cell)
    return {"rows": rows, "simulation": dict((k, {"cases": v["cases"], "failed": len(v["failed"])}) for k, v in sim.items())}


def _label(c):
    if c["device"]:
        return "REAL DEVICE VERIFIED"
    if c["simulated"]:
        return "SIMULATED TESTED"
    if c["implemented"]:
        return "IMPLEMENTED"
    return "UNVERIFIED / BLOCKED"


def render_markdown(m):
    out = ["# NETOPS Hardware Health - vendor coverage matrix", "",
           "Generated from `vendors/*.yaml`. Every OID / API path / enumeration comes from a cited vendor MIB or official Zabbix 7.0 template (see the definition's `sources`). "
           "**DOCUMENTATION-DERIVED, NOT DEVICE-VERIFIED:** nothing here has been observed on real equipment, and the SNMP Simulator verifies the pipeline, not any vendor's behaviour. "
           "Levels are kept apart: IMPLEMENTED < SIMULATED TESTED < REAL DEVICE VERIFIED; UNVERIFIED / BLOCKED means nothing is claimed.", ""]
    n = {}
    for c in m["rows"]:
        n[_label(c)] = n.get(_label(c), 0) + 1
    out.append("Cells: " + ", ".join("%s %d" % (k, n[k]) for k in sorted(n)) + ".")
    out.append("")
    out.append("| Family | Category | Level | Implemented as | Readings only (no alert) | Not available / reason |")
    out.append("|---|---|---|---|---|---|")
    for c in m["rows"]:
        out.append("| %s | %s | %s | %s | %s | %s |" % (c["title"], c["category"], _label(c), "; ".join(c["implemented"]) or "-", "; ".join(c["readings"]) or "-",
                                                      " / ".join(c["blocked"])[:260] or ("not defined" if not c["implemented"] else "-")))
    out.append("")
    out.append("## Simulation results")
    out.append("")
    for k, v in sorted(m["simulation"].items()):
        out.append("- `%s`: %d scenario checks, %d failed" % (k, v["cases"], v["failed"]))
    return "\n".join(out) + "\n"
