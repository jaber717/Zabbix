#!/usr/bin/env python3
"""Verify installed package NEVRAs against the immutable M1 RPM lock."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def read_locked_nevras(path: Path) -> set[str]:
    rows = path.read_text(encoding="utf-8").splitlines()
    if not rows or rows[0] != "NEVRA\tARCH\tREPO_ID\tSHA256":
        raise ValueError("invalid RPM lock header")
    return {row.split("\t", 1)[0] for row in rows[1:] if row}


def installed_nevra(package: str) -> str:
    result = subprocess.run(
        [
            "/usr/bin/rpm",
            "--query",
            "--queryformat",
            "%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}",
            package,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("packages", nargs="+")
    args = parser.parse_args()
    locked = read_locked_nevras(args.lock)
    for package in args.packages:
        nevra = installed_nevra(package)
        if nevra not in locked:
            raise SystemExit(f"NOT_LOCKED={nevra}")
        print(f"LOCKED={nevra}")
    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
