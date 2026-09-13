#!/usr/bin/env python3
"""Inspect M2 release state without changing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in match.groups())


def inspect_state(state_path: Path, target: str, zabbix: str) -> dict[str, str]:
    target_version = parse_version(target)
    if not state_path.exists():
        return {"status": "fresh", "target": target, "zabbix": zabbix}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        current = str(state["release"])
        current_zabbix = str(state["zabbix"])
        current_version = parse_version(current)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "invalid_state", "target": target, "reason": str(exc)}
    if current_version > target_version:
        status = "unsupported_downgrade"
    elif current_version < target_version:
        status = "upgrade_required"
    elif current_zabbix != zabbix:
        status = "version_conflict"
    else:
        status = "converge"
    return {
        "status": status,
        "current": current,
        "target": target,
        "current_zabbix": current_zabbix,
        "target_zabbix": zabbix,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--state", type=Path, required=True)
    inspect_parser.add_argument("--target", required=True)
    inspect_parser.add_argument("--zabbix", required=True)
    args = parser.parse_args()
    result = inspect_state(args.state, args.target, args.zabbix)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
