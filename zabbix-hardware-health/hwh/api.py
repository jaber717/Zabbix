"""Minimal Zabbix JSON-RPC client with a method allowlist. Reads are always allowed; writes exist only for the NETOPS Hardware Health action
and only when the client is opened with write=True (never by the audit)."""
import json
import urllib.error
import urllib.request

READ_METHODS = frozenset(["apiinfo.version", "host.get", "item.get", "trigger.get", "usermacro.get",
                          "action.get", "usergroup.get", "mediatype.get", "hostgroup.get", "user.get", "alert.get", "event.get",
                          "auditlog.get", "history.get", "settings.get", "template.get", "configuration.export", "configuration.importcompare"])
TEMPLATE_WRITE_METHODS = frozenset(["configuration.import", "template.delete"])
ACTION_WRITE_METHODS = frozenset(["action.create", "action.update", "action.delete"])


class AuditError(Exception):
    pass


class ZabbixAPI(object):
    def __init__(self, url, token, transport=None, write=False, write_templates=False):
        if not url.startswith("https://") and not url.startswith("http://"):
            raise AuditError("Zabbix URL must include http:// or https://")
        self.base_url = url.rstrip("/")
        self.url = self.base_url
        if not self.url.endswith("/api_jsonrpc.php"):
            self.url += "/api_jsonrpc.php"
        self.token = token
        self.transport = transport or urllib.request.urlopen
        self.write = write
        self.write_templates = write_templates
        self.seq = 0
        self.log = []                      # [(method, is_write)] - audit trail, never params

    def call(self, method, params=None):
        is_write = method in ACTION_WRITE_METHODS or method in TEMPLATE_WRITE_METHODS
        allowed = (method in ACTION_WRITE_METHODS and self.write) or (method in TEMPLATE_WRITE_METHODS and self.write_templates)
        if method not in READ_METHODS and not allowed:
            raise AuditError("API allowlist refused " + method)
        self.seq += 1
        self.log.append((method, is_write))
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params if params is not None else {},
                           "id": self.seq}).encode("utf-8")
        headers = {"Content-Type": "application/json-rpc"}
        if method != "apiinfo.version":
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with self.transport(req, timeout=20) as response:
                result = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise AuditError("Zabbix API request failed: " + str(exc)) from exc
        if "error" in result:
            # never echo request headers/tokens
            raise AuditError("Zabbix API rejected " + method + ": " + str(result["error"].get("message", "unknown"))
                             + " " + str(result["error"].get("data", ""))[:160])
        return result["result"]

    def writes_made(self):
        return [m for m, w in self.log if w]
