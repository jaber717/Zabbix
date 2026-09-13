"""Command-line entry point. Dry-run is the immutable default."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Optional

from .clients import ApiFailure, NetBoxClient, ZabbixClient
from .config import ConfigError, load_json, validate_mappings, validate_runtime
from .planner import apply_plan, build_candidates, reconcile


ENDPOINTS = {
    "devices": "/api/dcim/devices/",
    "interfaces": "/api/dcim/interfaces/",
    "virtualization_interfaces": "/api/virtualization/interfaces/",
    "ip_addresses": "/api/ipam/ip-addresses/",
    "virtual_machines": "/api/virtualization/virtual-machines/",
    "tags": "/api/extras/tags/",
    "custom_fields": "/api/extras/custom-fields/",
    "device_roles": "/api/dcim/device-roles/",
    "platforms": "/api/dcim/platforms/",
    "sites": "/api/dcim/sites/",
    "tenants": "/api/tenancy/tenants/",
}


def credential_path(explicit: Optional[str], name: str) -> Path:
    if explicit:
        return Path(explicit)
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory:
        raise ConfigError("systemd credential directory unavailable")
    return Path(directory) / name


def read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not value or "\x00" in value:
        raise ConfigError("credential is empty or invalid")
    return value


def acquire_lock(path: Path):
    """Acquire a non-blocking process lock; systemd owns the runtime directory."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise ConfigError("another reconciliation is already running") from exc
    return handle


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="netbox-zabbix-sync")
    parser.add_argument("--config", required=True)
    parser.add_argument("--mappings", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--netbox-token-file")
    parser.add_argument("--zabbix-password-file")
    parser.add_argument("--lock-file", default="/run/netbox-zabbix-sync/sync.lock")
    parser.add_argument("--apply", action="store_true", help="execute permitted Zabbix writes")
    parser.add_argument("--override-change-budget", action="store_true")
    return parser.parse_args(argv)


def run(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    mode = "APPLY" if args.apply else "DRY_RUN"
    lock_handle = None
    try:
        lock_handle = acquire_lock(Path(args.lock_file))
        config = load_json(args.config)
        mappings = load_json(args.mappings)
        validate_runtime(config)
        validate_mappings(mappings)
        netbox_token = read_secret(credential_path(args.netbox_token_file, "netbox-token"))
        zabbix_password = read_secret(credential_path(args.zabbix_password_file, "zabbix-password"))
        tls = config["tls"]
        timeout = float(config.get("timeout_seconds", 10))
        retries = int(config.get("retries", 2))
        netbox = NetBoxClient(config["netbox_url"], netbox_token, tls["netbox_ca"], timeout, retries)
        datasets = {name: netbox.collection(name, path) for name, path in ENDPOINTS.items()}
        zabbix = ZabbixClient(config["zabbix_url"], tls["zabbix_ca"], timeout, retries)
        zabbix.login(config["zabbix_user"], zabbix_password)
        hosts, groups, templates = zabbix.inventory()
        candidates = build_candidates(datasets, mappings)
        plan = reconcile(
            candidates,
            hosts,
            datasets,
            float(config["policy"].get("change_budget", 0.10)),
            tuple(config["policy"]["required_endpoints"]),
        )
        plan.mode = mode
        apply_credential_approved = bool(config["policy"].get("allow_apply_with_current_zabbix_credential", False))
        plan.gates["zabbix_credential_scope"] = "PASS" if apply_credential_approved else "BLOCKED"
        required_names = set(config["policy"]["required_endpoints"])
        if not required_names.issubset(datasets):
            plan.errors.append("runtime_required_endpoint_config_invalid")
            plan.gates["required_netbox_reads"] = "BLOCKED"
        missing_groups = {
            group
            for action in plan.actions
            if action.kind in ("CREATE", "UPDATE")
            for group in action.changes.get("groups", ())
            if group not in groups
        }
        missing_templates = {
            template
            for action in plan.actions
            if action.kind == "CREATE"
            for template in action.changes.get("templates", ())
            if template not in templates
        } | {
            template
            for action in plan.actions
            if action.kind == "UPDATE"
            for template in action.changes.get("template_additions", ())
            if template not in templates
        }
        plan.gates["mapping_targets"] = "PASS" if not missing_groups and not missing_templates else "BLOCKED"
        report = plan.as_dict()
        report["apply_result"] = {"status": "NOT_EXECUTED", "created": 0, "updated": 0}
        if args.apply:
            if plan.gates.get("zabbix_credential_scope") != "PASS":
                raise RuntimeError("apply blocked: Zabbix credential is dry-run only")
            if plan.gates.get("mapping_targets") != "PASS":
                raise RuntimeError("apply blocked: mapping target unavailable")
            result = apply_plan(plan, zabbix, groups, templates, args.override_change_budget)
            report["apply_result"] = {"status": "PASS", **result}
        write_report(Path(args.report), report)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        if args.apply:
            return 0
        return 3 if any(value == "BLOCKED" for value in plan.gates.values()) else 0
    except (ApiFailure, ConfigError, OSError, RuntimeError) as exc:
        safe = {
            "schema": "netbox-zabbix-sync-report-v1",
            "mode": mode,
            "result": "FAILED_SAFE",
            "error_class": type(exc).__name__,
        }
        try:
            write_report(Path(args.report), safe)
        except OSError:
            pass
        print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
        return 2
    finally:
        if lock_handle is not None:
            lock_handle.close()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
