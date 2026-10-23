"""./apply-health.sh [--env NAME] [--check | --dry-run] [--confirm production] [--allow-empty]   (UNTESTED)

Same safety model as ./apply.sh (identity macro, URL guards, --confirm production, read-only check/dry-run),
reusing its code unchanged. Reads ONLY config/network-health.<env>.yaml.
"""
import argparse
import os
import sys

from netalert import envsafety
from netalert.cli import (EXIT_API, EXIT_FAIL, EXIT_OK, EXIT_SAFETY, EXIT_USAGE, EXIT_VERIFY, make_client,
                          print_checks)
from netalert.config import ConfigError
from netalert.zbx import ApiUnavailable, ZabbixError

from . import config, planner


def default_base():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv):
    p = argparse.ArgumentParser(prog="apply-health.sh", description="Network Health alerting for Zabbix 7.0 (UNTESTED)")
    p.add_argument("--env", default="lab")
    p.add_argument("--config", help="default: config/network-health.<env>.yaml")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate only; PASS/FAIL per device")
    mode.add_argument("--dry-run", action="store_true", help="show ADD/CHANGE/REMOVE; change nothing")
    p.add_argument("--confirm", help="production only: repeat the environment name to allow writes")
    p.add_argument("--allow-empty", action="store_true", help="allow an apply that removes ALL Network Health objects")
    return p.parse_args(argv)


def run(argv, environ=None, out=print, base=None, transport_factory=None):
    environ = os.environ if environ is None else environ
    base = base or default_base()
    args = parse_args(argv)
    try:
        env = envsafety.load_env(base, args.env)
        cfg_path = args.config or os.path.join(base, "config", "network-health.%s.yaml" % args.env)
        desired = config.load(cfg_path)
        url, ro = make_client(env, environ, transport_factory, True)
        _, rw = make_client(env, environ, transport_factory, False)
    except (envsafety.EnvError, ConfigError, OSError) as exc:
        out("ERROR: %s" % exc)
        return EXIT_USAGE

    writing = not (args.check or args.dry_run)
    try:
        ident = envsafety.verify(base, env, ro, url, environ)
        out("NETWORK HEALTH (v1.0.3, UNTESTED) | environment %s%s | Zabbix %s | identity %s" % (
            env["environment"], " (PRODUCTION)" if env["is_production"] else "", ident.version, ident.state))
        for m in ident.messages:
            out("  %s" % m)
        if not ident.ok:
            out("RESULT: environment safety check FAILED — nothing was read further or changed")
            return EXIT_SAFETY
        if writing and ident.state != "ok":
            out("RESULT: refusing to write to an unclaimed Zabbix — claim it once with "
                "./apply.sh --env %s --init-identity%s" % (env["environment"],
                                                           " --confirm %s" % env["environment"] if env["is_production"] else ""))
            return EXIT_SAFETY
        plan = planner.build_plan(ro, desired)
    except ApiUnavailable as exc:
        out("FAIL  Zabbix API unavailable: %s" % exc)
        return EXIT_API
    except ZabbixError as exc:
        out("FAIL  Zabbix API error: %s" % exc)
        return EXIT_API

    if args.check:
        print_checks(plan.checks, out)
        for c in plan.conflicts:
            out("  REVIEW REQUIRED  %s" % c)
        if plan.failed or plan.conflicts:
            out("RESULT: FAIL (%d failed check(s), %d conflict(s))" % (len(plan.failed), len(plan.conflicts)))
            return EXIT_FAIL
        out("RESULT: PASS (%d device(s))%s" % (len(desired.devices), "" if desired.devices else
                                               " — Network Health not configured (disabled)"))
        return EXIT_OK

    if plan.failed or plan.conflicts:
        print_checks(plan.failed, out)
        for c in plan.conflicts:
            out("  REVIEW REQUIRED  %s" % c)
        out("RESULT: FAIL — fix the above first; nothing changed")
        return EXIT_FAIL
    if plan.empty:
        out("No changes required.")
        return EXIT_OK
    out(envsafety.banner(env, url, ident, plan.counts()))
    for ch in plan.changes:
        out("  " + ch.line())
    if args.dry_run:
        out("DRY RUN — nothing was changed.")
        return EXIT_OK

    if not desired.devices and not args.allow_empty:
        out("RESULT: network-health yaml selects no devices, so this would remove every Network Health object. "
            "If intended re-run with --allow-empty.")
        return EXIT_FAIL
    block = envsafety.production_gate(env, args.confirm)
    if block:
        out("RESULT: %s" % block)
        return EXIT_SAFETY
    try:
        path = planner.write_backup(base, rw, env["environment"], cfg_path)
        out("backup of Network Health objects: %s" % os.path.relpath(path, base))
        done = planner.execute(rw, plan, out)
        again = planner.build_plan(ro, desired)
    except planner.ApplyError as exc:
        out("RESULT: APPLY STOPPED after %d change(s): %s — fix and re-run (idempotent)" % (exc.done, exc))
        return EXIT_VERIFY
    except (ApiUnavailable, ZabbixError) as exc:
        out("RESULT: APPLY STOPPED: %s — fix and re-run (idempotent)" % exc)
        return EXIT_VERIFY
    if not again.empty:
        out("RESULT: applied %d change(s) but %d difference(s) remain:" % (done, len(again.changes)))
        for ch in again.changes:
            out("  " + ch.line())
        return EXIT_VERIFY
    out("RESULT: applied %d change(s); verification plan is empty." % done)
    return EXIT_OK


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
