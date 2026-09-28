#!/usr/bin/env python3
"""Plan or idempotently configure the native Zabbix scheduled report through its API."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from zabbix_daily_report import Api, load_config


def report_payload(config: dict, now: datetime | None = None) -> dict:
    native = config["native_pdf"]
    hour, minute = (int(value) for value in config["report"]["schedule_local"].split(":"))
    owner = str(native.get("owner_user_id", "")).strip()
    dashboard = str(native.get("dashboard_id", "")).strip()
    if not owner or not dashboard:
        raise ValueError("native_pdf.owner_user_id and native_pdf.dashboard_id are required")
    report_now = now or datetime.now(ZoneInfo(config["report"]["timezone"]))
    if report_now.tzinfo is None:
        raise ValueError("report payload time must be timezone-aware")
    payload = {
        "userid": owner,
        "name": config["report"]["name"],
        "dashboardid": dashboard,
        "period": 0,
        "cycle": 0,
        "start_time": hour * 3600 + minute * 60,
        "active_since": report_now.astimezone(ZoneInfo(config["report"]["timezone"])).date().isoformat(),
        "active_till": "2038-01-01",
        "subject": config["report"]["name"],
        "message": "Automated previous-day network health report.",
        "status": 0 if native.get("enabled") else 1,
        "description": "Managed by zabbix-daily-reporting-v1. Review configuration before enabling.",
        "users": [
            {"userid": str(user_id), "access_userid": owner, "exclude": "0"}
            for user_id in native.get("recipient_user_ids", [])
        ],
        "user_groups": [
            {"usrgrpid": str(group_id), "access_userid": owner}
            for group_id in native.get("recipient_group_ids", [])
        ],
    }
    if not payload["users"] and not payload["user_groups"]:
        raise ValueError("at least one native PDF recipient user/group ID is required")
    return payload


def reconcile(api: Api, config: dict, payload: dict, settings: dict | None = None, existing: list | None = None) -> tuple[str, str | None]:
    if settings is None:
        settings = api.call("settings.get", {"output": ["url"]})
    if existing is None:
        existing = api.call("report.get", {"filter": {"name": payload["name"]}, "output": ["reportid", "name"]})
    if settings.get("url", "") != config["zabbix"]["frontend_url"]:
        api.call("settings.update", {"url": config["zabbix"]["frontend_url"]})
    if existing:
        report_id = existing[0]["reportid"]
        api.call("report.update", dict(payload, reportid=report_id))
        return "UPDATED", report_id
    result = api.call("report.create", payload)
    report_ids = result.get("reportids", []) if isinstance(result, dict) else []
    return "CREATED", str(report_ids[0]) if report_ids else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    payload = report_payload(config)
    api = Api(config["zabbix"])
    api.authenticate()
    dashboard = api.call("dashboard.get", {"dashboardids": [payload["dashboardid"]], "output": ["dashboardid", "name"]})
    if not dashboard:
        raise RuntimeError("configured native dashboard ID is not visible to the API principal")
    settings = api.call("settings.get", {"output": ["url"]})
    existing = api.call("report.get", {"filter": {"name": payload["name"]}, "output": ["reportid", "name"]})
    plan = {
        "frontend_url_current": settings.get("url", ""),
        "frontend_url_proposed": config["zabbix"]["frontend_url"],
        "dashboard": dashboard[0],
        "scheduled_report": payload,
        "existing_report_id": existing[0]["reportid"] if existing else None,
        "mode": "APPLY" if args.apply else "PLAN_ONLY",
    }
    print(json.dumps(plan, indent=2, sort_keys=True))
    if not args.apply:
        print("RESULT=PASS PLAN_ONLY=1")
        return 0
    action, report_id = reconcile(api, config, payload, settings, existing)
    print(f"RESULT=PASS APPLIED=1 REPORT_ACTION={action} REPORT_ID={report_id or ''}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RESULT=FAIL ERROR={exc}", file=sys.stderr)
        raise SystemExit(1)
