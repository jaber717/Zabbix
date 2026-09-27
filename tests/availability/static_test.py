#!/usr/bin/env python3
"""Static contract checks that do not require a running Zabbix frontend."""

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "frontend" / "modules" / "NetworkAvailability"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


manifest = json.loads((MODULE / "manifest.json").read_text(encoding="utf-8"))
require(manifest["manifest_version"] == 2.0, "Zabbix 7.0 manifest v2 is required")
require(manifest["type"] == "widget", "module must be a widget")
require(manifest["version"] == (MODULE / "VERSION").read_text(encoding="utf-8").strip(),
        "manifest and module release must match")
require(manifest["widget"]["refresh_rate"] >= 10, "refresh must respect the configured floor")
require(manifest["actions"]["networkavailability.config.update"].get("layout") == "layout.json",
        "configuration update action must return the native JSON layout")

definitions = json.loads((MODULE / "config" / "node-definitions.json").read_text(encoding="utf-8"))
require(definitions == {"schema": "network-availability-config-v2", "revision": 1, "sites": [], "nodes": []},
        "repository default must not invent production Nodes")

limits = (MODULE / "config" / "Limits.php").read_text(encoding="utf-8")
for name, value in {
    "STALE_MULTIPLIER": 3,
    "MIN_REFRESH_INTERVAL_S": 10,
    "FLAP_WINDOW_S": 300,
    "FLAP_TRANSITIONS_N": 4,
    "HERO_DWELL_S": 90,
    "SECONDARY_INCIDENTS_MAX": 3,
    "MASS_STALE_THRESHOLD_PCT": 30,
    "MASS_STALE_MIN_N": 5,
    "MASS_STALE_WINDOW_S": 120,
}.items():
    require(re.search(rf"const\s+{name}\s*=\s*{value}\s*;", limits) is not None, f"missing {name}")

collector = (MODULE / "collector" / "ZabbixAvailabilityCollector.php").read_text(encoding="utf-8")
require("API::Host()->get" in collector and "API::Item()->get" in collector, "bulk host/item queries required")
require("API::Service()" not in collector, "Services must not become availability truth")
require("api_call_count" in collector and "problems_retrieved" in collector, "instrumentation is required")
require("value_type" in collector and "'history' => $value_type" in collector,
        "flap history must use each selected item's value type")
require("host.update" not in collector and "DBselect" not in collector, "collector must be API read-only")
require("tag_map']['availability_node" not in collector and "tag_map']['aggregation_policy" not in collector,
        "logical Node policy/membership must not come from Host Tags")
require("'criticality' => null" in collector and "?? 'tier3'" not in collector,
        "unassigned Hosts must keep Tier unset")

intervals = (MODULE / "domain" / "ExpectedIntervalResolver.php").read_text(encoding="utf-8")
require("resolveTimeUnitMacros" in intervals, "Zabbix macro resolution hook is required")
require("expected_interval_s" in intervals, "visible configuration fallback is required")

action = (MODULE / "actions" / "WidgetView.php").read_text(encoding="utf-8")
require("resolver_time_ms" in action and "total_widget_time_ms" in action,
        "resolver and total request timing instrumentation is required")

view = (MODULE / "views" / "widget.view.php").read_text(encoding="utf-8")
require("Needs attention" in view and "Unassigned hosts" in view and "No tier" in view,
        "NOC operational presentation is required")
require("Details" not in view or "na-details-panel" in view, "Details panel must be present")
require("data-instrumentation" in view, "bounded collector performance must remain observable")

resolver = (MODULE / "domain" / "AvailabilityResolver.php").read_text(encoding="utf-8")
require("return ['?'," in resolver and "priority_rank" in resolver, "Tier-unset P? ordering is required")

javascript = (MODULE / "assets" / "js" / "class.widget.js").read_text(encoding="utf-8")
for contract in ("#lastSuccessfulUpdate", "_pauseUpdating()", "isEditMode()", "CSRF_TOKEN_NAME",
                 "#openQuickAssign", "#renderEditor", "#applyFilters"):
    require(contract in javascript, f"missing UI contract: {contract}")
require("localStorage" not in javascript, "runtime configuration must not use browser localStorage")

update = (MODULE / "actions" / "ConfigUpdate.php").read_text(encoding="utf-8")
require("UI_ADMINISTRATION_GENERAL" in update, "server-side edit permission is required")
require("disableCsrfValidation" not in update, "native module CSRF validation must remain enabled")

print("PASS: Availability static contracts")
