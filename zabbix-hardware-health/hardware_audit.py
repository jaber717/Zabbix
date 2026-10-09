#!/usr/bin/env python3
"""Read-only hardware coverage and freshness audit for Zabbix 7.0.
Never calls write API methods, never creates triggers or actions.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import yaml

CATEGORIES = ("fan", "power", "temperature", "redundancy")
PATTERNS = {
    "fan": re.compile(r"\b(?:fans?|blowers?|fantray|fan.tray)\b", re.I),
    "power": re.compile(r"\b(?:psu|ps[12]|power[\s_-]*suppl(?:y|ies)|power[\s_-]*modules?|pwr)\b", re.I),
    "temperature": re.compile(r"\b(?:temperatures?|thermal|overheat|thermometer)\b", re.I),
    "redundancy": re.compile(r"\b(?:redundan(?:t|cy)|lost[\s_-]*redundancy)\b", re.I),
}
DEFAULT_AGE_MINUTES = 480


class AuditError(Exception):
    pass


def classify(text):
    """Conservative category hints, NOT an assertion of hardware state."""
    text = str(text or "")
    matches = [k for k in CATEGORIES if PATTERNS[k].search(text)]
    # A PSU fan is a fan sensor, not proof that the PSU itself is monitored.
    if "fan" in matches:
        matches = [k for k in matches if k != "power"]
    return matches


def load_config(path, environment):
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict) or config.get("environment") != environment:
        raise AuditError("Configuration environment mismatch")
    if set(config) - {"environment", "hosts"}:
        raise AuditError("Unknown top-level configuration keys")
    hosts = config.get("hosts")
    if not isinstance(hosts, dict):
        raise AuditError("hosts must be a mapping")
    for name, settings in hosts.items():
        if not isinstance(name, str) or not name:
            raise AuditError("Host name must be a nonempty string")
        if not isinstance(settings, dict):
            raise AuditError("Host settings must be a mapping: " + name)
        if set(settings) - {"site", "vendor", "expected", "max_sensor_age_minutes"}:
            raise AuditError("Unknown host setting for " + name)
        expected = settings.get("expected")
        if not isinstance(expected, list) or not expected or len(set(expected)) != len(expected):
            raise AuditError("Host needs a unique nonempty expected list: " + name)
        if any(v not in CATEGORIES for v in expected):
            raise AuditError("Unrecognized expected category for " + name)
        age = settings.get("max_sensor_age_minutes", DEFAULT_AGE_MINUTES)
        if type(age) is not int or not 1 <= age <= 10080:
            raise AuditError("Invalid max_sensor_age_minutes for " + name)
    return config


class ZabbixAPI:
    def __init__(self, url, token, transport=None):
        if not url.startswith("https://") and not url.startswith("http://"):
            raise AuditError("Zabbix URL must include http:// or https://")
        self.url = url.rstrip("/")
        if not self.url.endswith("/api_jsonrpc.php"):
            self.url += "/api_jsonrpc.php"
        self.token = token
        self.transport = transport or urllib.request.urlopen
        self.seq = 0

    def call(self, method, params=None):
        if method not in ("apiinfo.version", "host.get", "item.get", "trigger.get"):
            raise AuditError("Read-only API allowlist refused " + method)
        self.seq += 1
        body = json.dumps({"jsonrpc": "2.0", "method": method,
                           "params": params or {}, "id": self.seq}).encode("utf-8")
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
            # Do not leak API tokens or request headers.
            raise AuditError("Zabbix API rejected " + method + ": " +
                             str(result["error"].get("message", "unknown")))
        return result["result"]


def scan_host(api, name, settings, now=None):
    now = int(time.time()) if now is None else int(now)
    age_limit = settings.get("max_sensor_age_minutes", DEFAULT_AGE_MINUTES) * 60
    host_rows = api.call("host.get", {"output": ["hostid", "host", "status"],
                         "filter": {"host": [name]}, "selectParentTemplates": ["name"]})
    if len(host_rows) != 1:
        return {"host": name, "site": settings.get("site", ""), "status": "HOST_NOT_FOUND",
                "coverage": {}, "sensor_count": 0, "trigger_count": 0}
    host = host_rows[0]
    hid = host["hostid"]
    items = api.call("item.get", {"hostids": [hid],
                     "output": ["itemid", "name", "key_", "status", "state", "lastclock", "error"]})
    triggers = api.call("trigger.get", {"hostids": [hid],
                        "output": ["triggerid", "description", "status", "priority"],
                        "selectTags": ["tag", "value"],
                        "selectItems": ["itemid", "key_"]})
    result = {
        "host": name, "site": settings.get("site", ""),
        "vendor": settings.get("vendor", ""),
        "status": "HOST_DISABLED" if str(host["status"]) != "0" else "MONITORED",
        "templates": sorted(t["name"] for t in host.get("parentTemplates", [])),
        "sensor_count": 0, "trigger_count": 0, "coverage": {}
    }
    item_by_id = {str(i["itemid"]): i for i in items}
    for category in settings["expected"]:
        category_items = []
        category_triggers = []
        for item in items:
            if category in classify(item.get("name", "") + " " + item.get("key_", "")):
                category_items.append(item)
        for trigger in triggers:
            related = [item_by_id.get(str(x.get("itemid")), {}) for x in trigger.get("items", [])]
            hint = trigger.get("description", "") + " " + " ".join(
                x.get("key_", "") for x in related)
            if category in classify(hint):
                category_triggers.append(trigger)
        healthy_items = [i for i in category_items
                         if str(i.get("status")) == "0" and str(i.get("state")) == "0"
                         and 0 < now - int(i.get("lastclock") or 0) <= age_limit]
        enabled_triggers = [t for t in category_triggers if str(t.get("status")) == "0"]
        observed_tags = sorted({(x.get("tag", ""), x.get("value", ""))
                               for t in enabled_triggers for x in t.get("tags", [])})
        observed_tags = [{"tag": k, "value": v} for k, v in observed_tags]
        if not category_items:
            state = "NO_SENSOR_ITEMS"
        elif not enabled_triggers:
            state = "NO_ENABLED_TRIGGERS"
        elif not healthy_items:
            state = "STALE_OR_UNSUPPORTED"
        else:
            state = "COVERED"
        result["coverage"][category] = {
            "state": state, "item_count": len(category_items),
            "fresh_supported_items": len(healthy_items),
            "enabled_trigger_count": len(enabled_triggers),
            "event_tags": observed_tags,
            "trigger_examples": [x["description"] for x in enabled_triggers[:5]],
        }
        result["sensor_count"] += len(category_items)
        result["trigger_count"] += len(enabled_triggers)
    if result["status"] == "MONITORED" and all(
            v["state"] == "COVERED" for v in result["coverage"].values()):
        result["status"] = "COVERED"
    else:
        result["status"] = "REVIEW_REQUIRED"
    return result


def audit(api, config):
    version = api.call("apiinfo.version")
    if not str(version).startswith("7.0."):
        raise AuditError("Expected Zabbix 7.0.x, got " + str(version))
    report = {"project": "NETOPS Hardware Health", "schema": 1,
              "environment": config["environment"], "zabbix_version": version,
              "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "hosts": [], "summary": {"covered": 0, "review_required": 0}}
    for name, settings in sorted(config["hosts"].items()):
        h = scan_host(api, name, settings)
        report["hosts"].append(h)
        if h["status"] == "COVERED":
            report["summary"]["covered"] += 1
        else:
            report["summary"]["review_required"] += 1
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Zabbix hardware coverage audit")
    parser.add_argument("--env", choices=["lab", "production"], required=True)
    parser.add_argument("--config", help="Explicit policy file")
    parser.add_argument("--output", help="Optional JSON report path")
    args = parser.parse_args(argv)
    config_path = args.config or ("config/hardware." + args.env + ".yaml")
    try:
        cfg = load_config(config_path, args.env)
        if not cfg["hosts"]:
            raise AuditError("No approved hosts in inventory. Audit not run.")
        suffix = args.env.upper()
        url = os.environ.get("ZABBIX_HARDWARE_URL_" + suffix, "")
        token = os.environ.get("ZABBIX_HARDWARE_TOKEN_" + suffix, "")
        if not url or not token:
            raise AuditError("Set environment-specific ZABBIX_HARDWARE_URL_ and TOKEN_ variables")
        report = audit(ZabbixAPI(url, token), cfg)
        encoded = json.dumps(report, indent=2, sort_keys=True)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(encoded + "\n")
        print(encoded)
        return 2 if report["summary"]["review_required"] else 0
    except (AuditError, OSError, yaml.YAMLError) as exc:
        print("HARDWARE AUDIT INCOMPLETE: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
