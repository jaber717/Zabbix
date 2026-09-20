from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'installer/lib/platform.sh'
BASH = os.environ.get('TEST_BASH') or shutil.which('bash')


def module(relative):
    spec = importlib.util.spec_from_file_location('tested', ROOT / relative)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class PlatformTests(unittest.TestCase):
    def shell(self, script, *args):
        self.assertIsNotNone(BASH, 'bash required for actual shell helper tests')
        return subprocess.run([BASH, '-c', script, 'test', HELPER.as_posix(), *args],
                              text=True, capture_output=True)

    def test_os_acceptance_matrix_and_caller_globals(self):
        cases = [('rhel', v, 'x86_64', True) for v in ('9.4', '9.6', '9.7', '9.10')]
        cases += [('rhel', v, 'x86_64', False) for v in ('8.10', '10.0', '9')]
        cases += [(name, '9.7', 'x86_64', False) for name in ('centos', 'rocky', 'almalinux')]
        cases += [('rhel', '9.6', 'aarch64', False), ('rhel', '9x7', 'x86_64', False)]
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'os-release'
            for name, version, arch, accepted in cases:
                with self.subTest(name=name, version=version, arch=arch):
                    fixture.write_text(f'ID="{name}"\nVERSION_ID="{version}"\nNAME="ignored"\n')
                    result = self.shell('source "$1"; ID=caller; NAME=caller; VERSION=caller; '
                        'validate_rhel_platform "$2" "$3" || exit $?; '
                        '[[ $ID == caller && $NAME == caller && $VERSION == caller ]] || exit 2; '
                        'printf "%s" "$RHEL_VERSION_ID"', fixture.as_posix(), arch)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    if accepted:
                        self.assertEqual(result.stdout, version)
                    else:
                        self.assertIn('detected ID=', result.stderr)

    def test_os_release_is_never_evaluated(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'os-release'
            fixture.write_text('ID=rhel\nVERSION_ID="$(printf 9.7)"\n')
            result = self.shell('source "$1"; validate_rhel_platform "$2" x86_64', fixture.as_posix())
            self.assertNotEqual(result.returncode, 0)

    def test_release_pin_parser(self):
        for status, output, expected in [
            ('0', 'Release: 9.7', '9.7'), ('0', '9.6', '9.6'),
            ('0', 'Release not set', ''), ('1', 'Release: 9.7', ''),
            ('124', 'Release: 9.7', ''), ('0', 'informational 9.7', ''),
            ('0', 'Release: 9.7\nwarning', '')]:
            with self.subTest(output=output, status=status):
                result = self.shell('source "$1"; parse_release_pin "$2" "$3"', status, output)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), expected)

    def test_release_context_uses_host_dnf_without_pin(self):
        self.assertIn('substitutions.update_from_etc("/", varsdir=b.conf.varsdir)', HELPER.read_text())
        script = '''source "$1"
RHEL_VERSION_ID=9.7
timeout() { printf 'Release not set'; }
python3() { printf '9'; }
detect_release_context || exit $?
[[ ${#HOST_RELEASE_ARGS[@]} == 0 && $DNF_EFFECTIVE_RELEASE == 9 ]]
'''
        self.assertEqual(self.shell(script).returncode, 0)

    def test_release_context_honors_real_pin_and_rejects_conflict(self):
        script = '''source "$1"
RHEL_VERSION_ID=$2
timeout() { printf 'Release: 9.7'; }
python3() { return 99; }
detect_release_context || exit $?
[[ ${HOST_RELEASE_ARGS[0]} == --releasever=9.7 && $DNF_EFFECTIVE_RELEASE == 9.7 ]]
'''
        self.assertEqual(self.shell(script, '9.7').returncode, 0)
        self.assertNotEqual(self.shell(script, '9.6').returncode, 0)

    def test_bundle_minor_mismatch_fails(self):
        validator = module('installer/lib/validate_bundle.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'compat').mkdir()
            profile = json.loads((ROOT / 'compat/zabbix-7.0.yaml').read_text())
            profile['target']['release'] = '9.6'
            (root / 'compat/zabbix-7.0.yaml').write_text(json.dumps(profile))
            (root / 'BUILD-INFO.json').write_text(json.dumps({
                'target': {'rhel_release': '9.6', 'arch': 'x86_64'},
                'zabbix': '7.0.30-release1.el9'}))
            validator.validate(root, '9.6')
            with self.assertRaisesRegex(ValueError, 'bundle target differs'):
                validator.validate(root, '9.7')

    def test_connected_rejects_explicit_old_bundle(self):
        parser = module('scripts/prepare-runtime.py')
        with self.assertRaisesRegex(SystemExit, 'empty OFFLINE_BUNDLE_ROOT'):
            parser.validate_values({'INSTALL_MODE': 'connected', 'OFFLINE_BUNDLE_ROOT': '/old'})

    def test_runtime_timezone_and_transport_validation(self):
        parser = module('scripts/prepare-runtime.py')
        values = {'INSTALL_MODE': 'connected', 'ZABBIX_TIMEZONE': 'Etc/UTC',
                  'ZABBIX_DB_PASSWORD': 'X' * 24}
        with patch.object(Path, 'is_file', return_value=True):
            parser.validate_values(values)
            with self.assertRaisesRegex(SystemExit, 'transport-safe'):
                parser.validate_values(dict(values, ZABBIX_DB_PASSWORD='bad value with spaces'))
        with patch.object(Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(SystemExit, 'IANA timezone'):
                parser.validate_values(values)
        with self.assertRaisesRegex(SystemExit, 'IANA timezone'):
            parser.validate_values(dict(values, ZABBIX_TIMEZONE='../etc/passwd'))

    def test_upgrade_uses_shared_controls_and_propagates_failure(self):
        script = (ROOT / 'installer/roles/backup/files/zabbix-offline-upgrade-preflight').read_text()
        self.assertIn('source /usr/libexec/zabbix-offline/platform.sh', script)
        self.assertIn('validate_rhel_platform || exit 1', script)
        self.assertIn('validate_bundle.py "$release_root" "$RHEL_VERSION_ID"', script)
        self.assertNotIn('readarray -t versions < <(', script)
        self.assertIn('version_output=$(python3', script)

    def test_staging_controls_and_generated_lock(self):
        install = (ROOT / 'install.sh').read_text()
        stage = (ROOT / 'scripts/stage-offline-bundle.sh').read_text()
        build = (ROOT / 'build/build.sh').read_text()
        self.assertNotIn('read -r release_root </etc/zabbix-offline/bundle-root', install)
        self.assertIn('status --porcelain', stage)
        self.assertNotIn('--untracked-files=no', stage)
        self.assertIn('export LOCK_MODE=resolve', stage)
        self.assertIn('download --resolve --alldeps', build)
        self.assertIn('rpm --root "$LOCAL_ROOT" --initdb', build)
        self.assertIn('local_dnf "$LOCAL_ROOT" "$REPO_DIR" install', build)
        self.assertIn('cp "$LOCK_CANDIDATE" "$RELEASE_TREE/rpm-lockfile.txt"', build)
        self.assertIn('"$LOCK_MODE" == frozen', build)
        self.assertIn('assert_lock_source_policy "$LOCK_CANDIDATE"', build)
        self.assertIn('$content_release == "$RHEL_VERSION_ID"', build)

    def test_no_active_exact_minor_gate_or_forced_pin(self):
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
        for name in tracked:
            path = ROOT / name
            if name.startswith(('tests/', 'docs/')) or path.suffix == '.md':
                continue
            if path.suffix not in ('.sh', '.py', '.yml', '.yaml', ''):
                continue
            text = path.read_text()
            with self.subTest(path=name):
                self.assertNotIn('--releasever=' + '9.6', text)
                self.assertNotIn('release --set', text)
                if name != 'compat/zabbix-7.0.yaml':
                    self.assertNotIn('9.6', text)

    def test_tracked_shell_lf_and_modes(self):
        rows = subprocess.check_output(['git', 'ls-files', '--stage'], cwd=ROOT, text=True).splitlines()
        for row in rows:
            meta, name = row.split('\t', 1)
            path = ROOT / name
            data = path.read_bytes()
            if path.suffix != '.sh' and not data.startswith(b'#!/usr/bin/env bash'):
                continue
            with self.subTest(path=name):
                self.assertNotIn(b'\r\n', data)
                sourced = name in ('installer/lib/platform.sh', 'build/lib/common.sh')
                self.assertEqual(meta.split()[0], '100644' if sourced else '100755')

    def test_required_files_are_tracked(self):
        tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines())
        for directory in ('installer', 'scripts', 'build', 'compat', 'tests'):
            for path in (ROOT / directory).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and 'out' not in path.parts:
                    self.assertIn(path.relative_to(ROOT).as_posix(), tracked)


if __name__ == '__main__':
    unittest.main()
