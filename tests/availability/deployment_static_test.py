#!/usr/bin/env python3
"""Static safety contracts for Network Availability deployment tooling."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "frontend" / "modules" / "NetworkAvailability"
SCRIPTS = ROOT / "scripts"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


manifest = json.loads((MODULE / "manifest.json").read_text(encoding="utf-8"))
version = (MODULE / "VERSION").read_text(encoding="utf-8").strip()
require(version == "1.0.1", "production release marker must be 1.0.1")
require(manifest["version"] == version, "manifest and release marker must match")

default_config = json.loads((MODULE / "config" / "node-definitions.json").read_text(encoding="utf-8"))
require(default_config == {"schema": "network-availability-node-definitions-v1", "nodes": []},
        "production default must remain empty")
example = json.loads((MODULE / "config" / "node-definitions.example.json").read_text(encoding="utf-8"))
require(example.get("example_only") is True, "configuration template must be explicitly marked as an example")

installer = (SCRIPTS / "install-network-availability.sh").read_text(encoding="utf-8")
verifier = (SCRIPTS / "verify-network-availability.sh").read_text(encoding="utf-8")
rollback = (SCRIPTS / "rollback-network-availability.sh").read_text(encoding="utf-8")
common = (SCRIPTS / "lib" / "network-availability-common.sh").read_text(encoding="utf-8")

for name, content in {"installer": installer, "verifier": verifier, "rollback": rollback}.items():
    require(content.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n"), f"{name} must fail closed")
    require("systemctl restart" not in content and "service " not in content,
            f"{name} must not restart services")

require("na_require_root" in installer, "installer must require privilege before changing files")
require("NetworkAvailability.backup-$TIMESTAMP" in installer, "installer backup is required")
require("NODE_CONFIGURATION=PRESERVED" in installer, "installer must preserve operator Node configuration")
require("na_validate_release_module \"$SOURCE_DIR\"" in installer, "installer must validate before changes")
require("ALREADY_INSTALLED" in installer, "same-release install must be idempotent")
require("--confirm-module-disabled" in rollback, "rollback must require UI-disable confirmation")
require("NetworkAvailability.removed-$TIMESTAMP" in rollback, "uninstall must preserve files recoverably")
require("rm -rf" not in rollback, "rollback must not delete module trees")
require("Zabbix 7.0.x is required" in common, "supported Zabbix series must be enforced")
require("RHEL 9 is required" in common, "supported OS series must be enforced")
require("PHP 8.1 or newer" in common, "supported PHP series must be enforced")

checksum_manifest = MODULE / "RELEASE.sha256"
require(checksum_manifest.is_file(), "module checksum manifest is required")
for line in checksum_manifest.read_text(encoding="utf-8").splitlines():
    digest, relative = line.split("  ", 1)
    require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "invalid module SHA256")
    require(relative != "config/node-definitions.json", "mutable production configuration must be excluded")
    target = MODULE / relative
    require(target.is_file(), f"checksummed file missing: {relative}")
    require(hashlib.sha256(target.read_bytes()).hexdigest() == digest, f"checksum mismatch: {relative}")

release_manifest = SCRIPTS / "network-availability-release.sha256"
require(release_manifest.is_file(), "deployment release checksum manifest is required")
for line in release_manifest.read_text(encoding="utf-8").splitlines():
    digest, relative = line.split("  ", 1)
    target = ROOT / relative
    require(target.is_file(), f"release file missing: {relative}")
    require(hashlib.sha256(target.read_bytes()).hexdigest() == digest, f"release checksum mismatch: {relative}")

print("PASS: Network Availability deployment safety contracts")
