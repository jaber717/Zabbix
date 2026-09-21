#!/usr/bin/env python3
"""Static safety tests for the offline AR8100 diagnostic package."""

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/diagnose-huawei-ar8100-snmp.sh"
SCAFFOLD = ROOT / "templates/huawei_ar8100_extensions_by_snmp.yaml"
DOC = ROOT / "docs/HUAWEI-AR8100-SNMP-DIAGNOSTIC.md"


class HuaweiDiagnosticPackageTests(unittest.TestCase):
    @staticmethod
    def embedded_python_blocks():
        text = SCRIPT.read_text(encoding="utf-8")
        return re.findall(r"<<'PY'.*?\n(.*?)\nPY(?:\s|$)", text, flags=re.DOTALL)

    def test_script_is_read_only_and_keeps_secrets_off_arguments(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertNotRegex(text, r"(?m)^\s*snmpset(?:\s|$)")
        self.assertNotRegex(text, r"SNMP_ARGS=.*(?:-A|-X)")
        self.assertIn("read -r -s -p 'SNMPv3 authentication passphrase", text)
        self.assertIn("read -r -s -p 'SNMPv3 privacy passphrase", text)
        self.assertIn("/dev/shm is not a verified tmpfs", text)
        self.assertIn('SNMPCONFPATH=$SECRET_DIR', text)
        self.assertIn("set +x", text)
        self.assertIn("does not advertise SHA-256 support", text)
        self.assertIn("does not advertise AES-192 support", text)
        self.assertIn("readonly SHARE_SUMMARY=/tmp/huawei-ar8100-share-summary.txt", text)
        self.assertIn('cat "$SHARE_SUMMARY"', text)
        self.assertNotIn('TARGET=', text.split("'SHARE SUMMARY'", 1)[-1])

    def test_collection_is_bounded_and_contains_required_checks(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("readonly MAX_WALK_ROWS=10000", text)
        self.assertIn("readonly COMMAND_TIMEOUT=30", text)
        self.assertIn("ulimit -f 16384", text)
        for oid in (
            ".1.3.6.1.2.1.1.5.0",
            ".1.3.6.1.2.1.1.1.0",
            ".1.3.6.1.2.1.1.2.0",
            ".1.3.6.1.2.1.2.2.1.10",
            ".1.3.6.1.2.1.2.2.1.16",
            ".1.3.6.1.2.1.31.1.1.1.6",
            ".1.3.6.1.2.1.31.1.1.1.10",
            ".1.3.6.1.2.1.2.2.1.5",
            ".1.3.6.1.2.1.31.1.1.1.15",
        ):
            self.assertIn(oid, text)
        for classification in (
            "HC64_ACTIVE",
            "HC64_ZERO_32_ACTIVE",
            "BOTH_ZERO",
            "COUNTER_UNSUPPORTED",
            "WRONG_MAPPING",
            "INTERFACE_DOWN",
            "SPEED_UNKNOWN",
        ):
            self.assertIn(classification, text)

    def test_embedded_python_is_syntactically_valid(self):
        blocks = self.embedded_python_blocks()
        self.assertEqual(len(blocks), 4)
        for number, block in enumerate(blocks, 1):
            with self.subTest(block=number):
                compile(block, f"embedded-python-{number}", "exec")

    def test_mock_mapping_and_counter_classification(self):
        mapping_code, analysis_code, _, summary_code = self.embedded_python_blocks()
        columns = {
            'ifIndex': ('.1.3.6.1.2.1.2.2.1.1', 'INTEGER: 10'),
            'ifName': ('.1.3.6.1.2.1.31.1.1.1.1', 'STRING: "10GE0/0/5"'),
            'ifDescr': ('.1.3.6.1.2.1.2.2.1.2', 'STRING: "10GE0/0/5"'),
            'ifAlias': ('.1.3.6.1.2.1.31.1.1.1.18', 'STRING: "Uplink"'),
            'ifType': ('.1.3.6.1.2.1.2.2.1.3', 'INTEGER: ethernetCsmacd(6)'),
            'ifOperStatus': ('.1.3.6.1.2.1.2.2.1.8', 'INTEGER: up(1)'),
            'ifAdminStatus': ('.1.3.6.1.2.1.2.2.1.7', 'INTEGER: up(1)'),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (base, value) in columns.items():
                (root / f'{name}.raw').write_text(f'{base}.10 = {value}\n', encoding='utf-8')
            subprocess.run(
                [sys.executable, '-c', mapping_code, str(root), '10GE0/0/5'],
                check=True, capture_output=True, text=True,
            )
            self.assertIn('\x1fOK\x1f10\x1f10GE0/0/5', (root / 'selected-interfaces.txt').read_text())

            before = '\n'.join((
                '.1.3.6.1.2.1.2.2.1.10.10 = Counter32: 100',
                '.1.3.6.1.2.1.2.2.1.16.10 = Counter32: 200',
                '.1.3.6.1.2.1.31.1.1.1.6.10 = Counter64: 0',
                '.1.3.6.1.2.1.31.1.1.1.10.10 = Counter64: 0',
                '.1.3.6.1.2.1.2.2.1.5.10 = Gauge32: 4294967295',
                '.1.3.6.1.2.1.31.1.1.1.15.10 = Gauge32: 10000',
            )) + '\n'
            after = before.replace('Counter32: 100', 'Counter32: 400').replace('Counter32: 200', 'Counter32: 500')
            (root / 'standard-counters-before.raw').write_text(before, encoding='utf-8')
            (root / 'standard-counters-after.raw').write_text(after, encoding='utf-8')
            (root / 'huawei-if-ext-before.raw').write_text(
                '.1.3.6.1.4.1.2011.5.25.41.1.7.1.1.8.10 = Counter64: 1000\n', encoding='utf-8')
            (root / 'huawei-if-ext-after.raw').write_text(
                '.1.3.6.1.4.1.2011.5.25.41.1.7.1.1.8.10 = Counter64: 1600\n', encoding='utf-8')
            (root / 'huawei-cbqos-before.raw').write_text('', encoding='utf-8')
            (root / 'huawei-cbqos-after.raw').write_text('', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, '-c', analysis_code, str(root),
                 '2026-01-01T00:00:00Z', '2026-01-01T00:00:15Z', '15'],
                check=True, capture_output=True, text=True,
            ).stdout
            (root / 'analysis.txt').write_text(result, encoding='utf-8')
            (root / 'device-identity.txt').write_text(
                'sysName=router\n'
                'sysDescr=Huawei Versatile Routing Platform AR8100 VRP V800R023\n'
                'sysObjectID=OID: .1.3.6.1.4.1.2011.2.999\n',
                encoding='utf-8',
            )
            summary = root / 'share-summary.txt'
            subprocess.run(
                [sys.executable, '-c', summary_code, str(root), str(summary), '1.0.0'],
                check=True, capture_output=True, text=True,
            )
            self.assertIn('classification=HC64_ZERO_32_ACTIVE', result)
            self.assertIn('selected_index_component=TRUE', result)
            self.assertIn('huawei_changed_numeric_candidates=PRESENT_UNVERIFIED', result)
            summary_text = summary.read_text(encoding='utf-8')
            self.assertIn('MODEL=AR8100', summary_text)
            self.assertIn('IFINDEX_1=10', summary_text)
            self.assertIn('RX32_1=MOVING DELTA=300', summary_text)
            self.assertIn('RX64_1=ZERO DELTA=0', summary_text)
            self.assertIn('ROOT_CAUSE_1=HC64_ZERO_32_ACTIVE', summary_text)
            self.assertIn(
                'LIVE_CANDIDATE_OIDS=.1.3.6.1.4.1.2011.5.25.41.1.7.1.1.8.10',
                summary_text,
            )
            self.assertLessEqual(len(summary_text.splitlines()), 30)

    def test_scaffold_defines_no_monitoring_entities(self):
        text = SCAFFOLD.read_text(encoding="utf-8")
        self.assertIn("NON-PRODUCTION SCAFFOLD", text)
        for key in ("items:", "discovery_rules:", "item_prototypes:", "triggers:", "graphs:", "snmp_oid:"):
            self.assertNotRegex(text, rf"(?m)^\s+{re.escape(key)}\s*$")

    def test_documentation_preserves_evidence_gate(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("no runtime validation against an AR8100", text)
        self.assertIn("sudo ./scripts/diagnose-huawei-ar8100-snmp.sh", text)
        self.assertIn("sudo cat /tmp/huawei-ar8100-share-summary.txt", text)
        self.assertIn("Until then the root cause and remediation remain unproven", text)


if __name__ == "__main__":
    unittest.main()
