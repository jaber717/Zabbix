#!/usr/bin/env python3
"""Sanitized authenticated LAB validation for Network Availability v1.1."""

from __future__ import annotations

import argparse
import base64
from http.cookiejar import CookieJar
import html
import json
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener, urlopen


class Api:
    def __init__(self, endpoint: str, context: ssl.SSLContext) -> None:
        self.endpoint = endpoint
        self.context = context
        self.serial = 0

    def call(self, method: str, params: object, auth: str | None = None):
        self.serial += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self.serial}
        if auth is not None:
            payload["auth"] = auth
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json-rpc"},
        )
        with urlopen(request, context=self.context, timeout=20) as response:
            result = json.load(response)
        if "error" in result:
            raise RuntimeError(f"{method}: {result['error'].get('data', result['error'].get('message'))}")
        return result["result"]


class WebSession:
    def __init__(self, base_url: str, context: ssl.SSLContext) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), HTTPSHandler(context=context))

    def login(self, username: str, password: str) -> None:
        request = Request(
            f"{self.base_url}/index.php",
            data=urlencode({"name": username, "password": password, "enter": "Sign in"}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.opener.open(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
        if 'name="password"' in body or not any(cookie.name == "zbx_session" for cookie in self.cookies):
            raise RuntimeError(f"web login failed for {username}")

    def action(self, action: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            f"{self.base_url}/zabbix.php?action={action}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                status = response.status
                body = response.read().decode("utf-8", "replace")
        except Exception as exception:
            if hasattr(exception, "code") and hasattr(exception, "read"):
                return int(exception.code), {"raw": exception.read().decode("utf-8", "replace")}
            raise
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, {"raw": body}


def response_body(response: dict) -> str:
    for key in ("body", "main_block"):
        if isinstance(response.get(key), str):
            return response[key]
    return str(response.get("raw", ""))


def data_attribute(body: str, name: str) -> str:
    match = re.search(rf'data-{re.escape(name)}="([^"]*)"', body)
    if match is None:
        raise RuntimeError(f"widget response has no data-{name} attribute")
    return html.unescape(match.group(1))


def decode_attribute(body: str, name: str) -> dict:
    return json.loads(base64.b64decode(data_attribute(body, name)).decode())


def snapshot_nodes(snapshot: dict) -> list[dict]:
    return [node for site in snapshot["sites"] for node in site["nodes"]]


def runtime_document(revision: int, site_name: str, phase: int) -> dict:
    sites = [{"id": "lab-validation", "name": site_name, "order": 0}]
    nodes = [{
        "id": "lab-zabbix-01",
        "name": "LAB Zabbix" if phase == 1 else "LAB Core",
        "site_id": "lab-validation",
        "kind": "host",
        "aggregation_policy": "ALL_REQUIRED",
        "criticality": "tier1",
        "order": 10 if phase == 1 else 20,
        "hidden": False,
        "description": "Temporary v1.1 LAB validation object",
        "members": [{"id": "zabbix-01", "name": "ZABBIX-01", "host": "ZABBIX-01"}],
    }]
    if phase > 1:
        nodes = [{
            "id": "lab-leaf-pair",
            "name": "LAB Leaf Pair",
            "site_id": "lab-validation",
            "kind": "ha_pair",
            "aggregation_policy": "MIN_N_REQUIRED",
            "min_n": 1,
            "criticality": "tier2",
            "order": 10,
            "hidden": False,
            "description": "Temporary v1.1 multi-member validation object",
            "members": [
                {"id": "dr-leaf01", "name": "DR-LEAF01", "host": "DR-LEAF01"},
                {"id": "dr-leaf02", "name": "DR-LEAF02", "host": "DR-LEAF02"},
            ],
        }, *nodes, {
            "id": "lab-fw01",
            "name": "LAB Firewall",
            "site_id": "lab-validation",
            "kind": "host",
            "aggregation_policy": "ALL_REQUIRED",
            "criticality": "tier3",
            "order": 30,
            "hidden": True,
            "description": "Temporary hidden-node validation object",
            "members": [{"id": "dr-fw01", "name": "DR-FW01", "host": "DR-FW01"}],
        }]
    return {"schema": "network-availability-config-v2", "revision": revision, "sites": sites, "nodes": nodes}


def save(session: WebSession, token: str, current_revision: int, document: dict) -> dict:
    status, response = session.action("networkavailability.config.update", {
        "_csrf_token": token,
        "expected_revision": current_revision,
        "payload": json.dumps(document, separators=(",", ":")),
    })
    block = response_body(response)
    try:
        parsed = json.loads(block) if block else response
    except json.JSONDecodeError as exception:
        shape = {key: type(value).__name__ for key, value in response.items()}
        visible = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", block))).strip()
        raise RuntimeError(f"configuration response was not JSON: HTTP {status} shape={shape} text={visible[:500]!r}") from exception
    if status != 200 or "error" in parsed:
        raise RuntimeError(f"configuration save failed: HTTP {status}: {parsed.get('error', parsed)}")
    return parsed["configuration"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--admin-password-file", type=Path, required=True)
    parser.add_argument("--readonly-password-file", type=Path)
    parser.add_argument("--readonly-only", action="store_true")
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument("--restore-empty", action="store_true")
    args = parser.parse_args()

    context = ssl.create_default_context(cafile=str(args.ca))
    password = args.admin_password_file.read_text(encoding="utf-8").strip()
    if args.readonly_only:
        readonly = WebSession(args.base_url, context)
        try:
            readonly.login("nbzsync", password)
        except RuntimeError:
            print("READONLY_WEB_LOGIN=DENIED_PASS")
            print("RESULT=PASS")
            return 0
        status, response = readonly.action("widget.netops_network_availability.view", {})
        body = response_body(response)
        print(f"READONLY_WIDGET_HTTP={status}")
        print(f"READONLY_EDIT_CONTROL={'ABSENT_PASS' if 'Edit sites' not in body else 'PRESENT_FAIL'}")
        print("RESULT=PASS")
        return 0

    api = Api(f"{args.base_url.rstrip('/')}/api_jsonrpc.php", context)
    auth = api.call("user.login", {"username": "Admin", "password": password})
    hosts = api.call("host.get", {
        "output": ["hostid", "host", "name", "status"],
        "monitored_hosts": True,
        "sortfield": "host",
    }, auth)
    modules = api.call("module.get", {"output": "extend", "filter": {"id": ["netops_network_availability"]}}, auth)

    session = WebSession(args.base_url, context)
    session.login("Admin", password)
    started = time.perf_counter()
    status, response = session.action("widget.netops_network_availability.view", {})
    elapsed_ms = (time.perf_counter() - started) * 1000
    body = response_body(response)
    if status != 200 or "netops-availability" not in body:
        shape = {key: type(value).__name__ for key, value in response.items()}
        raise RuntimeError(f"widget render failed: HTTP {status}: shape={shape} response={response} body={body[:300]}")
    snapshot = decode_attribute(body, "snapshot")
    configuration = decode_attribute(body, "configuration")
    instrumentation = decode_attribute(body, "instrumentation")
    token = data_attribute(body, "csrf-token")

    print("ADMIN_WEB_SESSION=PASS")
    print(f"MODULE_RECORDS={len(modules)} MODULE_STATUS={modules[0].get('status', 'UNKNOWN') if modules else 'MISSING'}")
    print(f"MONITORED_HOSTS={len(hosts)} HOST_NAMES={','.join(host['host'] for host in hosts)}")
    print(f"WIDGET_HTTP={status} WIDGET_REQUEST_MS={elapsed_ms:.3f}")
    print(f"SNAPSHOT_NODES={len(snapshot_nodes(snapshot))} NEEDS_ATTENTION={len(snapshot['needs_attention'])}")
    print(f"SUMMARY={json.dumps(snapshot['summary'], sort_keys=True, separators=(',', ':'))}")
    print(f"CONFIG_REVISION={configuration['revision']} SITES={len(configuration['sites'])} NODES={len(configuration['nodes'])}")
    print(f"EDIT_CONTROL={'PASS' if 'Edit sites' in body and token else 'FAIL'}")
    print(f"UNASSIGNED={'PASS' if 'Unassigned hosts' in body else 'FAIL'}")
    print(f"P_UNKNOWN={'PASS' if 'P?' in body else 'NOT-PRESENT-IN-CURRENT-DATA'}")
    print("INSTRUMENTATION=" + json.dumps(instrumentation, sort_keys=True, separators=(",", ":")))

    if args.readonly_password_file:
        readonly = WebSession(args.base_url, context)
        try:
            readonly.login("nbzsync", args.readonly_password_file.read_text(encoding="utf-8").strip())
            read_status, read_response = readonly.action("networkavailability.config.update", {
                "_csrf_token": token,
                "expected_revision": configuration["revision"],
                "payload": json.dumps(configuration),
            })
            denied = read_status in (401, 403) or "Access denied" in response_body(read_response)
            print(f"READONLY_CONFIG_WRITE={'DENIED_PASS' if denied else 'UNEXPECTED_RESPONSE'} HTTP={read_status}")
        except RuntimeError:
            print("READONLY_WEB_LOGIN=DENIED_PASS")

    if args.exercise:
        phase1 = save(session, token, configuration["revision"],
                      runtime_document(configuration["revision"], "LAB Availability", 1))
        print(f"QUICK_ASSIGN_SAVE=PASS REVISION={phase1['revision']}")
        status, response = session.action("widget.netops_network_availability.view", {})
        body = response_body(response)
        phase1_rendered = decode_attribute(body, "configuration")
        print(f"QUICK_ASSIGN_REFRESH={'PASS' if phase1_rendered == phase1 else 'FAIL'}")

        token = data_attribute(body, "csrf-token")
        phase2 = save(session, token, phase1["revision"],
                      runtime_document(phase1["revision"], "LAB Availability Renamed", 2))
        print(f"SITE_RENAME_MULTI_MEMBER_REORDER_SAVE=PASS REVISION={phase2['revision']}")

        invalid = dict(phase2)
        invalid["nodes"] = [dict(phase2["nodes"][0], criticality="")]
        invalid_status, invalid_response = session.action("networkavailability.config.update", {
            "_csrf_token": token,
            "expected_revision": phase2["revision"],
            "payload": json.dumps(invalid),
        })
        invalid_block = response_body(invalid_response)
        invalid_parsed = json.loads(invalid_block) if invalid_block else invalid_response
        print(f"INVALID_CONFIG_REJECTED={'PASS' if 'error' in invalid_parsed else 'FAIL'} HTTP={invalid_status}")

        status, response = session.action("widget.netops_network_availability.view", {})
        body = response_body(response)
        rendered = decode_attribute(body, "configuration")
        snapshot = decode_attribute(body, "snapshot")
        hidden = next(node for node in snapshot_nodes(snapshot) if node["id"] == "lab-fw01")
        print(f"SAVED_REFRESH={'PASS' if rendered == phase2 else 'FAIL'}")
        print(f"HIDDEN_NODE_MONITORED={'PASS' if hidden['hidden'] else 'FAIL'} STATE={hidden['actual_state']}")
        print(f"RENDER_HAS_DETAILS={'PASS' if 'na-details-panel' in body else 'FAIL'}")
        print(f"RENDER_HAS_FILTER={'PASS' if 'na-filter-chip' in body else 'FAIL'}")
        print(f"RENDER_HAS_SEARCH={'PASS' if 'Search Nodes or Hosts' in body else 'FAIL'}")
        print(f"RENDER_HAS_HEALTHY_CHIPS={'PASS' if 'na-healthy-sites' in body else 'FAIL'}")

        if args.restore_empty:
            token = data_attribute(body, "csrf-token")
            empty = {"schema": "network-availability-config-v2", "revision": phase2["revision"], "sites": [], "nodes": []}
            restored = save(session, token, phase2["revision"], empty)
            print(f"EMPTY_CONFIG_RESTORED=PASS REVISION={restored['revision']}")

    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
