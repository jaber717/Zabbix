from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_state = load_module(
    "release_state",
    ROOT / "installer/roles/os_baseline/files/release_state.py",
)
runtime_secret = load_module(
    "runtime_secret",
    ROOT / "installer/roles/zabbix_server/files/render_runtime_secret.py",
)
locked_packages = load_module(
    "locked_packages",
    ROOT / "installer/roles/verification/files/verify_locked_packages.py",
)
listening_ports = load_module(
    "listening_ports",
    ROOT / "installer/roles/verification/files/verify_listening_ports.py",
)


class ReleaseStateTests(unittest.TestCase):
    def test_fresh_and_converged(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "release.json"
            self.assertEqual(release_state.inspect_state(state, "1.0.0", "7.0.30")["status"], "fresh")
            state.write_text('{"release":"1.0.0","zabbix":"7.0.30"}', encoding="utf-8")
            self.assertEqual(release_state.inspect_state(state, "1.0.0", "7.0.30")["status"], "converge")

    def test_upgrade_and_downgrade_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "release.json"
            state.write_text('{"release":"1.0.0","zabbix":"7.0.30"}', encoding="utf-8")
            self.assertEqual(release_state.inspect_state(state, "1.1.0", "7.0.30")["status"], "upgrade_required")
            self.assertEqual(release_state.inspect_state(state, "0.9.0", "7.0.30")["status"], "unsupported_downgrade")


class RuntimeSecretTests(unittest.TestCase):
    def test_safe_secret_and_rendering(self):
        secret = runtime_secret.validate_secret("Abcdefghijklmnop12345678\n")
        server = runtime_secret.render("zabbix-server", secret, {})
        self.assertEqual(server, "DBPassword=Abcdefghijklmnop12345678\n")
        web = runtime_secret.render(
            "zabbix-web",
            secret,
            {
                "host": "127.0.0.1",
                "port": "5432",
                "name": "zabbix",
                "user": "zabbix",
                "tls": "0",
                "server_port": "10051",
                "server_name": "zabbix.example.invalid",
            },
        )
        self.assertIn("$DB['TYPE'] = 'POSTGRESQL';", web)
        self.assertNotIn("<?php\n$DB['PASSWORD'] = ''", web)

    def test_unsafe_secret_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime_secret.validate_secret("short")
        with self.assertRaises(ValueError):
            runtime_secret.validate_secret("Abcdefghijklmnop12345678\nsecond-line")


class LockAndPortTests(unittest.TestCase):
    def test_m1_lock_contains_exact_fping(self):
        locked = locked_packages.read_locked_nevras(ROOT / "rpm-lockfile.txt")
        self.assertIn("fping-0:5.1-1.el9.x86_64", locked)
        self.assertEqual(len(locked), 313)

    def test_proc_port_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory) / "tcp"
            proc.write_text(
                "  sl  local_address rem_address st\n"
                "   0: 0100007F:2743 00000000:0000 0A\n"
                "   1: 0100007F:1538 00000000:0000 01\n",
                encoding="ascii",
            )
            self.assertEqual(listening_ports.listening_ports((proc,)), {10051})


if __name__ == "__main__":
    unittest.main()
