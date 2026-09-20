#!/usr/bin/env python3
"""Read and validate the JSON-form YAML compatibility profile."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path


REQUIRED = {
    "target.os": "rhel",
    "target.arch": "x86_64",
    "zabbix.major": "7.0",
    "zabbix.version": "7.0.30",
    "zabbix.release": "release1.el9",
    "modules.postgresql": "16",
    "modules.php": "8.3",
    "modules.nginx": "1.24",
    "python.abi": "3.11",
    "fping.nevra": "fping-0:5.1-1.el9.x86_64",
}


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not re.fullmatch(r'9\.(?:x|[0-9]+)', str(get(data, 'target.release'))):
        raise ValueError('target.release must describe RHEL 9.x or a concrete RHEL 9 minor')
    for dotted, expected in REQUIRED.items():
        value = get(data, dotted)
        if value != expected:
            raise ValueError(f"{dotted}: expected {expected!r}, got {value!r}")
    return data


def get(data: dict, dotted: str):
    value = data
    for part in dotted.split("."):
        value = value[part]
    return value


def emit_env(data: dict) -> None:
    values = {
        "RELEASE_NAME": get(data, "release.name"),
        "RELEASE_VERSION": get(data, "release.version"),
        "RELEASE_BUILD": str(get(data, "release.build")),
        "TARGET_ARCH": get(data, "target.arch"),
        "BASEOS_REPO": os.environ.get('BASEOS_REPO') or get(data, "repositories.baseos"),
        "APPSTREAM_REPO": os.environ.get('APPSTREAM_REPO') or get(data, "repositories.appstream"),
        "ZABBIX_REPO": get(data, "repositories.zabbix.id"),
        "ZABBIX_REPO_URL": get(data, "repositories.zabbix.url"),
        "ZABBIX_KEY_URL": get(data, "repositories.zabbix.key_url"),
        "ZABBIX_KEY_FINGERPRINT": get(data, "repositories.zabbix.key_fingerprint"),
        "NON_SUPPORTED_REPO": get(data, "repositories.zabbix_non_supported.id"),
        "NON_SUPPORTED_REPO_URL": get(data, "repositories.zabbix_non_supported.url"),
        "NON_SUPPORTED_KEY_URL": get(data, "repositories.zabbix_non_supported.key_url"),
        "NON_SUPPORTED_KEY_FINGERPRINT": get(data, "repositories.zabbix_non_supported.key_fingerprint"),
        "ZABBIX_MAJOR": get(data, "zabbix.major"),
        "ZABBIX_VERSION": get(data, "zabbix.version"),
        "ZABBIX_RELEASE": get(data, "zabbix.release"),
        "FPING_VERSION": get(data, "fping.version"),
        "FPING_RELEASE": get(data, "fping.release"),
        "FPING_ARCH": get(data, "fping.arch"),
        "FPING_NEVRA": get(data, "fping.nevra"),
        "FPING_SHA256": get(data, "fping.sha256"),
        "POSTGRESQL_STREAM": get(data, "modules.postgresql"),
        "PHP_STREAM": get(data, "modules.php"),
        "NGINX_STREAM": get(data, "modules.nginx"),
        "PYTHON_ABI": get(data, "python.abi"),
    }
    for key, value in values.items():
        print(f"{key}={shlex.quote(str(value))}")


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: profile.py env|list|get PROFILE [KEY]", file=sys.stderr)
        return 2
    command, path = sys.argv[1:3]
    data = load(path)
    if command == "env":
        emit_env(data)
    elif command == "list" and len(sys.argv) == 4:
        value = get(data, sys.argv[3])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{sys.argv[3]} is not a string list")
        print("\n".join(value))
    elif command == "get" and len(sys.argv) == 4:
        value = get(data, sys.argv[3])
        print(json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list)) else value)
    else:
        print("invalid profile.py invocation", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
