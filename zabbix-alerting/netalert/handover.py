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


def verify(client, data, extras=None):
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
    if extras:
        for key, why in cross_check(client, extras, hosts_live).items():
            bad.setdefault(key, []).append(why)
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


# ---------------------------------------------------------------- Codex P2P handover format
# hosts: {PNET-X: {zabbix_hostid, site, interfaces: {Gi0/0: {zabbix_ifname, snmp_index,
#         zabbix_status_itemid, description, link_id, severity, utilization_threshold, ...}}}}

def is_codex_format(data):
    if not (isinstance(data, dict) and isinstance(data.get("hosts"), dict)):
        return False
    for h in data["hosts"].values():
        for i in (h.get("interfaces") or {}).values():
            if isinstance(i, dict) and ("zabbix_ifname" in i or "device_interface" in i):
                return True
    return False


def from_codex(data):
    """(policy, extras). Policy uses our schema; extras are the identifiers to cross-check live.

    Nothing is invented: speeds are NOT copied (nominal values were never read live), so capacity
    comes from ifHighSpeed. Every end keeps its own notification
    and shares link_id with its peer.
    """
    sel = data.get("selection_rules") or {}
    policy = {"hosts": {}}
    extras = {}
    for host, h in sorted(data["hosts"].items()):
        ph = policy["hosts"].setdefault(host, {"site": str(h.get("site", "")), "interfaces": {}})
        for key, i in sorted(h["interfaces"].items()):
            ifname = i.get("zabbix_ifname") or key
            rec = i.get("recommended_alerts") or {}
            entry = {
                "description": i.get("description") or "",
                "role": "P2P",
                "severity": i.get("severity", "high"),
                "link_id": i.get("link_id", ""),
                "link_alert": bool(rec.get("link", True)),
                "utilization": {"enabled": bool(rec.get("utilization", False)),
                                "threshold": i.get("utilization_threshold", sel.get("utilization_threshold_pct", 70)),
                                "recovery": i.get("utilization_recovery", sel.get("utilization_recovery_pct", 65))},
                "errors": {"enabled": bool(rec.get("errors", True)), "rate": 1},
                "discards": {"enabled": bool(rec.get("discards", True)), "rate": 1},
                "flapping": {"enabled": bool(rec.get("flapping", True)), "transitions": 3, "window": "10m"},
            }
            ph["interfaces"][str(ifname)] = entry
            extras[(host, str(ifname))] = {"hostid": str(h.get("zabbix_hostid", "")),
                                           "itemid": str(i.get("zabbix_status_itemid", "")),
                                           "index": str(i.get("snmp_index", "")), "ifname": str(ifname)}
    return policy, extras


def cross_check(client, extras, hosts_live):
    """Identity checks beyond name existence: host id, status item id, its interface tag and SNMP index."""
    bad = {}
    wanted = [x["itemid"] for x in extras.values() if x["itemid"]]
    items = {}
    if wanted:
        for r in client.call("item.get", {"output": ["itemid", "hostid", "key_"], "itemids": wanted,
                                          "selectTags": ["tag", "value"]}):
            items[r["itemid"]] = r
    for (host, ifname), x in extras.items():
        why = []
        live = hosts_live.get(host)
        if live and x["hostid"] and live["hostid"] != x["hostid"]:
            why.append("host id differs (handover %s, Zabbix %s)" % (x["hostid"], live["hostid"]))
        if live:
            it = items.get(x["itemid"])
            if not it:
                why.append("status item %s not found" % x["itemid"])
            else:
                tag = [t["value"] for t in it.get("tags", []) if t["tag"] == "interface"]
                if it["hostid"] != live["hostid"]:
                    why.append("status item %s belongs to another host" % x["itemid"])
                if ifname not in tag:
                    why.append("status item %s is tagged interface=%s, not %s" % (x["itemid"], tag, ifname))
                if x["index"] and not it["key_"].endswith(".%s]" % x["index"]):
                    why.append("status item key %s does not match snmp_index %s" % (it["key_"], x["index"]))
        if why:
            bad[(host, ifname)] = "; ".join(why)
    return bad
