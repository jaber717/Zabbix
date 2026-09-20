#!/usr/bin/env python3
"""Require exact bundle/host minor compatibility, independently of OS support."""
import json
from pathlib import Path
import sys


def validate(root: Path, version: str) -> None:
    info = json.loads((root / 'BUILD-INFO.json').read_text())
    profile = json.loads((root / 'compat/zabbix-7.0.yaml').read_text())
    if info.get('target') != {'rhel_release': version, 'arch': 'x86_64'}:
        raise ValueError('bundle target differs from running host; stage a bundle on matching RHEL content')
    target = profile['target']
    if target != {'os': 'rhel', 'release': version, 'arch': 'x86_64', 'selinux': 'Enforcing'}:
        raise ValueError('bundle profile target differs from running host')
    if info.get('zabbix') != '7.0.30-release1.el9':
        raise ValueError('unexpected pinned Zabbix version')
    if profile['zabbix']['version'] != '7.0.30' or profile['zabbix']['release'] != 'release1.el9':
        raise ValueError('unexpected Zabbix profile')
    if profile['modules'] != {'postgresql': '16', 'php': '8.3', 'nginx': '1.24'}:
        raise ValueError('unexpected application streams')


if __name__ == '__main__':
    try:
        validate(Path(sys.argv[1]), sys.argv[2])
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit('FAIL: ' + str(exc))
