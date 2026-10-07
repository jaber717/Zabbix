"""Environment loading and the identity checks that keep LAB away from PRODUCTION.

Identity is proven by what the *server* says (an API-readable global macro that
only `--init-identity` creates), not by the URL we were given. The URL checks are
an additional layer, not the primary one.
"""
import os
import re

import yaml

from .config import ConfigError

IDENTITY_MACRO = "{$NETOPS.ENVIRONMENT}"
IDENTITY_MARKER = "managed_by=zabbix-alerting-as-code"
ENV_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
PRODUCTION_NAMES = {"production", "prod"}


class EnvError(Exception):
    pass


def env_dir(base):
    return os.path.join(base, "config", "environments")


def load_env(base, name):
    if not ENV_NAME_RE.match(name or ""):
        raise EnvError("invalid environment name %r" % (name,))
    path = os.path.join(env_dir(base), name + ".yaml")
    if not os.path.isfile(path):
        raise EnvError("no such environment: %s (expected %s)" % (name, path))
    with open(path, "r", encoding="utf-8") as fh:
        env = yaml.safe_load(fh) or {}
    if env.get("environment") != name:
        raise EnvError("%s declares environment=%r but was selected as %r — refusing" %
                       (path, env.get("environment"), name))
    z = env.get("zabbix") or {}
    for key in ("url_env", "token_env"):
        if not z.get(key):
            raise EnvError("%s: zabbix.%s is required" % (path, key))
    act = env.get("alert_action")
    if act:
        if not str(act.get("name", "")).startswith("NETOPS-IaC"):
            raise EnvError("%s: alert_action.name must start with 'NETOPS-IaC' (ownership marker)" % path)
        if not act.get("usergroups") or not isinstance(act["usergroups"], list):
            raise EnvError("%s: alert_action.usergroups must be a non-empty list of Zabbix user group names" % path)
    env["_path"] = path
    env["is_production"] = name in PRODUCTION_NAMES or bool(env.get("production"))
    if env["is_production"] and not z.get("url_regex"):
        raise EnvError("%s: a production environment must define zabbix.url_regex" % path)
    return env


def resolve_target(env, environ=None):
    """(url, token) from the environment variables named in the env file — never from a default."""
    environ = os.environ if environ is None else environ
    z = env["zabbix"]
    url = environ.get(z["url_env"], "").strip()
    token = environ.get(z["token_env"], "").strip()
    if not url:
        raise EnvError("environment variable %s is not set (needed for --env %s)" %
                       (z["url_env"], env["environment"]))
    if not token:
        raise EnvError("environment variable %s is not set (needed for --env %s)" %
                       (z["token_env"], env["environment"]))
    return url, token


def normalize_url(url):
    u = url.strip().lower().rstrip("/")
    if u.endswith("/api_jsonrpc.php"):
        u = u[: -len("/api_jsonrpc.php")]
    return u


def url_findings(base, env, url, environ=None):
    """Static URL guards. Returns a list of failure strings (empty = ok)."""
    environ = os.environ if environ is None else environ
    fails = []
    z = env["zabbix"]
    if z.get("url_regex") and not re.search(z["url_regex"], url):
        fails.append("URL does not match zabbix.url_regex of %s" % env["environment"])
    if z.get("forbid_url_regex") and re.search(z["forbid_url_regex"], url):
        fails.append("URL matches zabbix.forbid_url_regex of %s" % env["environment"])
    # the same URL must not be the declared target of a different environment
    me = normalize_url(url)
    d = env_dir(base)
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.endswith(".yaml") or fn[:-5] == env["environment"]:
            continue
        try:
            with open(os.path.join(d, fn), "r", encoding="utf-8") as fh:
                other = yaml.safe_load(fh) or {}
            ov = environ.get(((other.get("zabbix") or {}).get("url_env")) or "", "")
        except (OSError, yaml.YAMLError):
            continue
        if ov and normalize_url(ov) == me:
            fails.append("URL is also the configured target of environment '%s'" % fn[:-5])
    return fails


def read_identity(client):
    rows = client.call("usermacro.get", {"output": ["globalmacroid", "macro", "value", "description"],
                                          "globalmacro": True, "filter": {"macro": IDENTITY_MACRO}})
    return rows[0] if rows else None


class Identity(object):
    def __init__(self, ok, state, messages, version=""):
        self.ok = ok                # safe to proceed with read-only work
        self.state = state          # 'ok' | 'uninitialised' | 'mismatch' | 'unreachable' | 'blocked'
        self.messages = messages
        self.version = version


def verify(base, env, client, url, environ=None):
    """Fail closed. 'uninitialised' is reported separately so the planner can offer to create it."""
    msgs = []
    url_fail = url_findings(base, env, url, environ)
    if url_fail:
        return Identity(False, "blocked", url_fail)
    version = client.version()
    want = str(env["zabbix"].get("api_version", "7.0"))
    if not version.startswith(want):
        return Identity(False, "blocked", ["Zabbix API version %s does not match required %s.x" %
                                          (version, want)], version)
    row = read_identity(client)
    if row is None:
        how = ("it will be claimed as '%s' by the first apply" if env.get("auto_init_identity") else
               "run with --init-identity once to claim this server as '%s'") % env["environment"]
        return Identity(True, "uninitialised",
                        ["Zabbix has no %s global macro yet; %s" % (IDENTITY_MACRO, how)], version)
    if row["value"] != env["environment"]:
        return Identity(False, "mismatch",
                        ["IDENTITY MISMATCH: this Zabbix says it is '%s' but --env is '%s'. "
                         "Refusing to continue." % (row["value"], env["environment"])], version)
    msgs.append("identity %s=%s matches --env" % (IDENTITY_MACRO, row["value"]))
    return Identity(True, "ok", msgs, version)


def production_gate(env, confirm):
    """Production writes require --confirm <environment name> typed explicitly."""
    if not env["is_production"]:
        return None
    if confirm != env["environment"]:
        return ("%s is a production environment: re-run with --confirm %s to apply" %
                (env["environment"], env["environment"]))
    return None


def banner(env, url, identity, counts):
    lines = ["=" * 64,
             "  ENVIRONMENT : %s%s" % (env["environment"].upper(), "   (PRODUCTION)" if env["is_production"] else ""),
             "  ZABBIX      : %s  (API %s)" % (url, identity.version or "?"),
             "  IDENTITY    : %s" % identity.state,
             "  PLANNED     : %s" % counts,
             "=" * 64]
    return "\n".join(lines)
