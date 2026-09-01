#!/usr/bin/env python3
"""Return the single accepted M1 lock entry for a package name."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


def package_name(nevra: str) -> str:
    match = re.match(r"^(.+)-[0-9]+:", nevra)
    if match is None:
        raise ValueError(f"invalid locked NEVRA: {nevra}")
    return match.group(1)


def locked_nevra(path: Path, requested_name: str) -> str:
    rows = path.read_text(encoding="utf-8").splitlines()
    if not rows or rows[0] != "NEVRA\tARCH\tREPO_ID\tSHA256":
        raise ValueError("invalid RPM lock header")
    matches = [
        row.split("\t", 1)[0]
        for row in rows[1:]
        if row and package_name(row.split("\t", 1)[0]) == requested_name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one locked NEVRA for {requested_name}, found {len(matches)}"
        )
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--package", required=True)
    args = parser.parse_args()
    print(locked_nevra(args.lock, args.package))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
