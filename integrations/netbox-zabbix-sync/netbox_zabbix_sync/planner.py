"""Deterministic resolver and non-destructive reconciliation planner."""

from __future__ import annotations

from collections import Counter
import ipaddress
from typing import Any, Optional, Tuple

from .models import Access, Action, Candidate, Dataset, Plan, Resolution


def slug(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        candidate = value.get("slug") or value.get("name") or value.get("display")
        return str(candidate) if candidate else None
    return str(value)


def _dimension(table: dict[str, Any], key: Optional[str]) -> tuple[Resolution, dict[str, Any]]:
    if not key or key not in table:
        return Resolution.UNMAPPED, {}
    value = table[key]
    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], dict):
            return Resolution.AMBIGUOUS, {}
        value = value[0]
    if not isinstance(value, dict):
        return Resolution.NEEDS_REVIEW, {}
    return Resolution.RESOLVED, value


def _eligibility(record: dict[str, Any], mappings: dict[str, Any], metadata_ready: bool) -> Tuple[Optional[bool], Resolution, str]:
    if not metadata_ready:
        return None, Resolution.NEEDS_REVIEW, "eligibility_metadata_denied"
    policy = mappings["eligibility"]
    wanted_tag = policy.get("tag")
    wanted_field = policy.get("custom_field")
    tag_values = {
        str(item.get("slug") or item.get("name"))
        for item in (record.get("tags") or [])
        if isinstance(item, dict)
    }
    fields = record.get("custom_fields") or {}
    field_value = fields.get(wanted_field) if isinstance(fields, dict) and wanted_field else None
    truthy = (True, 1, "true", "yes", "enabled", "on")
    eligible = bool((wanted_tag and wanted_tag in tag_values) or field_value in truthy)
    return eligible, Resolution.RESOLVED, "eligible" if eligible else "not_opted_in"


def _management_ip(
    record: dict[str, Any], ip_data_ready: bool, known_ip_ids: set[int]
) -> Tuple[Optional[str], Resolution, str]:
    if not ip_data_ready:
        return None, Resolution.NEEDS_REVIEW, "ip_dataset_denied"
    primary = record.get("primary_ip4") or record.get("primary_ip6")
    address = primary.get("address") if isinstance(primary, dict) else primary
    if not address:
        return None, Resolution.NEEDS_REVIEW, "missing_primary_ip"
    primary_id = primary.get("id") if isinstance(primary, dict) else None
    if isinstance(primary_id, int) and primary_id not in known_ip_ids:
        return None, Resolution.NEEDS_REVIEW, "primary_ip_not_in_readable_ip_dataset"
    try:
        parsed = ipaddress.ip_interface(str(address)).ip
    except ValueError:
        return None, Resolution.NEEDS_REVIEW, "invalid_primary_ip"
    if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified:
        return None, Resolution.NEEDS_REVIEW, "unsafe_primary_ip"
    return str(parsed), Resolution.RESOLVED, "primary_ip"


def build_candidates(datasets: dict[str, Dataset], mappings: dict[str, Any]) -> list[Candidate]:
    metadata_ready = all(datasets[name].access is Access.PASS for name in ("tags", "custom_fields"))
    ip_ready = datasets["ip_addresses"].access is Access.PASS
    known_ip_ids = {
        item["id"]
        for item in (datasets["ip_addresses"].records or ())
        if isinstance(item.get("id"), int)
    }
    candidates: list[Candidate] = []
    for object_type, dataset_name in (("device", "devices"), ("vm", "virtual_machines")):
        dataset = datasets[dataset_name]
        if dataset.records is None:
            continue
        for record in dataset.records:
            object_id = record.get("id")
            if not isinstance(object_id, int):
                continue
            name = str(record.get("name") or record.get("display") or "").strip()
            display_name = str(record.get("display") or name).strip()
            eligible, eligibility_state, eligibility_reason = _eligibility(record, mappings, metadata_ready)
            management_ip, ip_state, ip_reason = _management_ip(record, ip_ready, known_ip_ids)
            role_key = slug(record.get("role"))
            platform_key = slug(record.get("platform"))
            site_key = slug(record.get("site"))
            type_state, type_map = _dimension(mappings["object_types"], object_type)
            role_state, role_map = _dimension(mappings["roles"], role_key)
            platform_state, platform_map = _dimension(mappings["platforms"], platform_key)
            site_state, site_map = _dimension(mappings["sites"], site_key)
            dimension_states = (type_state, role_state, platform_state, site_state)
            if Resolution.AMBIGUOUS in dimension_states:
                mapping_state = Resolution.AMBIGUOUS
            elif Resolution.NEEDS_REVIEW in dimension_states:
                mapping_state = Resolution.NEEDS_REVIEW
            elif Resolution.UNMAPPED in dimension_states:
                mapping_state = Resolution.UNMAPPED
            else:
                mapping_state = Resolution.RESOLVED
            groups = sorted(
                {
                    str(group)
                    for item in (type_map, role_map, platform_map, site_map)
                    for group in item.get("groups", [])
                }
            )
            templates = sorted(
                {
                    str(template)
                    for item in (type_map, role_map, platform_map, site_map)
                    for template in item.get("templates", [])
                }
            )
            reasons = [eligibility_reason, ip_reason]
            if mapping_state is not Resolution.RESOLVED:
                reasons.append(f"mapping_{mapping_state.value.lower()}")
            if not name:
                mapping_state = Resolution.NEEDS_REVIEW
                reasons.append("missing_name")
            candidates.append(
                Candidate(
                    object_type=object_type,
                    netbox_id=object_id,
                    host=name,
                    display_name=display_name,
                    management_ip=management_ip,
                    site=site_key,
                    role=role_key,
                    platform=platform_key,
                    eligible=eligible,
                    eligibility_state=eligibility_state,
                    mapping_state=mapping_state,
                    ip_state=ip_state,
                    groups=tuple(groups),
                    templates=tuple(templates),
                    reasons=reasons,
                )
            )

    address_counts = Counter(candidate.management_ip for candidate in candidates if candidate.management_ip)
    duplicates = {address for address, count in address_counts.items() if count > 1}
    for candidate in candidates:
        if candidate.management_ip in duplicates:
            candidate.ip_state = Resolution.AMBIGUOUS
            candidate.reasons.append("duplicate_management_ip")
    return candidates


def _host_identity(host: dict[str, Any]) -> Optional[tuple[str, str]]:
    tags = {str(item.get("tag")): str(item.get("value")) for item in host.get("tags", [])}
    if tags.get("source") != "netbox" or not tags.get("netbox_type") or not tags.get("netbox_id"):
        return None
    return tags["netbox_type"], tags["netbox_id"]


def reconcile(
    candidates: list[Candidate],
    hosts: list[dict[str, Any]],
    datasets: dict[str, Dataset],
    change_budget: float = 0.10,
    required_endpoints: Optional[tuple[str, ...]] = None,
) -> Plan:
    plan = Plan(change_budget=change_budget)
    plan.endpoint_access = {name: dataset.access.value for name, dataset in datasets.items()}
    plan.source_counts = {name: dataset.count for name, dataset in datasets.items()}
    required = required_endpoints or ("devices", "interfaces", "ip_addresses", "virtual_machines", "tags", "custom_fields")
    plan.source_complete = all(datasets[name].access is Access.PASS for name in required)

    counts = Counter(
        {
            "eligible": 0,
            "ineligible": 0,
            "eligibility_unknown": 0,
            "mapped": 0,
            "unmapped": 0,
            "ambiguous": 0,
            "needs_review": 0,
            "missing_or_unsafe_ip": 0,
            "duplicate_ip": 0,
            "actionable": 0,
            "blocked_due_permission": 0,
        }
    )
    for candidate in candidates:
        if candidate.eligible is True:
            counts["eligible"] += 1
        elif candidate.eligible is False:
            counts["ineligible"] += 1
        else:
            counts["eligibility_unknown"] += 1
            counts["blocked_due_permission"] += 1
        counts[candidate.mapping_state.value.lower()] += 1
        if candidate.mapping_state is Resolution.RESOLVED:
            counts["mapped"] += 1
        if candidate.ip_state is Resolution.NEEDS_REVIEW:
            counts["missing_or_unsafe_ip"] += 1
        if candidate.ip_state is Resolution.AMBIGUOUS:
            counts["duplicate_ip"] += 1
        if candidate.actionable:
            counts["actionable"] += 1
    plan.candidate_counts = dict(sorted(counts.items()))

    managed_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_identities: set[tuple[str, str]] = set()
    for host in hosts:
        identity = _host_identity(host)
        if identity is None:
            continue
        if identity in managed_by_identity:
            duplicate_identities.add(identity)
        managed_by_identity[identity] = host
    if duplicate_identities:
        plan.errors.append("duplicate_zabbix_identity")

    candidate_identities = {candidate.identity for candidate in candidates}
    for candidate in candidates:
        if not candidate.actionable:
            kind = "SKIPPED"
            if candidate.mapping_state is Resolution.UNMAPPED:
                kind = "UNMAPPED"
            elif candidate.mapping_state is Resolution.AMBIGUOUS or candidate.ip_state is Resolution.AMBIGUOUS:
                kind = "AMBIGUOUS"
            elif candidate.eligible is None or candidate.eligibility_state is Resolution.NEEDS_REVIEW:
                kind = "NEEDS_REVIEW"
            plan.actions.append(Action(kind, candidate.identity, reason=",".join(candidate.reasons)))
            continue
        existing = managed_by_identity.get(candidate.identity)
        desired = {
            "host": candidate.host,
            "display_name": candidate.display_name,
            "management_ip": candidate.management_ip,
            "groups": candidate.groups,
            "templates": candidate.templates,
            "tags": {
                "source": "netbox",
                "netbox_type": candidate.object_type,
                "netbox_id": str(candidate.netbox_id),
            },
        }
        if existing is None:
            plan.actions.append(Action("CREATE", candidate.identity, changes=desired))
            continue
        changes: dict[str, Any] = {}
        reports: list[str] = []
        if existing.get("host") != candidate.host:
            changes["host"] = candidate.host
        if existing.get("name") != candidate.display_name:
            changes["name"] = candidate.display_name
        existing_groups = {item.get("name") for item in existing.get("groups", [])}
        group_additions = set(candidate.groups) - existing_groups
        group_removals = existing_groups - set(candidate.groups)
        if group_additions:
            changes["groups"] = tuple(sorted(existing_groups | set(candidate.groups)))
        if group_removals:
            reports.append("group_removal_report_only")
            plan.actions.append(Action("GROUP_DRIFT", candidate.identity, reason="automatic_group_removal_forbidden"))
        existing_templates = {item.get("name") for item in existing.get("parentTemplates", [])}
        additions = set(candidate.templates) - existing_templates
        removals = existing_templates - set(candidate.templates)
        if additions:
            changes["template_additions"] = tuple(sorted(additions))
        if removals:
            reports.append("template_removal_report_only")
            plan.actions.append(Action("TEMPLATE_DRIFT", candidate.identity, reason="automatic_unlink_forbidden"))
        existing_tags = {str(item.get("tag")): str(item.get("value")) for item in existing.get("tags", [])}
        desired_tags = {**existing_tags, **desired["tags"]}
        if existing_tags != desired_tags:
            changes["tags"] = [{"tag": key, "value": value} for key, value in sorted(desired_tags.items())]
        desired_interface_type = "2" if any("by SNMP" in name for name in candidate.templates) else "1"
        main_interface = next(
            (item for item in existing.get("interfaces", []) if item.get("type") == desired_interface_type and item.get("main") == "1"),
            None,
        )
        current_ip = main_interface.get("ip") if main_interface and main_interface.get("useip") == "1" else None
        if current_ip != candidate.management_ip:
            reports.append("management_ip_change_needs_review")
            plan.actions.append(Action("IP_CHANGE_REVIEW", candidate.identity, reason="identity_confirmation_required"))
        if changes:
            changes["hostid"] = existing["hostid"]
            plan.actions.append(Action("UPDATE", candidate.identity, changes=changes, reason=",".join(reports)))
        elif not reports:
            plan.actions.append(Action("UNCHANGED", candidate.identity))

    if plan.source_complete:
        for identity in sorted(set(managed_by_identity) - candidate_identities):
            plan.actions.append(Action("ORPHAN", identity, reason="report_only_no_host_deletion"))
        plan.gates["orphan_evaluation"] = "PASS"
    else:
        plan.gates["orphan_evaluation"] = "BLOCKED_INCOMPLETE_SOURCE"

    modifications = sum(action.kind in ("CREATE", "UPDATE") for action in plan.actions)
    managed_population = max(len(managed_by_identity), sum(candidate.actionable for candidate in candidates), 1)
    plan.change_ratio = modifications / managed_population
    plan.gates["required_netbox_reads"] = "PASS" if plan.source_complete else "BLOCKED"
    plan.gates["duplicate_identity"] = "BLOCKED" if duplicate_identities else "PASS"
    unresolved_eligible = any(
        candidate.eligible is True and not candidate.actionable for candidate in candidates
    )
    unknown_eligibility = any(candidate.eligible is None for candidate in candidates)
    plan.gates["candidate_resolution"] = "BLOCKED" if unresolved_eligible or unknown_eligibility else "PASS"
    plan.gates["change_budget"] = "PASS" if plan.change_ratio <= change_budget else "BLOCKED"
    plan.gates["destructive_operations"] = "PASS_REPORT_ONLY"
    return plan


def apply_plan(plan: Plan, client: Any, groups: dict[str, str], templates: dict[str, str], override_budget: bool = False) -> dict[str, int]:
    if plan.gates.get("required_netbox_reads") != "PASS":
        raise RuntimeError("apply blocked: required NetBox reads unavailable")
    if plan.gates.get("duplicate_identity") != "PASS":
        raise RuntimeError("apply blocked: duplicate stable identity")
    if plan.gates.get("candidate_resolution") != "PASS":
        raise RuntimeError("apply blocked: unresolved candidates")
    if plan.gates.get("change_budget") != "PASS" and not override_budget:
        raise RuntimeError("apply blocked: change budget exceeded")
    results = {"created": 0, "updated": 0}
    for action in plan.actions:
        if action.kind == "CREATE":
            missing_groups = set(action.changes["groups"]) - set(groups)
            missing_templates = set(action.changes["templates"]) - set(templates)
            if missing_groups or missing_templates:
                raise RuntimeError("apply blocked: referenced Zabbix mapping target missing")
            client.create_host(action.changes, groups, templates)
            results["created"] += 1
        elif action.kind == "UPDATE":
            referenced_groups = set(action.changes.get("groups", ()))
            referenced_templates = set(action.changes.get("template_additions", ()))
            if referenced_groups - set(groups) or referenced_templates - set(templates):
                raise RuntimeError("apply blocked: referenced Zabbix mapping target missing")
            client.update_host(action.changes["hostid"], action.changes, groups, templates)
            results["updated"] += 1
    return results
