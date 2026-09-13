#!/usr/bin/env python3
"""Normalize the modules timestamp in createrepo_c repomd.xml."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: normalize_repomd_timestamp.py REPOMD EPOCH", file=sys.stderr)
        return 2

    repomd = Path(sys.argv[1])
    epoch = sys.argv[2]
    if not epoch.isdigit():
        print("epoch must contain only decimal digits", file=sys.stderr)
        return 2

    original = repomd.read_text(encoding="utf-8")
    pattern = re.compile(
        r'(<data type="modules">.*?<timestamp>)\d+(</timestamp>)', re.DOTALL
    )
    normalized, replacements = pattern.subn(rf"\g<1>{epoch}\g<2>", original)
    if replacements != 1:
        print(
            f"expected exactly one modules timestamp, found {replacements}",
            file=sys.stderr,
        )
        return 1

    repomd.write_text(normalized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
