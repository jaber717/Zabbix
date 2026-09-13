#!/usr/bin/env python3
"""Fail on priority 0..3 journal entries from the current service process."""

from __future__ import annotations

import json
import subprocess


UNIT = "zabbix-server.service"


def run(argv: list[str]) -> str:
    completed = subprocess.run(
        argv,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RuntimeError("service journal query failed")
    return completed.stdout


def entries_at_or_after(rows: list[dict[str, object]], start: int) -> list[dict[str, object]]:
    result = []
    for row in rows:
        raw = row.get("__MONOTONIC_TIMESTAMP")
        if raw is None:
            raise RuntimeError("journal entry lacks a monotonic timestamp")
        if int(str(raw)) >= start:
            result.append(row)
    return result


def main() -> int:
    raw_start = run(
        [
            "/usr/bin/systemctl",
            "show",
            "--property=ExecMainStartTimestampMonotonic",
            "--value",
            UNIT,
        ]
    ).strip()
    if not raw_start or int(raw_start) <= 0:
        raise RuntimeError("current Zabbix process start time is unavailable")
    raw_journal = run(
        [
            "/usr/bin/journalctl",
            "--unit",
            UNIT,
            "--boot",
            "--priority",
            "0..3",
            "--output=json",
            "--no-pager",
        ]
    )
    try:
        rows = [json.loads(line) for line in raw_journal.splitlines() if line]
    except json.JSONDecodeError as exc:
        raise RuntimeError("service journal returned invalid JSON") from exc
    failures = entries_at_or_after(rows, int(raw_start))
    if failures:
        raise RuntimeError(
            f"current Zabbix process has {len(failures)} priority 0..3 journal entries"
        )
    print("PASS: current Zabbix process has no priority 0..3 journal entries")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
