"""Line-based review session for ./onboard.sh (works over any SSH terminal; no curses, no extra packages).

Every command that changes a decision saves config/onboarding.<env>.yaml immediately. The inventories are
written only by `w`, after the generated files pass the projects' own strict validation.
"""
import re
import time

from . import coverage, onboarding as ob
from .config import SEVERITIES

HELP = """\
Ports view (default)                      Device view (h)            Ranges: 3   1,4,7-12   all  (= all listed rows)
  l [pending|approved|excluded|review|all] [text]   list rows (default: candidates)
  v N            details: evidence, triggers, freshness, pairing, notification path
  a N..          approve (refused while a blocker exists)      x N..  exclude / remove      u N..  undo decision
  r ROLE N..     role ISP|WAN|DCI|P2P      s SEV N..  severity warning|average|high|disaster      d N text  description
  p N M          pair two ports you confirm are connected     p N  accept the suggested peer
  p N -          confirm the port is single-ended (no monitored peer); releases any previous pairing
  h              switch ports <-> devices (Network Health)     f N +ospf -cpu ...  device features     pl N PLATFORM
  ev N ospf|bgp REFERENCE      record MIB evidence (e.g. "snmpwalk 2026-11-12 ticket CHG123")
  ex N ospf|bgp seen|IP,IP,..  expected neighbors (router-ids) / peers; 'seen' = those Zabbix currently sees up
  c              coverage summary          w  write both inventories + validate + dry-run          q  quit
"""
SPEED = ((10 ** 12, "T"), (10 ** 9, "G"), (10 ** 6, "M"), (10 ** 3, "K"))
LETTER = {"PENDING": "P", "APPROVED": "A", "EXCLUDED": "X", "REMOVE": "R"}


def fmt_speed(bps):
    if not bps:
        return "?"
    for div, u in SPEED:
        if bps >= div:
            v = bps / float(div)
            return ("%d%s" % (v, u)) if v == int(v) else ("%.1f%s" % (v, u))
    return str(bps)


def parse_range(text, n):
    if text == "all":
        return list(range(1, n + 1))
    out = []
    for part in text.split(","):
        m = re.match(r"^(\d+)(?:-(\d+))?$", part.strip())
        if not m:
            raise ValueError("bad range '%s'" % part)
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        out += list(range(min(a, b), max(a, b) + 1))
    bad = [i for i in out if i < 1 or i > n]
    if bad:
        raise ValueError("row %d is not in the current list (1..%d)" % (bad[0], n))
    return sorted(set(out))


class Session(object):
    def __init__(self, ctx, out):
        self.c = ctx                      # dict: snap, rules, dec, iface_raw, health_raw, paths, writer, now
        self.out = out
        self.view = "ports"
        self.listing = []
        self.rebuild()

    # ------------------------------------------------------------------ helpers
    def rebuild(self):
        c = self.c
        self.model = ob.build(c["snap"], c["rules"], c["iface_raw"], c["health_raw"], c["dec"], c["now"])
        self.devs = dict((d.id, d) for d in self.model["devices"])

    def rows(self):
        return self.model["by_id"] if self.view == "ports" else self.devs

    def save(self):
        ob.save_decisions(self.c["paths"]["decisions"], self.c["dec"])
        self.rebuild()

    def pick(self, spec):
        idx = parse_range(spec, len(self.listing))
        rows = self.rows()
        return [rows[self.listing[i - 1]] for i in idx if self.listing[i - 1] in rows]

    # ------------------------------------------------------------------ views
    def list(self, args):
        if args and args[0] in ("pending", "approved", "excluded", "review", "all", "candidates"):
            flt, rest = args[0], args[1:]
        else:
            flt, rest = "candidates", args
        text = " ".join(rest).lower()
        src = self.model["ports"] if self.view == "ports" else self.model["devices"]
        sel = []
        for r in src:
            if flt == "candidates" and not (r.candidate and r.status != "EXCLUDED"):
                continue
            if flt in ("pending", "approved", "excluded") and r.status != flt.upper() and not (
                    flt == "approved" and r.status == "REMOVE"):
                continue
            if flt == "review" and not (r.blockers or r.review):
                continue
            hay = " ".join([r.id, getattr(r, "alias", ""), getattr(r, "description", "") or ""]).lower()
            if text and text not in hay:
                continue
            sel.append(r)
        self.listing = [r.id for r in sel]
        if self.view == "ports":
            self.out("  #  S HOST                 PORT                   OPER  SPEED ROLE  SEVERITY DESCRIPTION / NOTE")
            for i, r in enumerate(sel, 1):
                role = (r.role or "-") + ("" if r.decision.get("role") or r.in_yaml or not r.role else "?")
                note = ("BLOCKED: " + r.blockers[0]) if r.blockers else (
                    ("ISSUE: " + r.issues[0]) if r.issues else ("REVIEW: " + r.review[0]) if r.review else (
                        ("pair: %s (%s)" % (r.pair, r.pair_source or "operator")) if r.pair else (
                            ("suggested peer: %s" % r.pair_hints[0]) if r.pair_hints else r.role_reason)))
                p = r.p or {}
                self.out("%3d  %s %-20s %-22s %-5s %-5s %-5s %-8s %s%s" % (
                    i, LETTER.get(r.status, "?"), r.host[:20], r.port[:22], p.get("oper", "gone")[:5],
                    fmt_speed(p.get("speed_bps")), role[:5], r.severity, (r.alias or r.description)[:40],
                    ("  [%s]" % note) if note else ""))
        else:
            self.out("  #  S HOST                 PLATFORM        SNMP        FEATURES (suggested*)                    NOTE")
            for i, d in enumerate(sel, 1):
                feats = ", ".join(d.features) + ("*" if d.status == "PENDING" and d.features else "")
                snmp = "-" if not d.h or not d.h["snmp"]["present"] else {"1": "available", "2": "UNAVAILABLE"}.get(
                    d.h["snmp"]["available"], "unknown")
                note = ("BLOCKED: " + d.blockers[0]) if d.blockers else ""
                self.out("%3d  %s %-20s %-15s %-11s %-40s %s" % (i, LETTER.get(d.status, "?"), d.host[:20],
                                                                 d.platform or "?", snmp, feats or "-", note))
        self.out("  %d row(s). S: P pending, A approved, X excluded, R remove on write. ROLE? = suggestion only." % len(sel))

    def detail(self, args):
        for r in self.pick(args[0]):
            self.out("-- %s" % r.id)
            if r.kind == "port":
                p = r.p or {}
                st = (p.get("items") or {}).get("status")
                self.out("   status: %s | decision: %s | ifAlias: %s" % (r.status, r.decision.get("decision", "-"), r.alias or "-"))
                self.out("   oper %s, speed %s, ifIndex %s, data %s%s" % (
                    p.get("oper", "?"), fmt_speed(p.get("speed_bps")), p.get("index", "?"), p.get("fresh", "?"),
                    (" (last value %ds ago)" % (self.c["snap"]["taken_at"] - st["lastclock"])) if st and st["lastclock"] else ""))
                self.out("   suggestion: %s %s | severity %s" % (r.suggest_role or "none", r.role_reason, r.severity))
                self.out("   pairing: %s%s" % (r.pair or "none", (" via %s" % r.pair_source) if r.pair else "")
                         + ("; suggested (unverified): %s" % ", ".join(r.pair_hints) if r.pair_hints else ""))
                if r.p and r.p.get("netbox_peer"):
                    self.out("   NetBox cable to: %s / %s" % tuple(r.p["netbox_peer"]))
                cls, why, ev = coverage.port_coverage(self.c["snap"], r)
                self.out("   coverage: %s" % cls)
                for w in why:
                    self.out("     - %s" % w)
                for k in ("link", "util", "stale", "notify", "delivery"):
                    if ev.get(k):
                        self.out("     %s: %s" % (k, "; ".join(ev[k])))
                for b in r.blockers + r.issues + r.review:
                    self.out("   ! %s" % b)
            else:
                self.out("   status %s | platform %s%s" % (r.status, r.platform or "unknown", (
                    " (from template %s)" % r.h["platform_source"]) if r.h and r.h.get("platform_source") else ""))
                for f in ob.HEALTH_FEATURES:
                    self.out("   %-18s %s%s" % (f, "ON " if f in r.features else "off",
                                               " - " + (r.unsupported.get(f) or r.support.get(f, ""))))
                for f in ("ospf", "bgp"):
                    if f in r.features or r.seen_ok.get(f):
                        self.out("   %s expected: %s | seen up now: %s" % (f, ", ".join(r.expected[f]) or "NONE",
                                                                     ", ".join(r.seen_ok[f]) or "-"))
                for b in r.blockers:
                    self.out("   ! %s" % b)

    # ------------------------------------------------------------------ decisions
    def approve(self, args):
        now = int(time.time())
        for r in self.pick(args[0]):
            if r.blockers:
                self.out("  refused %s: %s" % (r.id, "; ".join(r.blockers)))
                continue
            if r.kind == "port":
                if not r.role:
                    self.out("  refused %s: no role suggested - set one first (r ISP|WAN|DCI|P2P %s)" % (r.id, args[0]))
                    continue
                ob.decide_port(self.c["dec"], r, "approved", now)
            else:
                if not r.features:
                    self.out("  refused %s: no feature selected (f N +device_unreachable ...)" % r.id)
                    continue
                d = dict(self.c["dec"]["devices"].get(r.id) or {}, decision="approved", features=list(r.features),
                         platform=r.platform, decided_at=now)
                self.c["dec"]["devices"][r.id] = d
            self.out("  approved %s" % r.id)
        self.save()

    def exclude(self, args):
        now = int(time.time())
        for r in self.pick(args[0]):
            if r.kind == "port":
                ob.decide_port(self.c["dec"], r, "excluded", now)
            else:
                self.c["dec"]["devices"][r.id] = dict(self.c["dec"]["devices"].get(r.id) or {}, decision="excluded")
            self.out("  %s %s" % ("will be REMOVED on write:" if r.in_yaml else "excluded", r.id))
        self.save()

    def undo(self, args):
        for r in self.pick(args[0]):
            store = self.c["dec"]["ports" if r.kind == "port" else "devices"]
            store.pop(r.id, None)
            self.out("  reset %s" % r.id)
        self.save()

    def setf(self, field, args):
        value = args[0]
        if field == "role":
            value = value.upper()
            if value not in ob.ROLES:
                raise ValueError("role must be one of %s" % ", ".join(ob.ROLES))
        if field == "severity" and value not in SEVERITIES:
            raise ValueError("severity must be one of %s" % ", ".join(SEVERITIES))
        for r in self.pick(args[1]):
            d = dict(self.c["dec"]["ports"].get(r.id) or {})
            d[field] = value
            self.c["dec"]["ports"][r.id] = d
            self.out("  %s %s = %s" % (r.id, field, value))
        self.save()

    def describe(self, args):
        text = " ".join(args[1:]).strip()
        if not text or '"' in text or "\\" in text:
            raise ValueError("description must be non-empty plain text")
        for r in self.pick(args[0]):
            d = dict(self.c["dec"]["ports"].get(r.id) or {})
            d["description"] = text
            self.c["dec"]["ports"][r.id] = d
        self.save()

    def pair(self, args):
        a = self.pick(args[0])
        if len(a) != 1:
            raise ValueError("pair takes single rows: p N M")
        a = a[0]
        if len(args) > 1 and args[1] == "-":
            ob.set_pair(self.c["dec"], a, None, "single-ended")
            self.out("  %s confirmed single-ended (no link_id); any previous peer was released and must be resolved" % a.id)
        else:
            if len(args) > 1:
                b = self.pick(args[1])[0]
            elif a.pair_hints:
                b = self.model["by_id"][a.pair_hints[0]]
            else:
                raise ValueError("no suggested peer for %s: use p N M" % a.id)
            if b.id == a.id or b.host == a.host:
                raise ValueError("a link joins two different hosts")
            ob.set_pair(self.c["dec"], a, b, "operator-confirmed")
            self.out("  paired %s <-> %s (operator-confirmed; link_id is generated when both ends are approved)" % (a.id, b.id))
        self.save()

    def features(self, args):
        r = self.pick(args[0])
        for d in r:
            feats = list(d.features)
            for tok in args[1:]:
                f = tok[1:]
                if f not in ob.HEALTH_FEATURES or tok[0] not in "+-":
                    raise ValueError("use +feature / -feature with: %s" % ", ".join(ob.HEALTH_FEATURES))
                if tok[0] == "+" and f not in feats:
                    if f in d.unsupported:
                        self.out("  refused +%s on %s: %s" % (f, d.id, d.unsupported[f]))
                        continue
                    if "UNVERIFIED" in d.support.get(f, ""):
                        self.out("  WARNING %s on %s: %s" % (f, d.id, d.support[f]))
                    feats.append(f)
                elif tok[0] == "-" and f in feats:
                    feats.remove(f)
            self.c["dec"]["devices"][d.id] = dict(self.c["dec"]["devices"].get(d.id) or {}, features=feats)
            self.out("  %s features: %s" % (d.id, ", ".join(feats) or "none"))
        self.save()

    def evidence(self, args):
        feat, ref = args[1], " ".join(args[2:]).strip()
        if feat not in ("ospf", "bgp") or not ref:
            raise ValueError("ev N ospf|bgp REFERENCE")
        for d in self.pick(args[0]):
            rec = dict(self.c["dec"]["devices"].get(d.id) or {})
            rec["evidence"] = dict(rec.get("evidence") or {}, **{feat: ref})
            self.c["dec"]["devices"][d.id] = rec
            self.out("  %s %s evidence recorded: %s" % (d.id, feat, ref))
        self.save()

    def expected(self, args):
        from nethealth.config import IPV4
        feat, spec = args[1], (args[2] if len(args) > 2 else "")
        if feat not in ("ospf", "bgp") or not spec:
            raise ValueError("ex N ospf|bgp seen|IP,IP,...")
        for d in self.pick(args[0]):
            vals = list(d.seen_ok.get(feat, [])) if spec == "seen" else [x for x in re.split(r"[,\s]+", spec) if x]
            if not vals or any(not IPV4.match(v) for v in vals):
                raise ValueError("%s: need IPv4 addresses%s" % (d.id, " (nothing seen up yet)" if spec == "seen" else ""))
            rec = dict(self.c["dec"]["devices"].get(d.id) or {})
            rec["expected"] = dict(rec.get("expected") or {}, **{feat: sorted(set(vals))})
            self.c["dec"]["devices"][d.id] = rec
            self.out("  %s %s expected: %s" % (d.id, feat, ", ".join(sorted(set(vals)))))
        self.save()

    def platform(self, args):
        from nethealth.config import PLATFORMS
        if args[1] not in PLATFORMS:
            raise ValueError("platform must be one of %s" % ", ".join(PLATFORMS))
        for d in self.pick(args[0]):
            self.c["dec"]["devices"][d.id] = dict(self.c["dec"]["devices"].get(d.id) or {}, platform=args[1])
        self.save()

    # ------------------------------------------------------------------ loop
    def handle(self, line):
        parts = line.strip().split()
        if not parts:
            return True
        cmd, args = parts[0], parts[1:]
        try:
            if cmd in ("q", "quit", "exit"):
                return False
            if cmd in ("?", "help"):
                self.out(HELP)
            elif cmd == "l":
                self.list(args)
            elif cmd == "h":
                self.view = "devices" if self.view == "ports" else "ports"
                self.out("  view: %s" % self.view)
                self.list([])
            elif cmd == "v" and args:
                self.detail(args)
            elif cmd == "a" and args:
                self.approve(args)
            elif cmd == "x" and args:
                self.exclude(args)
            elif cmd == "u" and args:
                self.undo(args)
            elif cmd == "r" and len(args) == 2 and self.view == "ports":
                self.setf("role", args)
            elif cmd == "s" and len(args) == 2 and self.view == "ports":
                self.setf("severity", args)
            elif cmd == "d" and len(args) >= 2 and self.view == "ports":
                self.describe(args)
            elif cmd == "p" and args and self.view == "ports":
                self.pair(args)
            elif cmd == "f" and len(args) >= 2 and self.view == "devices":
                self.features(args)
            elif cmd == "pl" and len(args) == 2 and self.view == "devices":
                self.platform(args)
            elif cmd == "ev" and len(args) >= 3 and self.view == "devices":
                self.evidence(args)
            elif cmd == "ex" and len(args) >= 3 and self.view == "devices":
                self.expected(args)
            elif cmd == "c":
                self.c["summary"](self.model)
            elif cmd == "w":
                self.c["writer"](self.model)
                self.rebuild()
            else:
                self.out("  unknown or incomplete command in %s view - '?' for help" % self.view)
        except (ValueError, IndexError, KeyError) as exc:
            self.out("  error: %s" % exc)
        return True
