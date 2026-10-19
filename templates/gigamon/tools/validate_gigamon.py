#!/usr/bin/env python3
"""Offline validation of the Gigamon template export against the vendor MIBs (no Zabbix server available)."""
import re
import sys
import yaml
from mibtree import Mib

Y = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/gigamon/zbx_templates_gigamon_snmp.yaml'
B = '/root/.claude/uploads/d610f59a-ffc4-54bb-b482-e4b7ab6c7482/'
mib = Mib([B + '9f302649-GIGAMON-FM-SNMP.mib', B + '5c680e8a-GIGAMONINLINEBYPASS-61203.mib', B + 'd7fdf7fa-GIGAMONGIGASMART-61203.mib'])
fails = []
warns = []


def check(c, m):
    if not c:
        fails.append(m)
        print('FAIL:', m)


doc = yaml.safe_load(open(Y, encoding='utf-8'))
ex = doc['zabbix_export']
check(ex['version'] == '7.0', 'export version')
all_uuids = []


def walk(o):
    if isinstance(o, dict):
        if 'uuid' in o:
            all_uuids.append(o['uuid'])
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


walk(ex)
check(len(all_uuids) == len(set(all_uuids)), 'duplicate uuids')
check(all(re.fullmatch(r'[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}', u) for u in all_uuids), 'uuid shape')

# independent table of standard OIDs (RFC 1213 / RFC 2863)
STD = {'1.3.6.1.2.1.1.1.0', '1.3.6.1.2.1.1.2.0', '1.3.6.1.2.1.1.3.0', '1.3.6.1.2.1.1.5.0',
       '1.3.6.1.2.1.31.1.1.1.1', '1.3.6.1.2.1.31.1.1.1.18', '1.3.6.1.2.1.2.2.1.2', '1.3.6.1.2.1.2.2.1.7', '1.3.6.1.2.1.2.2.1.8',
       '1.3.6.1.2.1.31.1.1.1.15', '1.3.6.1.2.1.31.1.1.1.6', '1.3.6.1.2.1.31.1.1.1.10', '1.3.6.1.2.1.2.2.1.14',
       '1.3.6.1.2.1.2.2.1.20', '1.3.6.1.2.1.2.2.1.13', '1.3.6.1.2.1.2.2.1.19'}
oid2name = {}
for n, o in mib.all_oids().items():
    oid2name[o] = n
GIGA = '1.3.6.1.4.1.26866'
ALLOWED_FUNCS = {'last', 'min', 'max', 'avg', 'nodata', 'find'}
BUILTIN_MACROS = re.compile(r'\{(ITEM\.(LAST)?VALUE\d*|HOST\.[A-Z]+|#SNMPINDEX)\}')
notify_only_seen = set()
total_triggers = 0


def split_expr_refs(expr, T, known=()):
    refs = []
    for k in sorted(known, key=len, reverse=True):   # keys with nested brackets/quotes (snmptrap) are matched literally
        lit = '/%s/%s' % (T, k)
        while lit in expr:
            refs.append(k)
            expr = expr.replace(lit, '', 1)
    for m in re.finditer(r'/%s/((?:[^\[\],()\s"]+)(?:\[[^\]]*\])?)' % re.escape(T), expr):
        refs.append(m.group(1))
    return refs


def check_oid(oid, where):
    base = oid
    if base.endswith('.{#SNMPINDEX}'):
        base = base[:-len('.{#SNMPINDEX}')]
    if re.fullmatch(r'[0-9.]+', base) is None:
        check(False, '%s: bad oid %s' % (where, oid))
        return None
    if base in STD:
        return None
    if base.startswith(GIGA + '.'):
        scalar = base.endswith('.0') and base[:-2] in oid2name
        name = oid2name.get(base) or (oid2name.get(base[:-2]) if scalar else None)
        check(name is not None, '%s: OID %s is not an object in the supplied MIBs' % (where, base))
        if name:
            if mib.access.get(name) == 'accessible-for-notify':
                notify_only_seen.add(name)
            check(mib.access.get(name) in ('read-only', 'accessible-for-notify', 'read-write'), '%s: %s not readable (%s)' % (where, name, mib.access.get(name)))
            if mib.syntax.get(name) in ('SEQUENCE',) or mib.kind.get(name) == 'OBJECT IDENTIFIER':
                check(False, '%s: OID %s is a table/node, not a column' % (where, name))
        return name
    check(False, '%s: OID %s outside known trees' % (where, base))
    return None


for tpl in ex['templates']:
    T = tpl['template']
    print('==', T)
    vms = {v['name']: v for v in tpl.get('valuemaps', [])}
    macros_def = {m['macro'] for m in tpl.get('macros', [])}
    keys, pkeys = {}, {}
    names_seen = set()
    texts = []

    items = tpl.get('items', [])
    rules = tpl.get('discovery_rules', [])
    for it in items:
        keys[it['key']] = it
    for r in rules:
        check(bool(r.get('item_prototypes')), '%s: rule without prototypes' % r['name'])
        for p in r['item_prototypes']:
            pkeys[p['key']] = (r, p)
    check(len(keys) == len(items), '%s: duplicate item keys' % T)
    check(not (set(keys) & set(pkeys)), '%s: key shared by item and prototype' % T)

    def item_checks(it, proto, rule=None):
        where = '%s/%s' % (T, it['key'])
        if it['type'] == 'SNMP_AGENT':
            name = check_oid(it['snmp_oid'], where)
            if name and 'description' in it:
                check(('MIB object %s ' % name) in it['description'] or 'MIB object' not in it['description'], where + ': description names another object')
            if name:
                en = None
                try:
                    en = mib.enum(name)
                except Exception:
                    pass
                if 'valuemap' in it:
                    vm = vms.get(it['valuemap']['name'])
                    check(vm is not None, where + ': unknown valuemap')
                    if vm and en is not None:
                        got = {int(m['value']): m['newvalue'].lower().replace(' ', '') for m in vm['mappings']}
                        want = {k: re.sub(r'[\s-]', '', v).lower() for k, v in en.items()}
                        check(got == want, where + ': value map differs from MIB enum')
                elif en is not None and mib.syntax.get(name) not in ('Integer32',):
                    check(False, where + ': enumerated object %s without value map' % name)
                # counters: Counter64 must be turned into a rate
                if mib.syntax.get(name) == 'Counter64':
                    check(any(p['type'] == 'CHANGE_PER_SECOND' for p in it.get('preprocessing', [])), where + ': Counter64 without CHANGE_PER_SECOND')
        elif 'valuemap' in it:
            check(it['valuemap']['name'] in vms, where + ': unknown valuemap')
        if proto:
            check(re.search(r'\{#[A-Z.]+\}', it['name']) is not None, where + ': prototype name lacks LLD macro')
            check('{#SNMPINDEX}' in it['key'] or '{#' in it['key'], where + ': prototype key not unique per instance')
        check(len(it['name']) <= 255 and len(it['key']) <= 2048, where + ': length')
        texts.append(yaml.safe_dump(it))

    for it in items:
        item_checks(it, False)
    for r in rules:
        parts = re.fullmatch(r'discovery\[(.*)\]', r['snmp_oid'])
        check(parts is not None, r['name'] + ': snmp_oid form')
        toks = parts.group(1).split(',')
        check(len(toks) % 2 == 0, r['name'] + ': odd discovery[] args')
        lld_macros = {'{#SNMPINDEX}'}
        for i in range(0, len(toks), 2):
            lld_macros.add(toks[i])
            check_oid(toks[i + 1], r['name'])
        for c in r.get('filter', {}).get('conditions', []):
            check(c['macro'] in lld_macros, r['name'] + ': filter macro ' + c['macro'])
        for p in r['item_prototypes']:
            item_checks(p, True, r)
            used = set(re.findall(r'\{#[A-Z.]+\}', yaml.safe_dump(p)))
            check(used <= lld_macros, '%s/%s: undefined LLD macros %s' % (T, p['key'], used - lld_macros))

    def trigger_checks(tr, pool, where):
        global total_triggers
        total_triggers += 1
        for field in ('expression', 'recovery_expression'):
            e = tr.get(field)
            if not e:
                continue
            check(e.count('(') == e.count(')'), '%s: unbalanced parens in %s' % (where, field))
            for f in re.findall(r'([a-z]+)\(/', e):
                check(f in ALLOWED_FUNCS, '%s: function %s' % (where, f))
            for ref in split_expr_refs(e, T, pool):
                check(ref in pool, '%s: unknown key %s' % (where, ref))
            # enumerated comparisons stay inside the item's enum
            for m in re.finditer(r'last\(/%s/((?:[^\[\],()\s"]+)(?:\[[^\]]*\])?)\)\s*(=|<>)\s*(\d+)' % re.escape(T), e):
                key, num = m.group(1), int(m.group(3))
                src = pool.get(key)
                if src and src.get('valuemap'):
                    vm = vms[src['valuemap']['name']]
                    check(str(num) in {x['value'] for x in vm['mappings']}, '%s: %s compared with %d which is not in its value map' % (where, key, num))
        check(tr['name'] not in names_seen, '%s: duplicate trigger name' % where)
        names_seen.add(tr['name'])
        check(tr['priority'] in ('INFO', 'WARNING', 'AVERAGE', 'HIGH', 'DISASTER'), where + ': priority')
        texts.append(yaml.safe_dump(tr))

    for it in items:
        for tr in it.get('triggers', []):
            trigger_checks(tr, keys, '%s/%s' % (T, tr['name']))
    for r in rules:
        pool = {k: p for k, (rr, p) in pkeys.items() if rr is r}
        for p in r['item_prototypes']:
            for tr in p.get('trigger_prototypes', []):
                trigger_checks(tr, pool, '%s/%s' % (T, tr['name']))
                check(re.search(r'\{#[A-Z.]+\}', tr['name']) is not None, '%s: trigger prototype name needs LLD macro' % tr['name'])

    body = '\n'.join(texts) + yaml.safe_dump(rules)
    used_macros = set(re.findall(r'\{\$[A-Z0-9_.]+', body))
    used_macros = {m + '}' for m in used_macros}
    check(used_macros <= macros_def, '%s: macros used but undefined %s' % (T, sorted(used_macros - macros_def)))
    check(macros_def <= used_macros, '%s: macros defined but unused %s' % (T, sorted(macros_def - used_macros)))
    for vn in vms:
        check(vn in body, '%s: unused value map %s' % (T, vn))

    # SNMP trap template: regexes versus real notification numbering
    if 'traps' in T:
        fm = mib.oid('gigamonFM')
        notifs = {n: int(p[1]) for n, p in mib.parent.items() if p[0] == 'gigamonFM'}
        check(len(notifs) == 41 or len(notifs) > 30, 'notification count %d' % len(notifs))
        allitem = items[0]
        keyre = re.search(r'snmptrap\["(.*)"\]', allitem['key']).group(1)
        for nm, num in notifs.items():
            for sample in ('SNMPv2-MIB::snmpTrapOID.0 = GIGAMON-FM-SNMP::%s' % nm, 'snmpTrapOID.0 = OID: .%s.%d gigamonFMSysObjectID = STRING: x' % (fm, num)):
                check(re.search(keyre, sample) is not None, 'catch-all key misses %s' % sample)
        sample_other = 'snmpTrapOID.0 = OID: .1.3.6.1.4.1.9.9.1 something'
        check(re.search(keyre, sample_other) is None, 'catch-all key matches foreign trap')
        for tr in allitem['triggers']:
            rx = '|'.join(re.findall(r',"regexp","(.*?)"\)=1', tr['expression']))
            check(all(len(x) <= 255 for x in re.findall(r',"regexp","(.*?)"\)=1', tr['expression'])), tr['name'] + ': regex parameter > 255 chars')
            hits = set()
            for nm, num in notifs.items():
                num_text = 'snmpTrapOID.0 = OID: .%s.%d gigamonFMNotifEventSeverity = STRING: x' % (fm, num)
                name_text = 'snmpTrapOID.0 = GIGAMON-FM-SNMP::%s' % nm
                a, b = re.search(rx, num_text) is not None, re.search(rx, name_text) is not None
                check(a == b, '%s: numeric/name forms disagree for %s' % (tr['name'], nm))
                if a:
                    hits.add(nm)
            check(len(hits) >= 1, tr['name'] + ': matches nothing')
            for nm in hits:
                check(nm in tr['expression'], '%s: matched %s that is not listed (numeric over-match?)' % (tr['name'], nm))
            check(tr.get('manual_close') == 'YES' and tr.get('recovery_mode') == 'NONE', tr['name'] + ': manual close')
            # varbind OIDs inside the payload (26866.6.2.x) must not trigger
            check(re.search(rx, 'varbind .%s.2.1 = STRING: 26866.6.2.100') is None, tr['name'] + ': matches payload varbind OIDs')

print('triggers checked:', total_triggers, '| accessible-for-notify objects used:', sorted(notify_only_seen))
check(notify_only_seen <= {'tunnelGwStatus'}, 'unexpected notify-only objects used: %s' % notify_only_seen)
print('RESULT:', 'FAILED (%d)' % len(fails) if fails else 'all checks passed')
sys.exit(1 if fails else 0)
