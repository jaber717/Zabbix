#!/usr/bin/env python3
"""Field-length / parameter checks for a Zabbix 7.0 template export. No MIBs or Zabbix server needed.
255 per trigger-function parameter and per preprocessing parameter is confirmed by the Zabbix 7.0.30 importer;
the other limits are Zabbix DB schema sizes as recalled and are NOT verified."""
import re
import sys
import yaml

Y = sys.argv[1] if len(sys.argv) > 1 else 'zbx_templates_gigamon_snmp.yaml'
PARAM_MAX = 255
LIM = {  # field -> max length (recalled schema sizes)
    'name': 255, 'template': 128, 'key': 2048, 'snmp_oid': 512, 'units': 255, 'expression': 2048, 'recovery_expression': 2048,
    'macro': 255, 'tag': 255, 'newvalue': 64, 'delay': 1024, 'history': 255, 'trends': 255, 'lifetime': 255,
}
fails = []
stats = {'params': 0, 'longest_param': 0}
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def key_free(expr, keys):
    for k in sorted(keys, key=len, reverse=True):      # item keys may carry quoted parameters; they are not function parameters
        expr = expr.replace(k, '')
    return expr


def walk(o, keys, path=''):
    if isinstance(o, dict):
        for f, v in o.items():
            if isinstance(v, str) and f in LIM and len(v) > LIM[f]:
                fails.append('%s %s: %d > %d' % (path, f, len(v), LIM[f]))
            if f in ('expression', 'recovery_expression') and isinstance(v, str):
                for q in QUOTED.findall(key_free(v, keys)):
                    stats['params'] += 1
                    stats['longest_param'] = max(stats['longest_param'], len(q))
                    if len(q) > PARAM_MAX:
                        fails.append('%s %s: function parameter of %d chars (> %d): %s...' % (path, f, len(q), PARAM_MAX, q[:60]))
            if f == 'preprocessing':
                for i, s in enumerate(v):
                    for p in s.get('parameters', []):
                        stats['params'] += 1
                        stats['longest_param'] = max(stats['longest_param'], len(str(p)))
                        if len(str(p)) > PARAM_MAX:
                            fails.append('%s preprocessing[%d] parameter of %d chars' % (path, i, len(str(p))))
        for f, v in o.items():
            walk(v, keys, path + '/' + str(o.get('key') or o.get('template') or o.get('name') or f)[:50])
    elif isinstance(o, list):
        for v in o:
            walk(v, keys, path)


doc = yaml.safe_load(open(Y, encoding='utf-8'))
keys = set()


def collect(o):
    if isinstance(o, dict):
        if 'key' in o and isinstance(o['key'], str):
            keys.add(o['key'])
        for v in o.values():
            collect(v)
    elif isinstance(o, list):
        for v in o:
            collect(v)


collect(doc)
walk(doc, keys)
print('parameters checked: %d, longest: %d chars (limit %d)' % (stats['params'], stats['longest_param'], PARAM_MAX))
for f in fails:
    print('FAIL:', f)
print('RESULT:', 'FAILED (%d)' % len(fails) if fails else 'all passed')
sys.exit(1 if fails else 0)
