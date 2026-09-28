#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class StaticContracts(unittest.TestCase):
    def test_required_delivery_files(self):
        required = [
            "reporting/daily-reporting/VERSION",
            "reporting/daily-reporting/DEPENDENCIES.txt",
            "reporting/daily-reporting/bin/zabbix_daily_report.py",
            "reporting/daily-reporting/bin/native_preflight.py",
            "reporting/daily-reporting/bin/native_reporting.py",
            "reporting/daily-reporting/config/report.example.json",
            "reporting/daily-reporting/config/dashboard-blueprint.json",
            "reporting/daily-reporting/systemd/zabbix-daily-report.service",
            "reporting/daily-reporting/systemd/zabbix-daily-report.timer",
            "scripts/install_daily_reporting.sh",
            "scripts/verify_daily_reporting.sh",
            "scripts/rollback_daily_reporting.sh",
            "scripts/build_offline_bundle.sh",
            "scripts/daily-reporting-release.sha256",
            "tests/daily-reporting/native_rollback_test.sh",
            "docs/DAILY-REPORTING.md",
        ]
        self.assertEqual([path for path in required if not (ROOT / path).is_file()], [])

    def test_json_and_no_credentials(self):
        config = json.loads((ROOT / "reporting/daily-reporting/config/report.example.json").read_text())
        self.assertEqual(config["schema"], "zabbix-daily-reporting-v1")
        text = "\n".join((ROOT / path).read_text(errors="replace") for path in [
            "reporting/daily-reporting/config/report.example.json",
            "reporting/daily-reporting/bin/zabbix_daily_report.py",
            "scripts/install_daily_reporting.sh",
        ])
        self.assertNotRegex(text, r"(?i)(password|token)\s*[=:]\s*['\"]?[A-Za-z0-9_-]{16,}")

    def test_safety_contracts(self):
        install = (ROOT / "scripts/install_daily_reporting.sh").read_text()
        rollback = (ROOT / "scripts/rollback_daily_reporting.sh").read_text()
        self.assertIn("zabbix_server -T", install)
        self.assertIn("--apply-native-config", install)
        self.assertIn("CONFIGURATION=PRESERVED", rollback)
        self.assertIn("NATIVE_CONFIGURATION_VALIDATION=PASS", rollback)
        self.assertIn("dr_restore_native_state", rollback)
        self.assertNotIn("setenforce", install)
        self.assertNotIn("systemctl stop firewalld", install)
        self.assertNotIn("ssl._create_unverified_context", (ROOT / "reporting/daily-reporting/bin/zabbix_daily_report.py").read_text())

    def test_network_modules_are_not_delivery_dependencies(self):
        build = (ROOT / "scripts/build_offline_bundle.sh").read_text()
        self.assertNotIn("frontend/modules/NetworkAvailability", build)
        self.assertNotIn("frontend/modules/NetworkUtilization", build)


if __name__ == "__main__":
    unittest.main()
