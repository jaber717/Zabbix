#!/usr/bin/env python3
"""Checks every preprocessing step in the template export (no MIBs or Zabbix server needed).
Limits: 255 characters per parameter (limit reported by the Zabbix 7.0.30 importer), 2048 joined (schema size as
recalled, unverified); per-type parameter counts/formats for the step types this template uses."""
import re
import sys
import yaml

Y = sys.argv[1] if len(sys.argv) > 1 else 'templates/gigamon/zbx_templates_gigamon_snmp.yaml'
RULES = {  # type: (allowed param counts, validator)
    'MULTIPLIER': ({1}, lambda p: re.fullmatch(r'-?\d+(\.\d+)?', p[0]) is not None),
    'DISCARD_UNCHANGED_HEARTBEAT': ({1}, lambda p: re.fullmatch(r'\d+[smhdw]?', p[0]) is not None),
    'CHANGE_PER_SECOND': ({0}, lambda p: True),
    'REGEX': ({2}, lambda p: re.compile(p[0]) is not None),
}
fails, n, longest = [], 0, 0


def walk(o, path):
    global n, longest
    if isinstance(o, dict):
        if 'preprocessing' in o:
            for i, s in enumerate(o['preprocessing']):
                n += 1
                where = '%s key=%s step[%d] %s' % (path, o.get('key'), i, s.get('type'))
                params = [str(x) for x in s.get('parameters', [])]
                if params == ['']:
                    params = []          # exported form of "no parameters"
                longest = max([longest] + [len(x) for x in params])
                if s.get('type') not in RULES:
                    fails.append(where + ': step type not covered by this check')
                    continue
                counts, ok = RULES[s['type']]
                if len(params) not in counts:
                    fails.append(where + ': %d parameters' % len(params))
                elif params and not ok(params):
                    fails.append(where + ': bad parameter %r' % params)
                for x in params:
                    if len(x) > 255 or '\n' in x:
                        fails.append(where + ': parameter length %d / newline' % len(x))
                if len('\n'.join(params)) > 2048:
                    fails.append(where + ': joined parameters > 2048')
        for k, v in o.items():
            walk(v, path + '/' + str(o.get('key') or o.get('template') or k))
    elif isinstance(o, list):
        for v in o:
            walk(v, path)


walk(yaml.safe_load(open(Y, encoding='utf-8')), '')
print('preprocessing steps checked: %d, longest parameter: %d chars' % (n, longest))
for f in fails:
    print('FAIL:', f)
print('RESULT:', 'FAILED' if fails else 'all passed')
sys.exit(1 if fails else 0)
