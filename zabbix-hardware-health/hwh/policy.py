"""Approved device policy (YAML per environment) and the vendor catalogue."""
import yaml

from .api import AuditError

CATEGORIES = ("fan", "power", "temperature", "hw_redundancy", "ha")
STATUS_CATEGORIES = ("fan", "power", "hw_redundancy", "ha")          # interpreted through a verified status mapping
COMPONENT_TAG = {"fan": "fan", "power": "power", "temperature": "temperature", "hw_redundancy": "redundancy", "ha": "ha"}
VENDORS = ("cisco", "paloalto", "fortinet", "huawei")
DEFAULT_AGE_MINUTES = 480
TOP_KEYS = {"environment", "zabbix", "hosts"}
HOST_KEYS = {"site", "vendor", "family", "model", "expected", "not_applicable", "sensors", "max_sensor_age_minutes"}
SENSOR_KEYS = {"category", "key", "slot", "semantics", "units", "plausible_range"}


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_catalogue(path):
    data = load_yaml(path) or {}
    fam = data.get("families")
    if not isinstance(fam, dict) or not fam:
        raise AuditError("vendor catalogue has no families")
    for fid, f in fam.items():
        if f.get("vendor") not in VENDORS or any(c not in CATEGORIES for c in f.get("categories", [])):
            raise AuditError("vendor catalogue entry %s is invalid" % fid)
    return fam


def load_config(path, environment, catalogue=None):
    config = load_yaml(path)
    if not isinstance(config, dict) or config.get("environment") != environment:
        raise AuditError("Configuration environment mismatch")
    if set(config) - TOP_KEYS:
        raise AuditError("Unknown top-level configuration keys")
    hosts = config.get("hosts")
    if not isinstance(hosts, dict):
        raise AuditError("hosts must be a mapping")
    z = config.get("zabbix") or {}
    if not isinstance(z, dict) or set(z) - {"url_regex", "forbid_url_regex"}:
        raise AuditError("zabbix: only url_regex and forbid_url_regex are allowed")
    for name, h in hosts.items():
        _validate_host(name, h, catalogue)
    return config


def _validate_host(name, h, catalogue):
    if not isinstance(name, str) or not name:
        raise AuditError("Host name must be a nonempty string")
    if not isinstance(h, dict):
        raise AuditError("Host settings must be a mapping: " + name)
    if set(h) - HOST_KEYS:
        raise AuditError("Unknown host setting for %s: %s" % (name, ", ".join(sorted(set(h) - HOST_KEYS))))
    if h.get("vendor") not in VENDORS:
        raise AuditError("%s: vendor must be one of %s" % (name, ", ".join(VENDORS)))
    if catalogue is not None:
        fam = catalogue.get(h.get("family"))
        if fam is None:
            raise AuditError("%s: family must be one of %s" % (name, ", ".join(sorted(catalogue))))
        if fam["vendor"] != h["vendor"]:
            raise AuditError("%s: family %s belongs to vendor %s, not %s" % (name, h["family"], fam["vendor"], h["vendor"]))
    elif not h.get("family"):
        raise AuditError("%s: family is required" % name)
    if not isinstance(h.get("model"), str) or not h["model"].strip():
        raise AuditError("%s: model (the exact, human-verified model) is required" % name)
    expected = h.get("expected") or []
    na = h.get("not_applicable") or {}
    if not isinstance(expected, list) or len(set(expected)) != len(expected):
        raise AuditError("Host needs a unique expected list: " + name)
    if any(v not in CATEGORIES for v in expected):
        raise AuditError("Unrecognized expected category for %s (valid: %s; 'ha' and 'hw_redundancy' are different)" % (name, ", ".join(CATEGORIES)))
    if not isinstance(na, dict):
        raise AuditError("not_applicable must be a mapping: " + name)
    for cat, v in na.items():
        if cat not in CATEGORIES:
            raise AuditError("%s: not_applicable category %s unknown" % (name, cat))
        if cat in expected:
            raise AuditError("%s: %s is both expected and not_applicable" % (name, cat))
        if not isinstance(v, dict) or len(str(v.get("evidence") or "").strip()) < 10 or set(v) - {"evidence"}:
            raise AuditError("%s: not_applicable.%s needs an 'evidence' reference (model-specific proof); N/A is never implicit" % (name, cat))
    if not expected and not na:
        raise AuditError("%s: declare expected categories (or not_applicable with evidence)" % name)
    age = h.get("max_sensor_age_minutes", DEFAULT_AGE_MINUTES)
    if type(age) is not int or not 1 <= age <= 10080:
        raise AuditError("Invalid max_sensor_age_minutes for " + name)
    sensors = h.get("sensors") or []
    if not isinstance(sensors, list):
        raise AuditError("%s: sensors must be a list" % name)
    seen = set()
    for s in sensors:
        if not isinstance(s, dict) or set(s) - SENSOR_KEYS:
            raise AuditError("%s: sensor has unknown keys" % name)
        cat, key = s.get("category"), s.get("key")
        if cat not in expected:
            raise AuditError("%s: sensor category %r is not in expected" % (name, cat))
        if not isinstance(key, str) or not key:
            raise AuditError("%s: every sensor needs the exact item key" % name)
        if key in seen:
            raise AuditError("%s: duplicate sensor key %s" % (name, key))
        seen.add(key)
        if cat in STATUS_CATEGORIES and not s.get("semantics"):
            raise AuditError("%s: sensor %s needs 'semantics' (a verified status mapping id) - status codes are never guessed" % (name, key))
        if cat == "temperature":
            if not s.get("units"):
                raise AuditError("%s: temperature sensor %s needs the expected 'units'" % (name, key))
            pr = s.get("plausible_range")
            if pr is not None and not (isinstance(pr, list) and len(pr) == 2 and all(isinstance(x, (int, float)) for x in pr) and pr[0] < pr[1]):
                raise AuditError("%s: plausible_range must be [min, max]" % name)
    # an expected category with no declared sensor is allowed (it audits as GAP) so an approved inventory can record a known gap
    return h
