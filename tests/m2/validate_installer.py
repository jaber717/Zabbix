#!/usr/bin/env python3
"""Fail-closed static policy validation for the M2 installer."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"
REQUIRED_ROLES = {
    "offline_repo",
    "os_baseline",
    "postgresql",
    "zabbix_server",
    "zabbix_web",
    "zabbix_agent2",
    "selinux",
    "firewall",
    "tls",
    "backup",
    "verification",
}
TEXT_SUFFIXES = {".cfg", ".j2", ".json", ".md", ".py", ".sh", ".yml", ".yaml", ""}

FORBIDDEN = {
    "selinux-disable": re.compile(r"\bsetenforce\s+0\b|SELINUX\s*=\s*(?:disabled|permissive)", re.I),
    "general-update": re.compile(r"\bdnf\s+(?:update|upgrade)\b|\byum\s+(?:update|upgrade)\b", re.I),
    "database-destruction": re.compile(r"\bDROP\s+DATABASE\b|\bdropdb\b|rm\s+-rf\s+[^\n]*pgsql", re.I),
    "network-fetch": re.compile(r"\b(?:curl|wget)\b[^\n]*(?:repo\.zabbix\.com|redhat\.com|pypi\.org)", re.I),
    "broad-error-ignore": re.compile(r"\bignore_errors\s*:\s*true\b", re.I),
    "unapproved-collection": re.compile(r"\b(?:community\.|ansible\.posix\.)"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "lab-leakage": re.compile(r"JaberLAB|netbox-demo|192\.168\.|LXC\s*9000|LAB-MOCK|LAB-EMULATED", re.I),
}


def installer_files() -> list[Path]:
    return sorted(path for path in INSTALLER.rglob("*") if path.is_file())


def validate_structure() -> list[str]:
    failures: list[str] = []
    roles = {path.name for path in (INSTALLER / "roles").iterdir() if path.is_dir()}
    missing = sorted(REQUIRED_ROLES - roles)
    if missing:
        failures.append("missing roles: " + ", ".join(missing))
    for relative in (
        "bootstrap.sh",
        "ansible.cfg",
        "playbooks/site.yml",
        "playbooks/verify.yml",
        "playbooks/backup.yml",
        "playbooks/upgrade-preflight.yml",
        "inventory/group_vars/all.yml",
    ):
        if not (INSTALLER / relative).is_file():
            failures.append(f"missing installer file: {relative}")
    return failures


def validate_python() -> list[str]:
    failures: list[str] = []
    for path in installer_files() + sorted((ROOT / "tests" / "m2").glob("*.py")):
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"python syntax: {exc}")
    return failures


def validate_policy() -> list[str]:
    failures: list[str] = []
    for path in installer_files():
        if path.suffix not in TEXT_SUFFIXES:
            continue
        content = path.read_text(encoding="utf-8")
        for name, pattern in FORBIDDEN.items():
            if pattern.search(content):
                failures.append(f"{name}: {path.relative_to(ROOT)}")
    return failures


def validate_offline_dnf() -> list[str]:
    failures: list[str] = []
    for path in (INSTALLER / "roles").rglob("tasks/main.yml"):
        content = path.read_text(encoding="utf-8")
        if "ansible.builtin.dnf:" in content:
            if 'disablerepo: "*"' not in content or 'enablerepo: "{{ offline_repo_id }}"' not in content:
                failures.append(f"unbounded DNF task file: {path.relative_to(ROOT)}")
    bootstrap = (INSTALLER / "bootstrap.sh").read_text(encoding="utf-8")
    if "--disablerepo='*' --enablerepo=zabbix-offline" not in bootstrap:
        failures.append("bootstrap DNF source isolation is missing")
    return failures


def main() -> int:
    failures = validate_structure() + validate_python() + validate_policy() + validate_offline_dnf()
    if failures:
        for failure in failures:
            print(f"FAIL={failure}")
        return 1
    print(f"FILES_SCANNED={len(installer_files())}")
    print("STRUCTURE=PASS")
    print("PYTHON_SYNTAX=PASS")
    print("SOURCE_POLICY=PASS")
    print("OFFLINE_DNF_POLICY=PASS")
    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
