"""Release regression gate: every Python file in the repository compiles (the v1.0.1 ingest-handover.py defect) and every shell script passes bash -n."""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("check_syntax", os.path.join(HERE, "..", "scripts", "check-syntax.py"))
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class TestSyntaxGate(unittest.TestCase):
    def test_every_python_file_in_the_repository_compiles(self):
        top, files = gate.tracked_files()
        py = [f for f in files if f.endswith(".py")]
        self.assertGreater(len(py), 20, "gate found suspiciously few Python files")
        bad = [e for e in (gate.check_python(os.path.join(top, f)) for f in py if os.path.isfile(os.path.join(top, f))) if e]
        self.assertEqual(bad, [])

    def test_ingest_handover_regression(self):
        top, files = gate.tracked_files()
        rel = [f for f in files if f.endswith("scripts/ingest-handover.py")]
        self.assertEqual(len(rel), 1)
        self.assertIsNone(gate.check_python(os.path.join(top, rel[0])))

    def test_ingest_handover_starts_and_prints_help(self):
        script = os.path.join(HERE, "..", "scripts", "ingest-handover.py")
        res = subprocess.run([sys.executable, script, "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
        self.assertIn(b"--via-grafana-proxy", res.stdout)

    def test_every_shell_script_passes_bash_n(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash not available")
        top, files = gate.tracked_files()
        sh = [f for f in files if f.endswith(".sh")]
        self.assertGreater(len(sh), 3)
        bad = [e for e in (gate.check_bash(os.path.join(top, f), bash) for f in sh if os.path.isfile(os.path.join(top, f))) if e]
        self.assertEqual(bad, [])

    def test_the_gate_detects_an_unterminated_string(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "broken.py")
            with open(p, "w") as fh:
                fh.write('header = ("# a\n"\n          "b\n"\n          % ())\nx = "unterminated\n')
            err = gate.check_python(p)
            self.assertIsNotNone(err)
            self.assertIn("broken.py", err)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_gate_detects_newer_than_supported_syntax(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "new.py")
            with open(p, "w") as fh:
                fh.write("match 1:\n    case 1:\n        pass\n")
            self.assertIsNotNone(gate.check_python(p))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_gate_detects_a_bad_shell_script(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash not available")
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "bad.sh")
            with open(p, "w") as fh:
                fh.write('if true; then\necho "x\n')
            self.assertIsNotNone(gate.check_bash(p, bash))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
