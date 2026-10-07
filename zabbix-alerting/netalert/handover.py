"""Turn an externally produced interface list (the Codex P2P handover) into a verified policy.

Nothing from the handover is trusted: every entry is checked against the live Zabbix with the
same read-only checks as `--check`. Entries that verify go into the generated policy; anything
else is listed as REVIEW REQUIRED with the reason. Never writes to Zabbix.
"""
import yaml

from . import config, planner

HOST_KEYS = ("host", "device", "hostname")
IFACE_KEYS = ("interface", "ifname", "name", "port")
PASS_THROUGH = ("description", "role", "severity", "link_alert", "utilization", "errors", "discards",
                "flapping", "expected_speed")


def normalize(data):
    """Accept our own schema, or a flat list of {host, interface, ...} records."""
    if isinstance(data, dict) and isinstance(data.get("hosts"), dict):
        return data
    rows = None
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for k in ("interfaces", "p2p_interfaces", "p2p", "links"):
            if isinstance(data.get(k), list):
                rows = data[k]
                break
    if rows is None:
        raise config.ConfigError("handover file is neither a `hosts:` mapping nor a list of interface records")
    out = {"hosts": {}}
    if isinstance(data, dict) and isinstance(data.get("defaults"), dict):
        out["defaults"] = data["defaults"]
    for r in rows:
        if not isinstance(r, dict):
            raise config.ConfigError("handover record is not a mapping: %r" % (r,))
        host = next((str(r[k]) for k in HOST_KEYS if r.get(k)), None)
        iface = next((str(r[k]) for k in IFACE_KEYS if r.get(k)), None)
        if not host or not iface:
            raise config.ConfigError("handover record needs a host and an interface: %r" % (r,))
        h = out["hosts"].setdefault(host, {"site": str(r.get("site", "")), "interfaces": {}})
        entry = dict((k, r[k]) for k in PASS_THROUGH if k in r)
        entry.setdefault("description", str(r.get("peer", "") or r.get("remote", "") or ""))
        h["interfaces"][iface] = entry
    return out


def verify(client, data):
    """Returns (verified_dict, review_rows, checks). `data` must already be normalized."""
    review = []
    verified = {"hosts": {}}
    if "defaults" in data:
        verified["defaults"] = data["defaults"]
    desired = config.parse(data)
    hosts_live = planner.get_hosts(client, list(desired.hosts))
    checks = planner.run_checks(client, desired, hosts_live)
    bad = {}
    for c in checks:
        if not c.ok:
            bad.setdefault((c.host, c.iface), []).append(c.message)
    for host, h in data["hosts"].items():
        for iface, entry in h["interfaces"].items():
            reasons = bad.get((host, iface), []) + bad.get((host, "-"), [])
            if reasons:
                review.append((host, iface, "; ".join(reasons)))
                continue
            vh = verified["hosts"].setdefault(host, {"site": h.get("site", ""), "interfaces": {}})
            vh["interfaces"][iface] = entry
    for (host, iface), msgs in bad.items():
        if host not in data["hosts"] or iface not in data["hosts"][host]["interfaces"]:
            review.append((host, iface, "; ".join(msgs)))
    return verified, sorted(set(review)), checks


def render_policy(verified, header):
    return header + yaml.safe_dump(verified, default_flow_style=False, sort_keys=True)


def render_review(review):
    if not review:
        return "# REVIEW REQUIRED\n\nNothing: every handover entry verified against Zabbix.\n"
    lines = ["# REVIEW REQUIRED", "",
             "These handover entries did NOT verify against the live Zabbix and were left out of the policy.", ""]
    for host, iface, why in review:
        lines.append("- `%s` / `%s` — %s" % (host, iface, why))
    return "\n".join(lines) + "\n"
