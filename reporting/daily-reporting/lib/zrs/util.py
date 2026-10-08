"""Small, dependency-free helpers shared by collectors, KPIs and renderers."""
from __future__ import annotations

import hashlib
import json
import math
import re


def chunks(seq, size):
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def percentile_nearest_rank(values, pct):
    """Nearest-rank percentile of raw values; None when there are no values."""
    vals = sorted(values)
    if not vals:
        return None
    rank = max(1, int(math.ceil(pct / 100.0 * len(vals))))
    return vals[rank - 1]


def parse_delay(delay):
    """Zabbix update interval -> seconds, or None when it is a macro/flexible/unparseable."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhdw]?)\s*", str(delay or ""))
    if not m:
        return None
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]


def to_float(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ratio(num, den):
    return None if not den else num / float(den)


def clamp01(x):
    return None if x is None else max(0.0, min(1.0, x))
