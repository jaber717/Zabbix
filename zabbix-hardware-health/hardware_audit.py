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
                _write_json(args.output, report)
                out(json.dumps(report, indent=2, sort_keys=True))
                s = report["summary"]
                return 0 if s["GAP"] == 0 and s["BLOCKED"] == 0 else 2
            res = {"project": "NETOPS Hardware Health", "schema": 2, "mode": "discover", "environment": args.env, "zabbix_version": version,
                   "hosts": [AU.discover_host(api, h, now) for h in args.host]}
            _write_json(args.output, res)
            out(json.dumps(res, indent=2, sort_keys=True))
            return 0
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
