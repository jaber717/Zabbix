"""Compile a validated inventory into the exact Zabbix objects that must exist (pure functions)."""
import datetime
import zoneinfo

from . import tags as T
from .inventory import parse_member, member_included

ALGO_SERIES = 2        # most critical of child services
ALGO_PARALLEL = 1      # most critical if ALL children have problems
SEVERITY_NUM = {"information": 1, "warning": 2, "average": 3, "high": 4, "disaster": 5}


class Desired(object):
    def __init__(self):
        self.services = {}       # sla_id -> dict
        self.slas = {}           # class -> dict
        self.probes = {}         # probe id -> dict (active only)
        self.deferred = []       # human-readable reasons something was not compiled
        self.notes = []          # modelling notes (excluded fallbacks, partial coverage)

    def children_of(self, sid):
        return self.services[sid]["children"]


def _title(entity_id, entity):
    return entity.get("title") or entity.get("description") or entity_id


def _svc(sid, title, layer, algorithm, children=(), problem_tags=(), site=None, provider=None, tier=None, sla_class=None, description=""):
    return {
        "sla_id": sid, "name": T.NAME_PREFIX + title, "algorithm": algorithm, "description": description,
        "tags": T.owned_tags(sid, layer=layer, site=site, provider=provider, tier=tier, sla_class=sla_class),
        "problem_tags": sorted(set(problem_tags)), "children": list(children), "layer": layer,
    }


def compile_inventory(inv):
    """Inventory -> Desired. Probes with status 'proposed' (and everything that depends on them) are deferred, not applied."""
    d, data = Desired(), inv.data
    comps, paths, conns = inv.section("components"), inv.section("paths"), inv.section("connectivity")
    biz, probes, slas = inv.section("business"), inv.section("probes"), inv.section("slas")
    semantics = data.get("tag_semantics", "unknown")

    for cid, c in comps.items():
        if semantics != "and":
            continue                                  # validation already reports it; never emit a half-correct condition
        tags_ = [(T.NETOPS_LINK_ID, T.OP_EQUALS, c["link_id"]), (T.NETOPS_ALERT, T.OP_EQUALS, "link_down")]
        d.services[cid] = _svc(cid, "Link " + c["link_id"], "component", ALGO_SERIES, problem_tags=tags_, site=c.get("site"), provider=c.get("provider"),
                               tier="T1", description=c.get("description", ""))
        d.services[cid]["meta"] = {"expected_ends": 1 if c.get("signal_coverage", "both") == "partial" else 2}
        if c.get("signal_coverage", "both") == "partial":
            d.notes.append("%s: signal_coverage partial - one end of the link is not monitored; a far-end failure that keeps this end up/up is invisible at T1" % cid)

    active, deferred_probes = {}, set()
    for pid, p in probes.items():
        if p.get("status", "proposed") != "active":
            deferred_probes.add(pid)
            d.deferred.append("probe %s: status '%s' (not applied until runner/destinations/routing proof are confirmed)" % (pid, p.get("status", "proposed")))
            continue
        active[pid] = p
        d.probes[pid] = dict(p, id=pid)
        d.services["probe." + pid] = _svc("probe." + pid, "Probe " + _title(pid, p), "probe", ALGO_SERIES,
                                          problem_tags=[(T.PROBE_DOWN, T.OP_EQUALS, pid)], tier="T3", description=p.get("description", ""))
        d.services["quality." + pid] = _svc("quality." + pid, "Data freshness " + _title(pid, p), "quality", ALGO_SERIES,
                                            problem_tags=[(T.PROBE_STALE, T.OP_EQUALS, pid)], tier="T3")

    for pid, p in paths.items():
        kids = [r for r in p["components"] if r in d.services]
        if len(kids) != len(p["components"]):
            d.deferred.append("path %s: components not compiled (%s)" % (pid, "tag semantics unproven" if semantics != "and" else "missing"))
            continue
        d.services[pid] = _svc(pid, _title(pid, p), "path", ALGO_SERIES, kids, site=p.get("site"), provider=p.get("provider"), tier="T2",
                               description=p.get("description", ""))

    def compile_conn(cid, stack=()):
        if cid in d.services:
            return True
        c = conns[cid]
        kids = []
        for raw in c["members"]:
            m = parse_member(raw)
            if not member_included(m):
                d.notes.append("%s: member %s excluded - unverified transit fallback is not modelled" % (cid, m["ref"]))
                continue
            ref = m["ref"]
            if ref in conns and ref not in d.services:
                compile_conn(ref)
            if ref in d.services:
                kids.append(ref)
        if not kids:
            d.deferred.append("connectivity %s: no compilable member" % cid)
            return False
        algo = ALGO_PARALLEL if (c["redundancy"] == "parallel" and len(kids) > 1) else ALGO_SERIES
        if c["redundancy"] == "parallel" and len(kids) == 1:
            d.notes.append("%s: declared parallel but only one member is modelled - NO redundancy is represented" % cid)
        d.services[cid] = _svc(cid, _title(cid, c), "connectivity", algo, kids, site=c.get("site"), tier="T2", description=c.get("description", ""))
        return True
    for cid in conns:
        compile_conn(cid)

    pending, progress = dict(biz), True
    while pending and progress:
        progress = False
        for bid in list(pending):
            b = pending[bid]
            refs = list(b["requires"])
            if any(r in probes and r in deferred_probes for r in refs):
                d.deferred.append("business %s: requires probe(s) still proposed" % bid)
                del pending[bid]
                progress = True
                continue
            need = [("probe." + r) if r in probes else r for r in refs]
            if all(n in d.services for n in need):
                algo = ALGO_PARALLEL if b.get("redundancy", "series") == "parallel" and len(need) > 1 else ALGO_SERIES
                d.services[bid] = _svc(bid, _title(bid, b), "business", algo, need, site=b.get("site"), tier=b["tier"], sla_class=b["sla_class"],
                                       description=b.get("description", ""))
                del pending[bid]
                progress = True
    for bid in pending:
        d.deferred.append("business %s: dependencies not compiled" % bid)

    if d.services:
        roots = [s for s, v in d.services.items() if v["layer"] == "business"]
        if roots:
            d.services["root"] = _svc("root", "Service assurance", "root", ALGO_SERIES, roots, description="Root of the business services (browse here)")
        qual = [s for s in d.services if s.startswith("quality.")]
        if qual:
            d.services["quality.root"] = _svc("quality.root", "Monitoring data quality", "quality", ALGO_SERIES, qual,
                                              description="Probe data freshness; never part of an availability SLA")

    for cls, s in slas.items():
        tz = s.get("timezone", "Asia/Riyadh")
        eff = datetime.datetime.combine(datetime.date.fromisoformat(str(s["effective_date"])), datetime.time(0, 0), tzinfo=zoneinfo.ZoneInfo(tz))
        pds = []
        for pd in data.get("planned_downtime") or []:
            if cls in pd["slas"]:
                a = _aware(pd["start"])
                b = _aware(pd["end"])
                pds.append({"name": "PD %s %s" % (pd["id"], pd["ticket"]), "period_from": int(a.timestamp()), "period_to": int(b.timestamp())})
        d.slas[cls] = {
            "class": cls, "name": T.NAME_PREFIX + _title(cls, s), "slo": float(s["slo"]), "period": 2, "timezone": tz, "status": 1,
            "effective_date": int(eff.timestamp()), "approved": s["approved"],
            "description": "%s sla_id=%s %s" % (T.SLA_DESC_MARKER, cls, s.get("description", "")),
            "service_tags": [{"tag": "sla_class", "operator": T.OP_EQUALS, "value": cls}],
            "schedule": [], "excluded_downtimes": sorted(pds, key=lambda x: x["period_from"]),
        }
    if any(s["layer"] == "quality" for s in d.services.values()) and d.slas:
        # Not a business commitment: it measures how long each probe had no fresh data, so reports can qualify T3 figures.
        d.slas[FRESHNESS_CLASS] = {
            "class": FRESHNESS_CLASS, "name": T.NAME_PREFIX + "Monitoring data freshness (not an availability SLA)", "slo": 99.0, "period": 2,
            "timezone": min(d.slas.values(), key=lambda a: a["effective_date"])["timezone"], "status": 1, "approved": True,
            "effective_date": min(a["effective_date"] for a in d.slas.values()),
            "description": "%s sla_id=%s internal data-quality measure; downtime here means STALE PROBE DATA, not an outage" % (T.SLA_DESC_MARKER, FRESHNESS_CLASS),
            "service_tags": [{"tag": "layer", "operator": T.OP_EQUALS, "value": "quality"}], "schedule": [], "excluded_downtimes": [],
        }
    return d


FRESHNESS_CLASS = "data-freshness"


def _aware(v):
    d = v if isinstance(v, datetime.datetime) else datetime.datetime.fromisoformat(str(v))
    return d


def probe_objects(host, probe):
    """Items and triggers a probe needs on its runner host (pure data; see probes.py for the API calls)."""
    pid = probe["id"]
    interval = probe.get("interval", "30s")
    items = []
    names = []
    for dest in probe["destinations"]:
        if dest.get("check", "icmp") == "icmp":
            key = "icmpping[%s,3,200,,1000]" % dest["address"]
        else:
            key = "net.tcp.service[tcp,%s,%s]" % (dest["address"], dest["port"])
        names.append(key)
        items.append({"key": key, "name": "SLA probe %s -> %s" % (pid, dest["name"]), "type": 3, "value_type": 3, "delay": interval,
                      "tags": {T.MANAGED_KEY: T.MANAGED_VALUE, T.PROBE_DOWN: pid, "sla_dest": dest["name"]}})
    formula = "+".join("last(//%s)" % k for k in names)
    calc = {"key": "sla.probe.up[%s]" % pid, "name": "SLA probe %s destinations up (need %d of %d)" % (pid, probe["quorum"], len(names)), "type": 15,
            "value_type": 3, "delay": interval, "params": formula, "tags": {T.MANAGED_KEY: T.MANAGED_VALUE, T.PROBE_DOWN: pid}}
    sev = SEVERITY_NUM[probe.get("severity", "disaster")]
    down = {"description": T.TRIGGER_MARKER + "Probe %s: fewer than %d of %d destinations answer" % (pid, probe["quorum"], len(names)),
            "expression": "last(/%s/sla.probe.up[%s])<%d" % (host, pid, probe["quorum"]), "priority": sev,
            "tags": {T.MANAGED_KEY: T.MANAGED_VALUE, T.PROBE_DOWN: pid}}
    stale = {"description": T.TRIGGER_MARKER + "Probe %s: no fresh data for %s (SLI cannot be trusted)" % (pid, probe.get("stale_after", "5m")),
             "expression": "nodata(/%s/sla.probe.up[%s],%s)=1" % (host, pid, probe.get("stale_after", "5m")), "priority": 2,
             "tags": {T.MANAGED_KEY: T.MANAGED_VALUE, T.PROBE_STALE: pid}}
    return {"items": items + [calc], "triggers": [down, stale]}
