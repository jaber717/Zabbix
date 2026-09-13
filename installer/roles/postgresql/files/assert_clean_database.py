#!/usr/bin/env python3
"""Fail closed when a database is not the expected clean Zabbix seed."""

from __future__ import annotations

import argparse
import subprocess


STOCK_LOCAL_RANGE = ".".join(("192", "168", "0", "1")) + "-254"


def query(database: str, sql: str) -> list[str]:
    completed = subprocess.run(
        ["/usr/bin/psql", "--no-psqlrc", "--dbname", database, "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1", "--command", sql],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line for line in completed.stdout.splitlines() if line]


def scalar(database: str, sql: str) -> int:
    rows = query(database, sql)
    if len(rows) != 1:
        raise RuntimeError("unexpected database check result")
    return int(rows[0])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--mode", required=True, choices=("seed", "runtime"))
    args = parser.parse_args()
    database = args.database
    # Zabbix ships host prototypes as stock template data.  They share enabled or
    # disabled status values with real hosts, but flags=2 identifies them as
    # prototypes.  Only normal hosts (flags=0) are operational inventory.
    real_hosts = query(
        database,
        "SELECT host FROM hosts WHERE status IN (0,1) AND flags=0 ORDER BY host",
    )
    require(real_hosts == ["Zabbix server"], "unexpected real host set")
    users = query(database, "SELECT username FROM users ORDER BY username")
    require(users == ["Admin", "guest"], "unexpected user set")
    checks = {
        "api tokens": "SELECT count(*) FROM token",
        "discovered hosts": "SELECT count(*) FROM dhosts",
        "discovered services": "SELECT count(*) FROM dservices",
        "host inventory": "SELECT count(*) FROM host_inventory",
        "problems": "SELECT count(*) FROM problem",
        "alerts": "SELECT count(*) FROM alerts",
    }
    for label, sql in checks.items():
        require(scalar(database, sql) == 0, f"unexpected {label}")
    discovery_rules = query(
        database,
        "SELECT name || '|' || iprange || '|' || status FROM drules ORDER BY druleid",
    )
    require(
        discovery_rules == [f"Local network|{STOCK_LOCAL_RANGE}|1"],
        "unexpected network discovery rule set",
    )
    discovery_checks = query(
        database,
        "SELECT r.name || '|' || c.type || '|' || c.key_ || '|' || c.ports "
        "|| '|' || c.uniq || '|' || c.host_source || '|' || c.name_source "
        "|| '|' || c.allow_redirect FROM dchecks c JOIN drules r "
        "ON r.druleid=c.druleid ORDER BY c.dcheckid",
    )
    require(
        discovery_checks == ["Local network|9|system.uname|10050|0|1|0|0"],
        "unexpected network discovery check set",
    )
    interfaces = query(
        database,
        "SELECT h.host FROM interface i JOIN hosts h ON h.hostid=i.hostid "
        "WHERE h.flags=0 ORDER BY h.host",
    )
    require(interfaces == ["Zabbix server"], "unexpected host interface set")
    if args.mode == "seed":
        for table in ("history", "history_uint", "history_str", "history_text", "history_log", "trends", "trends_uint", "events", "sessions"):
            require(scalar(database, f"SELECT count(*) FROM {table}") == 0, f"fresh seed contains rows in {table}")
    print(f"PASS: clean Zabbix database ({args.mode})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"FAIL: clean database policy: {exc}") from exc
