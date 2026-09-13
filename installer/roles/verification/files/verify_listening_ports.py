#!/usr/bin/env python3
"""Verify listening TCP ports using procfs without adding an iproute dependency."""

from __future__ import annotations

import argparse
from pathlib import Path


def listening_ports(paths: tuple[Path, ...]) -> set[int]:
    ports: set[int] = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4 and fields[3] == "0A":
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
    return ports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ports", nargs="+", type=int)
    args = parser.parse_args()
    actual = listening_ports((Path("/proc/net/tcp"), Path("/proc/net/tcp6")))
    missing = sorted(set(args.ports) - actual)
    if missing:
        raise SystemExit("MISSING_PORTS=" + ",".join(str(port) for port in missing))
    print("LISTENING_PORTS=" + ",".join(str(port) for port in sorted(set(args.ports))))
    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
