#!/usr/bin/env python3
"""Preserve selected upstream modulemd documents without rewriting them."""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path


WANTED = {"postgresql": "16", "php": "8.3", "nginx": "1.24"}


def field(document: str, name: str) -> str | None:
    match = re.search(rf"(?m)^  {re.escape(name)}:\s*[\"']?([^\"'\s]+)", document)
    return match.group(1) if match else None


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: filter_modulemd.py INPUT.modules.yaml.gz OUTPUT.yaml", file=sys.stderr)
        return 2
    source, output = map(Path, sys.argv[1:])
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        raw = handle.read()
    documents = re.split(r"(?m)(?=^---\s*$)", raw)
    selected: list[str] = []
    for document in documents:
        if not document.startswith("---"):
            continue
        kind_match = re.search(r"(?m)^document:\s*(\S+)", document)
        kind = kind_match.group(1) if kind_match else ""
        name = field(document, "name")
        stream = field(document, "stream")
        if name not in WANTED:
            continue
        if kind == "modulemd" and stream == WANTED[name]:
            selected.append(document.rstrip() + "\n")
        elif kind in {"modulemd-defaults", "modulemd-obsoletes"}:
            selected.append(document.rstrip() + "\n")
    missing = [f"{name}:{stream}" for name, stream in WANTED.items() if not any(field(doc, "name") == name and field(doc, "stream") == stream for doc in selected)]
    if missing:
        raise SystemExit("required module metadata missing: " + ", ".join(missing))
    output.write_text("".join(selected), encoding="utf-8")
    print(f"selected_documents={len(selected)}")
    for name, stream in WANTED.items():
        count = sum(field(doc, "name") == name and field(doc, "stream") == stream for doc in selected)
        print(f"{name}:{stream}={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
