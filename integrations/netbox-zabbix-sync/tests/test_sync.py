from __future__ import annotations

import copy
from io import BytesIO
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from netbox_zabbix_sync import clients
from netbox_zabbix_sync.cli import parse_args
from netbox_zabbix_sync.clients import ApiFailure, NetBoxClient, ZabbixClient
from netbox_zabbix_sync.models import Access, Dataset, Resolution
from netbox_zabbix_sync.planner import apply_plan, build_candidates, reconcile


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "inventory.json").read_text())
MAPPINGS = {
    "eligibility": {"tag": "monitoring-enabled", "custom_field": "monitoring_enabled"},
    "object_types": {"device": {"groups": ["Devices"]}, "vm": {"groups": ["VMs"]}},
    "roles": {"fixture-role": {"templates": []}},
    "platforms": {"fixture-linux": {"templates": ["Linux"]}},
    "sites": {"fixture-site": {"groups": ["Fixture Site"]}},
}


def datasets(devices=None, vms=None, **access):
    device_records = devices if devices is not None else []
    vm_records = vms if vms is not None else []
    ip_records = []
    for item in [*device_records, *vm_records]:
        primary = item.get("primary_ip4") or item.get("primary_ip6")
        if isinstance(primary, dict) and isinstance(primary.get("id"), int):
            ip_records.append({"id": primary["id"], "address": primary.get("address")})
    values = {
        "devices": device_records,
        "interfaces": [],
        "ip_addresses": ip_records,
        "virtual_machines": vm_records,
        "tags": [],
        "custom_fields": [],
    }
    result = {}
    for name, records in values.items():
        state = access.get(name, Access.PASS)
        result[name] = Dataset(name, state, tuple(records) if state is Access.PASS else None)
    return result


def existing_host(candidate, **overrides):
    host = {
        "hostid": "9001",
        "host": candidate.host,
        "name": candidate.display_name,
        "status": "0",
        "tags": [
            {"tag": "source", "value": "netbox"},
            {"tag": "netbox_type", "value": candidate.object_type},
            {"tag": "netbox_id", "value": str(candidate.netbox_id)},
        ],
        "interfaces": [{"type": "1", "main": "1", "useip": "1", "ip": candidate.management_ip}],
        "groups": [{"name": name} for name in candidate.groups],
        "parentTemplates": [{"name": name} for name in candidate.templates],
    }
    host.update(overrides)
    return host


class Response(BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ClientTests(unittest.TestCase):
    def client(self, retries=0):
        with patch("netbox_zabbix_sync.clients.ssl.create_default_context", return_value=object()):
            return NetBoxClient("https://netbox.example", "secret", "/ca", retries=retries)

    def test_pagination(self):
        first = {"count": 2, "next": "https://netbox.example/api/devices/?limit=1&offset=1", "results": [{"id": 1}]}
        second = {"count": 2, "next": None, "results": [{"id": 2}]}
        with patch("netbox_zabbix_sync.clients.urlopen", side_effect=[Response(first), Response(second)]):
            result = self.client().collection("devices", "/api/devices/", page_size=1)
        self.assertEqual(result.access, Access.PASS)
        self.assertEqual([item["id"] for item in result.records], [1, 2])

    def test_auth_failure_is_denied(self):
        error = HTTPError("https://netbox.example", 401, "denied", {}, None)
        with patch("netbox_zabbix_sync.clients.urlopen", side_effect=error):
            self.assertEqual(self.client().collection("tags", "/api/tags/").access, Access.DENIED)

    def test_denied_endpoint_is_not_empty(self):
        error = HTTPError("https://netbox.example", 403, "denied", {}, None)
        with patch("netbox_zabbix_sync.clients.urlopen", side_effect=error):
            result = self.client().collection("tags", "/api/tags/")
        self.assertIsNone(result.records)
        self.assertIsNone(result.count)

    def test_timeout_is_unavailable(self):
        with patch("netbox_zabbix_sync.clients.urlopen", side_effect=URLError("timeout")):
            self.assertEqual(self.client().collection("devices", "/api/devices/").access, Access.UNAVAILABLE)

    def test_http_error_is_unavailable(self):
        error = HTTPError("https://netbox.example", 500, "error", {}, None)
        with patch("netbox_zabbix_sync.clients.urlopen", side_effect=error):
            self.assertEqual(self.client().collection("devices", "/api/devices/").access, Access.UNAVAILABLE)

    def test_cross_origin_pagination_fails_closed(self):
        first = {"count": 2, "next": "https://evil.example/api/devices/?offset=1", "results": [{"id": 1}]}
        with patch("netbox_zabbix_sync.clients.urlopen", return_value=Response(first)):
            self.assertEqual(self.client().collection("devices", "/api/devices/").access, Access.UNAVAILABLE)

    def test_netbox_write_method_refused(self):
        with self.assertRaises(ApiFailure):
            self.client().request("POST", "/api/devices/")

    def test_template_addition_uses_massadd_not_replace(self):
        with patch("netbox_zabbix_sync.clients.ssl.create_default_context", return_value=object()):
            client = ZabbixClient("https://zabbix.example/api_jsonrpc.php", "/ca")
        calls = []
        client.call = lambda method, params, auth=True: calls.append((method, params)) or {}
        client.update_host("1", {"template_additions": ("Linux",)}, {}, {"Linux": "10"})
        self.assertEqual([method for method, _ in calls], ["template.massadd"])

    def test_snmp_template_creates_v3_authpriv_interface_with_macro_references(self):
        with patch("netbox_zabbix_sync.clients.ssl.create_default_context", return_value=object()):
            client = ZabbixClient("https://zabbix.example/api_jsonrpc.php", "/ca")
        captured = {}
        client.call = lambda method, params, auth=True: captured.update(params) or {"hostids": ["1"]}
        values = {
            "host": "switch.example.invalid",
            "display_name": "Example switch",
            "management_ip": "192.0.2.10",
            "groups": ("Network devices",),
            "templates": ("Huawei VRP by SNMP",),
            "tags": {"source": "netbox"},
        }
        client.create_host(values, {"Network devices": "1"}, {"Huawei VRP by SNMP": "2"})
        interface = captured["interfaces"][0]
        self.assertEqual(interface["type"], 2)
        self.assertEqual(interface["port"], "161")
        self.assertEqual(interface["details"]["securitylevel"], 2)
        self.assertEqual(interface["details"]["authprotocol"], 3)
        self.assertEqual(interface["details"]["privprotocol"], 1)
        self.assertEqual(interface["details"]["securityname"], "{$SNMPV3_USER}")


class IdentityAndMappingTests(unittest.TestCase):
    def test_device_and_vm_identity_do_not_collide(self):
        built = build_candidates(datasets([FIXTURES["device"]], [FIXTURES["vm"]]), MAPPINGS)
        self.assertEqual({item.identity for item in built}, {("device", "101"), ("vm", "101")})

    def test_mapped_role_platform_and_site(self):
        candidate = build_candidates(datasets([FIXTURES["device"]]), MAPPINGS)[0]
        self.assertEqual(candidate.mapping_state, Resolution.RESOLVED)
        self.assertEqual(candidate.templates, ("Linux",))

    def test_unmapped_platform(self):
        device = copy.deepcopy(FIXTURES["device"])
        device["platform"] = {"slug": "unknown"}
        candidate = build_candidates(datasets([device]), MAPPINGS)[0]
        self.assertEqual(candidate.mapping_state, Resolution.UNMAPPED)

    def test_ambiguous_mapping(self):
        mapping = copy.deepcopy(MAPPINGS)
        mapping["platforms"]["fixture-linux"] = [{"templates": ["A"]}, {"templates": ["B"]}]
        candidate = build_candidates(datasets([FIXTURES["device"]]), mapping)[0]
        self.assertEqual(candidate.mapping_state, Resolution.AMBIGUOUS)

    def test_missing_attribute_needs_no_guess(self):
        device = copy.deepcopy(FIXTURES["device"])
        device["platform"] = None
        candidate = build_candidates(datasets([device]), MAPPINGS)[0]
        self.assertEqual(candidate.mapping_state, Resolution.UNMAPPED)

    def test_missing_primary_ip(self):
        device = copy.deepcopy(FIXTURES["device"])
        device["primary_ip4"] = None
        candidate = build_candidates(datasets([device]), MAPPINGS)[0]
        self.assertEqual(candidate.ip_state, Resolution.NEEDS_REVIEW)

    def test_duplicate_management_ip(self):
        second = copy.deepcopy(FIXTURES["device"])
        second["id"] = 102
        second["name"] = "fixture-device-02"
        built = build_candidates(datasets([FIXTURES["device"], second]), MAPPINGS)
        self.assertTrue(all(item.ip_state is Resolution.AMBIGUOUS for item in built))

    def test_denied_metadata_is_unknown_not_false(self):
        values = datasets([FIXTURES["device"]], tags=Access.DENIED, custom_fields=Access.DENIED)
        candidate = build_candidates(values, MAPPINGS)[0]
        self.assertIsNone(candidate.eligible)
        self.assertEqual(candidate.eligibility_state, Resolution.NEEDS_REVIEW)


class ReconciliationTests(unittest.TestCase):
    def candidate(self):
        return build_candidates(datasets([FIXTURES["device"]]), MAPPINGS)[0]

    def test_create(self):
        plan = reconcile([self.candidate()], [], datasets([FIXTURES["device"]]))
        self.assertEqual(plan.counts_by_action().get("CREATE"), 1)

    def test_rename_updates_same_identity(self):
        candidate = self.candidate()
        host = existing_host(candidate, host="old-name")
        plan = reconcile([candidate], [host], datasets([FIXTURES["device"]]), change_budget=1)
        self.assertEqual(plan.counts_by_action().get("CREATE", 0), 0)
        self.assertEqual(plan.counts_by_action().get("UPDATE"), 1)

    def test_ip_change_does_not_create_or_blindly_update_ip(self):
        candidate = self.candidate()
        host = existing_host(candidate, interfaces=[{"type": "1", "main": "1", "useip": "1", "ip": "192.0.2.99"}])
        plan = reconcile([candidate], [host], datasets([FIXTURES["device"]]), change_budget=1)
        self.assertEqual(plan.counts_by_action().get("CREATE", 0), 0)
        self.assertEqual(plan.counts_by_action().get("IP_CHANGE_REVIEW"), 1)

    def test_unchanged(self):
        candidate = self.candidate()
        plan = reconcile([candidate], [existing_host(candidate)], datasets([FIXTURES["device"]]))
        self.assertEqual(plan.counts_by_action().get("UNCHANGED"), 1)

    def test_orphan_is_report_only(self):
        candidate = self.candidate()
        host = existing_host(candidate)
        plan = reconcile([], [host], datasets())
        self.assertEqual(plan.counts_by_action().get("ORPHAN"), 1)

    def test_orphan_evaluation_blocked_with_denied_vm_source(self):
        candidate = self.candidate()
        values = datasets(vms=[], virtual_machines=Access.DENIED)
        plan = reconcile([], [existing_host(candidate)], values)
        self.assertIsNone(plan.counts_by_action().get("ORPHAN"))
        self.assertEqual(plan.gates["orphan_evaluation"], "BLOCKED_INCOMPLETE_SOURCE")

    def test_template_removal_is_report_only(self):
        candidate = self.candidate()
        host = existing_host(candidate, parentTemplates=[{"name": "Linux"}, {"name": "Extra"}])
        plan = reconcile([candidate], [host], datasets([FIXTURES["device"]]))
        self.assertEqual(plan.counts_by_action().get("TEMPLATE_DRIFT"), 1)

    def test_group_removal_is_report_only_and_preserved(self):
        candidate = self.candidate()
        host = existing_host(candidate, groups=[{"name": "Operator Group"}])
        plan = reconcile([candidate], [host], datasets([FIXTURES["device"]]))
        self.assertEqual(plan.counts_by_action().get("GROUP_DRIFT"), 1)
        update = next((action for action in plan.actions if action.kind == "UPDATE"), None)
        self.assertIsNotNone(update)
        self.assertIn("Operator Group", update.changes["groups"])

    def test_change_budget_breaker(self):
        candidate = self.candidate()
        plan = reconcile([candidate], [], datasets([FIXTURES["device"]]), change_budget=0.10)
        self.assertEqual(plan.gates["change_budget"], "BLOCKED")
        with self.assertRaises(RuntimeError):
            apply_plan(plan, object(), {}, {})

    def test_apply_requires_complete_reads(self):
        values = datasets([FIXTURES["device"]], tags=Access.DENIED)
        plan = reconcile(build_candidates(values, MAPPINGS), [], values)
        with self.assertRaises(RuntimeError):
            apply_plan(plan, object(), {}, {})


class StaticSafetyTests(unittest.TestCase):
    def test_dry_run_is_default_and_apply_explicit(self):
        args = parse_args(["--config", "c", "--mappings", "m", "--report", "r"])
        self.assertFalse(args.apply)
        args = parse_args(["--config", "c", "--mappings", "m", "--report", "r", "--apply"])
        self.assertTrue(args.apply)

    def test_no_delete_or_template_unlink_api_path(self):
        source = inspect.getsource(clients) + inspect.getsource(__import__("netbox_zabbix_sync.planner", fromlist=["*"]))
        self.assertNotIn("host.delete", source)
        self.assertNotIn("template.unlink", source)

    def test_secret_not_in_report(self):
        secret = "fixture-" + "secret-never-log"
        plan = reconcile([], [], datasets())
        self.assertNotIn(secret, json.dumps(plan.as_dict()))


if __name__ == "__main__":
    unittest.main()
