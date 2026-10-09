"""Vendor status semantics registry. NOTHING is built in: the shipped registry is empty, because a status code only means what the vendor's
MIB/API says and this project does not invent mappings. An entry is usable only when it has `verified: true`, a non-empty `evidence`
reference (MIB object + document/URL, or a device capture) and belongs to the same vendor as the sensor that uses it - a mapping verified for one
vendor is never applied to another."""
import yaml

STATE_NAMES = ("normal", "degraded", "failed", "absent", "unknown")


def load(path):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return validate(data)


def validate(data):
    from .api import AuditError
    if not isinstance(data, dict) or set(data) - {"schema", "semantics"}:
        raise AuditError("status-semantics: only 'schema' and 'semantics' are allowed at top level")
    sem = data.get("semantics") or {}
    if not isinstance(sem, dict):
        raise AuditError("status-semantics: 'semantics' must be a mapping")
    out = {}
    for sid, s in sem.items():
        if not isinstance(s, dict) or set(s) - {"vendor", "description", "evidence", "verified", "states", "families", "device_verified", "origin"}:
            raise AuditError("status-semantics %s: unknown or missing keys" % sid)
        states = s.get("states")
        if not isinstance(states, dict) or not states:
            raise AuditError("status-semantics %s: states must be a non-empty mapping raw-value -> %s" % (sid, "|".join(STATE_NAMES)))
        for raw, name in states.items():
            if name not in STATE_NAMES:
                raise AuditError("status-semantics %s: state '%s' for value %s is not one of %s" % (sid, name, raw, STATE_NAMES))
        if "normal" not in states.values():
            raise AuditError("status-semantics %s: no raw value maps to 'normal'" % sid)
        out[sid] = {"vendor": s.get("vendor"), "families": list(s.get("families") or []), "description": s.get("description", ""),
                    "evidence": str(s.get("evidence") or "").strip(), "verified": s.get("verified") is True,
                    "states": dict((str(k), v) for k, v in states.items())}
    return out


def usable(reg, sid, vendor, family):
    """-> (entry or None, reason). Reason is None when usable."""
    s = reg.get(sid)
    if s is None:
        return None, "semantics '%s' is not in the registry" % sid
    if not s["verified"] or len(s["evidence"]) < 10:
        return None, "semantics '%s' is not verified (needs verified: true and an evidence reference)" % sid
    if s["vendor"] != vendor:
        return None, "semantics '%s' belongs to vendor '%s', not '%s'" % (sid, s["vendor"], vendor)
    if s["families"] and family not in s["families"]:
        return None, "semantics '%s' is limited to families %s" % (sid, s["families"])
    return s, None


def interpret(entry, raw_value):
    """Raw item value -> one of STATE_NAMES, or None when the value is not in the verified mapping."""
    return entry["states"].get(str(raw_value).strip())


def registry(base):
    """Documented vendor semantics (from vendors/*.yaml; documentation-derived, NOT device-verified) plus any operator-added entries in
    config/status-semantics.yaml. An operator entry may not shadow a built-in one."""
    import os
    from . import vendordefs
    from .api import AuditError
    reg = load(os.path.join(base, "config", "status-semantics.yaml"))
    merged = vendordefs.registry_entries(vendordefs.load_dir(os.path.join(base, "vendors")))
    for k in reg:
        if k in merged:
            raise AuditError("operator semantics '%s' would shadow the built-in documented mapping of the same id" % k)
    merged.update(reg)
    return merged
