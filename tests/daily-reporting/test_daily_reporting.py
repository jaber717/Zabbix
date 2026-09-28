#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "reporting" / "daily-reporting" / "bin"
sys.path.insert(0, str(BIN))
import zabbix_daily_report as report_module
import native_reporting


class FakeApi:
    def __init__(self, _config):
        self.serial = 0

    def authenticate(self):
        return None

    def call(self, method, params, auth=True):
        del params, auth
        self.serial += 1
        now = int(datetime(2026, 9, 27, 12, tzinfo=ZoneInfo("Asia/Riyadh")).timestamp())
        values = {
            "host.get": {
                "1": {"host": "r1", "name": "Router 1", "interfaces": [{"available": "1", "type": "2", "error": ""}], "tags": [{"tag": "site", "value": "DC"}], "hostgroups": [{"groupid": "1", "name": "Routers"}]},
                "2": {"host": "fw1", "name": "Firewall 1", "interfaces": [{"available": "2", "type": "2", "error": "timeout"}], "tags": [{"tag": "site", "value": "DR"}], "hostgroups": [{"groupid": "2", "name": "Firewalls"}]},
            },
            "problem.get": [],
            "event.get": [],
            "trigger.get": [],
            "item.get": [
                {"itemid": "10", "hostid": "1", "name": "CPU utilization", "key_": "system.cpu.util", "units": "%", "lastvalue": "91", "lastclock": str(now), "state": "0"},
                {"itemid": "11", "hostid": "2", "name": "Memory utilization", "key_": "vm.memory.util", "units": "%", "lastvalue": "93", "lastclock": str(now - 7200), "state": "0"},
            ],
        }
        return values[method]


class DailyReportingTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "reporting/daily-reporting/config/report.example.json").read_text())
        self.config["scope"]["sites"] = []
        self.original_api = report_module.Api
        report_module.Api = FakeApi

    def tearDown(self):
        report_module.Api = self.original_api

    def test_previous_day_and_neutral_raw_metrics(self):
        now = datetime(2026, 9, 28, 8, tzinfo=ZoneInfo("Asia/Riyadh"))
        result = report_module.collect(self.config, now)
        self.assertEqual(result["period"]["start"], "2026-09-27T00:00:00+03:00")
        self.assertEqual(result["summary"]["available"], 1)
        self.assertEqual(result["summary"]["currently_down"], 1)
        self.assertEqual(result["raw_metric_exceptions"], [])
        self.assertIn("Firewall 1", result["stale_devices"])
        self.assertEqual(result["api_calls"], 5)

    def test_opt_in_raw_thresholds_and_html_sections(self):
        self.config["thresholds"]["raw_metric_evaluation"] = True
        result = report_module.collect(self.config, datetime(2026, 9, 28, 8, tzinfo=ZoneInfo("Asia/Riyadh")))
        self.assertEqual({row["metric"] for row in result["raw_metric_exceptions"]}, {"cpu", "memory"})
        markup = report_module.render_html(result)
        for section in ("Availability by site", "Devices currently DOWN", "High / Disaster problems", "Critical interface / utilization exceptions"):
            self.assertIn(section, markup)
        self.assertNotIn("ZABBIX_API_PASSWORD", markup)

    def test_config_rejects_invalid_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            self.config["thresholds"]["cpu_percent"] = 101
            path.write_text(json.dumps(self.config))
            with self.assertRaises(ValueError):
                report_module.load_config(path)

    def test_config_rejects_invalid_schedule_and_native_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            self.config["report"]["schedule_local"] = "29:00"
            self.config["native_pdf"]["report_writers"] = 0
            path.write_text(json.dumps(self.config))
            with self.assertRaises(ValueError):
                report_module.load_config(path)

    def test_native_payload_is_previous_day_daily_and_explicit(self):
        native = self.config["native_pdf"]
        native.update({"owner_user_id": "1", "dashboard_id": "57", "recipient_user_ids": ["2"], "enabled": True})
        payload = native_reporting.report_payload(self.config)
        self.assertEqual(payload["period"], 0)
        self.assertEqual(payload["cycle"], 0)
        self.assertEqual(payload["dashboardid"], "57")
        self.assertEqual(payload["users"][0]["userid"], "2")


if __name__ == "__main__":
    unittest.main()
