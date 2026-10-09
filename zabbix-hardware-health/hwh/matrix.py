"""Per-vendor coverage matrix: PASS / GAP / N/A (with evidence) / BLOCKED for every mandatory family and category.

Inputs are audit reports (live evidence) and/or hand-written observation files (what was seen but not provable). An observation file may
never contain PASS - PASS exists only in a report produced by the audit from a real, fresh, mapped, triggered sensor.
A family with no device in the environment is BLOCKED, never implicitly green and never N/A."""
import yaml

from .api import AuditError
from .policy import CATEGORIES

PASS, GAP, BLOCKED, NA = "PASS", "GAP", "BLOCKED", "N/A"
VENDOR_TITLES = {"cisco": "Cisco", "paloalto": "Palo Alto Networks", "fortinet": "Fortinet", "huawei": "Huawei"}


def load_observations(path):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    out = []
    for i, o in enumerate(data.get("observations") or []):
        where = "observation %d" % (i + 1)
        if set(o) - {"hosts", "family", "model", "source", "categories", "note"}:
            raise AuditError(where + ": unknown keys")
        if not o.get("hosts") or not o.get("family") or not o.get("source"):
            raise AuditError(where + ": hosts, family and source are required")
        for cat, c in (o.get("categories") or {}).items():
            if cat not in CATEGORIES:
                raise AuditError("%s: unknown category %s" % (where, cat))
            if c.get("verdict") == PASS:
                raise AuditError("%s: PASS cannot be asserted by hand; it comes only from an audit report" % where)
            if c.get("verdict") not in (GAP, BLOCKED, NA):
                raise AuditError("%s: verdict must be GAP, BLOCKED or N/A" % where)
            if len(str(c.get("evidence") or "").strip()) < 10:
                raise AuditError("%s: %s needs an evidence statement" % (where, cat))
        out.append(o)
    return out


def entries_from_report(report):
    out = []
    for h in report.get("hosts", []):
        cats = {}
        for cat, c in h.get("categories", {}).items():
            cats[cat] = {"verdict": c["verdict"], "evidence": c.get("evidence") or c.get("detail") or c.get("reason") or "; ".join(
                "%s: %s" % (s["key"], s["reason"]) for s in c.get("sensors", []) if s["verdict"] != PASS) or "verified live"}
        out.append({"hosts": [h["host"]], "family": h["family"], "model": h.get("model", ""), "source": "audit report " + report.get("generated_at_utc", ""),
                    "categories": cats})
    return out


def _agg(verdicts):
    s = set(verdicts)
    if not s:
        return BLOCKED
    for v in (GAP, BLOCKED, PASS):
        if v in s:
            return v
    return NA


def build(catalogue, entries):
    """-> {"families": {fid: {title, vendor, categories: {cat: {verdict, notes[]}}, devices: [...]}}}"""
    fams = {}
    unknown = [e["family"] for e in entries if e["family"] not in catalogue]
    if unknown:
        raise AuditError("observation/report references unknown family: " + ", ".join(sorted(set(unknown))))
    for fid, f in catalogue.items():
        mine = [e for e in entries if e["family"] == fid]
        cats = {}
        for cat in f["categories"]:
            rows = [(e, e["categories"][cat]) for e in mine if cat in e.get("categories", {})]
            if not mine:
                cats[cat] = {"verdict": BLOCKED, "notes": ["no device of this family is monitored in this environment (NOT TESTABLE)"]}
            elif not rows:
                cats[cat] = {"verdict": GAP, "notes": ["devices exist but nothing was recorded for this category"]}
            else:
                cats[cat] = {"verdict": _agg([c["verdict"] for _, c in rows]),
                             "notes": ["%s [%s]: %s - %s" % (", ".join(e["hosts"]), c["verdict"], c["evidence"], e["source"]) for e, c in rows]}
        fams[fid] = {"title": f["title"], "vendor": f["vendor"], "categories": cats,
                     "devices": [{"hosts": e["hosts"], "model": e.get("model", ""), "source": e["source"]} for e in mine]}
    return {"families": fams}


def render_markdown(matrix, heading="NETOPS Hardware Health - coverage matrix"):
    lines = ["# " + heading, "",
             "PASS = real, fresh, supported sensor with a verified status meaning and a dedicated-tag trigger bound to it. GAP = monitoring missing or unusable. "
             "BLOCKED = cannot be judged (no device, unreachable, mock host). N/A = only with model-specific evidence. Nothing here is a claim about what an "
             "absent physical model can or cannot expose.", ""]
    counts = {PASS: 0, GAP: 0, BLOCKED: 0, NA: 0}
    for f in matrix["families"].values():
        for c in f["categories"].values():
            counts[c["verdict"]] += 1
    lines.append("Totals over all vendor x category cells: PASS %d, GAP %d, BLOCKED %d, N/A %d." % (counts[PASS], counts[GAP], counts[BLOCKED], counts[NA]))
    lines.append("")
    for vendor, title in VENDOR_TITLES.items():
        lines += ["## " + title, ""]
        for fid, f in matrix["families"].items():
            if f["vendor"] != vendor:
                continue
            devs = "; ".join("%s (%s)" % (", ".join(d["hosts"]), d["model"] or "model not recorded") for d in f["devices"]) or "none"
            lines += ["### %s (`%s`)" % (f["title"], fid), "", "Devices: " + devs, "", "| Category | Verdict | Evidence |", "|---|---|---|"]
            for cat, c in f["categories"].items():
                lines.append("| %s | **%s** | %s |" % (cat, c["verdict"], " / ".join(c["notes"]).replace("|", "/")))
            lines.append("")
    return "\n".join(lines) + "\n"
