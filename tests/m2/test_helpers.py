from __future__ import annotations

import importlib.util
import inspect
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
firewall_lock = load_module(
    "firewall_lock",
    ROOT / "installer/roles/firewall/files/locked_nevra.py",
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
        server_config = runtime_secret.render_server_config("DBName=zabbix\n", secret)
        self.assertEqual(
            server_config,
            "DBName=zabbix\nDBPassword=Abcdefghijklmnop12345678\n",
        )
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
        with self.assertRaises(ValueError):
            runtime_secret.render_server_config("DBPassword=persistent\n", "safe")

    def test_runtime_directory_is_group_traversable(self):
        source = inspect.getsource(runtime_secret.atomic_write)
        self.assertIn("os.chmod(path.parent, 0o755)", source)
        self.assertNotIn("os.chown(path.parent", source)


class LockAndPortTests(unittest.TestCase):
    def test_firewall_role_resolves_exact_accepted_nevra(self):
        self.assertEqual(
            firewall_lock.locked_nevra(ROOT / "rpm-lockfile.txt", "firewalld"),
            "firewalld-0:1.3.4-15.el9_6.noarch",
        )

    def test_runtime_handlers_are_applied_before_verification(self):
        verification = (
            ROOT / "installer/roles/verification/tasks/main.yml"
        ).read_text(encoding="utf-8")
        firewall = (
            ROOT / "installer/roles/firewall/tasks/main.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("ansible.builtin.meta: flush_handlers", verification)
        self.assertIn("Query desired rich rules in the active runtime", firewall)
        web = (
            ROOT / "installer/roles/zabbix_web/tasks/main.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("Detect whether nginx has applied the managed Zabbix listener", web)

    def test_selinux_safety_probe_runs_in_check_mode(self):
        baseline = (
            ROOT / "installer/roles/os_baseline/tasks/main.yml"
        ).read_text(encoding="utf-8")
        probe = baseline[baseline.index("Read current SELinux enforcement") :]
        probe = probe[: probe.index("Require SELinux Enforcing")]
        self.assertIn("check_mode: false", probe)
        selinux = (
            ROOT / "installer/roles/selinux/tasks/main.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(selinux.count("check_mode: false"), 2)

    def test_check_mode_guards_precede_skipped_database_probe_results(self):
        database = (
            ROOT / "installer/roles/postgresql/tasks/main.yml"
        ).read_text(encoding="utf-8")
        for probe in (
            "postgresql_role_probe.stdout",
            "postgresql_database_probe.stdout",
            "postgresql_schema_probe.stdout",
        ):
            self.assertLess(
                database.rfind("not ansible_check_mode", 0, database.index(probe)),
                database.index(probe),
            )

    def test_database_role_installs_schema_payload_before_import(self):
        defaults = (
            ROOT / "installer/roles/postgresql/defaults/main.yml"
        ).read_text(encoding="utf-8")
        tasks = (
            ROOT / "installer/roles/postgresql/tasks/main.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("- zabbix-sql-scripts", defaults)
        self.assertLess(
            tasks.index("Install PostgreSQL 16 from the offline repository"),
            tasks.index("Import the accepted Zabbix schema only when absent"),
        )
        self.assertIn("--username {{ zabbix_db_user | quote }}", tasks)
        self.assertIn('PGPASSWORD: "{{ zabbix_db_password }}"', tasks)

    def test_systemd_host_key_is_initialized_before_secret_encryption(self):
        tasks = (
            ROOT / "installer/roles/zabbix_server/tasks/main.yml"
        ).read_text(encoding="utf-8")
        self.assertLess(
            tasks.index("Initialize the systemd host credential key when absent"),
            tasks.index("Encrypt the operator-provided database credential for systemd"),
        )
        self.assertIn("- --with-key=host", tasks)

    def test_server_config_matches_vendor_pid_contract(self):
        config = (
            ROOT / "installer/roles/zabbix_server/templates/zabbix_server.conf.j2"
        ).read_text(encoding="utf-8")
        self.assertIn("PidFile=/run/zabbix/zabbix_server.pid", config)

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
