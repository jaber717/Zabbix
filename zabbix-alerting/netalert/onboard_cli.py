"""./onboard.sh — discovery-assisted onboarding for both inventories (read-only until you deploy).

  ./onboard.sh --env production                      discover (read-only) -> coverage audit -> review -> write
  ./onboard.sh --env production --report             discover + coverage audit only
  ./onboard.sh --env production --verify             deployment gate (read-only, fail closed)
  ./onboard.sh --env production --deploy --confirm production   gate, then the existing apply.sh / apply-health.sh
Scope (optional, repeatable): --group "Network devices"  --host EDGE-RTR-01
"""
import argparse
import getpass
import os
import re
import sys
import time

from . import cli as icli
from . import coverage, discovery, envsafety, netbox
from . import onboarding as ob
from .config import ConfigError
from .review import Session
from .zbx import ApiUnavailable, ReadOnlyViolation, ZabbixError

PLACEHOLDER = "CHANGE-ME"


def default_base():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv):
    p = argparse.ArgumentParser(prog="onboard.sh", description="Discovery-assisted onboarding (read-only until --deploy)")
    p.add_argument("--env", default="production")
    p.add_argument("--group", action="append", default=[], help="limit discovery to this Zabbix host group (repeatable)")
    p.add_argument("--host", action="append", default=[], help="limit discovery to this host (repeatable)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true", help="discovery + coverage audit only")
    mode.add_argument("--verify", action="store_true", help="deployment gate only (read-only)")
    mode.add_argument("--deploy", action="store_true", help="gate, then apply both inventories")
    mode.add_argument("--setup", action="store_true", help="(re)enter Zabbix/NetBox connection settings")
    p.add_argument("--confirm", help="production deploy: repeat the environment name")
    p.add_argument("--commands", help="run review commands from this file instead of interactively")
    p.add_argument("--no-netbox", action="store_true", help="skip optional NetBox enrichment")
    return p.parse_args(argv)


# ----------------------------------------------------------------------------------------- settings

def load_dotenv(base, environ):
    path = os.path.join(base, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$", line.rstrip("\n"))
            if m and m.group(1) not in environ:
                environ[m.group(1)] = m.group(2).strip().strip("'\"")


def _set_dotenv(base, values):
    path = os.path.join(base, ".env")
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.isfile(path) else []
    for k, v in values.items():
        lines = [l for l in lines if not re.match(r"^\s*(?:export\s+)?%s=" % k, l)]
        lines.append("%s=%s" % (k, v))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def setup(base, env, environ, ask, secret, out):
    """Minimal interactive configuration: URL, token, optional NetBox; fixes the production URL guard."""
    z = env["zabbix"]
    out("Connection settings for environment '%s' (stored in .env, mode 600, git-ignored)." % env["environment"])
    url = ask("Zabbix frontend URL [%s]: " % (environ.get(z["url_env"]) or "")).strip() or environ.get(z["url_env"], "")
    tok = secret("API token for %s (input hidden, Enter keeps current): " % z["token_env"]).strip() or environ.get(z["token_env"], "")
    vals = {z["url_env"]: url, z["token_env"]: tok}
    nb = ask("NetBox URL for optional read-only enrichment (Enter = none) [%s]: " % environ.get("NETBOX_URL", "")).strip()
    if nb:
        vals["NETBOX_URL"] = nb
        vals["NETBOX_TOKEN"] = secret("NetBox read-only token (hidden): ").strip()
    _set_dotenv(base, vals)
    environ.update(vals)
    if env["is_production"] and PLACEHOLDER in str(z.get("url_regex", "")) and url:
        rx = "^" + re.escape(envsafety.normalize_url(url)) + "/?$"
        if ask("Production URL guard is not set. Allow only %s  (regex %s)? [y/N]: " % (url, rx)).strip().lower() == "y":
            path = env["_path"]
            text = open(path, encoding="utf-8").read()
            text = re.sub(r"(?m)^(\s*url_regex:\s*).*$", lambda m: m.group(1) + "'%s'" % rx.replace("'", "''"), text, count=1)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            out("  %s: url_regex set (commit this file locally)" % os.path.relpath(path, base))
    out("Settings saved.")


# ------------------------------------------------------------------------------------------------ run

def run(argv, environ=None, out=print, lines=None, base=None, transport_factory=None, netbox_opener=None,
        now=None, ask=None, secret=None):
    """`lines`: iterable of review commands (tests / --commands). None = interactive when stdin is a TTY."""
    environ = dict(os.environ) if environ is None else environ
    base = base or default_base()
    args = parse_args(argv)
    load_dotenv(base, environ)
    interactive = lines is None and args.commands is None and sys.stdin.isatty()
    ask = ask or (lambda q: input(q))
    secret = secret or (lambda q: getpass.getpass(q))
    try:
        env = envsafety.load_env(base, args.env)
    except envsafety.EnvError as exc:
        out("ERROR: %s" % exc)
        return icli.EXIT_USAGE
    try:
        if args.setup:
            raise envsafety.EnvError("setup requested")
        envsafety.resolve_target(env, environ)
    except envsafety.EnvError as exc:
        if not (interactive or args.setup):
            out("ERROR: %s - run ./onboard.sh --env %s --setup" % (exc, args.env))
            return icli.EXIT_USAGE
        setup(base, env, environ, ask, secret, out)
        env = envsafety.load_env(base, args.env)
        if args.setup:
            return icli.EXIT_OK

    try:
        url, ro = icli.make_client(env, environ, transport_factory, True)
        ident = envsafety.verify(base, env, ro, url, environ)
    except (envsafety.EnvError, ApiUnavailable, ZabbixError) as exc:
        out("FAIL  cannot reach / identify Zabbix: %s" % exc)
        return icli.EXIT_API
    out("ONBOARDING | environment %s%s | Zabbix %s | identity %s | READ-ONLY" % (
        env["environment"], " (PRODUCTION)" if env["is_production"] else "", ident.version or "?", ident.state))
    for m in ident.messages:
        out("  %s" % m)
    if not ident.ok:
        out("RESULT: environment safety check FAILED - nothing was discovered or written")
        return icli.EXIT_SAFETY

    try:
        rules = ob.load_rules(base)
    except (ob.OnboardError, ConfigError) as exc:          # rules are local config; report and stop
        out("ERROR: %s" % exc)
        return icli.EXIT_USAGE
    t0 = time.time()
    try:
        snap = discovery.discover(ro, args.group, args.host, now=now, stale_after=rules["_stale_s"])
        if environ.get("NETBOX_URL") and environ.get("NETBOX_TOKEN") and not args.no_netbox:
            netbox.enrich(snap, netbox.NetBox(environ["NETBOX_URL"], environ["NETBOX_TOKEN"],
                                              opener=netbox_opener), snap["limits"])
    except (ApiUnavailable, ZabbixError, discovery.DiscoveryError, ReadOnlyViolation) as exc:
        out("FAIL  discovery aborted: %s - nothing was written" % exc)
        return icli.EXIT_API
    if ro.writes_made():                                   # cannot happen (client refuses); belt and braces
        out("FAIL  a write was attempted during discovery - aborting")
        return icli.EXIT_SAFETY

    p = ob.paths(base, args.env)
    try:
        iface_raw, health_raw = ob.read_yaml(p["interfaces"]), ob.read_yaml(p["health"])
        dec = ob.load_decisions(p["decisions"])
    except (ob.OnboardError, ConfigError) as exc:
        out("ERROR: cannot read the current inventories: %s" % exc)
        return icli.EXIT_USAGE
    model = ob.build(snap, rules, iface_raw, health_raw, dec, snap["taken_at"])
    nports = sum(len(h["ports"]) for h in snap["hosts"].values())
    out("discovered %d host(s), %d port(s) in %.1fs (%d API reads, 0 writes)%s" % (
        len(snap["hosts"]), nports, time.time() - t0, len(ro.log),
        "; NetBox enrichment on" if environ.get("NETBOX_URL") and not args.no_netbox else ""))

    def summary(m):
        result = coverage.audit(snap, m)
        text = coverage.render(snap, m, result, args.env, url)
        os.makedirs(p["state"], exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime(snap["taken_at"]))
        for name in ("coverage-latest.md", "coverage-%s.md" % stamp):
            with open(os.path.join(p["state"], name), "w", encoding="utf-8") as fh:
                fh.write(text)
        c = coverage.counts(result)
        out("COVERAGE  " + " | ".join("%s %d" % (k, c[k]) for k in coverage.CLASSES))
        for f in result["findings"][:8]:
            out("  finding: %s" % f)
        if len(result["findings"]) > 8:
            out("  ... %d more finding(s) in the report" % (len(result["findings"]) - 8))
        out("  report: %s" % os.path.relpath(os.path.join(p["state"], "coverage-latest.md"), base))
        return result

    summary(model)
    if args.report:
        return icli.EXIT_OK

    if args.verify or args.deploy:
        fails, warns = ob.verify(ro, base, args.env, model, dec, iface_raw, health_raw)
        if ident.state != "ok":
            fails.append("this Zabbix is not claimed as '%s' yet: ./apply.sh --env %s --init-identity%s" % (
                args.env, args.env, " --confirm %s" % args.env if env["is_production"] else ""))
        for w in warns:
            out("  WARN  %s" % w)
        for f in fails:
            out("  FAIL  %s" % f)
        if fails:
            out("DEPLOY GATE: FAIL - nothing was applied")
            return icli.EXIT_FAIL
        out("DEPLOY GATE: PASS (%d warning(s))" % len(warns))
        if args.verify:
            return icli.EXIT_OK
        block = envsafety.production_gate(env, args.confirm)
        if block:
            out("RESULT: %s" % block)
            return icli.EXIT_SAFETY
        conf = ["--confirm", args.confirm] if args.confirm else []
        rc = icli.EXIT_OK
        if iface_raw.get("hosts"):
            rc = icli.run(["--env", args.env, "--config", p["interfaces"]] + conf,
                          environ=environ, out=out, base=base, transport_factory=transport_factory)
        else:
            out("interface inventory is empty - Interface Alerting not applied (removing everything needs "
                "./apply.sh --allow-empty, deliberately not automated)")
        if rc != icli.EXIT_OK:
            return rc
        if (health_raw.get("devices") or {}):
            from nethealth import cli as hcli
            out("Network Health (v1.0.3, UNTESTED on a real Zabbix) - applying approved devices")
            rc = hcli.run(["--env", args.env, "--config", p["health"]] + conf, environ=environ, out=out, base=base,
                          transport_factory=transport_factory)
        return rc

    # --------------------------------------------------------------------- review session
    ctx = {"snap": snap, "rules": rules, "dec": dec, "iface_raw": iface_raw, "health_raw": health_raw, "paths": p,
           "now": snap["taken_at"], "summary": summary}

    def writer(m):
        _, probs = ob.write_all(base, args.env, m, rules, dec, ctx["iface_raw"], ctx["health_raw"])
        if probs:
            out("WRITE REFUSED - the generated inventories would not pass validation:")
            for x in probs:
                out("  %s" % x)
            return
        ctx["iface_raw"], ctx["health_raw"] = ob.read_yaml(p["interfaces"]), ob.read_yaml(p["health"])
        out("written: %s, %s, %s" % tuple(os.path.relpath(p[k], base) for k in ("interfaces", "health", "decisions")))
        hidden = [0]

        def brief(line):                        # the full per-macro plan is in --dry-run; show the shape here
            if re.match(r"^\s+(ADD|CHANGE|REMOVE)\s+macro\s", line):
                hidden[0] += 1
            else:
                out(line)
        out("--- validation: ./apply.sh --dry-run (read-only)")
        icli.run(["--env", args.env, "--dry-run", "--config", p["interfaces"]], environ=environ, out=brief, base=base,
                 transport_factory=transport_factory)
        if ctx["health_raw"].get("devices"):
            from nethealth import cli as hcli
            out("--- validation: ./apply-health.sh --dry-run (read-only; Network Health is UNTESTED)")
            hcli.run(["--env", args.env, "--dry-run", "--config", p["health"]], environ=environ, out=brief, base=base,
                     transport_factory=transport_factory)
        if hidden[0]:
            out("  (%d macro line(s) not shown; full plan: ./apply.sh --env %s --dry-run)" % (hidden[0], args.env))
        out("next: ./onboard.sh --env %s --deploy%s" % (args.env, " --confirm %s" % args.env if env["is_production"] else ""))

    ctx["writer"] = writer
    sess = Session(ctx, out)
    out("Review: '?' for help. Nothing is monitored until you approve (a), write (w) and deploy.")
    sess.list([])
    if args.commands:
        with open(args.commands, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    if lines is None and not interactive:
        out("(no terminal: review skipped; use --commands FILE or run in an SSH session)")
        return icli.EXIT_OK
    src = iter(lines) if lines is not None else None
    while True:
        try:
            line = next(src) if src is not None else input("onboard> ")
        except (StopIteration, EOFError):
            break
        if src is not None:
            out("onboard> %s" % line)
        if not sess.handle(line):
            break
    return icli.EXIT_OK


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
