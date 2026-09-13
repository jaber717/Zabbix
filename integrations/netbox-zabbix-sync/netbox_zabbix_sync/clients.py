"""Bounded HTTP clients. NetBox permits GET/HEAD only by construction."""

from __future__ import annotations

import json
import ssl
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from .models import Access, Dataset


class ApiFailure(RuntimeError):
    pass


class NetBoxClient:
    ALLOWED_METHODS = frozenset(("GET", "HEAD"))

    def __init__(self, base_url: str, token: str, ca_file: Optional[str], timeout: float = 10, retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.context = ssl.create_default_context(cafile=ca_file) if base_url.startswith("https://") else None
        self.timeout = timeout
        self.retries = retries

    def request(self, method: str, path_or_url: str) -> tuple[int, Any]:
        method = method.upper()
        if method not in self.ALLOWED_METHODS:
            raise ApiFailure(f"NetBox method refused: {method}")
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else urljoin(self.base_url + "/", path_or_url.lstrip("/"))
        expected = urlsplit(self.base_url)
        actual = urlsplit(url)
        if (expected.scheme, expected.hostname, expected.port) != (actual.scheme, actual.hostname, actual.port):
            raise ApiFailure("NetBox pagination crossed the configured origin")
        request = Request(
            url,
            method=method,
            headers={"Accept": "application/json", "Authorization": f"Token {self.token}"},
        )
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, context=self.context, timeout=self.timeout) as response:
                    if method == "HEAD":
                        return response.status, None
                    return response.status, json.load(response)
            except HTTPError as exc:
                if exc.code >= 500 and attempt < self.retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                return exc.code, None
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                raise ApiFailure(f"NetBox request unavailable: {type(exc).__name__}") from exc
        raise ApiFailure("NetBox retry loop exhausted")

    def collection(self, name: str, path: str, page_size: int = 100) -> Dataset:
        url = f"{path}?{urlencode({'limit': page_size, 'offset': 0})}"
        records: list[dict[str, Any]] = []
        while url:
            try:
                status, payload = self.request("GET", url)
            except ApiFailure as exc:
                return Dataset(name, Access.UNAVAILABLE, None, reason=type(exc).__name__)
            if status in (401, 403):
                return Dataset(name, Access.DENIED, None, status=status, reason="permission_denied")
            if not 200 <= status < 300:
                return Dataset(name, Access.UNAVAILABLE, None, status=status, reason="http_error")
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                return Dataset(name, Access.INVALID, None, status=status, reason="unexpected_schema")
            records.extend(item for item in payload["results"] if isinstance(item, dict))
            next_url = payload.get("next")
            url = str(next_url) if next_url else ""
        return Dataset(name, Access.PASS, tuple(records), status=200)


class ZabbixClient:
    def __init__(self, endpoint: str, ca_file: str, timeout: float = 15, retries: int = 2) -> None:
        self.endpoint = endpoint
        self.context = ssl.create_default_context(cafile=ca_file)
        self.timeout = timeout
        self.retries = retries
        self.serial = 0
        self.auth: Optional[str] = None

    def call(self, method: str, params: Any, auth: bool = True) -> Any:
        self.serial += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params, "id": self.serial}
        if auth and self.auth:
            body["auth"] = self.auth
        request = Request(
            self.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json-rpc"},
        )
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, context=self.context, timeout=self.timeout) as response:
                    result = json.load(response)
                if "error" in result:
                    error = result["error"]
                    raise ApiFailure(f"Zabbix {method} failed: {error.get('message', 'API error')}")
                return result["result"]
            except HTTPError as exc:
                if exc.code >= 500 and attempt < self.retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                raise ApiFailure(f"Zabbix HTTP failure: {exc.code}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                raise ApiFailure(f"Zabbix unavailable: {type(exc).__name__}") from exc
        raise ApiFailure("Zabbix retry loop exhausted")

    def login(self, username: str, password: str) -> None:
        self.auth = self.call("user.login", {"username": username, "password": password}, auth=False)

    def inventory(self) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
        hosts = self.call(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status"],
                "selectTags": ["tag", "value"],
                "selectInterfaces": ["interfaceid", "type", "main", "useip", "ip", "dns", "port"],
                "selectGroups": ["groupid", "name"],
                "selectParentTemplates": ["templateid", "name"],
            },
        )
        groups = {item["name"]: item["groupid"] for item in self.call("hostgroup.get", {"output": ["groupid", "name"]})}
        templates = {item["name"]: item["templateid"] for item in self.call("template.get", {"output": ["templateid", "name"]})}
        return hosts, groups, templates

    def create_host(self, values: dict[str, Any], groups: dict[str, str], templates: dict[str, str]) -> Any:
        snmp = any("by SNMP" in name for name in values["templates"])
        interface: dict[str, Any] = {
            "type": 2 if snmp else 1,
            "main": 1,
            "useip": 1,
            "ip": values["management_ip"],
            "dns": "",
            "port": "161" if snmp else "10050",
        }
        if snmp:
            interface["details"] = {
                "version": 3,
                "bulk": 1,
                "securityname": "{$SNMPV3_USER}",
                "securitylevel": 2,
                "authpassphrase": "{$SNMPV3_AUTH_PASSPHRASE}",
                "privpassphrase": "{$SNMPV3_PRIV_PASSPHRASE}",
                "authprotocol": 3,
                "privprotocol": 1,
                "contextname": "{$SNMPV3_CONTEXT}",
            }
        params = {
            "host": values["host"],
            "name": values["display_name"],
            "groups": [{"groupid": groups[name]} for name in values["groups"]],
            "templates": [{"templateid": templates[name]} for name in values["templates"]],
            "interfaces": [interface],
            "tags": [{"tag": key, "value": value} for key, value in values["tags"].items()],
        }
        return self.call("host.create", params)

    def update_host(self, hostid: str, changes: dict[str, Any], groups: dict[str, str], templates: dict[str, str]) -> Any:
        params: dict[str, Any] = {"hostid": hostid}
        for key in ("host", "name", "tags"):
            if key in changes:
                params[key] = changes[key]
        if "groups" in changes:
            params["groups"] = [{"groupid": groups[name]} for name in changes["groups"]]
        result = self.call("host.update", params) if len(params) > 1 else {"hostids": [hostid]}
        if "template_additions" in changes:
            self.call(
                "template.massadd",
                {
                    "templates": [{"templateid": templates[name]} for name in changes["template_additions"]],
                    "hosts": [{"hostid": hostid}],
                },
            )
        return result
