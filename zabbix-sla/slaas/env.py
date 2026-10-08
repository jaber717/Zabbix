"""Environment selection and identity protection (wraps the published netalert.envsafety; nothing is re-implemented).

Three independent locks must agree before anything is written:
  1. --env names an environment file, and the inventory file declares the SAME environment;
  2. the URL passes the file's url_regex / forbid_url_regex and is not another environment's target;
  3. the server itself says who it is: global macro {$NETOPS.ENVIRONMENT} == --env (created by zabbix-alerting --init-identity).
Production additionally needs --confirm production.  This project never creates the identity macro.
"""
import os

from . import _compat
from ._compat import envsafety
from .client import SlaClient

EnvError = envsafety.EnvError

BASE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def load(name, base=None):
    base = base or BASE
    env = envsafety.load_env(base, name)
    rel = env.get("inventory") or "inventory/%s.yaml" % name
    env["inventory_path"] = os.path.join(base, rel)
    return env


def check_inventory_env(env, inventory_data):
    declared = (inventory_data or {}).get("environment")
    if declared != env["environment"]:
        raise EnvError("inventory %s declares environment=%r but --env is %r - refusing (an inventory is never applied to another environment)"
                       % (env["inventory_path"], declared, env["environment"]))


def open_client(name, read_only=True, base=None, environ=None, transport_factory=None):
    """-> (client, env, url, identity). Raises EnvError on any failed lock. Writes need identity.state == 'ok'."""
    base = base or BASE
    env = load(name, base)
    url, token = envsafety.resolve_target(env, environ)
    if transport_factory is None:
        transport = _compat.HttpTransport(url, token, verify_tls=bool(env["zabbix"].get("verify_tls", True)))
    else:
        transport = transport_factory(url, token, bool(env["zabbix"].get("verify_tls", True)))
    client = SlaClient(transport, read_only=read_only)
    ident = envsafety.verify(base, env, client, url, environ)
    if not ident.ok:
        raise EnvError("; ".join(ident.messages))
    if not read_only and ident.state != "ok":
        raise EnvError("refusing to write: identity is '%s' (%s). The SLA platform does not claim a server; run zabbix-alerting --init-identity first."
                       % (ident.state, "; ".join(ident.messages)))
    return client, env, url, ident


def production_gate(env, confirm):
    return envsafety.production_gate(env, confirm)
