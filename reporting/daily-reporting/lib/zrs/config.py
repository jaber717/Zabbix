"""Suite configuration: report.json (the RC2 contract, unchanged) + suite.json (new, optional)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

SUITE_SCHEMA = "zabbix-reporting-suite-v1"
REPORT_KEYS = ("daily_network_health", "wan_isp_performance", "infrastructure_health", "executive_summary",
               "incident_analysis", "monitoring_quality")

DEFAULT_SUITE = {
    "schema": SUITE_SCHEMA,
    "output": {"directory": "/var/lib/zabbix-daily-reporting/suite", "file_mode": "0640", "dir_mode": "0750",
               "retention_days": {"daily": 90, "weekly": 180, "monthly": 730}, "include_dataset_in_json": True},
    "week_start": "monday",
    "formats": ["pdf", "xlsx", "json"],
    "sla": {"target_percent": 99.9, "min_coverage": 0.9},
    "limits": {"items": 30000, "hosts_per_request": 100, "trend_items_per_request": 50, "trend_rows": 20000,
               "history_items_per_request": 20, "history_rows": 50000, "history_p95_max_items": 200},
    "incident": {"lookback_days": 30, "top_n": 10},
    "infra": {"host_groups": [], "top_n": 10},
    "wan": {"links": []},
    "reports": dict((k, {"enabled": True}) for k in REPORT_KEYS),
    # Local times used to render systemd OnCalendar. The timers are installed DISABLED.
    "schedule": {"daily": "06:30", "weekly": "Mon 06:45", "monthly": "1 07:00"},
    # Delivery is OFF. Even when enabled, mail goes only to test_recipients unless mode is "live" AND the
    # environment variable ZRS_ALLOW_LIVE_DELIVERY=YES is set AND the command line has --send.
    "delivery": {"enabled": False, "mode": "test", "test_recipients": [], "recipients": [], "allowed_recipient_domains": [],
                 "subject_prefix": "[Zabbix Report]", "max_attachment_mb": 20},
}


class ConfigError(ValueError):
    pass


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def validate_suite(s):
    if s.get("schema") != SUITE_SCHEMA:
        raise ConfigError("suite configuration must declare schema %s" % SUITE_SCHEMA)
    if s["week_start"] not in ("monday", "sunday"):
        raise ConfigError("week_start must be monday or sunday")
    if not s["formats"] or not set(s["formats"]) <= {"pdf", "xlsx", "json"}:
        raise ConfigError("formats must be a non-empty subset of pdf, xlsx, json")
    sla = s["sla"]
    if not 0 < float(sla["target_percent"]) <= 100 or not 0 <= float(sla["min_coverage"]) <= 1:
        raise ConfigError("sla.target_percent must be within 0..100 and sla.min_coverage within 0..1")
    for k, v in s["limits"].items():
        if not isinstance(v, int) or v < 1:
            raise ConfigError("limits.%s must be a positive integer" % k)
    for kind in ("daily", "weekly", "monthly"):
        if int(s["output"]["retention_days"].get(kind, 0)) < 1:
            raise ConfigError("output.retention_days.%s must be positive" % kind)
    for m in (s["output"]["file_mode"], s["output"]["dir_mode"]):
        if not re.fullmatch(r"0[0-7]{3}", m):
            raise ConfigError("file/dir modes must be octal strings like 0640")
        if int(m, 8) & 0o007:
            raise ConfigError("output modes must not grant any access to other users")
    for link in s["wan"]["links"]:
        if not link.get("host") or not link.get("interface"):
            raise ConfigError("every wan.links entry needs host and interface")
        cap = link.get("capacity_bps")
        if cap is not None and not (isinstance(cap, (int, float)) and cap > 0):
            raise ConfigError("wan.links capacity_bps must be a positive number or null")
    sch = s["schedule"]
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", sch["daily"]):
        raise ConfigError("schedule.daily must be HH:MM")
    if not re.fullmatch(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:[01][0-9]|2[0-3]):[0-5][0-9]", sch["weekly"]):
        raise ConfigError("schedule.weekly must be like 'Mon 06:45'")
    if not re.fullmatch(r"(?:[1-9]|1[0-9]|2[0-8]) (?:[01][0-9]|2[0-3]):[0-5][0-9]", sch["monthly"]):
        raise ConfigError("schedule.monthly must be like '1 07:00' (day 1-28)")
    for k in s["reports"]:
        if k not in REPORT_KEYS:
            raise ConfigError("unknown report in suite.reports: %s" % k)
    d = s["delivery"]
    if d["mode"] not in ("test", "live"):
        raise ConfigError("delivery.mode must be test or live")
    addr = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    for a in list(d["recipients"]) + list(d["test_recipients"]):
        if not addr.match(a):
            raise ConfigError("invalid e-mail address in delivery: %r" % a)
    if d["enabled"] and d["mode"] == "live":
        doms = [x.lower() for x in d["allowed_recipient_domains"]]
        if not doms:
            raise ConfigError("delivery.allowed_recipient_domains must be set for live delivery")
        bad = [a for a in d["recipients"] if a.split("@")[-1].lower() not in doms]
        if bad:
            raise ConfigError("recipient(s) outside allowed_recipient_domains: %s" % ", ".join(bad))
    return s


def load_suite(path):
    data = {}
    if path and Path(path).is_file():
        data = json.loads(Path(path).read_text())
    return validate_suite(deep_merge(DEFAULT_SUITE, data))


def load_all(report_json, suite_json, base_loader):
    """Merged configuration: the RC2 report.json (validated by its own loader) with the suite section attached."""
    cfg = base_loader(report_json)
    cfg["suite"] = load_suite(suite_json)
    return cfg


def on_calendar(suite, kind):
    """systemd OnCalendar string for a cadence, from suite['schedule']."""
    v = suite["schedule"][kind]
    if kind == "daily":
        return "*-*-* %s:00" % v
    if kind == "weekly":
        day, hm = v.split(" ")
        return "%s *-*-* %s:00" % (day, hm)
    day, hm = v.split(" ")
    return "*-*-%02d %s:00" % (int(day), hm)
