"""Load and validate an inventory file (the only thing an engineer edits).

Validation is strict (unknown keys, duplicate YAML keys, dangling references, cycles) and *semantic*: it refuses
inventories that could silently report unqualified availability (see HLD section 1).
"""
import datetime
import re

import yaml

from ._compat import ConfigError, UniqueKeyLoader

SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
DURATION = re.compile(r"^\d+[smh]$")
SEVERITIES = ("information", "warning", "average", "high", "disaster")
TOP_KEYS = {"schema", "environment", "tag_semantics", "settings", "components", "paths", "connectivity", "business",
            "probes", "slas", "planned_downtime", "provider_sla"}
SCHEMA = "zabbix-sla-inventory-v1"


class Problem(object):
    def __init__(self, where, message, level="ERROR"):
        self.where, self.message, self.level = where, message, level

    def __str__(self):
        return "%s: %s (%s)" % (self.level, self.message, self.where)


class Inventory(object):
    def __init__(self, data, problems):
        self.data = data
        self.problems = problems

    @property
    def errors(self):
        return [p for p in self.problems if p.level == "ERROR"]

    @property
    def infos(self):
        return [p for p in self.problems if p.level != "ERROR"]

    def section(self, name):
        return self.data.get(name) or {}


def load_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return yaml.load(fh, Loader=UniqueKeyLoader) or {}
        except yaml.YAMLError as exc:
            raise ConfigError("YAML error in %s: %s" % (path, exc))


def _keys(obj, allowed, where, problems):
    for k in obj:
        if k not in allowed:
            problems.append(Problem(where, "unknown key '%s' (allowed: %s)" % (k, ", ".join(sorted(allowed)))))


def _map(data, name, problems):
    v = data.get(name)
    if v is None:
        return {}
    if not isinstance(v, dict):
        problems.append(Problem(name, "must be a mapping of id -> definition"))
        return {}
    return v


def parse_member(m):
    """connectivity member: 'ref' or {ref, verified, fallback_via_transit, evidence} -> dict (or None)."""
    if isinstance(m, str):
        return {"ref": m, "verified": True, "fallback_via_transit": False, "evidence": "", "_extra": set()}
    if isinstance(m, dict) and isinstance(m.get("ref"), str):
        return {"ref": m["ref"], "verified": m.get("verified", True), "fallback_via_transit": bool(m.get("fallback_via_transit", False)),
                "evidence": str(m.get("evidence") or ""), "_extra": set(m) - {"ref", "verified", "fallback_via_transit", "evidence"}}
    return None


def member_included(m):
    """A member is part of the compiled tree unless it is an unverified transit fallback."""
    if m["fallback_via_transit"]:
        return m["verified"] is True and bool(m["evidence"])
    return m["verified"] is not False


def validate(data, now=None):
    """Returns Inventory. `now` (aware datetime) enables the planned-downtime retroactivity rule."""
    problems = []
    if not isinstance(data, dict):
        raise ConfigError("inventory must be a mapping")
    _keys(data, TOP_KEYS, "top level", problems)
    if data.get("schema") != SCHEMA:
        problems.append(Problem("schema", "must be '%s'" % SCHEMA))
    env = data.get("environment")
    if not isinstance(env, str) or not re.match(r"^[a-z][a-z0-9_-]{1,31}$", env or ""):
        problems.append(Problem("environment", "required (lab | production | ...)"))
    if data.get("tag_semantics", "unknown") not in ("unknown", "and", "or"):
        problems.append(Problem("tag_semantics", "must be unknown, and or or"))
    comps, paths, conns = _map(data, "components", problems), _map(data, "paths", problems), _map(data, "connectivity", problems)
    biz, probes, slas = _map(data, "business", problems), _map(data, "probes", problems), _map(data, "slas", problems)

    seen = {}
    for sect, objs in (("components", comps), ("paths", paths), ("connectivity", conns), ("business", biz), ("probes", probes)):
        for i in objs:
            if not isinstance(i, str) or not SLUG.match(i):
                problems.append(Problem("%s.%s" % (sect, i), "id must match %s" % SLUG.pattern))
            if i in seen:
                problems.append(Problem("%s.%s" % (sect, i), "id already used in %s" % seen[i]))
            seen[i] = sect
    for k in slas:
        if not SLUG.match(str(k)):
            problems.append(Problem("slas.%s" % k, "class id must match %s" % SLUG.pattern))

    links = {}
    for cid, c in comps.items():
        w = "components.%s" % cid
        if not isinstance(c, dict):
            problems.append(Problem(w, "must be a mapping"))
            continue
        _keys(c, {"kind", "link_id", "description", "title", "site", "provider", "signal_coverage"}, w, problems)
        if c.get("kind") != "link":
            problems.append(Problem(w, "kind must be 'link' (device components are Phase 3)"))
        lid = c.get("link_id")
        if not isinstance(lid, str) or not SLUG.match(lid):
            problems.append(Problem(w, "link_id (the NETOPS event tag value) is required"))
        elif lid in links:
            problems.append(Problem(w, "link_id '%s' already used by %s" % (lid, links[lid])))
        else:
            links[lid] = cid
        if c.get("signal_coverage", "both") not in ("both", "partial"):
            problems.append(Problem(w, "signal_coverage must be both or partial ('none' means no signal: such a component cannot be modelled)"))

    for pid, p in probes.items():
        w = "probes.%s" % pid
        if not isinstance(p, dict):
            problems.append(Problem(w, "must be a mapping"))
            continue
        _keys(p, {"status", "runner", "destinations", "quorum", "verification", "path", "interval", "stale_after", "severity", "title", "description", "evidence"}, w, problems)
        if p.get("status", "proposed") not in ("proposed", "active"):
            problems.append(Problem(w, "status must be proposed or active"))
        if not p.get("runner"):
            problems.append(Problem(w, "runner (the Zabbix host that executes the checks) is required"))
        dests = p.get("destinations")
        if not isinstance(dests, list) or len(dests) < 2:
            problems.append(Problem(w, "at least 2 destinations are required (one far end must not look like a path outage)"))
            dests = dests if isinstance(dests, list) else []
        names = set()
        for d in dests:
            dw = "%s.destinations" % w
            if not isinstance(d, dict) or not d.get("name") or not d.get("address"):
                problems.append(Problem(dw, "each destination needs name and address"))
                continue
            _keys(d, {"name", "address", "check", "port", "note"}, dw, problems)
            if d["name"] in names:
                problems.append(Problem(dw, "duplicate destination name '%s'" % d["name"]))
            names.add(d["name"])
            chk = d.get("check", "icmp")
            if chk not in ("icmp", "tcp"):
                problems.append(Problem(dw, "check must be icmp or tcp"))
            if chk == "tcp" and not (isinstance(d.get("port"), int) and 1 <= d["port"] <= 65535):
                problems.append(Problem(dw, "tcp destination needs a port 1-65535"))
            if re.search(r"[\s,\[\]\"]", str(d["address"])):
                problems.append(Problem(dw, "address contains characters that are unsafe in an item key"))
        q = p.get("quorum")
        if not isinstance(q, int) or isinstance(q, bool) or not (1 <= q <= max(len(dests), 1)):
            problems.append(Problem(w, "quorum K must be an integer with 1 <= K <= number of destinations (explicit, no default)"))
        ver = p.get("verification")
        if ver not in ("pinned_destination", "source_pbr", "traceroute", "none"):
            problems.append(Problem(w, "verification (routing proof) must be pinned_destination, source_pbr, traceroute or none"))
        if p.get("path") is not None:
            if p["path"] not in paths:
                problems.append(Problem(w, "path '%s' is not a defined path" % p["path"]))
            if ver == "none":
                problems.append(Problem(w, "a probe with verification 'none' is reachability-only and must not be tied to a path"))
        for k, dflt in (("interval", "30s"), ("stale_after", "5m")):
            if not DURATION.match(str(p.get(k, dflt))):
                problems.append(Problem(w, "%s must look like 30s, 5m or 1h" % k))
        if p.get("severity", "disaster") not in SEVERITIES:
            problems.append(Problem(w, "severity must be one of %s" % ", ".join(SEVERITIES)))

    for pid, p in paths.items():
        w = "paths.%s" % pid
        if not isinstance(p, dict):
            problems.append(Problem(w, "must be a mapping"))
            continue
        _keys(p, {"components", "title", "description", "site", "provider", "kind"}, w, problems)
        refs = p.get("components")
        if not isinstance(refs, list) or not refs:
            problems.append(Problem(w, "components must be a non-empty list (series: any one down = path down)"))
            continue
        if len(set(refs)) != len(refs):
            problems.append(Problem(w, "duplicate component reference"))
        for r in refs:
            if r not in comps:
                problems.append(Problem(w, "unknown component '%s'" % r))

    for cid, c in conns.items():
        w = "connectivity.%s" % cid
        if not isinstance(c, dict):
            problems.append(Problem(w, "must be a mapping"))
            continue
        _keys(c, {"redundancy", "members", "title", "description", "site", "kind"}, w, problems)
        if c.get("redundancy") not in ("parallel", "series"):
            problems.append(Problem(w, "redundancy must be parallel or series"))
        mem = c.get("members")
        if not isinstance(mem, list) or not mem:
            problems.append(Problem(w, "members must be a non-empty list"))
            continue
        for raw in mem:
            m = parse_member(raw)
            if m is None:
                problems.append(Problem(w, "invalid member %r" % (raw,)))
                continue
            if m["_extra"]:
                problems.append(Problem(w, "unknown member keys: %s" % ", ".join(sorted(m["_extra"]))))
            if m["ref"] not in paths and m["ref"] not in conns:
                problems.append(Problem(w, "member '%s' is not a path or connectivity" % m["ref"]))
            if not isinstance(m["verified"], bool):
                problems.append(Problem(w, "member verified must be true or false"))
            if not member_included(m):
                problems.append(Problem(w, "member '%s' is excluded from the model: an unverified/unevidenced fallback is not assumed" % m["ref"], "INFO"))

    for bid, b in biz.items():
        w = "business.%s" % bid
        if not isinstance(b, dict):
            problems.append(Problem(w, "must be a mapping"))
            continue
        _keys(b, {"tier", "requires", "redundancy", "sla_class", "site", "title", "description"}, w, problems)
        if b.get("tier") not in ("T2", "T3"):
            problems.append(Problem(w, "tier must be T2 (inferred) or T3 (verified end to end)"))
        req = b.get("requires")
        if not isinstance(req, list) or not req:
            problems.append(Problem(w, "requires must be a non-empty list"))
            req = []
        for r in req:
            if r not in paths and r not in conns and r not in probes and r not in biz:
                problems.append(Problem(w, "requires unknown id '%s'" % r))
        if b.get("redundancy", "series") not in ("series", "parallel"):
            problems.append(Problem(w, "redundancy must be series or parallel"))
        if b.get("sla_class") not in slas:
            problems.append(Problem(w, "sla_class '%s' is not defined under slas" % b.get("sla_class")))
        if b.get("tier") == "T3":
            pr = [r for r in req if r in probes]
            if not pr:
                problems.append(Problem(w, "a T3 (verified) service must require at least one probe"))
            for r in pr:
                pr_ = probes.get(r)
                if isinstance(pr_, dict) and pr_.get("verification") == "none":
                    lvl = "ERROR" if pr_.get("status") == "active" else "INFO"
                    problems.append(Problem(w, "probe '%s' has no routing proof (verification: none) and cannot back a verified service%s" % (r, "" if lvl == "ERROR" else " - it stays proposed until a proof exists"), lvl))

    for k, s in slas.items():
        w = "slas.%s" % k
        if not isinstance(s, dict):
            problems.append(Problem(w, "must be a mapping"))
            continue
        _keys(s, {"title", "slo", "approved", "period", "schedule", "effective_date", "timezone", "description", "source"}, w, problems)
        slo = s.get("slo")
        if isinstance(slo, bool) or not isinstance(slo, (int, float)) or not (0 < slo <= 100):
            problems.append(Problem(w, "slo must be a number > 0 and <= 100"))
        if not isinstance(s.get("approved"), bool):
            problems.append(Problem(w, "approved must be true or false (an unapproved SLO cannot be applied to production)"))
        if s.get("period", "monthly") != "monthly":
            problems.append(Problem(w, "only period: monthly is supported in Phase 1"))
        if s.get("schedule", "24x7") != "24x7":
            problems.append(Problem(w, "only schedule: 24x7 is supported in Phase 1"))
        try:
            datetime.date.fromisoformat(str(s.get("effective_date")))
        except ValueError:
            problems.append(Problem(w, "effective_date must be YYYY-MM-DD (fixed, never 'today')"))
        try:
            import zoneinfo
            zoneinfo.ZoneInfo(s.get("timezone", "Asia/Riyadh"))
        except Exception:      # noqa: BLE001
            problems.append(Problem(w, "unknown timezone"))

    cap = (data.get("settings") or {}).get("planned_downtime_cap_hours", 8)
    pds = data.get("planned_downtime") or []
    for i, pd in enumerate(pds):
        w = "planned_downtime[%d]" % i
        if not isinstance(pd, dict):
            problems.append(Problem(w, "must be a mapping"))
            continue
        _keys(pd, {"id", "slas", "start", "end", "reason", "ticket", "approver"}, w, problems)
        for k in ("id", "reason", "ticket", "approver"):
            if not pd.get(k):
                problems.append(Problem(w, "%s is required (planned downtime is an approved, ticketed exception)" % k))
        for c in pd.get("slas") or []:
            if c not in slas:
                problems.append(Problem(w, "unknown sla class '%s'" % c))
        if not pd.get("slas"):
            problems.append(Problem(w, "slas must list at least one class"))
        try:
            a, b = _dt(pd.get("start")), _dt(pd.get("end"))
            if b <= a:
                problems.append(Problem(w, "end must be after start"))
            elif (b - a).total_seconds() > cap * 3600:
                problems.append(Problem(w, "window longer than planned_downtime_cap_hours (%s h)" % cap))
            elif now is not None and b < now and (b.year, b.month) < (now.year, now.month):
                problems.append(Problem(w, "this window ended in a closed month: it is accepted only if it is already applied in Zabbix (adding it now is refused by the planner - closed periods are immutable)", "INFO"))
        except (ValueError, TypeError):
            problems.append(Problem(w, "start/end must be ISO-8601 timestamps with an offset"))
    ids = [pd.get("id") for pd in pds if isinstance(pd, dict)]
    if len(ids) != len(set(ids)):
        problems.append(Problem("planned_downtime", "duplicate id"))

    graph = {}
    for cid, c in conns.items():
        if isinstance(c, dict):
            graph[cid] = [m["ref"] for m in (parse_member(x) for x in (c.get("members") or [])) if m]
    for bid, b in biz.items():
        if isinstance(b, dict):
            graph[bid] = [r for r in (b.get("requires") or []) if r in biz or r in conns]
    state = {}

    def visit(n, stack):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            problems.append(Problem(n, "reference cycle: %s" % " -> ".join(stack + [n])))
            return
        state[n] = 1
        for m in graph.get(n, []):
            if m in graph:
                visit(m, stack + [n])
        state[n] = 2
    for n in list(graph):
        visit(n, [])

    if data.get("tag_semantics", "unknown") != "and" and comps:
        problems.append(Problem("tag_semantics", "components need 'link_id AND netops_alert=link_down'; this is only allowed once the live acceptance test "
                                "(scripts/accept_tag_semantics.py) proved AND semantics and the inventory says tag_semantics: and (currently %r)" % data.get("tag_semantics", "unknown")))
    return Inventory(data, problems)


def _dt(v):
    d = v if isinstance(v, datetime.datetime) else datetime.datetime.fromisoformat(str(v))
    if d.tzinfo is None:
        raise ValueError("offset required")
    return d


def load(path, now=None):
    return validate(load_file(path), now)
