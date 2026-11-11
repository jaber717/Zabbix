"""Read-only inventory discovery from a live Zabbix 7.0 (plus optional NetBox enrichment).

Only *.get / apiinfo.version calls, always through a ZabbixClient opened read_only=True (a write raises
ReadOnlyViolation before anything is sent). Network ports are taken from the items the stock interface
templates already discovered (item tag `interface`), NOT from Zabbix host interfaces, which are only the
management/monitoring endpoints. Nothing is inferred that the data does not show: a missing value stays
missing and is reported.
"""
import re
import time

from .zbx import ZabbixError

OWN_PREFIXES = ("netops.", "nhealth.")          # this project's own items: evidence of coverage, not ports
KINDS = (("status", re.compile(r"^net\.if\.status\[")), ("speed", re.compile(r"^net\.if\.speed\[")),
         ("type", re.compile(r"^net\.if\.type\[")), ("in_errors", re.compile(r"^net\.if\.in\.errors\[")),
         ("out_errors", re.compile(r"^net\.if\.out\.errors\[")), ("in_discards", re.compile(r"^net\.if\.in\.discards\[")),
         ("out_discards", re.compile(r"^net\.if\.out\.discards\[")), ("in", re.compile(r"^net\.if\.in\[")),
         ("out", re.compile(r"^net\.if\.out\[")))
INDEX_RE = re.compile(r"\.(\d+)\]$")
NAME_ALIAS_RE = re.compile(r"^Interface (.+?)\((.*)\): ")
DELAY_RE = re.compile(r"^(\d+)([smhdw]?)$")
UNIT_S = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
PLATFORM_RULES = (("cisco-nxos", re.compile(r"(?i)nexus|nx-?os")),
                  ("cisco-ios", re.compile(r"(?i)cisco (ios|catalyst)|ios[- ]?xe")),
                  ("huawei-vrp", re.compile(r"(?i)huawei.*vrp|vrp.*huawei")),
                  ("host-resources", re.compile(r"(?i)palo alto|linux by snmp|host[- ]resources")))
HEALTH_SEARCH = {"ospf": "ospf", "bgp": "bgp", "icmp": "icmpping"}
BATCH = 200


class DiscoveryError(Exception):
    """Discovery could not complete; nothing must be generated from a partial read."""


def parse_delay(text):
    """'1m' -> 60; '30' -> 30; macros / flexible intervals -> None (unknown)."""
    m = DELAY_RE.match(str(text or "").strip())
    if not m:
        return None
    return int(m.group(1)) * UNIT_S[m.group(2)]


def _chunks(seq, n=BATCH):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _kind(key):
    for name, rx in KINDS:
        if rx.match(key):
            return name
    return None


def _platform(template_names):
    for plat, rx in PLATFORM_RULES:
        for t in template_names:
            if rx.search(t):
                return plat, t
    return None, None


def _optional(client, limits, what, method, params):
    """Reads that a least-privilege token may be refused: record the gap instead of guessing."""
    try:
        return client.call(method, params)
    except ZabbixError as exc:
        limits.append("%s not readable with this token (%s) - reported as UNVERIFIED" % (what, exc.message or exc))
        return None


def discover(client, group_names=None, host_names=None, now=None, stale_after=900, delivery_days=90):
    """Return a snapshot dict. Raises DiscoveryError/ApiUnavailable/ZabbixError on any core read failure."""
    if not client.read_only:
        raise DiscoveryError("discovery must run on a read-only client")
    now = int(now if now is not None else time.time())
    limits = []
    snap = {"taken_at": now, "zabbix_version": client.version(), "limits": limits, "hosts": {},
            "actions": [], "mediatypes": {}, "usergroups": None, "users": None, "stale_after": stale_after,
            "scope": {"groups": sorted(group_names or []), "hosts": sorted(host_names or [])},
            "templates": None, "global_macros": None, "hostgroups": {}, "events": None,
            "delivery_days": delivery_days, "items": {}}

    params = {"output": ["hostid", "host", "name", "status", "maintenance_status"],
              "selectInterfaces": ["type", "main", "ip", "dns", "available", "error"],
              "selectHostGroups": ["groupid", "name"], "selectTags": ["tag", "value"],
              "selectParentTemplates": ["templateid", "host"],
              "selectMacros": ["hostmacroid", "macro", "value", "description"]}
    if group_names:
        groups = client.call("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": sorted(group_names)}})
        missing = sorted(set(group_names) - set(g["name"] for g in groups))
        if missing:
            raise DiscoveryError("host group(s) not found: %s" % ", ".join(missing))
        params["groupids"] = [g["groupid"] for g in groups]
    if host_names:
        params["filter"] = {"host": sorted(host_names)}
    rows = client.call("host.get", params)
    if host_names:
        missing = sorted(set(host_names) - set(r["host"] for r in rows))
        for m in missing:
            limits.append("host '%s' requested but not visible to this token / not in Zabbix" % m)

    by_id = {}
    for r in rows:
        tnames = [t["host"] for t in r.get("parentTemplates", [])]
        plat, src = _platform(tnames)
        snmp = [i for i in r.get("interfaces", []) if str(i.get("type")) == "2"]
        main = next((i for i in snmp if str(i.get("main")) == "1"), snmp[0] if snmp else None)
        h = {"hostid": r["hostid"], "host": r["host"], "name": r.get("name") or r["host"],
             "enabled": str(r.get("status")) == "0",
             "maintenance": str(r.get("maintenance_status", "0")) == "1",
             "groups": sorted(g["name"] for g in r.get("hostgroups", [])),
             "groupids": sorted(g["groupid"] for g in r.get("hostgroups", [])),
             "tags": sorted((t["tag"], t.get("value", "")) for t in r.get("tags", [])),
             "templates": sorted(tnames), "templateids": sorted(t["templateid"] for t in r.get("parentTemplates", [])),
             "platform": plat, "platform_source": src,
             "snmp": {"present": bool(snmp), "available": str(main.get("available", "0")) if main else None,
                      "error": (main or {}).get("error", "")},
             "has_interface": bool(r.get("interfaces")),
             "macros": dict((m["macro"], m) for m in r.get("macros", [])),
             "ports": {}, "health_items": {}, "triggers": [], "newest_clock": 0}
        snap["hosts"][r["host"]] = h
        by_id[r["hostid"]] = h

    item_port = {}            # itemid -> (host, port)
    item_host = {}            # itemid -> host (health/own items too)
    ids = list(by_id)
    for chunk in _chunks(ids):
        items = client.call("item.get", {
            "output": ITEM_OUTPUT,
            "hostids": chunk, "selectTags": ["tag", "value"], "tags": [{"tag": "interface", "operator": 4}]})
        for it in items:
            h = by_id.get(it["hostid"])
            if h is None:
                continue
            tagv = [t.get("value", "") for t in it.get("tags", []) if t["tag"] == "interface" and t.get("value")]
            if not tagv:
                continue
            port_name = tagv[0]
            snap.setdefault("item_tags", {})[it["itemid"]] = [(t["tag"], t.get("value", "")) for t in it.get("tags", [])]
            p = h["ports"].setdefault(port_name, {"name": port_name, "alias": "", "index": None, "items": {},
                                                  "dup": False, "own": {}, "indexes": set()})
            key = it["key_"]
            item_host[it["itemid"]] = h["host"]
            _remember(snap, it, h["host"])
            if key.startswith(OWN_PREFIXES):
                p["own"][key] = it["itemid"]
                item_port[it["itemid"]] = (h["host"], port_name)
                continue
            kind = _kind(key)
            m = INDEX_RE.search(key)
            if m:
                p["indexes"].add(m.group(1))
            alias = [t.get("value", "") for t in it.get("tags", []) if t["tag"] == "description"]
            if alias and alias[0] and not p["alias"]:
                p["alias"] = alias[0]
            nm = NAME_ALIAS_RE.match(it.get("name", ""))
            if nm and nm.group(1) == port_name and nm.group(2) and not p["alias"]:
                p["alias"] = nm.group(2)
            if kind is None:
                continue
            if kind in p["items"] and p["items"][kind]["key"] != key:
                p["dup"] = True
            p["items"][kind] = {"itemid": it["itemid"], "key": key, "lastvalue": it.get("lastvalue", ""),
                                "lastclock": int(it.get("lastclock") or 0), "state": str(it.get("state", "0")),
                                "enabled": str(it.get("status", "0")) == "0", "error": it.get("error", ""),
                                "delay": it.get("delay", "")}
            item_port[it["itemid"]] = (h["host"], port_name)
            h["newest_clock"] = max(h["newest_clock"], int(it.get("lastclock") or 0))
        for what, pattern in sorted(HEALTH_SEARCH.items()):
            for it in client.call("item.get", {"output": ITEM_OUTPUT,
                                               "hostids": chunk, "search": {"key_": pattern},
                                               "selectTags": ["tag", "value"]}):
                h = by_id.get(it["hostid"])
                if h is None:
                    continue
                snap.setdefault("item_tags", {})[it["itemid"]] = [(t["tag"], t.get("value", ""))
                                                                  for t in it.get("tags", [])]
                h["health_items"].setdefault(what, []).append(
                    {"itemid": it["itemid"], "key": it["key_"], "name": it.get("name", ""),
                     "lastvalue": it.get("lastvalue", ""), "lastclock": int(it.get("lastclock") or 0),
                     "state": str(it.get("state", "0")), "enabled": str(it.get("status", "0")) == "0",
                     "delay": it.get("delay", "")})
                item_host[it["itemid"]] = h["host"]
                _remember(snap, it, h["host"])

    for h in snap["hosts"].values():
        for p in h["ports"].values():
            idx = sorted(p.pop("indexes"))
            if len(idx) > 1:
                p["dup"] = True
            st = p["items"].get("status")
            p["index"] = INDEX_RE.search(st["key"]).group(1) if st and INDEX_RE.search(st["key"]) else (
                idx[0] if idx else None)
            sp = p["items"].get("speed")
            p["speed_bps"] = _speed_bps(sp)
            ty = p["items"].get("type")
            p["iftype"] = int(ty["lastvalue"]) if ty and str(ty["lastvalue"]).isdigit() else None
            p["oper"] = _oper(st)
            p["fresh"] = freshness(st, now, stale_after)

    # ---- triggers that use any port / health item (stock, NETOPS or anything else) -----------------------
    # Expressions are fetched RAW ({functionid} references, user macros untouched) with their functions and
    # rebuilt here: expandExpression would let Zabbix substitute macros, hiding gates from the validator.
    raw = []
    for chunk in _chunks(sorted(item_host), 1000):
        raw += client.call("trigger.get", {
            "output": ["triggerid", "description", "event_name", "priority", "status", "value", "state",
                       "error", "manual_close", "expression", "recovery_mode", "recovery_expression"],
            "itemids": chunk, "selectItems": ["itemid"], "selectTags": ["tag", "value"],
            "selectFunctions": ["functionid", "itemid", "name", "parameter"], "expandDescription": True})
    _fetch_missing_items(client, snap, set(f["itemid"] for t in raw for f in t.get("functions", [])) |
                         set(i["itemid"] for t in raw for i in t.get("items", [])))
    for it in snap["items"].values():
        if it is not None:
            it["quality"] = _quality(snap, it, now, stale_after)
    seen_t = set()
    for t in raw:
        if t["triggerid"] in seen_t:
            continue
        seen_t.add(t["triggerid"])
        fns = dict((f["functionid"], f) for f in t.get("functions", []))
        t["expression"] = rebuild(t.get("expression", ""), fns, snap["items"])
        t["recovery_expression"] = rebuild(t.get("recovery_expression", ""), fns, snap["items"])
        tid_items = [i["itemid"] for i in t.get("items", [])]
        hosts = set(item_host[i] for i in tid_items if i in item_host)
        for hn in hosts:
            h = snap["hosts"][hn]
            if any(x["triggerid"] == t["triggerid"] for x in h["triggers"]):
                continue
            ports = sorted(set(item_port[i][1] for i in tid_items if i in item_port and item_port[i][0] == hn))
            tags = sorted((x["tag"], x.get("value", "")) for x in t.get("tags", []))
            itags = sorted(set(tg for i in tid_items for tg in snap.get("item_tags", {}).get(i, [])))
            h["triggers"].append({"item_tags": itags,
                "triggerid": t["triggerid"], "name": t.get("description", ""), "priority": int(t.get("priority", 0)),
                "enabled": str(t.get("status", "0")) == "0", "problem": str(t.get("value", "0")) == "1",
                "unknown": str(t.get("state", "0")) == "1", "itemids": sorted(tid_items), "ports": ports,
                "expression": t.get("expression", ""), "recovery_mode": str(t.get("recovery_mode", "0")),
                "recovery_expression": t.get("recovery_expression", ""), "event_name": t.get("event_name", ""),
                "tags": tags, "netops": any(k == "netops_alert" for k, _ in tags)})

    # ---- macro / tag context: template ancestry, global macros, all host groups ---------------------------
    _templates(client, snap, limits)
    gm = _optional(client, limits, "global macros", "usermacro.get",
                   {"output": ["macro", "value"], "globalmacro": True})
    if gm is not None:
        snap["global_macros"] = dict((m["macro"], m.get("value", "")) for m in gm)
    for g in client.call("hostgroup.get", {"output": ["groupid", "name"]}):
        snap["hostgroups"][g["groupid"]] = g["name"]

    # ---- notification path (reads only; a least-privilege token may not see users) -----------------------
    snap["actions"] = client.call("action.get", {
        "output": ["actionid", "name", "eventsource", "status", "esc_period"], "filter": {"eventsource": "0"},
        "selectFilter": "extend", "selectOperations": "extend", "selectRecoveryOperations": "extend"})
    for m in client.call("mediatype.get", {"output": ["mediatypeid", "name", "type", "status"]}):
        snap["mediatypes"][m["mediatypeid"]] = {"name": m["name"], "type": str(m.get("type")),
                                                "enabled": str(m.get("status", "0")) == "0"}
    ug = _optional(client, limits, "user groups", "usergroup.get", {
        "output": ["usrgrpid", "name", "users_status"], "selectHostGroupRights": ["id", "permission"]})
    if ug is not None:
        snap["usergroups"] = dict((g["usrgrpid"], {
            "name": g["name"], "enabled": str(g.get("users_status", "0")) == "0",
            "rights": dict((r["id"], int(r["permission"])) for r in g.get("hostgroup_rights", []))}) for g in ug)
    us = _optional(client, limits, "users and their media", "user.get", {
        "output": ["userid", "username"], "selectMedias": ["mediatypeid", "active", "severity", "period"],
        "selectUsrgrps": ["usrgrpid"]})
    if us is not None:
        snap["users"] = [{"userid": u["userid"], "username": u.get("username", ""),
                          "groups": sorted(g["usrgrpid"] for g in u.get("usrgrps", [])),
                          "medias": [{"mediatypeid": str(m["mediatypeid"]), "active": str(m.get("active", "0")) == "0",
                                      "severity": int(m.get("severity", 63)), "period": str(m.get("period", ""))}
                                     for m in u.get("medias", [])]}
                         for u in us]
    _delivery(client, snap, limits, now)
    return snap


def _templates(client, snap, limits):
    """Template ancestry of every host, with template macros and tags (needed for macro and tag resolution)."""
    pending = set(t for h in snap["hosts"].values() for t in h["templateids"])
    seen = {}
    while pending:
        chunk = sorted(pending - set(seen))[:BATCH]
        pending -= set(chunk)
        if not chunk:
            break
        rows = _optional(client, limits, "templates (macros/tags)", "template.get", {
            "output": ["templateid", "host"], "templateids": chunk, "selectParentTemplates": ["templateid"],
            "selectMacros": ["macro", "value"], "selectTags": ["tag", "value"]})
        if rows is None:
            return
        for t in rows:
            seen[t["templateid"]] = {"name": t["host"], "parents": sorted(p["templateid"] for p in t.get("parentTemplates", [])),
                                     "macros": dict((m["macro"], m.get("value", "")) for m in t.get("macros", [])),
                                     "tags": [(x["tag"], x.get("value", "")) for x in t.get("tags", [])]}
            pending |= set(seen[t["templateid"]]["parents"]) - set(seen)
        missing = set(chunk) - set(r["templateid"] for r in rows)
        if missing:
            limits.append("%d linked template(s) not readable - macro/tag context incomplete" % len(missing))
            return
    snap["templates"] = seen
    for h in snap["hosts"].values():
        order, queue = [], list(h["templateids"])
        while queue:
            t = queue.pop(0)
            if t in order or t not in seen:
                continue
            order.append(t)
            queue += seen[t]["parents"]
        h["ancestry"] = order


def _delivery(client, snap, limits, now):
    """Raw event/alert history per trigger (correlated into Problem/Recovery pairs by coverage, never aggregated).
    Recovery messages are alerts on the recovery event whose p_eventid is the problem event."""
    tids = sorted(set(t["triggerid"] for h in snap["hosts"].values() for t in h["triggers"]))
    events = {}
    for chunk in _chunks(tids, 500):
        rows = _optional(client, limits, "event/alert history (delivery evidence)", "event.get", {
            "output": ["eventid", "objectid", "value", "clock", "r_eventid"], "source": 0, "object": 0,
            "objectids": chunk, "time_from": now - snap["delivery_days"] * 86400,
            "select_alerts": ["alertid", "actionid", "status", "alerttype", "eventid", "p_eventid", "mediatypeid",
                              "userid", "clock"]})
        if rows is None:
            return
        for e in rows:
            events.setdefault(e["objectid"], []).append({
                "eventid": e["eventid"], "value": str(e.get("value")), "clock": int(e.get("clock") or 0),
                "r_eventid": str(e.get("r_eventid") or "0"),
                "alerts": [dict((k, str(a.get(k, ""))) for k in ("alertid", "actionid", "status", "alerttype",
                                                                 "p_eventid", "mediatypeid", "userid", "clock"))
                           for a in e.get("alerts", [])]})
    snap["events"] = events


ITEM_OUTPUT = ["itemid", "hostid", "key_", "name", "lastvalue", "lastclock", "state", "status", "error", "delay",
               "value_type", "type", "master_itemid"]
FUNC_REF = re.compile(r"\{(\d+)\}")


def _remember(snap, it, host):
    """Data-quality record of every item a trigger may use (port, NETOPS, health and referenced items)."""
    snap["items"][it["itemid"]] = {
        "itemid": it["itemid"], "host": host, "key": it.get("key_", ""), "lastclock": int(it.get("lastclock") or 0),
        "state": str(it.get("state", "0")), "enabled": str(it.get("status", "0")) == "0",
        "delay": it.get("delay", ""), "type": str(it.get("type", "0")), "master": str(it.get("master_itemid") or "0"),
        "error": it.get("error", "")}


def _fetch_missing_items(client, snap, itemids):
    """Items referenced by triggers (and masters of dependent items) that were not read yet."""
    for _ in range(4):                                     # dependent chains are short; bounded on purpose
        want = set(i for i in itemids if i not in snap["items"])
        want |= set(it["master"] for it in snap["items"].values()
                    if it and it["type"] == "18" and it["master"] != "0" and it["master"] not in snap["items"])
        if not want:
            return
        got = set()
        for chunk in _chunks(sorted(want)):
            for it in client.call("item.get", {"output": ITEM_OUTPUT, "itemids": chunk, "selectHosts": ["host"]}):
                hosts = it.get("hosts") or []
                _remember(snap, it, hosts[0]["host"] if hosts else None)
                got.add(it["itemid"])
        for i in want - got:                               # not readable with this token: quality unknown
            snap["items"].setdefault(i, None)
        itemids = set()


def _quality(snap, it, now, stale_after):
    """freshness() of one item; a dependent item is judged with its master's polling interval."""
    if it is None:
        return "not readable"
    if it["type"] == "18":
        master = snap["items"].get(it["master"])
        if not master:
            return "master item not readable"
        mq = freshness(master, now, stale_after)
        if mq != "fresh":
            return "master item %s" % mq
        return freshness(dict(it, delay=master["delay"]), now, stale_after)
    return freshness(it, now, stale_after)


def rebuild(expr, functions, items):
    """'{123}=2' + functions -> 'last(/HOST/key)=2'. An unknown reference becomes {UNKNOWN} (fails closed)."""
    def one(m):
        f = functions.get(m.group(1))
        it = items.get(f["itemid"]) if f else None
        if not f or not it or not it.get("host"):
            return "{UNKNOWN}"
        par = str(f.get("parameter", "$"))
        rest = par[1:] if par.startswith("$") else None
        if rest is None:
            return "{UNKNOWN}"
        return "%s(/%s/%s%s)" % (f["name"], it["host"], it["key"], rest)
    return FUNC_REF.sub(one, expr or "")


def _speed_bps(item):
    """ifHighSpeed is Mbit/s in IF-MIB; stock templates multiply to bps. Unknown -> None (never guessed)."""
    if not item or item["state"] != "0" or not item["lastclock"]:
        return None
    try:
        v = float(item["lastvalue"])
    except (TypeError, ValueError):
        return None
    return int(v) if v > 0 else None


def _oper(item):
    if not item or item["state"] != "0" or not item["lastclock"]:
        return "unknown"
    return {"1": "up", "2": "down", "3": "testing", "5": "dormant", "6": "notPresent",
            "7": "lowerLayerDown"}.get(str(item["lastvalue"]), "unknown")


def freshness(item, now, stale_after=900):
    """'fresh' | 'stale' | 'unsupported' | 'disabled' | 'missing' | 'never'."""
    if not item:
        return "missing"
    if not item["enabled"]:
        return "disabled"
    if item["state"] != "0":
        return "unsupported"
    if not item["lastclock"]:
        return "never"
    d = parse_delay(item.get("delay"))
    limit = max(stale_after, 3 * d) if d else stale_after
    return "fresh" if now - item["lastclock"] <= limit else "stale"
