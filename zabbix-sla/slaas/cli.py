"""sla.sh entry point.

    sla.sh --env lab check                  offline: validate the inventory, show what it compiles to (no Zabbix access)
    sla.sh --env lab plan                   read-only: ADD / CHANGE / orphan list against the live Zabbix
    sla.sh --env lab apply                  backup, write (journalled), readback-verify
    sla.sh --env lab verify                 read-only semantic drift check (exit 2 = drift)
    sla.sh --env lab rollback --backup F    restore the state recorded in a backup
    sla.sh --env lab simulate --down LINK   offline what-if on the compiled tree (no Zabbix access)
    sla.sh --env lab quality                read-only monitoring-quality check of the signals the services depend on
    sla.sh --env lab report --month YYYY-MM monthly SLI / error budget (JSON for the reporting suite; never an unqualified 100%)

Exit codes: 0 ok, 1 error / refused, 2 drift or quality findings.
"""
import argparse
import datetime
import json
import os
import sys

from . import VERSION
from . import apply as applier
from . import env as envmod
from . import evaluator, inventory, model, planner
from . import state as S
from ._compat import ApiUnavailable, ConfigError, ReadOnlyViolation, ZabbixError

RC_OK, RC_ERROR, RC_DRIFT = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="sla.sh", description="Zabbix service / SLA platform (YAML-first)")
    p.add_argument("--env", required=True, help="environment name (an environment file must exist under config/environments)")
    p.add_argument("--confirm", help="production writes: repeat the environment name to confirm")
    p.add_argument("--assume-tag-semantics", choices=["and"], help="READ-ONLY plan only: assume AND semantics for service problem tags (never for apply)")
    p.add_argument("--version", action="version", version="zabbix-sla " + VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("plan").add_argument("--prune", action="store_true")
    ap = sub.add_parser("apply")
    ap.add_argument("--prune", action="store_true", help="also delete managed objects that are no longer in the inventory")
    ap.add_argument("--allow-empty", action="store_true")
    vp = sub.add_parser("verify")
    vp.add_argument("--prune", action="store_true")
    rp = sub.add_parser("rollback")
    rp.add_argument("--backup", required=True)
    sp = sub.add_parser("simulate")
    sp.add_argument("--down", default="", help="comma separated link_id values with a link_down problem")
    sp.add_argument("--alert", default="", help="comma separated link_id:alert (e.g. stc--site-b:util_rx) - non-availability alerts")
    sp.add_argument("--probe-down", default="", help="comma separated probe ids")
    sp.add_argument("--probe-stale", default="", help="comma separated probe ids")
    sub.add_parser("quality")
    dp = sub.add_parser("dashboards")
    dp.add_argument("action", choices=["plan", "apply"])
    rep = sub.add_parser("report")
    rep.add_argument("--month", required=True, help="YYYY-MM (a closed month, or the current one as month-to-date)")
    rep.add_argument("--out", help="write the JSON document here instead of stdout")
    rep.add_argument("--suite-doc", help="also write the document in the zabbix-reporting-suite-report-v1 model (for the PDF/XLSX renderers) to this file")
    return p


def _load_inventory(env, assume, out):
    data = inventory.load_file(env["inventory_path"])
    envmod.check_inventory_env(env, data)
    if assume:
        data["tag_semantics"] = assume
    inv = inventory.validate(data, now=datetime.datetime.now(datetime.timezone.utc))
    for pr in inv.infos:
        out("  info   " + pr.message + "  (" + pr.where + ")")
    if inv.errors:
        for pr in inv.errors:
            out("  ERROR  " + pr.message + "  (" + pr.where + ")")
        return None, None
    return inv, model.compile_inventory(inv)


def _banner(env, url, ident, text):
    return "\n".join(["=" * 64, "  ENVIRONMENT : %s%s" % (env["environment"].upper(), "   (PRODUCTION)" if env["is_production"] else ""),
                      "  ZABBIX       : %s  (API %s)" % (url, ident.version or "?"), "  IDENTITY     : %s" % ident.state, "  %s" % text, "=" * 64])


def _show_plan(plan, out):
    for line in plan.lines():
        out("  " + line)
    for o in plan.orphans:
        out("  ORPHAN %s" % o)
    for c in plan.conflicts:
        out("  CONFLICT %s" % c)
    for w in plan.warnings:
        out("  warn   %s" % w)
    cnt = plan.counts()
    out("  summary: %s" % (", ".join("%d %s" % (v, k) for k, v in sorted(cnt.items())) or "no changes"))


def run(argv, environ=None, out=print, base=None, transport_factory=None, now=None):
    args = _parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    try:
        env = envmod.load(args.env, base)
        return _dispatch(args, env, environ, out, base, transport_factory, now)
    except (envmod.EnvError, ConfigError) as exc:
        out("REFUSED: %s" % exc)
        return RC_ERROR
    except ReadOnlyViolation as exc:
        out("REFUSED: %s" % exc)
        return RC_ERROR
    except applier.ApplyError as exc:
        out("FAILED: %s" % exc)
        if exc.backup:
            out("  the pre-apply state is in %s" % exc.backup)
            out("  restore with: sla.sh --env %s rollback --backup %s" % (args.env, exc.backup))
        if exc.journal:
            out("  journal: %s" % exc.journal)
        return RC_ERROR
    except (ZabbixError, ApiUnavailable) as exc:
        out("ERROR: %s" % exc)
        return RC_ERROR


def _dispatch(args, env, environ, out, base, transport_factory, now):
    cmd = args.cmd
    if cmd == "rollback":
        return _rollback(args, env, environ, out, base, transport_factory, now)
    if args.assume_tag_semantics and cmd not in ("plan", "check", "simulate"):
        out("REFUSED: --assume-tag-semantics is for read-only plan/check/simulate; it can never be used to %s" % cmd)
        return RC_ERROR
    inv, desired = _load_inventory(env, args.assume_tag_semantics, out)
    if inv is None:
        out("inventory INVALID - nothing was contacted")
        return RC_ERROR
    if cmd == "check":
        out("inventory OK: %d service(s), %d SLA(s), %d active probe(s); %d deferred" % (len(desired.services), len(desired.slas), len(desired.probes), len(desired.deferred)))
        for d in desired.deferred:
            out("  deferred: " + d)
        for n in desired.notes:
            out("  note: " + n)
        return RC_OK
    if cmd == "simulate":
        return _simulate(args, desired, out)

    desired_state = S.from_desired(desired)
    write = cmd == "apply" or (cmd == "dashboards" and args.action == "apply")
    if write:
        gate = envmod.production_gate(env, args.confirm)
        if gate:
            out("REFUSED: " + gate)
            return RC_ERROR
    client, env, url, ident = envmod.open_client(args.env, read_only=not write, base=base, environ=environ, transport_factory=transport_factory)
    version = ident.version
    if cmd == "plan":
        out(_banner(env, url, ident, "PLAN (read-only)" + ("  [tag semantics ASSUMED: results are not authoritative]" if args.assume_tag_semantics else "")))
        plan, _ = planner.build(client, desired_state, env, prune=args.prune, now=now)
        _show_plan(plan, out)
        return RC_OK if plan.ok else RC_ERROR
    if cmd == "verify":
        out(_banner(env, url, ident, "VERIFY (read-only)"))
        diffs = applier.verify(client, env, desired_state, prune=args.prune, now=now)
        for d in diffs:
            out("  DRIFT  " + d)
        out("  %s" % ("live state matches the inventory" if not diffs else "%d difference(s)" % len(diffs)))
        return RC_OK if not diffs else RC_DRIFT
    if cmd == "apply":
        out(_banner(env, url, ident, "APPLY"))
        res = applier.apply(client, env, desired_state, base or envmod.BASE, version, out, prune=args.prune, allow_empty=args.allow_empty, now=now)
        _show_plan(res["plan"], out)
        if res["verify_changes"]:
            out("READBACK VERIFICATION FAILED - live state still differs:")
            for d in res["verify_changes"]:
                out("  " + d)
            if res["backup"]:
                out("  restore with: sla.sh --env %s rollback --backup %s" % (args.env, res["backup"]))
            return RC_ERROR
        out("applied %d step(s); readback verification: PASS" % res["steps"])
        return RC_OK
    if cmd == "dashboards":
        return _dashboards(args, env, client, base, out)
    if cmd in ("quality", "report"):
        from . import reporting
        return reporting.run(args, env, desired, client, out, now)
    return RC_ERROR


def _dashboards(args, env, client, base, out):
    from . import dashboards
    base = base or envmod.BASE
    try:
        if args.action == "plan":
            changes, warnings, verified = dashboards.plan(client, base)
        else:
            changes, warnings = dashboards.apply(client, base, out)
    except dashboards.DashboardError as exc:
        out("REFUSED: %s" % exc)
        return RC_ERROR
    for action, name, _ in changes:
        out("  %-6s dashboard %s" % (action.upper(), name))
    for w in warnings:
        out("  warn   %s" % w)
    out("  summary: %s" % (", ".join("%d %s" % (sum(1 for c in changes if c[0] == a), a) for a in ("create", "update") if any(c[0] == a for c in changes)) or "no changes"))
    return RC_OK


def _rollback(args, env, environ, out, base, transport_factory, now):
    gate = envmod.production_gate(env, args.confirm)
    if gate:
        out("REFUSED: " + gate)
        return RC_ERROR
    client, env, url, ident = envmod.open_client(args.env, read_only=False, base=base, environ=environ, transport_factory=transport_factory)
    out(_banner(env, url, ident, "ROLLBACK to %s" % os.path.basename(args.backup)))
    res = applier.rollback(client, env, args.backup, base or envmod.BASE, ident.version, out, now=now)
    _show_plan(res["plan"], out)
    if res["verify_changes"]:
        out("ROLLBACK VERIFICATION FAILED - live state still differs from the backup:")
        for d in res["verify_changes"]:
            out("  " + d)
        return RC_ERROR
    out("rolled back %d step(s); readback verification: PASS" % res["steps"])
    return RC_OK


def _simulate(args, desired, out):
    probs = [evaluator.netops_link_down(x) for x in args.down.split(",") if x]
    for item in [x for x in args.alert.split(",") if x]:
        link, _, alert = item.partition(":")
        probs.append(evaluator.netops_alert(link, alert or "util_rx"))
    probs += [evaluator.probe_down(x) for x in args.probe_down.split(",") if x]
    probs += [evaluator.probe_stale(x) for x in args.probe_stale.split(",") if x]
    st = evaluator.evaluate(desired, probs, "and")
    out("what-if on the compiled tree (assumes AND semantics for problem tags; the live server decides - see acceptance test A-01)")
    for sid in sorted(desired.services, key=lambda s: (desired.services[s]["layer"], s)):
        if desired.services[sid]["layer"] in ("business", "connectivity", "root", "quality", "probe"):
            out("  %-10s %-34s %s" % (desired.services[sid]["layer"], sid, "OK" if st[sid] == evaluator.OK else "PROBLEM (severity %d)" % st[sid]))
    return RC_OK


def main(argv=None):
    sys.exit(run(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    main()
