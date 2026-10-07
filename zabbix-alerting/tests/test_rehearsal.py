"""Offline rehearsal of scripts/lab-write-test.sh: the same steps and the same expected text,
run against the Zabbix 7.0 model. When a write-capable LAB token exists the script runs these
steps for real; this proves the expectations themselves are consistent with the tool."""
import os
import re
import unittest

from tests.fake_zabbix import MockZabbix
from tests.helpers import World

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def example(name):
    with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as fh:
        return fh.read()


def script_steps():
    """(name, rc, needle, args) parsed out of the real shell script, so they cannot drift apart."""
    steps = []
    with open(os.path.join(ROOT, "scripts", "lab-write-test.sh"), encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r'step "([^"]+)"\s+(\d+) "([^"]*)"\s+\./apply\.sh --env lab (.*)$', line.rstrip())
            if m:
                steps.append((m.group(1), int(m.group(2)), m.group(3), m.group(4)))
    return steps


class Rehearsal(unittest.TestCase):
    def setUp(self):
        z = MockZabbix(token="tok-lab")
        z.add_host("PNET-STC", ["Gi0/0", "Gi0/1", "Gi0/5"])
        self.w = World(mock=z, yaml_text=example("lab-validation.yaml"))

    def tearDown(self):
        self.w.close()

    def test_script_steps_hold_against_the_model(self):
        steps = script_steps()
        self.assertGreaterEqual(len(steps), 11)
        for name, want_rc, needle, args in steps:
            argv = args.split()
            if "--config" in argv:
                i = argv.index("--config")
                path = os.path.join(ROOT, argv[i + 1].replace('"$CFG"', "examples/lab-validation.yaml"))
                argv[i + 1] = path
            argv = [a.replace('"$CFG"', os.path.join(ROOT, "examples", "lab-validation.yaml")) for a in argv]
            rc, out = self.w.run(*argv)
            self.assertEqual(rc, want_rc, "%s\n%s" % (name, out))
            self.assertIn(needle, out, "%s\n%s" % (name, out))
        # after step 11 the tool has removed everything it manages from the host
        self.assertEqual(self.w.mock.host_macro_map("PNET-STC"), {})
        self.assertEqual(self.w.mock.hosts[self.w.mock.host_id("PNET-STC")]["templates"], [])

    def test_empty_selection_is_refused_without_flag(self):
        self.w.run("--config", os.path.join(ROOT, "examples", "lab-validation.yaml"))
        before = self.w.mock.snapshot()
        rc, out = self.w.run("--config", os.path.join(ROOT, "examples", "empty.yaml"))
        self.assertEqual(rc, 1)
        self.assertIn("--allow-empty", out)
        self.assertEqual(before, self.w.mock.snapshot())
        rc, out = self.w.run("--config", os.path.join(ROOT, "examples", "empty.yaml"), "--allow-empty")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
