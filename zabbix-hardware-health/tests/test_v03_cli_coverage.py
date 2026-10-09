import os
import unittest

import hardware_audit
from hwh import coverage, policy, vendordefs
from hwh.api import AuditError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = policy.load_catalogue(os.path.join(ROOT, "config", "vendors.yaml"))
DEFS = vendordefs.load_dir(os.path.join(ROOT, "vendors"))


def run(args):
    lines = []
    rc = hardware_audit.main(args, base=ROOT, out=lines.append)
    return rc, "\n".join(lines)


class Coverage(unittest.TestCase):
    def test_no_real_device_claims(self):
        m = coverage.build(DEFS, CAT, coverage.load_device_evidence(os.path.join(ROOT, "config", "device-evidence.yaml")))
        self.assertFalse(any(c["device"] for c in m["rows"]))
        self.assertNotIn("REAL DEVICE VERIFIED |", coverage.render_markdown(m))

    def test_evidence_promotes_only_with_entry(self):
        m = coverage.build(DEFS, CAT, {"cisco-iosxe:fan": {"device": "x", "recorded_by": "y", "raw_capture": "z"}})
        row = [c for c in m["rows"] if c["family"] == "cisco-iosxe" and c["category"] == "fan"][0]
        self.assertTrue(row["device"])

    def test_bad_evidence_entry_rejected(self):
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        f.write("schema: 1\nverified:\n  a:b: {device: x}\n")
        f.close()
        with self.assertRaises(AuditError):
            coverage.load_device_evidence(f.name)

    def test_committed_vendor_coverage_is_current(self):
        m = coverage.build(DEFS, CAT, coverage.load_device_evidence(os.path.join(ROOT, "config", "device-evidence.yaml")))
        with open(os.path.join(ROOT, "docs", "VENDOR-COVERAGE.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().replace("\r\n", "\n"), coverage.render_markdown(m))

    def test_unsupported_blocked_cells_have_reasons(self):
        for c in coverage.build(DEFS, CAT)["rows"]:
            if not c["implemented"] and not c["readings"]:
                self.assertTrue(c["blocked"], c)


class Cli(unittest.TestCase):
    def test_offline_commands(self):
        for what in ("list", "simulate", "messages", "check", "coverage"):
            rc, text = run(["vendors", what])
            self.assertEqual(rc, 0, (what, text))

    def test_template_build_and_check(self):
        rc, text = run(["template", "check", "--definition", "cisco-iosxe"])
        self.assertEqual(rc, 0)
        rc, text = run(["template", "build", "--definition", "huawei-vrp"])
        self.assertEqual(rc, 0)
        self.assertIn("zabbix_export", text)

    def test_blocked_definition_cannot_be_built(self):
        rc, _ = run(["template", "check", "--definition", "cisco-asr8500"])
        self.assertEqual(rc, 3)

    def test_template_apply_refused_in_production_before_network(self):
        rc, _ = run(["--env", "production", "template", "apply", "--definition", "cisco-iosxe"])
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main()
