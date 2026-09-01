#!/usr/bin/env python3
"""Generate the deterministic installer checksum manifest."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"
MANIFEST = INSTALLER / "MANIFEST.sha256"


def main() -> int:
    lines: list[str] = []
    source_files = (
        item
        for item in INSTALLER.rglob("*")
        if item.is_file()
        and item != MANIFEST
        and "__pycache__" not in item.parts
        and item.suffix not in {".pyc", ".pyo"}
    )
    for path in sorted(source_files):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(INSTALLER).as_posix()}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"MANIFEST_ENTRIES={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
