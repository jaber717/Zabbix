import os
import tempfile
import unittest

from netalert import config


def parse_text(text):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(path, "w") as fh:
        fh.write(text)
    try:
        return config.load(path)
    finally:
        os.remove(path)


def msgs(desired):
    return [p.message for p in desired.problems]


GOOD = """
hosts:
  R1:
    site: HQ
    interfaces:
      Gi0/0: {description: x}
"""


class ConfigValidation(unittest.TestCase):
    def test_minimal_ok_and_defaults_applied(self):
        d = parse_text(GOOD)
        self.assertEqual(msgs(d), [])
        c = d.hosts["R1"]["interfaces"]["Gi0/0"]
        self.assertEqual(c["severity"], "high")
        self.assertEqual(c["utilization"]["threshold"], 70)
        self.assertEqual(c["utilization"]["recovery"], 65)
        self.assertFalse(c["utilization"]["enabled"])
        self.assertEqual(c["utilization"]["poll_seconds"], 10)

    def test_interface_overrides_defaults(self):
        d = parse_text("""
defaults: {severity: warning, utilization: {threshold: 80, recovery: 75}}
hosts:
  R1:
    interfaces:
      A: {description: a}
      B: {description: b, severity: disaster, utilization: {enabled: true, threshold: 90, recovery: 85}}
""")
        self.assertEqual(msgs(d), [])
        a, b = d.hosts["R1"]["interfaces"]["A"], d.hosts["R1"]["interfaces"]["B"]
        self.assertEqual((a["severity"], a["utilization"]["threshold"]), ("warning", 80))
        self.assertEqual((b["severity"], b["utilization"]["threshold"]), ("disaster", 90))

    def test_invalid_severity(self):
        d = parse_text(GOOD.replace("{description: x}", "{description: x, severity: urgent}"))
        self.assertTrue(any("invalid severity" in m for m in msgs(d)))

    def test_recovery_must_be_below_threshold(self):
        for rec in (70, 71, 100):
            d = parse_text(GOOD.replace("{description: x}",
                           "{description: x, utilization: {enabled: true, threshold: 70, recovery: %d}}" % rec))
            self.assertTrue(any("must be lower" in m for m in msgs(d)), rec)

    def test_threshold_range(self):
        for thr in (0, -5, 101, "high"):
            d = parse_text(GOOD.replace("{description: x}",
                           "{description: x, utilization: {enabled: true, threshold: %s, recovery: 1}}" % thr))
            self.assertTrue(msgs(d), thr)

    def test_bad_poll_interval(self):
        d = parse_text(GOOD.replace("{description: x}", "{description: x, utilization: {poll_interval: fast}}"))
        self.assertTrue(any("poll_interval" in m for m in msgs(d)))

    def test_unknown_keys_rejected_everywhere(self):
        self.assertTrue(any("unknown key 'treshold'" in m for m in msgs(parse_text(
            GOOD.replace("{description: x}", "{description: x, utilization: {treshold: 70}}")))))
        self.assertTrue(any("unknown key 'sevrity'" in m for m in msgs(parse_text(
            GOOD.replace("{description: x}", "{description: x, sevrity: high}")))))
        self.assertTrue(any("unknown key 'hots'" in m for m in msgs(parse_text("hots: {}\n" + GOOD))))

    def test_duplicate_yaml_keys_rejected(self):
        with self.assertRaises(config.ConfigError):
            parse_text("""
hosts:
  R1:
    interfaces:
      Gi0/0: {description: a}
      Gi0/0: {description: b}
""")

    def test_missing_description(self):
        d = parse_text("hosts:\n  R1:\n    interfaces:\n      Gi0/0: {role: ISP}\n")
        self.assertTrue(any("description is required" in m for m in msgs(d)))

    def test_host_without_interfaces(self):
        d = parse_text("hosts:\n  R1: {site: HQ}\n")
        self.assertTrue(any("at least one" in m for m in msgs(d)))

    def test_expected_speed_parsing(self):
        self.assertEqual(config.parse_speed("100G"), 100 * 10 ** 9)
        self.assertEqual(config.parse_speed("1000M"), 10 ** 9)
        self.assertEqual(config.parse_speed(None), None)
        with self.assertRaises(ValueError):
            config.parse_speed("fast")

    def test_error_recovery_must_be_lower_than_rate(self):
        d = parse_text(GOOD.replace("{description: x}", "{description: x, errors: {enabled: true, rate: 2, recovery: 2}}"))
        self.assertTrue(any("errors.recovery" in m for m in msgs(d)))

    def test_non_mapping_top_level(self):
        with self.assertRaises(config.ConfigError):
            parse_text("- a\n- b\n")

    def test_shipped_files_are_valid(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("config/interfaces.lab.yaml", "config/interfaces.production.yaml", "examples/interfaces.sample.yaml"):
            d = config.load(os.path.join(root, rel))
            self.assertEqual(msgs(d), [], rel)


if __name__ == "__main__":
    unittest.main()
