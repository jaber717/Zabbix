"""Load and validate config/interfaces.yaml (the only file an engineer edits).

Validation is strict on purpose: unknown keys are errors (typo protection) and
duplicate YAML keys are errors (PyYAML would silently keep the last one).
"""
import re
import yaml

SEVERITIES = {"warning": 2, "average": 3, "high": 4, "disaster": 5}
DEFAULT_SEVERITY = "high"
INTERVAL_RE = re.compile(r"^(\d+)([smh])$")
SPEED_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMGT]?)(?:bps)?$", re.IGNORECASE)
SPEED_MULT = {"": 1, "K": 10 ** 3, "M": 10 ** 6, "G": 10 ** 9, "T": 10 ** 12}

IFACE_KEYS = {"description", "role", "severity", "link_alert", "utilization",
              "errors", "discards", "flapping", "expected_speed", "link_id"}
SECTION_KEYS = {
    "utilization": {"enabled", "threshold", "recovery", "poll_interval"},
    "errors": {"enabled", "rate", "recovery"},
    "discards": {"enabled", "rate", "recovery"},
    "flapping": {"enabled", "transitions", "window"},
}
DEFAULTS_KEYS = IFACE_KEYS - {"description", "link_id"}
HOST_KEYS = {"site", "interfaces"}
TOP_KEYS = {"defaults", "hosts"}

BUILTIN_DEFAULTS = {
    "severity": DEFAULT_SEVERITY,
    "role": "",
    "link_alert": True,
    "expected_speed": None,
    "utilization": {"enabled": False, "threshold": 70, "recovery": 65, "poll_interval": "10s"},
    "errors": {"enabled": True, "rate": 1, "recovery": None},
    "discards": {"enabled": True, "rate": 1, "recovery": None},
    "flapping": {"enabled": True, "transitions": 3, "window": "10m"},
}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, "duplicate key %r" % (key,), key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


class ConfigError(Exception):
    pass


def parse_interval(text):
    m = INTERVAL_RE.match(str(text))
    if not m:
        raise ValueError("must look like 10s, 1m or 1h")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def parse_speed(value):
    """'100G' / '10G' / 1000000000 -> bits per second (int)."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    m = SPEED_RE.match(str(value).strip())
    if not m:
        raise ValueError("expected_speed must look like 100G, 10G, 1000M or a number of bps")
    return int(float(m.group(1)) * SPEED_MULT[m.group(2).upper()])


def load_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return yaml.load(fh, Loader=UniqueKeyLoader) or {}
        except yaml.YAMLError as exc:
            raise ConfigError("YAML error in %s: %s" % (path, exc))


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            m = dict(out[k])
            m.update(v)
            out[k] = m
        else:
            out[k] = v
    return out


class Problem(object):
    def __init__(self, host, iface, message):
        self.host, self.iface, self.message = host, iface, message

    def label(self):
        if self.iface:
            return "%s / %s" % (self.host, self.iface)
        return self.host or "(file)"


def _check_keys(obj, allowed, where, problems, host=None, iface=None):
    for k in obj:
        if k not in allowed:
            problems.append(Problem(host, iface, "unknown key '%s' in %s (allowed: %s)" %
                                    (k, where, ", ".join(sorted(allowed)))))


def _num(value, name, lo, hi, problems, host, iface):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(Problem(host, iface, "%s must be a number" % name))
        return None
    if not (lo < value <= hi):
        problems.append(Problem(host, iface, "%s must be > %s and <= %s" % (name, lo, hi)))
        return None
    return value


NOTIFY_MSG = ("notify=false is not supported by the Phase-1 P2P policy. "
              "All selected interfaces must notify.")


def _reject_notify(obj, host, iface, problems):
    if "notify" in obj:
        problems.append(Problem(host, iface, NOTIFY_MSG))


def normalize_interface(defaults, raw, host, name, problems):
    """Return the fully resolved settings dict for one interface (or None)."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        problems.append(Problem(host, name, "interface entry must be a mapping"))
        return None
    _check_keys(raw, IFACE_KEYS, "interface", problems, host, name)
    _reject_notify(raw, host, name, problems)
    for sect, keys in SECTION_KEYS.items():
        if sect in raw:
            if not isinstance(raw[sect], dict):
                problems.append(Problem(host, name, "%s must be a mapping" % sect))
                return None
            _check_keys(raw[sect], keys, sect, problems, host, name)
    cfg = _merge(defaults, raw)
    out = {"description": str(raw.get("description", "") or ""),
           "role": str(cfg.get("role") or "")}
    if not out["description"]:
        problems.append(Problem(host, name, "description is required"))

    sev = str(cfg.get("severity", DEFAULT_SEVERITY)).lower()
    if sev not in SEVERITIES:
        problems.append(Problem(host, name, "invalid severity '%s' (use: %s)" %
                                (cfg.get("severity"), ", ".join(SEVERITIES))))
    out["severity"] = sev

    if not isinstance(cfg.get("link_alert"), bool):
        problems.append(Problem(host, name, "link_alert must be true or false"))
    out["link_alert"] = bool(cfg.get("link_alert"))

    lid = raw.get("link_id", "")
    if lid is not None and (not isinstance(lid, (str, int)) or '"' in str(lid) or "\\" in str(lid)):
        problems.append(Problem(host, name, "link_id must be a plain string"))
    out["link_id"] = str(lid or "")

    try:
        out["expected_speed"] = parse_speed(cfg.get("expected_speed"))
    except ValueError as exc:
        problems.append(Problem(host, name, str(exc)))
        out["expected_speed"] = None

    for sect in ("utilization", "errors", "discards", "flapping"):
        s = dict(cfg.get(sect) or {})
        if not isinstance(s.get("enabled"), bool):
            problems.append(Problem(host, name, "%s.enabled must be true or false" % sect))
            s["enabled"] = False
        out[sect] = s

    u = out["utilization"]
    if u["enabled"]:
        thr = _num(u.get("threshold"), "utilization.threshold", 0, 100, problems, host, name)
        rec = _num(u.get("recovery"), "utilization.recovery", 0, 100, problems, host, name)
        if thr is not None and rec is not None and rec >= thr:
            problems.append(Problem(host, name, "utilization.recovery (%s) must be lower than "
                                    "utilization.threshold (%s)" % (rec, thr)))
    try:
        u["poll_seconds"] = parse_interval(u.get("poll_interval", "10s"))
        if u["poll_seconds"] < 1:
            raise ValueError("must be at least 1s")
    except ValueError as exc:
        problems.append(Problem(host, name, "utilization.poll_interval %s" % exc))
        u["poll_seconds"] = 10
    for sect in ("errors", "discards"):
        s = out[sect]
        if s["enabled"]:
            _num(s.get("rate"), "%s.rate" % sect, 0, 10 ** 9, problems, host, name)
            if s.get("recovery") is not None:
                r = _num(s["recovery"], "%s.recovery" % sect, -1, 10 ** 9, problems, host, name)
                if r is not None and s.get("rate") is not None and r >= s["rate"]:
                    problems.append(Problem(host, name, "%s.recovery must be lower than %s.rate" % (sect, sect)))
    f = out["flapping"]
    if f["enabled"]:
        _num(f.get("transitions"), "flapping.transitions", 1, 1000, problems, host, name)
        try:
            parse_interval(f.get("window", "10m"))
        except ValueError as exc:
            problems.append(Problem(host, name, "flapping.window %s" % exc))
    return out


class Desired(object):
    """Resolved desired state: {host: {"site": str, "interfaces": {name: settings}}}"""

    def __init__(self, hosts, problems):
        self.hosts = hosts
        self.problems = problems


def parse(data):
    problems = []
    if not isinstance(data, dict):
        raise ConfigError("top level of interfaces.yaml must be a mapping")
    _check_keys(data, TOP_KEYS, "top level", problems)
    raw_defaults = data.get("defaults") or {}
    if not isinstance(raw_defaults, dict):
        raise ConfigError("'defaults' must be a mapping")
    _check_keys(raw_defaults, DEFAULTS_KEYS, "defaults", problems)
    _reject_notify(raw_defaults, None, None, problems)
    for sect, keys in SECTION_KEYS.items():
        if isinstance(raw_defaults.get(sect), dict):
            _check_keys(raw_defaults[sect], keys, "defaults.%s" % sect, problems)
    defaults = _merge(BUILTIN_DEFAULTS, raw_defaults)

    hosts = {}
    raw_hosts = data.get("hosts") or {}
    if not isinstance(raw_hosts, dict):
        raise ConfigError("'hosts' must be a mapping of host name -> settings")
    for hname, hraw in raw_hosts.items():
        if not isinstance(hraw, dict):
            problems.append(Problem(str(hname), None, "host entry must be a mapping"))
            continue
        _check_keys(hraw, HOST_KEYS, "host", problems, str(hname))
        ifaces_raw = hraw.get("interfaces") or {}
        if not isinstance(ifaces_raw, dict) or not ifaces_raw:
            problems.append(Problem(str(hname), None, "host needs at least one entry under 'interfaces'"))
            continue
        ifaces = {}
        for iname, iraw in ifaces_raw.items():
            norm = normalize_interface(defaults, iraw, str(hname), str(iname), problems)
            if norm is not None:
                ifaces[str(iname)] = norm
        hosts[str(hname)] = {"site": str(hraw.get("site") or ""), "interfaces": ifaces}
    return Desired(hosts, problems)


def load(path):
    return parse(load_file(path))
