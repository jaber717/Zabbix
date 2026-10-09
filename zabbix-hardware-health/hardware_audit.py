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
    p.add_argument("--base", help="project / installation directory (default: the directory of this script)")
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
    syn.add_argument("what", choices=["review", "preflight", "snapshot", "diff", "verify", "cleanup-plan", "emergency-disable-plan", "observe", "audit-probe", "ledger-record", "ledger-mark"])
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
    syn.add_argument("--phase", choices=["before", "after"], help="observe: before or after the case")
    syn.add_argument("--event", choices=["enabled", "disabled", "sent"], help="ledger-mark: enablement started/ended, or (with --case) the time a case value was sent")
    act = sub.add_parser("action")
    act.add_argument("what", choices=["plan", "apply", "rollback"])
    act.add_argument("--notifications")
    act.add_argument("--enable", action="store_true", help="enable the action - allowed only with independently verified delivery evidence")
    act.add_argument("--backup")
    v = sub.add_parser("vendors", help="offline: list vendor definitions, the coverage matrix, simulation and the message contract")
    v.add_argument("what", choices=["list", "coverage", "simulate", "messages", "check"])
    v.add_argument("--out")
    t = sub.add_parser("template", help="generate / check (offline) or plan/apply/rollback (LAB, guarded) a NETOPS-HW template")
    t.add_argument("what", choices=["build", "check", "plan", "apply", "rollback"])
    t.add_argument("--definition", required=True)
    t.add_argument("--out")
    t.add_argument("--approve-linked-update", metavar="REF", help="independent approval reference required to update/restore a template that is linked to hosts")
    t.add_argument("--approve-removals", metavar="REF", help="approval reference required when the import would DELETE items / triggers / rules / value maps")
    t.add_argument("--accept-drift", action="store_true", help="overwrite a template whose live configuration no longer matches what this tool last wrote")
    ls = sub.add_parser("labsim", help="READ-ONLY verification of the existing LAB simulator objects")
    ls.add_argument("--config")
    ls.add_argument("--evidence-since", type=int, help="epoch seconds: instead of verifying, report events and alerts of the simulator triggers since then (read-only)")
    return p


def _open(env, policy_cfg, environ, transport, write=False, write_templates=False):
    url, token = identity.resolve_target(env, environ)
    api = ZabbixAPI(url, token, transport=transport, write=write, write_templates=write_templates)
    version = identity.verify(api, env, url, policy_cfg)
    return api, version


def _write_json(path, obj):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")


def _emergency(SY, api, ledger, base, out):
    try:
        steps = SY.emergency_disable_plan(api, ledger, base)
    except AuditError as exc:
        out("EMERGENCY DISABLE NOT AVAILABLE: " + str(exc))
        return 1
    if not steps:
        out("  nothing to disable: the recorded hardware action is already disabled (or no longer exists)")
    for step in steps:
        out("  %s  %s  -- %s" % (step["method"], json.dumps(step["params"]), step["why"]))
        out("  preconditions to re-check immediately before executing: %s" % json.dumps(step["preconditions"], sort_keys=True))
    return 0


def _vendors(args, base, catalogue, out):
    from hwh import coverage, messages, simulate, vendordefs
    defs = vendordefs.load_dir(os.path.join(base, "vendors"))
    if args.what == "list":
        for d in sorted(defs.values(), key=lambda x: x["id"]):
            out("%-22s %-9s sensors=%d unsupported=%d" % (d["id"], d["vendor"], len(d.get("sensors") or []), len(d.get("unsupported") or [])))
        return 0
    if args.what == "simulate":
        bad = 0
        for did, s in sorted(simulate.summary(defs).items()):
            out("%-22s %3d scenario checks, %d failed" % (did, s["cases"], len(s["failed"])))
            for f in s["failed"]:
                out("   FAILED: %s" % json.dumps(f, sort_keys=True))
            bad += len(s["failed"])
        return 1 if bad else 0
    if args.what == "messages":
        problems = messages.check()
        out(messages.render_examples())
        for p in problems:
            out("VIOLATION: " + p)
        return 1 if problems else 0
    m = coverage.build(defs, catalogue, coverage.load_device_evidence(os.path.join(base, "config", "device-evidence.yaml")))
    text = coverage.render_markdown(m)
    if args.what == "check":
        from hwh import template, importcheck
        bad = 0
        for d in defs.values():
            if d.get("sensors"):
                for pr in importcheck.check(template.build(d)):
                    out("%s: %s" % (d["id"], pr))
                    bad += 1
        out("template import check: %s" % ("PASS" if not bad else "%d problem(s)" % bad))
        return 1 if bad else 0
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        out(text)
    return 0


def _template(args, environ, transport, base, out, catalogue):
    from hwh import importcheck, template, tplmgr, vendordefs
    defs = vendordefs.load_dir(os.path.join(base, "vendors"))
    defn = defs.get(args.definition)
    if defn is None or not defn.get("sensors"):
        raise AuditError("no buildable definition %r (known with sensors: %s)" % (args.definition, ", ".join(sorted(k for k, v in defs.items() if v.get("sensors")))))
    doc = template.build(defn)
    if args.what in ("build", "check"):
        problems = importcheck.check(doc)
        for pr in problems:
            out("PROBLEM: " + pr)
        if args.what == "build" and not problems:
            text = json.dumps(doc, indent=2, sort_keys=True)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
            else:
                out(text)
        else:
            out("template %s: %s" % (args.definition, "import check PASS" if not problems else "import check FAILED"))
        return 1 if problems else 0
    if args.env != "lab":
        raise AuditError("template management is LAB only in this release (refused before contacting any server)")
    cfg = policy.load_config(os.path.join(base, "config", "hardware.lab.yaml"), "lab", catalogue)
    writing = args.what in ("apply", "rollback")
    api, _ = _open("lab", cfg, environ, transport, write_templates=writing)
    kw = {"approve_linked": args.approve_linked_update, "approve_removals": args.approve_removals, "accept_drift": args.accept_drift}
    if args.what == "rollback":
        out(json.dumps(tplmgr.rollback(api, "lab", defn, base, **kw), sort_keys=True))
        return 0
    if args.what == "plan":
        p = tplmgr.plan(api, "lab", defn, base, **kw)
    else:
        res = tplmgr.apply(api, "lab", defn, base, **kw)
        p = res["plan"]
        out("result: %s" % res["result"])
        for k in ("backup", "backup_export_sha256", "record"):
            if res.get(k):
                out("%s: %s" % (k.replace("_", " "), res[k]))
    out("template %s: %s" % (p["template"], p["action"]))
    cmp_ = p["compare"]
    out("  importcompare: %s" % ("not available on this Zabbix" if cmp_["available"] is False else "not run" if cmp_["available"] is None else "%d operation(s)" % len(cmp_["operations"])))
    for k, v in sorted(cmp_["counts"].items()):
        out("    %s: %d" % (k, v))
    for o in cmp_["operations"]:
        out("    %-8s %-40s %s" % (o["op"], o["path"], o["label"]))
    for n in p["notes"]:
        out("  note: " + n)
    for c in p["conflicts"]:
        out("  CONFLICT: " + c)
    out("  the template is NOT linked to any host by this tool")
    return 1 if p["conflicts"] else 0


def _synthetic(args, environ, transport, base, out, catalogue, clock):
    from hwh import synthetic as SY
    if args.env != "lab":
        raise AuditError("the synthetic notification test is LAB only (refused before contacting any server)")
    cfg = policy.load_config(os.path.join(base, "config", "hardware.lab.yaml"), "lab", catalogue)
    now = clock or datetime.datetime.now(datetime.timezone.utc)
    if args.what == "audit-probe":
        from hwh import evidence as EV
        api, version = _open("lab", cfg, environ, transport, write=False)
        r = EV.probe(api)
        for k in ("settings_readable", "auditlog_enabled", "auditlog_readable", "history_readable"):
            out("  %-22s %s" % (k, r[k]))
        for d in r["detail"]:
            out("  note: " + d)
        out("AUTHORITATIVE EVIDENCE %s" % ("AVAILABLE" if r["authoritative_evidence_available"] else "UNAVAILABLE: negative synthetic cases (B, C, D) can only be INCONCLUSIVE"))
        return 0 if r["authoritative_evidence_available"] else 4
    scope_path = args.scope or os.path.join(base, "config", "synthetic-test.yaml")
    if args.what in ("ledger-record", "ledger-mark"):
        if not args.ledger:
            raise AuditError("--ledger is required")
        # starting or advancing the test (recording a created fixture, marking the action ENABLED) is gated by the approved window;
        # recording that the action was DISABLED is never gated, so a test can always be wound down.
        if args.what == "ledger-record" or args.event in ("enabled", "sent"):
            SY.require_window(SY.load_scope(scope_path), now)
        led = SY.Ledger.load(args.ledger) if os.path.isfile(args.ledger) else SY.Ledger(args.ledger)
        if args.what == "ledger-record":
            if not args.kind or not args.id or not str(args.id).isdigit():
                raise AuditError("ledger-record needs --kind and a numeric Zabbix --id (the exact id returned by the create call)")
            led.record(args.kind, args.id, args.case)
            if args.kind == "action":
                if not args.created_by_test:
                    raise AuditError("a hardware action may only be recorded with --created-by-test: a pre-existing action is never part of this test")
                led.data["action_created_by_test"] = True
                led.save()
        else:
            if not args.event:
                raise AuditError("ledger-mark needs --event enabled|disabled|sent")
            if args.event == "sent":
                if args.case not in ("A", "B", "C", "D"):
                    raise AuditError("ledger-mark --event sent needs --case")
                led.data.setdefault("sent", {}).setdefault(args.case, []).append(int(now.timestamp()))
            else:
                led.data[args.event + "_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
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
    scope = SY.load_scope(scope_path)
    spec = A.load_spec(args.notifications or os.path.join(base, "config", "notifications.lab.yaml"))
    if args.what == "preflight":
        SY.require_window(scope, now)                       # the execution gate is checked BEFORE any server is contacted
    api, version = _open("lab", cfg, environ, transport, write=False)
    if args.what in ("preflight", "review"):
        mode = "execute" if args.what == "preflight" else "review"
        expected = SY.Ledger.load(args.ledger).data.get("action") if (args.ledger and os.path.isfile(args.ledger)) else None
        r = SY.preflight(api, scope, spec, now=now, mode=mode, base=base, expected_actionid=expected)
        for c in r["checks"]:
            out("  %s  %s%s" % ("ok  " if c["ok"] else "FAIL", c["check"], ("  - " + c["detail"]) if c["detail"] else ""))
        if mode == "review":
            out("REVIEW: %s. This is a read-only readiness review; it never authorises execution (%s)." % (
                "READY" if r["ok"] else "NOT READY", "inside the window" if r["in_window"] else "outside the approved window"))
            return 0 if r["ok"] else 1
        out("PREFLIGHT %s" % ("PASS: execution may start" if r["ok"] else "REFUSED: do not execute"))
        return 0 if r["ok"] else 1
    if args.what == "snapshot":
        m = SY.snapshot(api, scope, now=now)
        text = json.dumps(m, indent=2, sort_keys=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        out(text)
        return 0
    if not args.ledger:
        raise AuditError("--ledger is required (the file recording the exact ids this test created)")
    ledger = SY.Ledger.load(args.ledger)
    if args.what == "observe":
        SY.require_window(scope, now)
        o = SY.record_observation(api, ledger, args.case, args.phase, base, now)
        out("observation recorded: " + json.dumps(o, sort_keys=True))
        if o["status"] != "0":
            out("WARNING: the hardware action is DISABLED in this observation; negative cases will be rejected as inconclusive")
        return 0
    if args.what == "emergency-disable-plan":
        return _emergency(SY, api, ledger, base, out)
    if args.what == "cleanup-plan":
        try:
            steps = SY.cleanup_plan(api, ledger, base)
        except AuditError as exc:
            out("CLEANUP REFUSED (no deletion is planned): " + str(exc))
            out("-- the emergency disable path is independent of fixture cleanup:")
            _emergency(SY, api, ledger, base, out)
            return 1
        for step in steps:
            out("  %s  %s  -- %s" % (step["method"], json.dumps(step["params"]), step["why"]))
        return 0
    users, problems = SY.recipients(api, scope)
    if problems:
        raise AuditError("; ".join(problems))
    if not args.case:
        raise AuditError("--case is required for verify")
    r = SY.verify_case(api, args.case, ledger, users, scope, now)
    for x in r["findings"]:
        out("  FINDING: " + x)
    out("case %s: %s" % (args.case, {"PASS": "NOTIFICATION PIPELINE CHECK PASS (synthetic)", "FAIL": "FAIL", "INCONCLUSIVE": "INCONCLUSIVE - this is NOT a pass"}[r["verdict"]]))
    if not r["ok"]:
        out("ON ANY FAILURE: DISABLE THE HARDWARE ACTION NOW (run 'synthetic cleanup-plan'; its first step disables the recorded action if it is enabled)")
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 4}[r["verdict"]]


def main(argv=None, environ=None, transport=None, base=None, now=None, out=print, clock=None):
    args = _parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    base = args.base or base or HERE
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
        if args.cmd == "vendors":
            return _vendors(args, base, catalogue, out)
        if not args.env and not (args.cmd == "template" and args.what in ("build", "check")):
            raise AuditError("--env lab|production is required for this command")
        if args.cmd == "template":
            return _template(args, environ, transport, base, out, catalogue)
        if args.cmd == "labsim":
            from hwh import labsim
            if args.env != "lab":
                raise AuditError("the LAB simulator objects are LAB only")
            cfg = policy.load_config(os.path.join(base, "config", "hardware.lab.yaml"), "lab", catalogue)
            lcfg = labsim.load(args.config or os.path.join(base, "config", "lab-sim.yaml"))
            api, _ = _open("lab", cfg, environ, transport)
            if args.evidence_since is not None:
                ev = labsim.evidence(api, lcfg, args.evidence_since)
                out(json.dumps(ev, indent=2, sort_keys=True))
                return 0 if ev["ok"] else 1
            r = labsim.verify(api, lcfg)
            out(labsim.render(r, lcfg))
            return 0 if r["ok"] else 1
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
            return _synthetic(args, environ, transport, base, out, catalogue, clock)
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
                out(A.rollback(api, args.env, args.backup, base))
                return 0
            spec = A.load_spec(nfile)
            if args.what == "plan":
                p = A.plan(api, args.env, spec, args.enable, val_path, base)
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
