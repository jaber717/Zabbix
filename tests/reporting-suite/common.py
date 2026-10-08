"""Shared setup for reporting-suite tests (Python 3.9 compatible)."""
import copy
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = ROOT / "reporting" / "daily-reporting"
for p in (os.environ.get("ZRS_VENDOR", ""), str(APP / "vendor"), str(APP / "lib"), str(APP / "bin"), str(HERE)):
    if p and p not in sys.path:
        sys.path.insert(0, p)

from zrs.config import DEFAULT_SUITE, deep_merge, validate_suite   # noqa: E402
from zrs import plans                                              # noqa: E402
import fakezbx                                                     # noqa: E402

TZ = ZoneInfo("Asia/Riyadh")
NOW = datetime(2026, 10, 8, 7, 0, tzinfo=TZ)


def make_cfg(**suite_over):
    base = json.loads((APP / "config" / "report.example.json").read_text())
    base["scope"]["sites"] = []
    suite = validate_suite(deep_merge(DEFAULT_SUITE, suite_over))
    base["suite"] = suite
    return base


def world(wan=True, events=True, trends=True):
    w, _ = fakezbx.standard_world()
    if trends:
        fakezbx.add_trends_for_windows(w)
    if wan:
        fakezbx.add_wan(w)
    if events:
        fakezbx.add_events(w)
        fakezbx.add_september_events(w)
        fakezbx.add_week_events(w)
        fakezbx.add_unsupported(w)
    return w


WAN_LINKS = [{"host": "RTR-HQ", "interface": "Gi0/0", "isp": "STC", "site": "HQ"},
             {"host": "RTR-BR1", "interface": "Gi0/1", "isp": "MOBILY"}]


def period_for(key, cfg, day=None):
    from zrs.periods import containing, previous_complete
    kind = plans.REPORTS[key]["kind"]
    if day:
        from datetime import date
        return containing(kind, date.fromisoformat(day), TZ)
    return previous_complete(kind, NOW, TZ)


def dataset(key, cfg=None, w=None, day=None):
    cfg = cfg or make_cfg(wan={"links": WAN_LINKS})
    w = w or world()
    return plans.collect(w, cfg, NOW, key, period_for(key, cfg, day)), cfg, w
