"""LAB / Production isolation. Three independent locks, fail closed:
  1. environment-specific URL and token variables, which must not collide (same URL or same token for both environments is refused);
  2. optional URL guards from the policy file (`zabbix.url_regex`, `zabbix.forbid_url_regex`); mandatory for production;
  3. SERVER-SIDE identity: the global macro {$NETOPS.ENVIRONMENT} read from the Zabbix being queried must equal --env.
A missing macro is refused too: results gathered from a server that cannot say who it is cannot be attributed to an environment."""
import re

from .api import AuditError

IDENTITY_MACRO = "{$NETOPS.ENVIRONMENT}"


def normalize_url(url):
    u = url.strip().lower().rstrip("/")
    if u.endswith("/api_jsonrpc.php"):
        u = u[: -len("/api_jsonrpc.php")]
    return u


def resolve_target(env, environ):
    suffix = env.upper()
    url = (environ.get("ZABBIX_HARDWARE_URL_" + suffix) or "").strip()
    token = (environ.get("ZABBIX_HARDWARE_TOKEN_" + suffix) or "").strip()
    if not url or not token:
        raise AuditError("Set environment-specific ZABBIX_HARDWARE_URL_%s and ZABBIX_HARDWARE_TOKEN_%s" % (suffix, suffix))
    for other in ("LAB", "PRODUCTION"):
        if other == suffix:
            continue
        ou = (environ.get("ZABBIX_HARDWARE_URL_" + other) or "").strip()
        ot = (environ.get("ZABBIX_HARDWARE_TOKEN_" + other) or "").strip()
        if ou and normalize_url(ou) == normalize_url(url):
            raise AuditError("the %s URL is also configured as the %s URL: refusing (one Zabbix cannot be two environments)" % (env, other.lower()))
        if ot and ot == token:
            raise AuditError("the %s API token is identical to the %s token: use a separate token per environment" % (env, other.lower()))
    return url, token


def check_url(env, url, policy):
    z = policy.get("zabbix") or {}
    if env == "production" and not z.get("url_regex"):
        raise AuditError("a production policy must define zabbix.url_regex")
    if z.get("url_regex") and not re.search(z["url_regex"], url):
        raise AuditError("URL does not match zabbix.url_regex of %s" % env)
    if z.get("forbid_url_regex") and re.search(z["forbid_url_regex"], url):
        raise AuditError("URL matches zabbix.forbid_url_regex of %s" % env)


def verify(api, env, url, policy):
    """-> Zabbix version string. Raises AuditError on any failed lock."""
    check_url(env, url, policy)
    version = str(api.call("apiinfo.version"))
    if not version.startswith("7.0."):
        raise AuditError("Expected Zabbix 7.0.x, got " + version)
    rows = api.call("usermacro.get", {"output": ["macro", "value"], "globalmacro": True, "filter": {"macro": IDENTITY_MACRO}})
    if not rows:
        raise AuditError("server identity unknown: global macro %s is not set on this Zabbix. Refusing (initialise it with the Interface Alerting tool first)" % IDENTITY_MACRO)
    if rows[0]["value"] != env:
        raise AuditError("IDENTITY MISMATCH: this Zabbix says it is '%s' but --env is '%s'. Refusing." % (rows[0]["value"], env))
    return version
