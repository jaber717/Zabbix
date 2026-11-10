"""Production Monitoring Coverage Audit (read-only, from a discovery snapshot + the onboarding model).

A port is PROTECTED / VERIFIED only when ALL of these are shown by live data:
  fresh status data, an enabled link-state trigger that is not switched off by its macros, a utilization
  alert for project-managed ports, and a notification path that is READY for that trigger: an enabled
  trigger action whose conditions provably match, with problem AND recovery operations, an enabled media
  type, and at least one recipient with active media for the severity and read permission on the host.
Anything that cannot be proven (unreadable users, custom action formulas, time-period conditions) is
reported as such and never counted as protected.
"""
import re
import time

from . import discovery

CLASSES = ("PROTECTED / VERIFIED", "PARTIALLY COVERED", "NOT COVERED", "STALE / UNKNOWN", "REVIEW REQUIRED")
PROT, PART, NOTC, STALE, REVIEW = CLASSES
SEV_NAMES = {0: "not classified", 1: "information", 2: "warning", 3: "average", 4: "high", 5: "disaster"}


# ------------------------------------------------------------------------ action condition evaluation

def _tri_and(vals):
    if any(v is False for v in vals):
        return False
    return None if any(v is None for v in vals) else True


def _tri_or(vals):
    if any(v is True for v in vals):
        return True
    return None if any(v is None for v in vals) else False


def _match_text(op, actual, value):
    a, v = (actual or "").lower(), (value or "").lower()
    return {0: a == v, 1: a != v, 2: v in a, 3: v not in a}.get(op)


def eval_condition(c, host, trig):
    """True / False / None (cannot evaluate)."""
    ct, op = int(c["conditiontype"]), int(c.get("operator", 0))
    val = str(c.get("value", ""))
    if ct == 0:                                                       # host group
        r = val in host["groupids"]
        return r if op == 0 else (not r if op == 1 else None)
    if ct == 1:                                                       # host
        r = val == host["hostid"]
        return r if op == 0 else (not r if op == 1 else None)
    if ct == 2:                                                       # trigger
        r = val == trig["triggerid"]
        return r if op == 0 else (not r if op == 1 else None)
    if ct == 3:                                                       # event name
        return _match_text(op, trig["name"], val)
    if ct == 4:                                                       # severity
        s, v = trig["priority"], int(val or 0)
        return {0: s == v, 1: s != v, 5: s >= v, 6: s <= v}.get(op)
    if ct == 13:                                                      # template
        if val not in host["templateids"]:
            return False if op == 0 else (True if op == 1 else None)
        return None
    if ct == 16:                                                      # problem is suppressed
        return {11: True, 10: False}.get(op, True if op == 1 else (False if op == 0 else None))
    if ct in (25, 26):                                                # event tag name / tag value
        # trigger + host + item tags. Template-level tags are not read: a tag found nowhere counts as absent,
        # which can only UNDER-report coverage, never over-claim it.
        tags = list(trig["tags"]) + list(host["tags"]) + list(trig.get("item_tags", []))
        if ct == 25:
            names = [t for t, _ in tags]
            if op == 0:
                r = val in names
            elif op == 1:
                r = val not in names
            elif op == 2:
                r = any(val.lower() in n.lower() for n in names)
            elif op == 3:
                r = not any(val.lower() in n.lower() for n in names)
            else:
                return None
        else:
            name = str(c.get("value2", ""))
            vals = [v for t, v in tags if t == name]
            res = [_match_text(op, v, val) for v in vals]
            if op in (0, 2):
                r = any(res)
            elif op in (1, 3):
                r = all(res) if res else True
            else:
                return None
        return r
    return None                                                       # time period, maintenance, etc.


def eval_filter(flt, host, trig):
    conds = (flt or {}).get("conditions") or []
    if not conds:
        return True
    res = dict((c.get("formulaid", str(i)), eval_condition(c, host, trig)) for i, c in enumerate(conds))
    et = str((flt or {}).get("evaltype", "0"))
    if et == "1":
        return _tri_and(list(res.values()))
    if et == "2":
        return _tri_or(list(res.values()))
    if et == "3":
        tokens = re.findall(r"[A-Z]+|and|or|not|\(|\)|\S+", str(flt.get("formula", "")))
        if not tokens or any(not (t in ("and", "or", "not", "(", ")") or t in res) for t in tokens):
            return None
        if any(res[t] is None for t in tokens if t in res):
            return None
        expr = " ".join(("True" if res[t] else "False") if t in res else t for t in tokens)
        try:
            return bool(eval(expr, {"__builtins__": {}}, {}))       # tokens are only True/False/and/or/not/()
        except SyntaxError:
            return None
    groups = {}
    for c in conds:
        groups.setdefault(int(c["conditiontype"]), []).append(eval_condition(c, host, trig))
    return _tri_and([_tri_or(v) for v in groups.values()])


def _recipients(snap, op, host, trig):
    """(verified_count, unknown_reason)."""
    mt = str((op.get("opmessage") or {}).get("mediatypeid", "0"))
    mts = snap["mediatypes"]
    if mt != "0" and not mts.get(mt, {}).get("enabled"):
        return 0, None
    if snap["users"] is None or snap["usergroups"] is None:
        return 0, "recipients not readable with this token"
    groups = set(g["usrgrpid"] for g in op.get("opmessage_grp", []))
    users = set(u["userid"] for u in op.get("opmessage_usr", []))
    n = 0
    for u in snap["users"]:
        if u["userid"] not in users and not groups.intersection(u["groups"]):
            continue
        ugs = [snap["usergroups"].get(g) for g in u["groups"]]
        if any(g and not g["enabled"] for g in ugs):
            continue
        perms = {}
        for g in ugs:
            for hg, perm in (g or {}).get("rights", {}).items():
                perms.setdefault(hg, []).append(perm)
        rights = dict((hg, 0 if 0 in p else max(p)) for hg, p in perms.items())   # Zabbix: deny always wins
        if not any(rights.get(g, 0) >= 2 for g in host["groupids"]) or any(rights.get(g) == 0 for g in host["groupids"]):
            continue
        for m in u["medias"]:
            if not m["active"] or not (m["severity"] >> trig["priority"]) & 1:
                continue
            if (mt == "0" and mts.get(m["mediatypeid"], {}).get("enabled")) or m["mediatypeid"] == mt:
                n += 1
                break
    return n, None


def notification(snap, host, trig):
    """('READY'|'PARTIAL'|'NONE', [details])."""
    best, details = "NONE", []
    for a in snap["actions"]:
        if str(a.get("status", "0")) != "0":
            continue
        m = eval_filter(a.get("filter"), host, trig)
        if m is False:
            continue
        ops = [o for o in a.get("operations", []) if str(o.get("operationtype")) == "0"]
        rec = [o for o in a.get("recovery_operations", []) if str(o.get("operationtype")) in ("0", "11")]
        if not ops:
            continue
        n, unknown = 0, None
        for o in ops:
            c, u = _recipients(snap, o, host, trig)
            n += c
            unknown = unknown or u
        if m is True and n and rec:
            return "READY", ["action '%s': %d recipient(s), problem + recovery" % (a["name"], n)]
        why = []
        if m is None:
            why.append("conditions cannot be evaluated offline")
        if not rec:
            why.append("no recovery operation")
        if unknown:
            why.append(unknown)
        elif not n:
            why.append("no recipient with active media for %s and host permission" % SEV_NAMES[trig["priority"]])
        details.append("action '%s': %s" % (a["name"], "; ".join(why)))
        best = "PARTIAL"
    return best, details or ["no enabled trigger action matches"]


# ------------------------------------------------------------------------------------- classification

def _ctx(host, base, port, default):
    m = host["macros"].get('{$NETOPS.%s:"%s"}' % (base, port)) or host["macros"].get("{$NETOPS.%s}" % base)
    return m["value"] if m else default


def _stock_gated_off(host, port):
    m = host["macros"].get('{$IFCONTROL:"%s"}' % port) or host["macros"].get("{$IFCONTROL}")
    return bool(m and str(m["value"]) == "0")


def port_coverage(snap, row):
    """(class, [reasons], evidence dict)."""
    h, p = row.h, row.p
    reasons = list(row.blockers) + list(row.review)
    if any("ambiguous" in r or "no longer discovered" in r or "not found" in r or "index changed" in r
           or "pairing conflict" in r for r in reasons):
        return REVIEW, reasons, {}
    if h is None or p is None:
        return REVIEW, reasons or ["not discoverable"], {}
    if not h["enabled"]:
        return STALE, ["host disabled"], {}
    if h["snmp"]["available"] == "2":
        return STALE, ["SNMP interface unavailable: %s" % (h["snmp"]["error"] or "no error text")], {}
    if p["fresh"] != "fresh":
        return STALE, ["status item %s" % p["fresh"]], {}
    st_id = p["items"].get("status", {}).get("itemid")
    util_ids = set(x["itemid"] for k, x in p["items"].items() if k in ("in", "out"))
    managed = bool(p["own"])
    link, util = [], []
    for t in h["triggers"]:
        if not t["enabled"] or row.port not in t["ports"]:
            continue
        if t["netops"]:
            alert = dict(t["tags"]).get("netops_alert", "")
            sev_ok = str(_ctx(h, "SEV", row.port, "4")) == str(t["priority"])
            if not sev_ok:
                continue
            if alert == "link_down" and _ctx(h, "LINK", row.port, "1") == "1":
                link.append(t)
            elif alert in ("util_rx", "util_tx") and _ctx(h, "UTIL.ON", row.port, "0") == "1":
                util.append(t)
        elif st_id in t["itemids"] and not _stock_gated_off(h, row.port):
            link.append(t)
        elif util_ids.intersection(t["itemids"]) and not _stock_gated_off(h, row.port):
            util.append(t)
    ev = {"link": [t["name"] for t in link], "util": [t["name"] for t in util], "managed": managed}
    if any(t["unknown"] for t in link):
        return STALE, ["link trigger in UNKNOWN state"], ev
    if not link:
        why = ["no enabled link-state trigger (stock or project) on this port"]
        if row.status == "APPROVED" and not managed:
            why.append("approved but not yet deployed (run --deploy)")
        return NOTC, why + reasons, ev
    verdicts = [notification(snap, h, t) for t in link]
    ready = [v for v in verdicts if v[0] == "READY"]
    ev["notify"] = (ready or verdicts)[0][1]
    gaps = []
    if not ready:
        gaps.append("link alert has no verified Problem+Recovery notification path: %s" % "; ".join(verdicts[0][1]))
    if not util and (row.status == "APPROVED" or row.candidate):
        gaps.append("no utilization alert (agreed policy: 70% problem / 65% recovery)")
    if row.status == "APPROVED" and not managed:
        gaps.append("approved but not yet deployed by this project")
    if gaps or reasons:
        return PART, gaps + reasons, ev
    return PROT, [], ev


def device_coverage(snap, dev):
    h = dev.h
    if h is None:
        return REVIEW, ["host not in Zabbix"]
    if not h["enabled"]:
        return STALE, ["host disabled"]
    if not h["snmp"]["present"]:
        return NOTC, ["no SNMP interface: interfaces and health cannot be monitored by SNMP"]
    if h["snmp"]["available"] == "2":
        return STALE, ["SNMP unavailable: %s" % (h["snmp"]["error"] or "")]
    age = snap["taken_at"] - h["newest_clock"] if h["newest_clock"] else None
    if age is None or age > snap["stale_after"]:
        return STALE, ["no fresh interface data (newest value %s)" % ("never" if age is None else "%ds ago" % age)]
    icmp = [t for t in h["triggers"] if t["enabled"] and any(
        i["itemid"] in t["itemids"] for i in h["health_items"].get("icmp", []))]
    if not icmp:
        return PART, ["no enabled reachability (ICMP) trigger"]
    v = [notification(snap, h, t) for t in icmp]
    if not any(x[0] == "READY" for x in v):
        return PART, ["reachability alert has no verified notification path: %s" % "; ".join(v[0][1])]
    return PROT, []


# --------------------------------------------------------------------------------------------- report

def audit(snap, model):
    ports = []
    for r in model["ports"]:
        if not (r.candidate or r.status in ("APPROVED", "REMOVE") or (r.p and r.p["own"])):
            continue
        cls, why, ev = port_coverage(snap, r)
        ports.append((r, cls, why, ev))
    devices = [(d, ) + device_coverage(snap, d) for d in model["devices"] if d.h is not None or d.in_yaml]
    findings = list(snap["limits"])
    for a in snap["actions"]:
        if str(a.get("status")) == "0" and any(str(o.get("operationtype")) == "0" for o in a.get("operations", [])) \
                and not a.get("recovery_operations"):
            findings.append("action '%s' sends problems but has NO recovery operation" % a["name"])
    used = set()
    for a in snap["actions"]:
        if str(a.get("status")) != "0":
            continue
        for o in a.get("operations", []) + a.get("recovery_operations", []):
            mt = str((o.get("opmessage") or {}).get("mediatypeid", "0"))
            if mt != "0":
                used.add(mt)
    for mt in sorted(used):
        if not snap["mediatypes"].get(mt, {}).get("enabled"):
            findings.append("enabled action uses media type %s which is disabled or not readable"
                            % snap["mediatypes"].get(mt, {}).get("name", mt))
    if not any(str(a.get("status")) == "0" for a in snap["actions"]):
        findings.append("no enabled trigger action: no problem will notify anyone")
    netops = [a for a in snap["actions"] if a["name"].startswith("NETOPS-IaC")]
    if not netops:
        findings.append("NETOPS-IaC e-mail action not present (alert_action not deployed yet)")
    elif any(str(a.get("status")) != "0" for a in netops):
        findings.append("NETOPS-IaC action exists but is DISABLED")
    hosts_no_ports = [h["host"] for h in snap["hosts"].values() if h["snmp"]["present"] and not h["ports"]]
    if hosts_no_ports:
        findings.append("%d SNMP host(s) have no discovered interface items (blind spot): %s" % (
            len(hosts_no_ports), ", ".join(sorted(hosts_no_ports)[:20])))
    no_snmp = [h["host"] for h in snap["hosts"].values() if not h["snmp"]["present"]]
    if no_snmp:
        findings.append("%d host(s) without SNMP interface (ports not discoverable): %s" % (
            len(no_snmp), ", ".join(sorted(no_snmp)[:20])))
    return {"ports": ports, "devices": devices, "findings": findings}


def counts(result):
    c = dict((k, 0) for k in CLASSES)
    for _, cls, _, _ in result["ports"]:
        c[cls] += 1
    return c


def render(snap, model, result, env_name, url):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap["taken_at"]))
    c = counts(result)
    L = ["# Production Monitoring Coverage Audit", "",
         "Environment **%s** · Zabbix %s (%s) · discovered %s · read-only" % (env_name, snap["zabbix_version"], url, ts),
         "", "Scope: %d host(s), %d discovered port(s); %d port(s) in audit scope (candidates, approved, project-managed)."
         % (len(snap["hosts"]), sum(len(h["ports"]) for h in snap["hosts"].values()), len(result["ports"])),
         "Coverage is reported only for this scope. Anything listed under *Limits* could not be discovered.", "",
         "| Class | Ports |", "|---|---|"]
    L += ["| %s | %d |" % (k, c[k]) for k in CLASSES]
    L += ["", "## Ports", "", "| Class | Host | Port | Description | Role | Decision | Reasons / evidence |",
          "|---|---|---|---|---|---|---|"]
    order = dict((k, i) for i, k in enumerate((REVIEW, NOTC, STALE, PART, PROT)))
    for r, cls, why, ev in sorted(result["ports"], key=lambda x: (order[x[1]], x[0].host, x[0].port)):
        evtxt = "; ".join(why) if why else "link: %s; util: %s; %s" % (
            ", ".join(ev.get("link", [])) or "-", ", ".join(ev.get("util", [])) or "-", "; ".join(ev.get("notify", [])))
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (cls, r.host, r.port, _md(r.alias or r.description),
                                                            r.role or "-", r.status, _md(evtxt)))
    L += ["", "## Devices", "", "| Class | Host | Platform | SNMP | Health features | Unsupported / unverified checks | Reasons |",
          "|---|---|---|---|---|---|---|"]
    for d, cls, why in result["devices"]:
        snmp = "-" if not d.h or not d.h["snmp"]["present"] else {"1": "available", "2": "UNAVAILABLE"}.get(
            d.h["snmp"]["available"], "unknown")
        gaps = ["%s: %s" % (f, w) for f, w in sorted(d.unsupported.items())]
        gaps += ["%s: unverified" % f for f, s in sorted(d.support.items()) if "UNVERIFIED" in s]
        L.append("| %s | %s | %s | %s | %s (%s) | %s | %s |" % (
            cls, d.host, d.platform or "?", snmp, ", ".join(d.features) or "-", d.status, _md("; ".join(gaps) or "-"),
            _md("; ".join(why))))
    existing = []
    for h in snap["hosts"].values():
        for t in h["triggers"]:
            if t["enabled"] and not t["netops"] and t["ports"]:
                existing.append((h["host"], ", ".join(t["ports"]), t["name"]))
    L += ["", "## Existing alerts that are preserved (never modified by this project)", ""]
    L += ["- %s / %s - %s" % e for e in sorted(existing)[:300]] or ["- none found on interface items"]
    if len(existing) > 300:
        L.append("- ... %d more" % (len(existing) - 300))
    amb = [r for r in model["ports"] if r.candidate and (r.pair_hints or any("peer" in x for x in r.review))]
    L += ["", "## ISP / P2P endpoint relationships", ""]
    seen = set()
    for r in model["ports"]:
        if r.status == "APPROVED" and r.pair and tuple(sorted((r.id, r.pair))) not in seen:
            seen.add(tuple(sorted((r.id, r.pair))))
            L.append("- PAIRED (%s): %s <-> %s" % (r.pair_source or "operator", r.id, r.pair))
    for r in amb:
        if r.pair_hints and not r.pair and tuple(sorted((r.id, r.pair_hints[0]))) not in seen:
            seen.add(tuple(sorted((r.id, r.pair_hints[0]))))
            L.append("- SUGGESTED (description cross-reference only, NOT verified): %s <-> %s" % (r.id, r.pair_hints[0]))
        for x in r.review:
            if "peer" in x:
                L.append("- REVIEW: %s: %s" % (r.id, x))
    if L[-1] == "":
        L.append("- none")
    L += ["", "## Findings, blind spots and limits", ""]
    L += ["- %s" % f for f in result["findings"]] or ["- none"]
    return "\n".join(L) + "\n"


def _md(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


__all__ = ["audit", "render", "counts", "notification", "eval_filter", "port_coverage", "discovery"]
