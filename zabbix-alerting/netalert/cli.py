"""Command line: ./apply.sh [--env NAME] [--check | --dry-run | --init-identity]"""
import argparse
import os
import sys

from . import apply as applier
from . import backup, config, envsafety, model, planner
from .zbx import ApiUnavailable, HttpTransport, ReadOnlyViolation, ZabbixClient, ZabbixError

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_SAFETY, EXIT_API, EXIT_VERIFY = 0, 1, 2, 3, 4, 5


def default_base():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv):
    p = argparse.ArgumentParser(prog="apply.sh", description="Interface alerting as code for Zabbix 7.0")
    p.add_argument("--env", default="lab", help="environment file in config/environments (default: lab)")
    p.add_argument("--config", help="interfaces file (default: config/interfaces.yaml)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate only; PASS/FAIL per interface")
    mode.add_argument("--dry-run", action="store_true", help="show ADD/CHANGE/REMOVE; change nothing")
    mode.add_argument("--init-identity", action="store_true",
                      help="claim this Zabbix as --env by creating its identity macro (once)")
    p.add_argument("--confirm", help="production only: repeat the environment name to allow writes")
    p.add_argument("--allow-empty", action="store_true",
                   help="allow an apply that leaves NO interfaces selected (removes every alert this tool made)")
    return p.parse_args(argv)


def make_client(env, environ, transport_factory, read_only):
    url, token = envsafety.resolve_target(env, environ)
    verify = env["zabbix"].get("verify_tls", True)
    factory = transport_factory or (lambda u, t, v: HttpTransport(u, t, verify_tls=v))
    return url, ZabbixClient(factory(url, token, verify), read_only=read_only)


def print_checks(checks, out):
    for c in checks:
        out("  %s  %s / %s  %s" % ("PASS" if c.ok else "FAIL", c.host, c.iface, c.message))


def run(argv, environ=None, out=print, base=None, transport_factory=None):
    environ = os.environ if environ is None else environ
    base = base or default_base()
    args = parse_args(argv)
    try:
        env = envsafety.load_env(base, args.env)
        cfg_path = args.config or os.path.join(base, "config", "interfaces.yaml")
        desired = config.load(cfg_path)
    except (envsafety.EnvError, config.ConfigError, OSError) as exc:
        out("ERROR: %s" % exc)
        return EXIT_USAGE

    try:
        url, ro = make_client(env, environ, transport_factory, True)
        _, rw = make_client(env, environ, transport_factory, False)
    except envsafety.EnvError as exc:
        out("ERROR: %s" % exc)
        return EXIT_USAGE

    writing = not (args.check or args.dry_run)
    try:
        ident = envsafety.verify(base, env, ro, url, environ)
    except ApiUnavailable as exc:
        out("FAIL  Zabbix API unavailable: %s" % exc)
        out("RESULT: nothing was checked or changed")
        return EXIT_API
    except ZabbixError as exc:
        out("FAIL  Zabbix API refused the request: %s" % exc)
        return EXIT_API

    out("environment %s%s | Zabbix %s | identity %s" % (
        env["environment"], " (PRODUCTION)" if env["is_production"] else "", ident.version, ident.state))
    for m in ident.messages:
        out("  %s" % m)
    if not ident.ok:
        out("RESULT: environment safety check FAILED — nothing was read further or changed")
        return EXIT_SAFETY

    if args.init_identity:
        return init_identity(env, ident, rw, args, out)

    auto = bool(env.get("auto_init_identity"))
    if writing and ident.state == "uninitialised" and not auto:
        out("RESULT: refusing to write to an unclaimed Zabbix — run with --init-identity first")
        return EXIT_SAFETY
    try:
        # dry-run shows the identity step; a real apply only plans it where auto_init_identity is on
        plan = planner.build_plan(ro, env, desired, ident.state, allow_init=(auto or not writing))
    except ApiUnavailable as exc:
        out("FAIL  Zabbix API unavailable: %s" % exc)
        return EXIT_API
    except ZabbixError as exc:
        out("FAIL  Zabbix API error while reading: %s" % exc)
        return EXIT_API

    count, nvps, gets = model.nvps_estimate(desired)

    if args.check:
        print_checks(plan.checks, out)
        bad = len(plan.failed)
        out("selected interfaces: %d | estimated +%.2f new values/s, %.2f SNMP gets/s" % (count, nvps, gets))
        for c in plan.conflicts:
            out("  REVIEW REQUIRED  %s" % c)
        if bad or plan.conflicts:
            out("RESULT: FAIL (%d failed check(s), %d conflict(s)) — apply would change nothing" %
                (bad, len(plan.conflicts)))
            return EXIT_FAIL
        out("RESULT: PASS (%d interface(s))" % len(plan.checks))
        return EXIT_OK

    if plan.failed or plan.conflicts:
        print_checks(plan.failed, out)
        for c in plan.conflicts:
            out("  REVIEW REQUIRED  %s" % c)
        out("RESULT: FAIL — fix the above first; nothing applied" if writing else
            "RESULT: plan not valid (see failures above); nothing changed")
        return EXIT_FAIL

    if plan.empty:
        for n in plan.notes:
            out("  note: %s" % n)
        out("No changes required.")
        return EXIT_OK

    if args.dry_run:
        out(envsafety.banner(env, url, ident, plan.counts()))
        for ch in plan.changes:
            out("  " + ch.line())
        for n in plan.notes:
            out("  note: %s" % n)
        out("DRY RUN — nothing was changed.")
        return EXIT_OK

    # ---- apply -------------------------------------------------------------------------
    if not desired.hosts and not args.allow_empty:
        out("RESULT: interfaces.yaml selects no interfaces, so this would remove every alert the tool "
            "manages. If that is intended re-run with --allow-empty; otherwise the file is truncated.")
        return EXIT_FAIL
    block = envsafety.production_gate(env, args.confirm)
    if block:
        out(envsafety.banner(env, url, ident, plan.counts()))
        for ch in plan.changes:
            out("  " + ch.line())
        out("RESULT: %s" % block)
        return EXIT_SAFETY
    out(envsafety.banner(env, url, ident, plan.counts()))
    for ch in plan.changes:
        out("  " + ch.line())
    path = backup.write(base, backup.snapshot(rw, env, plan, cfg_path, ident.version))
    out("backup of managed objects: %s" % os.path.relpath(path, base))
    try:
        done, warns = applier.execute(rw, plan, out)
        hosts = sorted(desired.hosts)
        warns += applier.run_discovery(rw, hosts, out)
    except applier.ApplyError as exc:
        out("RESULT: APPLY STOPPED after %d change(s): %s" % (exc.done, exc))
        out("Fix the cause and re-run: apply is idempotent; backup is at %s" % os.path.relpath(path, base))
        return EXIT_VERIFY
    for w in warns:
        out("  warning: %s" % w)
    again = planner.build_plan(ro, env, desired, "ok")
    if not again.empty:
        out("RESULT: applied %d change(s) but verification found %d remaining difference(s):" %
            (done, len(again.changes)))
        for ch in again.changes:
            out("  " + ch.line())
        return EXIT_VERIFY
    out("RESULT: applied %d change(s); verification plan is empty." % done)
    return EXIT_OK


def init_identity(env, ident, rw, args, out):
    if ident.state == "ok":
        out("identity already set — nothing to do.")
        return EXIT_OK
    block = envsafety.production_gate(env, args.confirm)
    if block:
        out("RESULT: %s" % block)
        return EXIT_SAFETY
    try:
        rw.call("usermacro.createglobal", {"macro": envsafety.IDENTITY_MACRO, "value": env["environment"],
                                           "description": envsafety.IDENTITY_MARKER})
    except (ZabbixError, ReadOnlyViolation) as exc:
        out("FAIL  could not create identity macro: %s" % exc)
        return EXIT_API
    out("identity %s=%s created." % (envsafety.IDENTITY_MACRO, env["environment"]))
    return EXIT_OK


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
