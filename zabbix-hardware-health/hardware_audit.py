#!/usr/bin/env python3
"""NETOPS Hardware Health - read-only coverage audit, discovery, per-vendor matrix and the (disabled-by-default) notification action.

    hardware_audit.py --env lab audit                     verify the sensors the approved policy declares (exit 0 all PASS, 2 gaps, 3 untrustworthy)
    hardware_audit.py --env lab discover --host NAME ...  list raw inputs and CANDIDATE sensors with real values (never coverage)
    hardware_audit.py matrix --observations F --report R  build the PASS/GAP/N-A/BLOCKED matrix for the four vendors
    hardware_audit.py --env lab action plan|apply|rollback   the separate NETOPS-HW Hardware Health action (LAB only; created disabled)

The audit/discover/plan paths can only call apiinfo.version, host.get, item.get, trigger.get, usermacro.get, action.get, usergroup.get and
mediatype.get. Only `action apply|rollback` may write, and only action.create/update/delete on the NETOPS-HW action.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from hwh import VERSION                                   # noqa: E402
from hwh import action as A                               # noqa: E402
from hwh import audit as AU                               # noqa: E402
from hwh import identity, matrix, policy, semantics       # noqa: E402
from hwh.api import AuditError, ZabbixAPI                 # noqa: E402

try:
    import yaml                                           # noqa: E402
except ImportError:                                       # pragma: no cover
    yaml = None


def _parser():
    p = argparse.ArgumentParser(description="NETOPS Hardware Health")
    p.add_argument("--env", choices=["lab", "production"])
    p.add_argument("--version", action="version", version="hardware-health " + VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--config")
    a.add_argument("--output")
    d = sub.add_parser("discover")
    d.add_argument("--host", action="append", required=True)
    d.add_argument("--config")
    d.add_argument("--output")
    m = sub.add_parser("matrix")
    m.add_argument("--observations", action="append", default=[])
    m.add_argument("--report", action="append", default=[])
    m.add_argument("--out")
    m.add_argument("--json")
    syn = sub.add_parser("synthetic", help="READ-ONLY support for the approved LAB synthetic notification test")
    syn.add_argument("what", choices=["preflight", "snapshot", "diff", "verify", "cleanup-plan", "ledger-record", "ledger-mark"])
    syn.add_argument("--scope")
    syn.add_argument("--notifications")
    syn.add_argument("--out")
    syn.add_argument("--before")
    syn.add_argument("--after")
    syn.add_argument("--ledger")
    syn.add_argument("--case", choices=["A", "B", "C", "D"])
    syn.add_argument("--kind", choices=["hostgroup", "host", "item", "trigger", "action"])
    syn.add_argument("--id")
    syn.add_argument("--created-by-test", action="store_true", help="ledger-record --kind action: this test created the action (so cleanup may roll it back)")
    syn.add_argument("--event", choices=["enabled", "disabled"], help="ledger-mark: when the temporary approved enablement started/ended")
    act = sub.add_parser("action")
    act.add_argument("what", choices=["plan", "apply", "rollback"])
    act.add_argument("--notifications")
    act.add_argument("--enable", action="store_true", help="enable the action - allowed only with independently verified delivery evidence")
    act.add_argument("--backup")
    return p


def _open(env, policy_cfg, environ, transport, write=False):
    url, token = identity.resolve_target(env, environ)
    api = ZabbixAPI(url, token, transport=transport, write=write)
    version = identity.verify(api, env, url, policy_cfg)
    return api, version


def _write_json(path, obj):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")


def _synthetic(args, environ, transport, base, out, catalogue, now):
    from hwh import synthetic as SY
    if args.env != "lab":
        raise AuditError("the synthetic notification test is LAB only (refused before contacting any server)")
    cfg = policy.load_config(os.path.join(base, "config", "hardware.lab.yaml"), "lab", catalogue)
    if args.what in ("ledger-record", "ledger-mark"):
        if not args.ledger:
            raise AuditError("--ledger is required")
        led = SY.Ledger.load(args.ledger) if os.path.isfile(args.ledger) else SY.Ledger(args.ledger)
        if args.what == "ledger-record":
            if not args.kind or not args.id or not str(args.id).isdigit():
                raise AuditError("ledger-record needs --kind and a numeric Zabbix --id (the exact id returned by the create call)")
            led.record(args.kind, args.id, args.case)
            if args.kind == "action":
                led.data["action_created_by_test"] = bool(args.created_by_test)
                led.save()
        else:
            if not args.event:
                raise AuditError("ledger-mark needs --event enabled|disabled")
            led.data[args.event + "_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            led.save()
        out("ledger updated: " + json.dumps(led.ids(), sort_keys=True))
        return 0
    if args.what == "diff":
        with open(args.before, encoding="utf-8") as fb, open(args.after, encoding="utf-8") as fa:
            b, a = json.load(fb), json.load(fa)
        d = SY.diff(b, a)
        for x in d:
            out("  DIFFERENCE: " + x)
        out("  Zabbix is back to the before-state (event/alert history excepted)" if not d else "  NOT restored")
        return 0 if not d else 1
    scope = SY.load_scope(args.scope or os.path.join(base, "config", "synthetic-test.yaml"))
    spec = A.load_spec(args.notifications or os.path.join(base, "config", "notifications.lab.yaml"))
    api, version = _open("lab", cfg, environ, transport, write=False)
    if args.what == "preflight":
        r = SY.preflight(api, scope, spec, now=None)
        for c in r["checks"]:
            out("  %s  %s%s" % ("ok  " if c["ok"] else "FAIL", c["check"], ("  - " + c["detail"]) if c["detail"] else ""))
        out("PREFLIGHT %s" % ("PASS: execution may be requested" if r["ok"] else "REFUSED: do not execute"))
        return 0 if r["ok"] else 1
    if args.what == "snapshot":
        m = SY.snapshot(api, scope)
        text = json.dumps(m, indent=2, sort_keys=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        out(text)
        return 0
    if not args.ledger:
        raise AuditError("--ledger is required (the file recording the exact ids this test created)")
    ledger = SY.Ledger.load(args.ledger)
    if args.what == "cleanup-plan":
        for step in SY.cleanup_plan(api, ledger):
            out("  %s  %s  -- %s" % (step["method"], json.dumps(step["params"]), step["why"]))
        return 0
    users, problems = SY.recipients(api, scope)
    if problems:
        raise AuditError("; ".join(problems))
    if not args.case:
        raise AuditError("--case is required for verify")
    r = SY.verify_case(api, args.case, ledger, users)
    for x in r["findings"]:
        out("  FINDING: " + x)
    out("case %s: %s" % (args.case, "NOTIFICATION PIPELINE CHECK PASS (synthetic)" if r["ok"] else "FAIL"))
    return 0 if r["ok"] else 1


def main(argv=None, environ=None, transport=None, base=None, now=None, out=print):
    args = _parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    base = base or HERE
    try:
        catalogue = policy.load_catalogue(os.path.join(base, "config", "vendors.yaml"))
        if args.cmd == "matrix":
            entries = []
            for f in args.observations:
                entries += matrix.load_observations(f)
            for f in args.report:
                with open(f, encoding="utf-8") as fh:
                    entries += matrix.entries_from_report(json.load(fh))
            m = matrix.build(catalogue, entries)
            text = matrix.render_markdown(m)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text)
            else:
                out(text)
            _write_json(args.json, m)
            return 0
        if not args.env:
            raise AuditError("--env lab|production is required for this command")
        if args.cmd in ("audit", "discover"):
            cfg = policy.load_config(args.config or os.path.join(base, "config", "hardware.%s.yaml" % args.env), args.env, catalogue)
            reg = semantics.load(os.path.join(base, "config", "status-semantics.yaml"))
            if args.cmd == "audit" and not cfg["hosts"]:
                raise AuditError("No approved hosts in inventory. Audit not run.")
            api, version = _open(args.env, cfg, environ, transport)
            if args.cmd == "audit":
                report = AU.audit(api, cfg, reg, version, now)
                report["notification_readiness"] = A.readiness(api, os.path.join(base, "config", "action-validation.yaml"), AU.alert_pass_sensors(report["hosts"]))
                _write_json(args.output, report)
                out(json.dumps(report, indent=2, sort_keys=True))
                s = report["summary"]
                return 0 if s["GAP"] == 0 and s["BLOCKED"] == 0 else 2
            res = {"project": "NETOPS Hardware Health", "schema": 2, "mode": "discover", "environment": args.env, "zabbix_version": version,
                   "hosts": [AU.discover_host(api, h, now) for h in args.host]}
            _write_json(args.output, res)
            out(json.dumps(res, indent=2, sort_keys=True))
            return 0
        if args.cmd == "synthetic":
            return _synthetic(args, environ, transport, base, out, catalogue, now)
        if args.cmd == "action":
            if args.env != "lab":
                raise AuditError("hardware action management is LAB only in this release (refused before contacting any server)")
            cfg = policy.load_config(os.path.join(base, "config", "hardware.%s.yaml" % args.env), args.env, catalogue)
            nfile = args.notifications or os.path.join(base, "config", "notifications.%s.yaml" % args.env)
            val_path = os.path.join(base, "config", "action-validation.yaml")
            write = args.what in ("apply", "rollback")
            if write and args.env != "lab":
                raise AuditError("hardware action management is LAB only in this release")
            api, version = _open(args.env, cfg, environ, transport, write=write)
            if args.what == "rollback":
                if not args.backup:
                    raise AuditError("--backup is required")
                out(A.rollback(api, args.env, args.backup))
                return 0
            spec = A.load_spec(nfile)
            if args.what == "plan":
                p = A.plan(api, args.env, spec, args.enable, val_path)
            else:
                res = A.apply(api, args.env, spec, args.enable, val_path, base)
                p = res["plan"]
                if res["backup"]:
                    out("backup written: " + res["backup"])
            for c in p["changes"]:
                out("  " + c)
            for n in p["notes"]:
                out("  note: " + n)
            for c in p["conflicts"]:
                out("  CONFLICT: " + c)
            bad = [c for c in p["crossover"] if not c["ok"]]
            out("  crossover model: %d event types checked, %d wrong" % (len(p["crossover"]), len(bad)))
            if not p["changes"] and not p["conflicts"]:
                out("  no changes")
            return 1 if p["conflicts"] else 0
    except (AuditError, OSError, ValueError) as exc:
        print("HARDWARE AUDIT INCOMPLETE: " + str(exc), file=sys.stderr)
        return 3
    except Exception as exc:                                         # yaml errors etc.
        if yaml is not None and isinstance(exc, yaml.YAMLError):
            print("HARDWARE AUDIT INCOMPLETE: YAML error: " + str(exc), file=sys.stderr)
            return 3
        raise
    return 3


if __name__ == "__main__":
    sys.exit(main())
