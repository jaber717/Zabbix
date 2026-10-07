"""Turn the resolved YAML into the exact Zabbix objects we want to exist."""
import re

from . import template as tpl
from .config import SEVERITIES

IFCONTROL = "{$IFCONTROL"       # stock gating macro, only touched when suppress_stock is on
MAX_MACRO_VALUE = 2048          # Zabbix limit for a macro value


class ModelError(Exception):
    pass


def num(v):
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def ctx_name(base, iface):
    """{$NETOPS.X:"iface"} — Zabbix context macros cannot hold a double quote or backslash."""
    if '"' in iface or "\\" in iface:
        raise ModelError("interface name %r contains a quote or backslash, which Zabbix cannot "
                         "use as a macro context" % iface)
    return '{$NETOPS.%s:"%s"}' % (base, iface)


def regex_for(names):
    """PCRE that matches exactly the given interface names."""
    escaped = sorted(re.escape(n) for n in names)
    return "^(?:%s)$" % "|".join(escaped)


def host_macros(hostcfg, suppress_stock=False):
    """{macro: value} for one host. Includes the selection regex and per-interface context macros."""
    out = {}
    names = sorted(hostcfg["interfaces"])
    rx = regex_for(names)
    if len(rx) > MAX_MACRO_VALUE:
        raise ModelError("too many interfaces for one host: selection regex is %d characters "
                         "(limit %d)" % (len(rx), MAX_MACRO_VALUE))
    out["{$NETOPS.IF.MATCH}"] = rx
    out["{$NETOPS.SITE}"] = hostcfg["site"]
    for name in names:
        c = hostcfg["interfaces"][name]
        u, e, d, f = c["utilization"], c["errors"], c["discards"], c["flapping"]
        pairs = [
            ("DESCR", c["description"]), ("ROLE", c["role"]),
            ("SEV", str(SEVERITIES[c["severity"]])),
            ("LINK", "1" if c["link_alert"] else "0"),
            ("LINKID", c["link_id"]),
            ("POLL", str(u["poll_interval"])),
            ("UTIL.ON", "1" if u["enabled"] else "0"),
            ("UTIL.MAX", num(u["threshold"])), ("UTIL.RECOVER", num(u["recovery"])),
            ("ERR.ON", "1" if e["enabled"] else "0"), ("ERR.RATE", num(e["rate"])),
            ("ERR.RECOVER", num(e.get("recovery") or 0)),
            ("DISC.ON", "1" if d["enabled"] else "0"), ("DISC.RATE", num(d["rate"])),
            ("DISC.RECOVER", num(d.get("recovery") or 0)),
            ("FLAP.ON", "1" if f["enabled"] else "0"), ("FLAP.COUNT", num(f["transitions"])),
            ("FLAP.WINDOW", str(f["window"])),
            ("SPEED.EXPECTED", str(c["expected_speed"] or 0)),
        ]
        for base, value in pairs:
            out[ctx_name(base, name)] = value
        if suppress_stock:
            out['{$IFCONTROL:"%s"}' % name] = "0"
    return out


def macro_description():
    return tpl.MARKER


def is_owned(macro_row):
    return tpl.MARKER in (macro_row.get("description") or "")


def in_namespace(macro):
    return macro.startswith(tpl.MACRO_PREFIX)


# ------------------------------------------------------------------- alert action

ACTION_SUBJECT = "[{EVENT.SEVERITY}] {EVENT.NAME}"
ACTION_MESSAGE = (
    "Device:     {HOST.NAME} ({HOST.IP})\r\n"
    "Site:       {EVENT.TAGS.site}\r\n"
    "Link ID:    {EVENT.TAGS.link_id}\r\n"
    "Interface:  {EVENT.TAGS.if_name}\r\n"
    "Description:{EVENT.TAGS.if_descr}\r\n"
    "Role:       {EVENT.TAGS.if_role}\r\n"
    "Severity:   {EVENT.SEVERITY}\r\n"
    "Alert:      {EVENT.TAGS.netops_alert}  direction {EVENT.TAGS.direction}  "
    "threshold {EVENT.TAGS.threshold}\r\n"
    "Observed:   {EVENT.OPDATA}\r\n"
    "Problem:    {EVENT.NAME}\r\n"
    "Started:    {EVENT.DATE} {EVENT.TIME}\r\n"
    "Event ID:   {EVENT.ID}\r\n")
ACTION_RECOVERY_SUBJECT = "[RESOLVED] {EVENT.NAME}"
ACTION_RECOVERY_MESSAGE = (
    "Resolved:   {EVENT.RECOVERY.DATE} {EVENT.RECOVERY.TIME}\r\n"
    "Duration:   {EVENT.DURATION}\r\n" + ACTION_MESSAGE)


def desired_action(env):
    """None when the environment config declares no alert_action (nothing is created)."""
    cfg = env.get("alert_action")
    if not cfg:
        return None
    return {
        "name": cfg["name"],
        "enabled": bool(cfg.get("enabled", False)),
        "usergroups": list(cfg["usergroups"]),
        "media_type": cfg.get("media_type"),
        "subject": ACTION_SUBJECT, "message": ACTION_MESSAGE,
        "r_subject": ACTION_RECOVERY_SUBJECT, "r_message": ACTION_RECOVERY_MESSAGE,
    }


def nvps_estimate(desired):
    """Rough Zabbix load of the selected interfaces: (interfaces, new values/s, SNMP gets/s)."""
    values = 0.0
    gets = 0.0
    count = 0
    for host in desired.hosts.values():
        for c in host["interfaces"].values():
            count += 1
            poll = max(c["utilization"]["poll_seconds"], 1)
            values += 3.0 / poll + 6.0 / 60.0   # oper/in/out fast; hspeed, 4 counters slow (+ dependent)
            gets += 3.0 / poll + 5.0 / 60.0
    return count, values, gets
