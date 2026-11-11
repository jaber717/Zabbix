"""Production Monitoring Coverage Audit (read-only, from a discovery snapshot + the onboarding model).

Two protected levels, never inferred from the mere existence of a trigger or an action:

  CONFIG VERIFIED (DELIVERY NOT TESTED) - every link of the chain is proven from live configuration:
    fresh data; an enabled trigger whose EXPRESSION tests link-down on this port (and one that tests utilization);
    every gating macro in those expressions resolves (host -> template ancestry -> global) to an open gate;
    an enabled trigger action whose conditions provably match the event (full tag set incl. template tags,
    nested host groups, template ancestry); an immediate problem operation AND a recovery operation, each with
    at least one eligible recipient: active media of an enabled media type, the event severity, an unrestricted
    active period, an enabled user group and read permission on the host (a deny anywhere wins).
  PROTECTED (DELIVERY TESTED) - the above, plus Zabbix's own alert history shows a SENT problem message and a
    SENT recovery message from that action for that trigger inside the evidence window.

Anything that cannot be proven (unreadable users/templates/history, custom formulas with unknown inputs,
time-period conditions, unresolvable macros, unknown expression semantics) fails closed and is reported.
"""
import re
import time

PROT, CONFIG, PART, NOTC, STALE, REVIEW = (
    "PROTECTED (DELIVERY TESTED)", "CONFIG VERIFIED (DELIVERY NOT TESTED)", "PARTIALLY COVERED", "NOT COVERED",
    "STALE / UNKNOWN", "REVIEW REQUIRED")
CLASSES = (PROT, CONFIG, PART, NOTC, STALE, REVIEW)
PROTECTED_CLASSES = (PROT, CONFIG)
SEV_NAMES = {0: "not classified", 1: "information", 2: "warning", 3: "average", 4: "high", 5: "disaster"}
ALWAYS = "1-7,00:00-24:00"
MACRO_CMP = re.compile(r'(\{\$[A-Z0-9_.]+(?::"(?:[^"\\]|\\.)*")?\})\s*(=|<>)\s*"?(-?\d+)"?')
MACRO_ANY = re.compile(r'\{\$[A-Z0-9_.]+(?::[^}]*)?\}')


# ------------------------------------------------------------------------------------- macro resolution

def _split(macro):
    m = re.match(r'^\{\$([A-Z0-9_.]+)(?::"((?:[^"\\]|\\.)*)")?\}$', macro)
    return (m.group(1), m.group(2)) if m else (None, None)


def resolve_macro(snap, host, macro):
    """Value or None (unknown). Zabbix order: context macro at host -> templates -> global, then the plain
    macro at host -> templates -> global. Any level that could not be read makes the answer unknown."""
    name, ctx = _split(macro)
    if name is None:
        return None
    host_lvl = dict((k, v["value"]) for k, v in host["macros"].items())
    tpl_known = host.get("ancestry") is not None and snap.get("templates") is not None
    tpl_lvls = [snap["templates"][t]["macros"] for t in host["ancestry"]] if tpl_known else []
    glob = snap.get("global_macros")
    for lvl in [host_lvl] + tpl_lvls + ([glob] if glob is not None else []):
        if any(k.startswith("{$%s:regex:" % name) for k in lvl):
            return None                                           # regex contexts are not evaluated
    for cand in (['{$%s:"%s"}' % (name, ctx)] if ctx is not None else []) + ["{$%s}" % name]:
        if cand in host_lvl:
            return host_lvl[cand]
        if not tpl_known:
            return None
        vals = set(l[cand] for l in tpl_lvls if cand in l)
        if len(vals) > 1:
            return None                                           # ambiguous between templates
        if vals:
            return vals.pop()
        if glob is None:
            return None
        if cand in glob:
            return glob[cand]
    return None


def gates(snap, host, expression):
    """(open, [reasons]): every '{$M}=N' / '{$M}<>N' in the expression must resolve and hold."""
    reasons = []
    for macro, op, val in MACRO_CMP.findall(expression or ""):
        v = resolve_macro(snap, host, macro)
        if v is None:
            reasons.append("gate %s cannot be resolved" % macro)
            continue
        hold = (str(v).strip() == val) if op == "=" else (str(v).strip() != val)
        if not hold:
            reasons.append("gated off by %s=%s" % (macro, v))
    return not reasons, reasons


# ------------------------------------------------------------------------------------- expression semantics

def _fn(key):
    return r"\b(last|min|max|avg|count|find)\(/[^/()]+/%s(?:,[^)]*)?\)" % re.escape(key)


def tests_link_down(expr, keys):
    """True only if the expression compares the port's oper-status item with down(2) / not-up(1)."""
    for k in keys:
        if re.search(_fn(k) + r'\s*(=\s*"?2"?|<>\s*"?1"?|>=\s*"?2"?|>\s*"?1"?)(?![\d.])', expr or ""):
            return True
    return False


def tests_utilization(expr, keys):
    """True only if a traffic item of this port is compared with '>' against something (a threshold)."""
    for k in keys:
        if re.search(_fn(k) + r'[^()<>=]*>(?!=)', expr or "") or re.search(_fn(k) + r'[^()<>=]*>=', expr or ""):
            return True
    return False


def tests_icmp_down(expr, keys):
    for k in keys:
        if re.search(_fn(k) + r'\s*(=\s*0|<\s*1)(?![\d.])', expr or ""):
            return True
    return False


# ------------------------------------------------------------------------------- action condition evaluation

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


def event_tags(snap, host, trig):
    """Full event tag set, or None when template tags could not be read."""
    tags = list(trig["tags"]) + list(host["tags"]) + list(trig.get("item_tags", []))
    if host.get("ancestry") is None or snap.get("templates") is None:
        return None, tags
    for t in host["ancestry"]:
        tags += snap["templates"][t]["tags"]
    return tags, tags


def eval_condition(c, host, trig, snap=None):
    """True / False / None (cannot evaluate)."""
    snap = snap or {}
    ct, op = int(c["conditiontype"]), int(c.get("operator", 0))
    val = str(c.get("value", ""))
    if ct == 0:                                                       # host group (nested groups included)
        names = snap.get("hostgroups") or {}
        cname = names.get(val)
        if cname is None:
            return None
        hnames = [names.get(g) for g in host["groupids"]]
        if any(n is None for n in hnames):
            return None
        r = any(n == cname or n.startswith(cname + "/") for n in hnames)
        return r if op == 0 else (not r if op == 1 else None)
    if ct == 1:                                                       # host
        r = val == host["hostid"]
        return r if op == 0 else (not r if op == 1 else None)
    if ct == 2:                                                       # trigger
        r = val == trig["triggerid"]
        return r if op == 0 else (not r if op == 1 else None)
    if ct == 3:                                                       # event name
        name = trig.get("event_name") or trig["name"]
        if "{" in name:
            return None                                               # unexpanded macro in the event name
        return _match_text(op, name, val)
    if ct == 4:                                                       # severity
        s, v = trig["priority"], int(val or 0)
        return {0: s == v, 1: s != v, 5: s >= v, 6: s <= v}.get(op)
    if ct == 13:                                                      # template (inheritance included)
        anc = host.get("ancestry")
        if anc is None:
            return None
        r = val in anc
        return r if op == 0 else (not r if op == 1 else None)
    if ct == 16:                                                      # problem is suppressed
        if host.get("maintenance"):
            return None
        return {11: True, 10: False}.get(op)
    if ct in (25, 26):                                                # event tag name / tag value
        full, partial = event_tags(snap, host, trig)
        tags = full if full is not None else partial
        if ct == 25:
            names = [t for t, _ in tags]
            r = {0: val in names, 1: val not in names,
                 2: any(val.lower() in n.lower() for n in names),
                 3: not any(val.lower() in n.lower() for n in names)}.get(op)
        else:
            name = str(c.get("value2", ""))
            vals = [v for t, v in tags if t == name]
            if any("{" in v for v in vals):
                return None
            res = [_match_text(op, v, val) for v in vals]
            r = {0: any(res), 2: any(res), 1: all(res), 3: all(res)}.get(op) if vals else \
                {0: False, 2: False, 1: True, 3: True}.get(op)
        if r is None:
            return None
        if full is None and (r is True and op in (1, 3) or r is False and op in (0, 2)):
            return None                                               # unknown template tags could flip it
        return r
    return None                                                       # time period, maintenance, service, ...


def eval_filter(flt, host, trig, snap=None):
    conds = (flt or {}).get("conditions") or []
    if not conds:
        return True
    res = dict((c.get("formulaid", str(i)), eval_condition(c, host, trig, snap)) for i, c in enumerate(conds))
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
        groups.setdefault(int(c["conditiontype"]), []).append(eval_condition(c, host, trig, snap))
    return _tri_and([_tri_or(v) for v in groups.values()])


# --------------------------------------------------------------------------------- recipients / operations

def _eligible(snap, op, host, trig):
    """(eligible recipient count, [reasons]) for ONE message operation."""
    mt = str((op.get("opmessage") or {}).get("mediatypeid", "0"))
    mts = snap["mediatypes"]
    if mt != "0" and not mts.get(mt, {}).get("enabled"):
        return 0, ["media type %s disabled or not readable" % mts.get(mt, {}).get("name", mt)]
    if snap["users"] is None or snap["usergroups"] is None:
        return 0, ["recipients not readable with this token"]
    groups = set(g["usrgrpid"] for g in op.get("opmessage_grp", []))
    users = set(u["userid"] for u in op.get("opmessage_usr", []))
    n, why = 0, set()
    for u in snap["users"]:
        if u["userid"] not in users and not groups.intersection(u["groups"]):
            continue
        ugs = [snap["usergroups"].get(g) for g in u["groups"]]
        if any(g is None for g in ugs):
            why.add("a user group of %s is not readable" % u["username"])
            continue
        if any(not g["enabled"] for g in ugs):
            why.add("%s is in a disabled user group" % u["username"])
            continue
        perms = {}
        for g in ugs:
            for hg, perm in g.get("rights", {}).items():
                perms.setdefault(hg, []).append(perm)
        rights = dict((hg, 0 if 0 in p else max(p)) for hg, p in perms.items())   # deny always wins
        if any(rights.get(g) == 0 for g in host["groupids"]) or not any(rights.get(g, 0) >= 2 for g in host["groupids"]):
            why.add("%s has no read permission on the host" % u["username"])
            continue
        ok = False
        for m in u["medias"]:
            if mt != "0" and m["mediatypeid"] != mt:
                continue
            if not m["active"] or not mts.get(m["mediatypeid"], {}).get("enabled"):
                why.add("%s: media disabled" % u["username"])
                continue
            if not (m["severity"] >> trig["priority"]) & 1:
                why.add("%s: media excludes severity %s" % (u["username"], SEV_NAMES[trig["priority"]]))
                continue
            if (m.get("period") or ALWAYS).replace(" ", "").rstrip(";") != ALWAYS:
                why.add("%s: media active only %s" % (u["username"], m.get("period")))
                continue
            ok = True
            break
        if ok:
            n += 1
        elif not any(x.startswith(u["username"]) for x in why):
            why.add("%s: no matching media" % u["username"])
    return n, sorted(why)


def notification(snap, host, trig):
    """('READY'|'PARTIAL'|'NONE', [details], actionid or None). READY = problem AND recovery recipients proven."""
    best, details = "NONE", []
    for a in snap["actions"]:
        if str(a.get("status", "0")) != "0":
            continue
        m = eval_filter(a.get("filter"), host, trig, snap)
        if m is False:
            continue
        ops = [o for o in a.get("operations", []) if str(o.get("operationtype")) == "0"]
        if not ops:
            continue
        immediate = [o for o in ops if str(o.get("esc_step_from", "1")) in ("1", "0", "")]
        pn, why = 0, []
        for o in immediate:
            c, w = _eligible(snap, o, host, trig)
            pn += c
            why += w
        rn = 0
        recs = a.get("recovery_operations", []) or []
        for o in recs:
            t = str(o.get("operationtype"))
            if t == "11":
                rn += pn                                          # notify all involved = whoever got the problem
            elif t == "0":
                c, w = _eligible(snap, o, host, trig)
                rn += c
                why += ["recovery: " + x for x in w]
        if m is True and pn and rn:
            return "READY", ["action '%s': %d problem / %d recovery recipient(s) proven" % (a["name"], pn, rn)], a["actionid"]
        gaps = []
        if m is None:
            gaps.append("conditions cannot be fully evaluated")
        if not immediate:
            gaps.append("no immediate (step 1) problem operation")
        elif not pn:
            gaps.append("no eligible problem recipient")
        if not recs:
            gaps.append("no recovery operation")
        elif not rn:
            gaps.append("no eligible recovery recipient")
        details.append("action '%s': %s%s" % (a["name"], "; ".join(gaps) or "unproven",
                                              (" (%s)" % "; ".join(sorted(set(why))[:3])) if why else ""))
        best = "PARTIAL"
    return best, details or ["no enabled trigger action matches"], None


def delivered(snap, trig, actionid):
    """True / False / None (history not readable): SENT problem AND recovery message from this action."""
    if snap.get("events") is None:
        return None
    kinds = snap["events"].get(trig["triggerid"], {}).get(actionid, set())
    return "problem" in kinds and "recovery" in kinds


# ------------------------------------------------------------------------------------- classification

def _trigger_ok(snap, h, t):
    if not t["enabled"]:
        return False, ["disabled"]
    return gates(snap, h, t.get("expression", ""))


def port_coverage(snap, row):
    """(class, [reasons], evidence dict)."""
    h, p = row.h, row.p
    reasons = list(row.blockers) + list(getattr(row, "issues", [])) + list(row.review)
    if any(k in r for r in reasons for k in ("ambiguous", "no longer discovered", "not found", "index changed",
                                             "pairing", "link_id", "peer")):
        return REVIEW, reasons, {}
    if h is None or p is None:
        return REVIEW, reasons or ["not discoverable"], {}
    if not h["enabled"]:
        return STALE, ["host disabled"], {}
    if h["snmp"]["available"] == "2":
        return STALE, ["SNMP interface unavailable: %s" % (h["snmp"]["error"] or "no error text")], {}
    if p["fresh"] != "fresh":
        return STALE, ["status item %s" % p["fresh"]], {}
    status_keys = [x["key"] for k, x in p["items"].items() if k == "status"] + \
        [k for k in p["own"] if k.startswith("netops.if.oper[")]
    traffic_keys = [x["key"] for k, x in p["items"].items() if k in ("in", "out")] + \
        [k for k in p["own"] if k.startswith(("netops.if.in[", "netops.if.out["))]
    link, util, unproven, off = [], [], [], []      # unproven = might work but cannot be shown; off = cannot fire
    for t in h["triggers"]:
        if row.port not in t["ports"]:
            continue
        is_link = tests_link_down(t.get("expression", ""), status_keys)
        is_util = tests_utilization(t.get("expression", ""), traffic_keys)
        if not t["enabled"]:
            if is_link or is_util:
                off.append("'%s' is disabled" % t["name"])
            continue
        if not (is_link or is_util):
            unproven.append("'%s': expression does not prove a link-down or utilization test" % t["name"])
            continue
        ok, why = _trigger_ok(snap, h, t)
        if not ok:
            (unproven if any("cannot be resolved" in w for w in why) else off).append(
                "'%s': %s" % (t["name"], "; ".join(why)))
            continue
        (link if is_link else util).append(t)
    ev = {"link": [t["name"] for t in link], "util": [t["name"] for t in util], "managed": bool(p["own"]),
          "unproven": unproven, "off": off}
    if any(t["unknown"] for t in link + util):
        return STALE, ["trigger in UNKNOWN state"], ev
    if not link:
        why = ["no enabled, ungated trigger whose expression tests link-down on this port"] + unproven[:3] + off[:3]
        if row.status == "APPROVED" and not p["own"]:
            why.append("approved but not yet deployed")
        return (PART if unproven else NOTC), why + reasons, ev
    gaps = []
    verdicts = [(t,) + notification(snap, h, t) for t in link]
    ready = [v for v in verdicts if v[1] == "READY"]
    ev["notify"] = (ready or verdicts)[0][2]
    if not ready:
        gaps.append("link alert has no proven Problem+Recovery notification path: %s" % "; ".join(verdicts[0][2]))
    if not util:
        gaps.append("no proven utilization alert (agreed policy 70%/65%)")
    else:
        uv = [notification(snap, h, t) for t in util]
        if not any(v[0] == "READY" for v in uv):
            gaps.append("utilization alert has no proven notification path")
    if h.get("maintenance"):
        gaps.append("host is in maintenance (notifications may be suppressed)")
    if row.status == "APPROVED" and not p["own"]:
        gaps.append("approved but not yet deployed by this project")
    if gaps or reasons:
        return PART, gaps + reasons + unproven[:2], ev
    tested = [delivered(snap, v[0], v[3]) for v in ready]
    if any(x is True for x in tested):
        ev["delivery"] = ["SENT problem + recovery in the last %d days" % snap.get("delivery_days", 90)]
        return PROT, [], ev
    ev["delivery"] = ["no SENT problem+recovery pair in the last %d days" % snap.get("delivery_days", 90)
                      if any(x is False for x in tested) else "alert history not readable"]
    return CONFIG, ev["delivery"], ev


HEALTH_ALERTS = {"ospf": ("ospf_neighbor", "ospf_blind", "ospf_expected"),
                 "bgp": ("bgp_peer", "bgp_blind", "bgp_expected")}


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
    gaps = []
    keys = [i["key"] for i in h["health_items"].get("icmp", [])]
    icmp = [t for t in h["triggers"] if tests_icmp_down(t.get("expression", ""), keys) and _trigger_ok(snap, h, t)[0]]
    if not icmp:
        gaps.append("no enabled, ungated reachability (ICMP) trigger")
    elif not any(notification(snap, h, t)[0] == "READY" for t in icmp):
        gaps.append("reachability alert has no proven notification path")
    for feat in ("ospf", "bgp"):
        if feat not in (getattr(dev, "features", None) or []):
            continue
        tr = dict((a, [t for t in h["triggers"] if dict(t["tags"]).get("netops_alert") == a and _trigger_ok(snap, h, t)[0]])
                  for a in HEALTH_ALERTS[feat])
        if not tr[HEALTH_ALERTS[feat][0]] and not tr[HEALTH_ALERTS[feat][1]]:
            gaps.append("%s: Network Health alerts not deployed on this host" % feat.upper())
            continue
        if not tr[HEALTH_ALERTS[feat][1]]:
            gaps.append("%s: no SNMP-blind (data lost) alert - a silent router stays green" % feat.upper())
        if not tr[HEALTH_ALERTS[feat][2]]:
            gaps.append("%s: no expected-neighbor list - a neighbor that never reached Full/Established is not detected"
                        % feat.upper())
        anyt = [t for v in tr.values() for t in v]
        if anyt and not any(notification(snap, h, t)[0] == "READY" for t in anyt):
            gaps.append("%s alerts have no proven notification path" % feat.upper())
    if gaps:
        return PART, gaps
    return CONFIG, ["delivery of device-level alerts not evaluated (no fault history required)"]


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
    if snap.get("events") is None:
        findings.append("alert history not readable: nothing can be classified PROTECTED (DELIVERY TESTED)")
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
         "Coverage is reported only for this scope. Anything listed under *Limits* could not be discovered.",
         "CONFIG VERIFIED means the configuration proves detection and notification; only DELIVERY TESTED also has",
         "Zabbix's own record of a sent Problem and Recovery message. Neither is a substitute for a fault test.", "",
         "| Class | Ports |", "|---|---|"]
    L += ["| %s | %d |" % (k, c[k]) for k in CLASSES]
    L += ["", "## Ports", "", "| Class | Host | Port | Description | Role | Decision | Reasons / evidence |",
          "|---|---|---|---|---|---|---|"]
    order = dict((k, i) for i, k in enumerate((REVIEW, NOTC, STALE, PART, CONFIG, PROT)))
    for r, cls, why, ev in sorted(result["ports"], key=lambda x: (order[x[1]], x[0].host, x[0].port)):
        evtxt = "; ".join(why) if why else "link: %s; util: %s; %s; %s" % (
            ", ".join(ev.get("link", [])) or "-", ", ".join(ev.get("util", [])) or "-",
            "; ".join(ev.get("notify", [])), "; ".join(ev.get("delivery", [])))
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
    L += ["", "## ISP / P2P endpoint relationships", ""]
    seen, n0 = set(), len(L)
    for r in model["ports"]:
        if r.status == "APPROVED" and r.pair and tuple(sorted((r.id, r.pair))) not in seen:
            seen.add(tuple(sorted((r.id, r.pair))))
            L.append("- PAIRED (%s): %s <-> %s" % (r.pair_source or "operator", r.id, r.pair))
    for r in model["ports"]:
        if r.candidate and r.pair_hints and not r.pair and tuple(sorted((r.id, r.pair_hints[0]))) not in seen:
            seen.add(tuple(sorted((r.id, r.pair_hints[0]))))
            L.append("- SUGGESTED (description cross-reference only, NOT verified): %s <-> %s" % (r.id, r.pair_hints[0]))
        for x in list(getattr(r, "issues", [])) + list(r.review):
            if "pair" in x or "peer" in x or "link_id" in x:
                L.append("- REVIEW: %s: %s" % (r.id, x))
    if len(L) == n0:
        L.append("- none")
    L += ["", "## Findings, blind spots and limits", ""]
    L += ["- %s" % f for f in result["findings"]] or ["- none"]
    return "\n".join(L) + "\n"


def _md(s):
    return str(s).replace("|", "\\|").replace("\n", " ")
