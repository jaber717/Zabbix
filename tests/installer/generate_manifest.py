#!/usr/bin/env python3
"""Generate the deterministic installer checksum manifest."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer"
MANIFEST = INSTALLER / "MANIFEST.sha256"


def main() -> int:
    files = (
        path
        for path in INSTALLER.rglob("*")
        if path.is_file()
        and path != MANIFEST
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(INSTALLER).as_posix()}"
        for path in sorted(files)
    ]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"MANIFEST_ENTRIES={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
