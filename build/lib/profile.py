#!/usr/bin/env python3
"""Read and validate the JSON-form YAML compatibility profile."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path


REQUIRED = {
    "target.os": "rhel",
    "target.release": "9.6",
    "target.arch": "x86_64",
    "zabbix.major": "7.0",
    "zabbix.version": "7.0.30",
    "zabbix.release": "release1.el9",
    "modules.postgresql": "16",
    "modules.php": "8.3",
    "modules.nginx": "1.24",
    "python.abi": "3.11",
}


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
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
        "RHEL_RELEASE": get(data, "target.release"),
        "TARGET_ARCH": get(data, "target.arch"),
        "BASEOS_REPO": get(data, "repositories.baseos"),
        "APPSTREAM_REPO": get(data, "repositories.appstream"),
        "ZABBIX_REPO": get(data, "repositories.zabbix.id"),
        "ZABBIX_REPO_URL": get(data, "repositories.zabbix.url"),
        "ZABBIX_KEY_URL": get(data, "repositories.zabbix.key_url"),
        "ZABBIX_KEY_FINGERPRINT": get(data, "repositories.zabbix.key_fingerprint"),
        "ZABBIX_MAJOR": get(data, "zabbix.major"),
        "ZABBIX_VERSION": get(data, "zabbix.version"),
        "ZABBIX_RELEASE": get(data, "zabbix.release"),
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
