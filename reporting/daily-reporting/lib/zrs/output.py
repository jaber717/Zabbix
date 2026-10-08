"""Atomic writes, manifests, checksums, idempotency and retention for generated report files."""
from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path

from . import SUITE_VERSION
from .util import sha256_file

MANIFEST = "manifest.json"


def versions():
    out = {"suite": SUITE_VERSION, "python": platform.python_version(), "reportlab": None, "openpyxl": None}
    try:
        import reportlab
        out["reportlab"] = reportlab.Version
    except Exception:      # noqa: BLE001 - an absent module is recorded, not fatal here
        pass
    try:
        import openpyxl
        out["openpyxl"] = openpyxl.__version__
    except Exception:      # noqa: BLE001
        pass
    return out


def atomic_write(path, data, mode=0o640):
    """Write to a temp file in the same directory, fsync, chmod, then rename into place."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_dir(base, slug, label, dir_mode=0o750):
    """Create <base>/<slug>/<label>. Only directories created here get the secure mode; an existing
    directory (for example one passed with --output-directory) is never chmod-ed."""
    base, d = Path(base), Path(base) / slug / label
    for p in (base, base / slug, d):
        if not p.exists():
            p.mkdir(mode=dir_mode)
            os.chmod(str(p), dir_mode)          # mkdir honours the umask; make the mode exact
    return d


def existing_manifest(d):
    p = Path(d) / MANIFEST
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except ValueError:
        return None


def is_current(d, dataset_sha, formats):
    """True when a previous run produced the same dataset in every requested format and the files are intact."""
    m = existing_manifest(d)
    if not m or m.get("dataset_sha256") != dataset_sha or m.get("status") != "COMPLETE":
        return False
    have = dict((f["format"], f) for f in m.get("files", []))
    for fmt in formats:
        f = have.get(fmt)
        if not f or not (Path(d) / f["name"]).is_file() or sha256_file(str(Path(d) / f["name"])) != f["sha256"]:
            return False
    return True


def write_outputs(d, stem, rendered, doc, dataset_sha, file_mode, run_info):
    """rendered: {format: bytes}. Files first, manifest last (manifest present = run complete)."""
    files = []
    for fmt, data in sorted(rendered.items()):
        name = "%s.%s" % (stem, fmt)
        atomic_write(Path(d) / name, data, file_mode)
        files.append({"format": fmt, "name": name, "bytes": len(data), "sha256": sha256_file(str(Path(d) / name))})
    manifest = dict(run_info, status="COMPLETE", dataset_sha256=dataset_sha, files=files, versions=versions(),
                    report=doc["report"], period=doc["period"], warnings=len(doc["warnings"]),
                    kpis=dict((k["id"], k["value"]) for k in doc["kpis"]))
    atomic_write(Path(d) / MANIFEST, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), file_mode)
    return manifest


def apply_retention(base, retention_days, now_ts, keep=()):
    """Delete only runs this suite created (a manifest.json is present) and only the files it lists."""
    removed = []
    base = Path(base)
    if not base.is_dir():
        return removed
    for mpath in sorted(base.glob("*/*/" + MANIFEST)):
        try:
            m = json.loads(mpath.read_text())
            kind = m["period"]["kind"]
            end_ts = int(m["period"]["end_ts"])
        except (ValueError, KeyError):
            continue
        if end_ts < now_ts - int(retention_days.get(kind, 36500)) * 86400 and str(mpath.parent) not in keep:
            d = mpath.parent
            for f in m.get("files", []):
                try:
                    (d / f["name"]).unlink()
                except OSError:
                    pass
            mpath.unlink()
            try:
                d.rmdir()
            except OSError:
                pass
            removed.append(str(d))
    return removed
