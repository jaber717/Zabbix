"""Static packaging contracts, suite configuration validation and the offline dependency lock."""
import hashlib
import io
import json
import re
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path

from common import APP, ROOT
import zrs
from zrs import cli
from zrs.config import DEFAULT_SUITE, ConfigError, deep_merge, load_suite, on_calendar, validate_suite


def suite(**over):
    return validate_suite(deep_merge(DEFAULT_SUITE, over))


class SuiteConfig(unittest.TestCase):
    def test_example_equals_defaults(self):
        example = json.loads((APP / "config" / "suite.example.json").read_text())
        self.assertEqual(deep_merge(DEFAULT_SUITE, example), json.loads(json.dumps(DEFAULT_SUITE)))
        self.assertEqual(validate_suite(deep_merge(DEFAULT_SUITE, example))["delivery"]["enabled"], False)

    def test_version_files_agree(self):
        self.assertEqual((APP / "VERSION").read_text().strip(), zrs.SUITE_VERSION)

    def test_delivery_is_off_and_in_test_mode_by_default(self):
        d = suite()["delivery"]
        self.assertFalse(d["enabled"])
        self.assertEqual(d["mode"], "test")
        self.assertEqual((d["recipients"], d["test_recipients"]), ([], []))

    def test_rejections(self):
        cases = [
            {"schema": "wrong"}, {"week_start": "friday"}, {"formats": []}, {"formats": ["pdf", "doc"]},
            {"sla": {"target_percent": 0}}, {"sla": {"min_coverage": 1.5}}, {"limits": {"items": 0}},
            {"limits": {"trend_rows": "many"}}, {"output": {"retention_days": {"daily": 0}}},
            {"output": {"file_mode": "0644"}}, {"output": {"dir_mode": "0755"}}, {"output": {"file_mode": "rw-r-----"}},
            {"schedule": {"daily": "24:00"}}, {"schedule": {"weekly": "Funday 06:00"}}, {"schedule": {"monthly": "31 07:00"}},
            {"wan": {"links": [{"host": "x"}]}}, {"wan": {"links": [{"host": "x", "interface": "y", "capacity_bps": -1}]}},
            {"reports": {"nonexistent": {"enabled": True}}}, {"delivery": {"mode": "broadcast"}},
            {"delivery": {"test_recipients": ["not-an-address"]}},
            {"delivery": {"enabled": True, "mode": "live", "recipients": ["a@corp.test"], "allowed_recipient_domains": []}},
            {"delivery": {"enabled": True, "mode": "live", "recipients": ["a@evil.test"], "allowed_recipient_domains": ["corp.test"]}},
        ]
        for over in cases:
            with self.assertRaises(ConfigError, msg=str(over)):
                if "schema" in over:
                    validate_suite(dict(deep_merge(DEFAULT_SUITE, {}), **over))
                else:
                    suite(**over)

    def test_oncalendar_rendering(self):
        s = suite(schedule={"daily": "06:05", "weekly": "Sun 23:59", "monthly": "28 00:00"})
        self.assertEqual(on_calendar(s, "daily"), "*-*-* 06:05:00")
        self.assertEqual(on_calendar(s, "weekly"), "Sun *-*-* 23:59:00")
        self.assertEqual(on_calendar(s, "monthly"), "*-*-28 00:00:00")

    def test_missing_suite_file_uses_defaults(self):
        self.assertEqual(load_suite("/nonexistent/suite.json")["sla"]["target_percent"], 99.9)

    def test_rc2_report_json_is_still_valid_and_unchanged_in_contract(self):
        from zabbix_daily_report import load_config
        cfg = load_config(APP / "config" / "report.example.json")
        self.assertEqual(cfg["schema"], "zabbix-daily-reporting-v1")


class Units(unittest.TestCase):
    def test_timers_have_placeholders_and_are_not_enabled_by_files(self):
        for k in ("daily", "weekly", "monthly"):
            t = (APP / "systemd" / ("zabbix-report-suite-%s.timer" % k)).read_text()
            self.assertIn("OnCalendar=__ZRS_ON_CALENDAR__", t)
            self.assertIn("Unit=zabbix-report-suite@%s.service" % k, t)
        svc = (APP / "systemd" / "zabbix-report-suite@.service").read_text()
        for needle in ("NoNewPrivileges=true", "ProtectSystem=strict", "User=zabbix-report", "UMask=0027", "--cadence %i"):
            self.assertIn(needle, svc)
        self.assertNotIn("secrets.env --", svc)                       # secrets only via EnvironmentFile, never argv

    def test_installer_never_enables_suite_timers_by_default(self):
        common = (ROOT / "scripts" / "lib" / "daily-reporting-common.sh").read_text()
        install = (ROOT / "scripts" / "install_daily_reporting.sh").read_text()
        self.assertIn("--enable-suite-timers", install)
        self.assertIn("SUITE_TIMERS=INSTALLED_DISABLED", common)
        self.assertNotIn("enable --now zabbix-report-suite", install)
        self.assertNotIn("setenforce", common + install)
        self.assertNotIn("firewall-cmd", common + install)
        self.assertNotIn("sslverify=0", common + install)
        self.assertNotIn("--nogpgcheck", common + install)

    def test_no_zabbix_server_configuration_is_touched_by_suite_code(self):
        for p in (APP / "lib" / "zrs").glob("*.py"):
            t = p.read_text()
            self.assertNotIn("zabbix_server.conf", t, p.name)
            self.assertNotIn("_create_unverified_context", t, p.name)
            self.assertNotIn("verify=False", t, p.name)

    def test_gitattributes_keep_runtime_files_lf(self):
        ga = (ROOT / ".gitattributes").read_text()
        self.assertIn("reporting/daily-reporting/systemd/* text eol=lf", ga)


class Wheels(unittest.TestCase):
    LOCK = APP / "wheels.lock"

    def entries(self):
        out = []
        for line in self.LOCK.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                sha, name, url = line.split(None, 2)
                out.append((sha, name, url))
        return out

    def test_lock_is_complete_pinned_and_rhel9_compatible(self):
        names = [n for _, n, _ in self.entries()]
        for pkg in ("reportlab-4.2.5", "openpyxl-3.1.5", "et_xmlfile-2.0.0", "pillow-10.4.0", "charset_normalizer-3.4.0"):
            self.assertTrue([n for n in names if n.startswith(pkg)], pkg)
        for sha, name, url in self.entries():
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            self.assertTrue(url.startswith("https://files.pythonhosted.org/"), url)          # TLS, official index only
            if "cp3" in name:                                                                 # binary wheels: RHEL 9 = CPython 3.9 / x86_64 glibc
                self.assertIn("cp39", name)
                self.assertIn("x86_64", name)
                self.assertIn("manylinux", name)
            else:
                self.assertRegex(name, r"-(py3|py2\.py3)-none-any\.whl$")

    def test_real_wheels_match_the_lock_when_present(self):
        wh = APP / "wheelhouse"
        if not wh.is_dir() or not list(wh.glob("*.whl")):
            self.skipTest("wheelhouse not fetched (scripts/fetch_reporting_wheels.sh)")
        for sha, name, _ in self.entries():
            p = wh / name
            self.assertTrue(p.is_file(), name)
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), sha, name)

    def test_real_wheels_install_layout(self):
        wh = APP / "wheelhouse"
        if not wh.is_dir() or not list(wh.glob("*.whl")):
            self.skipTest("wheelhouse not fetched")
        tops = set()
        for _, name, _ in self.entries():
            with zipfile.ZipFile(str(wh / name)) as z:
                for m in z.namelist():
                    self.assertFalse(m.startswith("/") or ".." in m.split("/"), "unsafe member %s in %s" % (m, name))
                    tops.add(m.split("/")[0])
        for pkg in ("reportlab", "openpyxl", "et_xmlfile", "PIL", "charset_normalizer"):
            self.assertIn(pkg, tops)

    def test_no_wheelhouse_or_vendor_in_git(self):
        gi = (APP / ".gitignore").read_text()
        self.assertIn("wheelhouse/", gi)
        self.assertIn("vendor/", gi)


class SelfTest(unittest.TestCase):
    def test_selftest_runs_and_passes(self):
        buf = io.StringIO()
        self.assertEqual(cli.main(["--selftest"], stdout=buf), 0)
        text = buf.getvalue()
        for part in ("SELFTEST_PDF=PASS", "SELFTEST_XLSX=PASS", "SELFTEST_JSON=PASS", "SELFTEST_MANIFEST=PASS", "RESULT=PASS"):
            self.assertIn(part, text)

    def test_selftest_dataset_contains_no_real_hosts_or_secrets(self):
        t = (APP / "lib" / "zrs" / "data" / "selftest.json").read_text()
        self.assertIn("selftest.invalid", t)
        self.assertNotRegex(t, r"PNET|192\.168\.|10\.\d+\.\d+\.\d+")
        self.assertNotRegex(t, r"(?i)(password|token)\s*[=:]")

    def test_print_calendar_without_report_config(self):
        buf = io.StringIO()
        self.assertEqual(cli.main(["--print-calendar", "monthly", "--suite-config", "/nonexistent"], stdout=buf), 0)
        self.assertEqual(buf.getvalue().strip(), "*-*-01 07:00:00")

    def test_missing_config_is_an_error(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cli.main(["--report", "daily"]), 2)
        self.assertIn("--config is required", err.getvalue())


class NoSecrets(unittest.TestCase):
    def test_no_credentials_in_suite_sources_or_configs(self):
        files = list((APP / "lib").rglob("*.py")) + list((APP / "config").glob("*.json")) + list((APP / "systemd").glob("*")) + [APP / "bin" / "zabbix_report_suite.py"]
        for p in files:
            t = p.read_text(errors="replace")
            self.assertNotRegex(t, r"(?i)(api_token|password|secret)\s*[=:]\s*['\"][A-Za-z0-9_\-]{12,}['\"]", p.name)
            self.assertNotRegex(t, r"[0-9]{8,10}:[A-Za-z0-9_-]{34,36}", p.name)

    def test_python39_compatible_syntax(self):
        import ast
        for p in (APP / "lib").rglob("*.py"):
            tree = ast.parse(p.read_text(), feature_version=(3, 9))
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, getattr(ast, "Match", ()), p.name)       # no match statements (3.10+)
        for p in (APP / "lib" / "zrs").glob("*.py"):
            self.assertNotRegex(p.read_text(), r"^\s*def .*->\s*\w+\s*\|\s*\w+", p.name)      # no PEP 604 unions in annotations at runtime


if __name__ == "__main__":
    unittest.main()
