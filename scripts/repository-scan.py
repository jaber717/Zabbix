#!/usr/bin/env python3
"""Deterministic release-tree secret, data, and payload policy scan."""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".rpm", ".sql", ".dump", ".bak", ".key", ".pem", ".p12", ".pfx", ".pgpass", ".log", ".tar", ".zip"}
FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519", "database.dump"}
FORBIDDEN_DIRECTORIES = {".venv", "__pycache__", "node_modules", "evidence", "dist", "artifacts"}
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
TOKEN_SHAPES = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{20,})")
IPV4 = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
LAB_IDENTIFIERS = re.compile(r"(?:DR-FW01|DR-LB01|DR-LEAF01|DR-LEAF02|JaberLAB|LAB-MOCK|LAB-EMULATED)", re.I)
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
)
POLICY_FIXTURES = {
    "build/run-negative-tests.sh",
    "build/verify-build.sh",
    "scripts/repository-scan.py",
    "tests/installer/validate_installer.py",
}


def files() -> list[Path]:
    return sorted(
        path for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and not any(part in FORBIDDEN_DIRECTORIES for part in path.parts)
    )


def main() -> int:
    failures: list[str] = []
    candidates = files()
    for path in candidates:
        relative = path.relative_to(ROOT).as_posix()
        suffixes = {suffix.lower() for suffix in path.suffixes}
        if path.name.lower() in FORBIDDEN_NAMES or suffixes & FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden payload: {relative}")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"unexpected binary file: {relative}")
            continue
        if PRIVATE_KEY.search(content):
            failures.append(f"private-key header: {relative}")
        if TOKEN_SHAPES.search(content):
            failures.append(f"credential token shape: {relative}")
        if relative not in POLICY_FIXTURES and LAB_IDENTIFIERS.search(content):
            failures.append(f"source-system device data: {relative}")
        for match in (() if relative in POLICY_FIXTURES else IPV4.finditer(content)):
            try:
                address = ipaddress.ip_address(match.group(0))
            except ValueError:
                continue
            if address.is_private and not address.is_loopback and not address.is_unspecified and not any(address in network for network in DOCUMENTATION_NETWORKS):
                failures.append(f"RFC1918 address: {relative}")
                break
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    if any(line and not line.startswith("#") and ("=" not in line or line.split("=", 1)[1] != "") for line in env_example):
        failures.append(".env.example contains a value")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print(f"FILES_SCANNED={len(candidates)}")
    print("FORBIDDEN_PAYLOADS=PASS")
    print("PRIVATE_KEYS_AND_TOKEN_SHAPES=PASS")
    print("RFC1918_AND_LAB_DEVICE_DATA=PASS")
    print("ENV_EXAMPLE_VALUES=PASS")
    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
