#!/usr/bin/env python3
"""Parse root-only deployment input without shell evaluation or secret output."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import stat


ALLOWED = {
    "INSTALL_MODE",
    "OFFLINE_BUNDLE_ROOT",
    "ZABBIX_SERVER_HOSTNAME",
    "ZABBIX_WEB_SERVER_NAME",
    "ZABBIX_TIMEZONE",
    "ZABBIX_FRONTEND_PORT",
    "ZABBIX_DB_PASSWORD",
    "ZABBIX_ADMIN_PASSWORD",
    "TLS_ENABLED",
    "TLS_CERTIFICATE_FILE",
    "TLS_PRIVATE_KEY_FILE",
    "FIREWALL_WEB_SOURCES",
    "FIREWALL_SERVER_SOURCES",
    "FIREWALL_AGENT_SOURCES",
}
REQUIRED = ALLOWED - {"OFFLINE_BUNDLE_ROOT", "TLS_CERTIFICATE_FILE", "TLS_PRIVATE_KEY_FILE"}
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")


def die(message: str) -> "None":
    raise SystemExit(f"FAIL: {message}")


def parse_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "=" not in raw:
            die(f"invalid configuration line {number}")
        key, value = raw.split("=", 1)
        if key not in ALLOWED:
            die(f"unknown configuration key on line {number}: {key}")
        if key in result:
            die(f"duplicate configuration key: {key}")
        if "\x00" in value or "\r" in value or "\n" in value:
            die(f"invalid value for {key}")
        result[key] = value
    missing = sorted(key for key in REQUIRED if not result.get(key))
    if missing:
        die("missing required configuration keys: " + ", ".join(missing))
    return result


def bool_value(value: str, key: str) -> bool:
    lowered = value.lower()
    if lowered not in {"true", "false"}:
        die(f"{key} must be true or false")
    return lowered == "true"


def source_list(value: str, key: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        die(f"{key} must contain at least one source CIDR")
    try:
        return [str(ipaddress.ip_network(item, strict=False)) for item in values]
    except ValueError:
        die(f"{key} contains an invalid CIDR")


def protected_input(path: Path, repo: Path) -> None:
    info = path.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}:
        die("configuration must be root-owned mode 0400 or 0600")
    resolved = path.resolve()
    try:
        resolved.relative_to(repo.resolve())
    except ValueError:
        return
    die("configuration must be outside the Git repository")


def write_private(path: Path, value: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, value.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        die("root is required")
    protected_input(args.config, args.repo_root)
    values = parse_file(args.config)
    if values["INSTALL_MODE"] not in {"connected", "airgapped"}:
        die("INSTALL_MODE must be connected or airgapped")
    for key in ("ZABBIX_SERVER_HOSTNAME", "ZABBIX_WEB_SERVER_NAME"):
        if not HOST_RE.fullmatch(values[key]):
            die(f"{key} is invalid")
    if values["ZABBIX_TIMEZONE"] != "Asia/Riyadh":
        die("this release requires ZABBIX_TIMEZONE=Asia/Riyadh")
    try:
        frontend_port = int(values["ZABBIX_FRONTEND_PORT"])
    except ValueError:
        die("ZABBIX_FRONTEND_PORT must be numeric")
    if not 1 <= frontend_port <= 65535:
        die("ZABBIX_FRONTEND_PORT is outside 1-65535")
    for key in ("ZABBIX_DB_PASSWORD", "ZABBIX_ADMIN_PASSWORD"):
        if len(values[key]) < 12:
            die(f"{key} is too short")
    if values["ZABBIX_DB_PASSWORD"] != values["ZABBIX_ADMIN_PASSWORD"]:
        die("the requested bootstrap policy requires matching deployment passwords")
    tls = bool_value(values["TLS_ENABLED"], "TLS_ENABLED")
    if tls and (not values.get("TLS_CERTIFICATE_FILE") or not values.get("TLS_PRIVATE_KEY_FILE")):
        die("TLS certificate and private key paths are required when TLS is enabled")
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.output, 0o700)
    db_path = args.output / "db-password"
    admin_path = args.output / "admin-password"
    write_private(db_path, values["ZABBIX_DB_PASSWORD"])
    write_private(admin_path, values["ZABBIX_ADMIN_PASSWORD"])
    variables = {
        "zabbix_server_hostname": values["ZABBIX_SERVER_HOSTNAME"],
        "zabbix_web_server_name": values["ZABBIX_WEB_SERVER_NAME"],
        "zabbix_timezone": values["ZABBIX_TIMEZONE"],
        "zabbix_tls_enabled": tls,
        "zabbix_tls_certificate_source": values.get("TLS_CERTIFICATE_FILE", ""),
        "zabbix_tls_private_key_source": values.get("TLS_PRIVATE_KEY_FILE", ""),
        "zabbix_web_http_redirect": False,
        "zabbix_web_http_port": frontend_port if not tls else 80,
        "zabbix_web_https_port": frontend_port if tls else 443,
        "zabbix_firewall_web_sources": source_list(values["FIREWALL_WEB_SOURCES"], "FIREWALL_WEB_SOURCES"),
        "zabbix_firewall_server_sources": source_list(values["FIREWALL_SERVER_SOURCES"], "FIREWALL_SERVER_SOURCES"),
        "zabbix_firewall_agent_sources": source_list(values["FIREWALL_AGENT_SOURCES"], "FIREWALL_AGENT_SOURCES"),
        "zabbix_admin_secret_input_file": str(admin_path),
        "nbzsync_enabled": False,
    }
    write_private(args.output / "vars.json", json.dumps(variables, separators=(",", ":")))
    safe = {
        "install_mode": values["INSTALL_MODE"],
        "offline_bundle_root": values.get("OFFLINE_BUNDLE_ROOT", ""),
    }
    write_private(args.output / "paths.json", json.dumps(safe, separators=(",", ":")))
    print("PASS: protected runtime configuration prepared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
