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
runtime_input = load_module(
    "runtime_input",
    ROOT / "scripts/prepare-runtime.py",
)
repository_scan = load_module(
    "repository_scan",
    ROOT / "scripts/repository-scan.py",
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
        fixture_value = "A" * 24
        secret = runtime_secret.validate_secret(fixture_value + "\n")
        server = runtime_secret.render("zabbix-server", secret, {})
        self.assertEqual(server, "DBPassword=" + fixture_value + "\n")
        server_config = runtime_secret.render_server_config("DBName=zabbix\n", secret)
        self.assertEqual(
            server_config,
            "DBName=zabbix\nDBPassword=" + fixture_value + "\n",
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
            runtime_secret.validate_secret(("A" * 24) + "\nsecond-line")
        with self.assertRaises(ValueError):
            runtime_secret.render_server_config("DBPassword=persistent\n", "safe")

    def test_runtime_directory_is_group_traversable(self):
        source = inspect.getsource(runtime_secret.atomic_write)
        self.assertIn("os.chmod(path.parent, 0o755)", source)
        self.assertNotIn("os.chown(path.parent", source)

    def test_runtime_parser_preserves_shell_special_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input"
            special_value = "Example-" + chr(36) + "h@!2030-value"
            content = {
                "INSTALL_MODE": "airgapped",
                "ZABBIX_SERVER_HOSTNAME": "zabbix.example.invalid",
                "ZABBIX_WEB_SERVER_NAME": "zabbix.example.invalid",
                "ZABBIX_TIMEZONE": "Asia/Riyadh",
                "ZABBIX_FRONTEND_PORT": "80",
                "ZABBIX_DB_PASSWORD": special_value,
                "ZABBIX_ADMIN_PASSWORD": special_value,
                "TLS_ENABLED": "false",
                "FIREWALL_WEB_SOURCES": "192.0.2.0/24",
                "FIREWALL_SERVER_SOURCES": "192.0.2.0/24",
                "FIREWALL_AGENT_SOURCES": "192.0.2.0/24",
            }
            path.write_text("".join(f"{key}={value}\n" for key, value in content.items()), encoding="utf-8")
            parsed = runtime_input.parse_file(path)
            self.assertEqual(parsed["ZABBIX_DB_PASSWORD"], special_value)

    def test_entry_points_do_not_evaluate_runtime_configuration(self):
        for name in ("install.sh", "verify.sh"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("source \"$CONFIG\"", text)
            self.assertNotIn("eval ", text)

    def test_repository_scan_passes_current_tree(self):
        self.assertEqual(repository_scan.main([]), 0)

    def test_repository_scan_fails_closed_on_runtime_password_match(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            release = temporary / "release"
            release.mkdir()
            (release / ".env.example").write_text("ZABBIX_DB_PASSWORD=\n", encoding="utf-8")
            (release / "README.md").write_text("safe release content\n", encoding="utf-8")
            fixture_secret = "Fixture-" + chr(36) + "special-value-2030"
            config = temporary / "runtime.env"
            config.write_text(
                "ZABBIX_DB_PASSWORD=" + fixture_secret + "\n"
                "ZABBIX_ADMIN_PASSWORD=" + fixture_secret + "\n",
                encoding="utf-8",
            )
            failures, _ = repository_scan.scan(release, config)
            self.assertEqual(failures, [])
            (release / "README.md").write_text(fixture_secret + "\n", encoding="utf-8")
            failures, _ = repository_scan.scan(release, config)
            self.assertIn("runtime password occurs in release file: README.md", failures)


class LockAndPortTests(unittest.TestCase):
    def test_firewall_role_resolves_exact_accepted_nevra(self):
        self.assertEqual(
            firewall_lock.locked_nevra(ROOT / "manifests/rpm-lockfile.txt", "firewalld"),
            "firewalld-0:1.3.4-15.el9_6.noarch",
        )
        firewall_tasks = (
            ROOT / "installer/roles/firewall/tasks/main.yml"
        ).read_text(encoding="utf-8")
        resolver = firewall_tasks[firewall_tasks.index("Resolve the exact accepted firewalld NEVRA") :]
        resolver = resolver[: resolver.index("Install the exact accepted firewalld NEVRA")]
        self.assertIn("check_mode: false", resolver)

    def test_firewall_cidr_validation_runs_in_check_mode(self):
        firewall_tasks = (
            ROOT / "installer/roles/firewall/tasks/main.yml"
        ).read_text(encoding="utf-8")
        validation = firewall_tasks[
            firewall_tasks.index("Validate source CIDRs using the Python standard library") :
        ]
        validation = validation[: validation.index("Resolve the exact accepted firewalld NEVRA")]
        self.assertIn("check_mode: false", validation)

    def test_tls_input_validation_runs_in_check_mode(self):
        tls_tasks = (
            ROOT / "installer/roles/tls/tasks/main.yml"
        ).read_text(encoding="utf-8")
        validation = tls_tasks[: tls_tasks.index("Create TLS destination directories")]
        self.assertEqual(validation.count("check_mode: false"), 5)

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

    def test_backup_streams_through_root_owned_files(self):
        backup = (
            ROOT / "installer/roles/backup/files/zabbix-offline-backup"
        ).read_text(encoding="utf-8")
        verify = (
            ROOT / "installer/roles/backup/files/zabbix-offline-verify-backup"
        ).read_text(encoding="utf-8")
        self.assertIn('pg_dump --format=custom "$DB_NAME" >"$partial/database.dump"', backup)
        self.assertIn('pg_restore --list <"$partial/database.dump"', backup)
        self.assertIn("pg_restore --list <database.dump", verify)
        self.assertNotIn('pg_dump --format=custom --file="$partial/database.dump"', backup)

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
        locked = locked_packages.read_locked_nevras(ROOT / "manifests/rpm-lockfile.txt")
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

    def test_clean_database_guard_and_admin_verification_are_wired(self):
        site = (ROOT / "installer/playbooks/site.yml").read_text(encoding="utf-8")
        database = (ROOT / "installer/roles/postgresql/tasks/main.yml").read_text(encoding="utf-8")
        admin = (ROOT / "installer/roles/zabbix_admin/tasks/main.yml").read_text(encoding="utf-8")
        verify = (ROOT / "installer/roles/verification/tasks/main.yml").read_text(encoding="utf-8")
        self.assertIn("- zabbix_admin", site)
        self.assertIn("assert-clean-database", database)
        self.assertIn("PASSWORD_BCRYPT", admin)
        self.assertIn("verify-admin-api", verify)
        self.assertIn("clean-seed-verified", verify)

    def test_clean_database_guard_excludes_stock_host_prototypes(self):
        guard = (
            ROOT / "installer/roles/postgresql/files/assert_clean_database.py"
        ).read_text(encoding="utf-8")
        self.assertIn("status IN (0,1) AND flags=0", guard)
        self.assertIn("WHERE h.flags=0 ORDER BY h.host", guard)

    def test_connected_staging_installs_tools_from_rhel_sources_only(self):
        stage = (ROOT / "scripts/stage-offline-bundle.sh").read_text(encoding="utf-8")
        self.assertIn("--disablerepo='*'", stage)
        self.assertIn("--enablerepo=rhel-9-for-x86_64-baseos-rpms", stage)
        self.assertIn("--enablerepo=rhel-9-for-x86_64-appstream-rpms", stage)
        self.assertNotIn("epel", stage.lower())

    def test_exact_platform_profile_is_pinned(self):
        profile = (ROOT / "compat/zabbix-7.0.yaml").read_text(encoding="utf-8")
        self.assertIn('"release": "9.6"', profile)
        self.assertIn('"version": "7.0.30"', profile)
        self.assertIn('"postgresql": "16"', profile)
        self.assertIn('"purpose": "fping-only"', profile)


if __name__ == "__main__":
    unittest.main()
