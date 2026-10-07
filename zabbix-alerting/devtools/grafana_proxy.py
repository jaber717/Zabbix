"""DEV ONLY: a read-only transport that reaches a Zabbix through the Grafana datasource proxy.

Used to validate the read side of this tool (host lookup, interface names, ownership scan)
against a live LAB when only a read-only account is available. It is not part of the
operator workflow and cannot write: the proxy exposes read methods only, and the client
below is opened read-only anyway.
"""
import base64
import json
import ssl
import urllib.request

from netalert.zbx import ApiUnavailable


class GrafanaProxyTransport(object):
    def __init__(self, grafana_url, user, password, datasource_uid="zabbix-lab", verify_tls=False):
        self.url = "%s/api/datasources/uid/%s/resources/zabbix-api" % (grafana_url.rstrip("/"), datasource_uid)
        self._auth = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
        self._ctx = None if verify_tls else ssl._create_unverified_context()

    def send(self, payload, authenticated=True):
        body = json.dumps({"method": payload["method"], "params": payload.get("params") or {}}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json",
                                                       "Authorization": self._auth})
        try:
            with urllib.request.urlopen(req, timeout=40, context=self._ctx) as r:
                data = json.loads(r.read().decode())
        except Exception as exc:                      # noqa: BLE001 - any failure means "unreachable"
            raise ApiUnavailable("grafana proxy: %s" % exc)
        if "error" in data:
            return {"jsonrpc": "2.0", "id": payload["id"],
                    "error": {"code": -32500, "message": str(data.get("message") or data["error"]), "data": ""}}
        return {"jsonrpc": "2.0", "id": payload["id"], "result": data["result"]}
