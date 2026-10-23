"""Load and validate config/network-health.<env>.yaml — the Network Health inventory.

Independent of config/interfaces.<env>.yaml. A feature is ON for a device only when its key is present
under that device (`ospf:`, `ospf: {}` or `ospf: true`); absent or `false` means OFF. An empty file
(`devices: {}`) means Network Health is disabled.
"""
import yaml

from netalert.config import SEVERITIES, ConfigError, UniqueKeyLoader, parse_interval

FEATURES = {
    "device_unreachable": {"severity": "disaster", "window": "3m"},
    "snmp_stale": {"severity": "high", "timeout": "5m"},
    "cpu": {"severity": "high", "threshold": 90, "recovery": 80, "window": "5m"},
    "memory": {"severity": "high", "threshold": 90, "recovery": 85, "window": "5m"},
    "ospf": {"severity": "high", "exclude": []},
    "bgp": {"severity": "high", "exclude": []},
}
PLATFORMS = ("cisco-ios", "cisco-nxos", "huawei-vrp", "host-resources")
DEVICE_KEYS = {"site", "platform"} | set(FEATURES)
TOP_KEYS = {"defaults", "devices"}


class Desired(object):
    """devices: {host: {"site": str, "platform": str|None, "features": {name: settings}}}"""

    def __init__(self, devices, problems):
        self.devices = devices
        self.problems = problems      # [(device, feature, message)]


def _unknown(obj, allowed, where, dev, feat, problems):
    for k in obj:
        if k not in allowed:
            problems.append((dev, feat, "unknown key '%s' in %s (allowed: %s)" %
                             (k, where, ", ".join(sorted(allowed)))))


def _validate(dev, feat, s, problems):
    sev = str(s.get("severity", "")).lower()
    if sev not in SEVERITIES:
        problems.append((dev, feat, "invalid severity '%s' (use: %s)" % (s.get("severity"), ", ".join(SEVERITIES))))
    s["severity"] = sev
    for key in ("window", "timeout"):
        if key in s:
            try:
                parse_interval(s[key])
            except ValueError as exc:
                problems.append((dev, feat, "%s %s" % (key, exc)))
    if "threshold" in s:
        thr, rec = s.get("threshold"), s.get("recovery")
        for name, v in (("threshold", thr), ("recovery", rec)):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 100:
                problems.append((dev, feat, "%s must be a number > 0 and <= 100" % name))
                return
        if rec >= thr:
            problems.append((dev, feat, "recovery (%s) must be lower than threshold (%s)" % (rec, thr)))
    if "exclude" in s:
        ex = s.get("exclude") or []
        if not isinstance(ex, list) or any(not isinstance(x, str) or '"' in x or "\\" in x for x in ex):
            problems.append((dev, feat, "exclude must be a list of neighbor/peer IDs (plain strings)"))
            ex = []
        s["exclude"] = ex


def parse(data):
    problems = []
    if not isinstance(data, dict):
        raise ConfigError("top level of network-health yaml must be a mapping")
    _unknown(data, TOP_KEYS, "top level", "-", "-", problems)
    raw_def = data.get("defaults") or {}
    if not isinstance(raw_def, dict):
        raise ConfigError("'defaults' must be a mapping")
    _unknown(raw_def, FEATURES, "defaults", "-", "-", problems)
    defaults = {}
    for f, base in FEATURES.items():
        d = raw_def.get(f) or {}
        if not isinstance(d, dict):
            problems.append(("-", f, "defaults.%s must be a mapping" % f))
            d = {}
        _unknown(d, base, "defaults.%s" % f, "-", f, problems)
        defaults[f] = dict(base, **d)

    raw = data.get("devices") or {}
    if not isinstance(raw, dict):
        raise ConfigError("'devices' must be a mapping of Zabbix host name -> features")
    devices = {}
    for name, dev in raw.items():
        name = str(name)
        if not isinstance(dev, dict):
            problems.append((name, "-", "device entry must be a mapping"))
            continue
        _unknown(dev, DEVICE_KEYS, "device", name, "-", problems)
        feats = {}
        for f in FEATURES:
            if f not in dev or dev[f] is False:
                continue
            v = dev[f]
            if v is None or v is True:
                v = {}
            if not isinstance(v, dict):
                problems.append((name, f, "%s must be true, false or a mapping" % f))
                continue
            _unknown(v, FEATURES[f], f, name, f, problems)
            s = dict(defaults[f], **v)
            _validate(name, f, s, problems)
            feats[f] = s
        if not feats:
            problems.append((name, "-", "device selects no feature (remove it, or add one of: %s)" %
                             ", ".join(FEATURES)))
            continue
        platform = dev.get("platform")
        if "cpu" in feats or "memory" in feats:
            if platform not in PLATFORMS:
                problems.append((name, "platform", "platform is required for cpu/memory: one of %s" %
                                 ", ".join(PLATFORMS)))
        elif platform is not None and platform not in PLATFORMS:
            problems.append((name, "platform", "unknown platform '%s' (use: %s)" % (platform, ", ".join(PLATFORMS))))
        devices[name] = {"site": str(dev.get("site") or ""), "platform": platform, "features": feats}
    return Desired(devices, problems)


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = yaml.load(fh, Loader=UniqueKeyLoader) or {}
        except yaml.YAMLError as exc:
            raise ConfigError("YAML error in %s: %s" % (path, exc))
    return parse(data)
