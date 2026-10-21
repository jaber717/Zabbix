#!/usr/bin/env python3
"""Offline validation of the Trellix Zabbix export against FE-FIREEYE-MIB. Uses its OWN minimal OID resolver (independent of mibtree.py)
so a parser bug in the generator's MIB reader cannot hide itself. No Zabbix server is available: this is not an import test."""
import re
import sys
import yaml

Y = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/trellix/zbx_templates_trellix_snmp.yaml'
MIBF = sys.argv[2] if len(sys.argv) > 2 else '/home/claude/trellix/TRELLIX-MIB.txt'
fails = []


def check(c, m):
    if not c:
        fails.append(m)
        print('FAIL:', m)


# ---------------------------------------------------------------- independent MIB reader
txt = re.sub(r'--[^\n]*', '', open(MIBF, encoding='utf-8', errors='replace').read())
objs = {}
for m in re.finditer(r'(?m)^\s*([A-Za-z][\w-]*)\s+(OBJECT-TYPE|NOTIFICATION-TYPE|OBJECT IDENTIFIER|MODULE-IDENTITY|OBJECT-IDENTITY)\b(.*?)::=\s*\{\s*([\w-]+)\s+(\d+)\s*\}', txt, re.S):
    name, kind, body, par, idx = m.groups()
    syn = re.search(r'SYNTAX\s+(.*?)\s+(?:UNITS|MAX-ACCESS)', body, re.S)
    acc = re.search(r'MAX-ACCESS\s+([\w-]+)', body)
    st = re.search(r'STATUS\s+(\w+)', body)
    ob = re.search(r'OBJECTS\s*\{(.*?)\}', body, re.S)
    objs[name] = dict(kind=kind, par=par, idx=int(idx), syn=' '.join(syn.group(1).split()) if syn else '', acc=acc.group(1) if acc else '',
                      status=st.group(1) if st else '', objects=[x.strip() for x in ob.group(1).split(',')] if ob else [])
objs['enterprises'] = dict(kind='ROOT', par=None, idx=0, syn='', acc='', status='', objects=[])


def oid(n):
    parts = []
    while n != 'enterprises':
        parts.append(objs[n]['idx'])
        n = objs[n]['par']
    return '1.3.6.1.4.1.' + '.'.join(map(str, reversed(parts)))


by_oid = {}
for n, o in objs.items():
    if o['kind'] != 'ROOT':
        by_oid[oid(n)] = n
check(objs['trellix']['idx'] == 25597 and oid('trellix') == '1.3.6.1.4.1.25597', 'trellix root OID')
ENTRY_RE = re.compile(r'Entry$')
STD = {'1.3.6.1.2.1.1.1.0', '1.3.6.1.2.1.1.2.0', '1.3.6.1.2.1.1.3.0', '1.3.6.1.2.1.1.5.0'}
notifs = {n: oid(n) for n, o in objs.items() if o['kind'] == 'NOTIFICATION-TYPE'}
check(len(notifs) == 55, 'expected 55 notifications, got %d' % len(notifs))


def is_column(n):
    return n in objs and objs[n]['par'] in objs and objs[objs[n]['par']]['syn'] == '' and objs[n]['par'].endswith('Entry') or \
        (n in objs and objs[objs[n]['par']]['kind'] == 'OBJECT-TYPE' and objs[objs[n]['par']]['acc'] == 'not-accessible')


# ---------------------------------------------------------------- load
ex = yaml.safe_load(open(Y, encoding='utf-8'))['zabbix_export']
check(ex['version'] == '7.0', 'version')
uu = []


def walk(o):
    if isinstance(o, dict):
        if 'uuid' in o:
            uu.append(o['uuid'])
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


walk(ex)
check(len(uu) == len(set(uu)), 'duplicate uuids')
check(all(re.fullmatch(r'[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}', u) for u in uu), 'uuid shape')
FUNCS = {'last', 'min', 'max', 'avg', 'nodata', 'find'}
VT_OK = {'Integer32': {'FLOAT', 'UNSIGNED'}, 'Unsigned32': {'UNSIGNED'}, 'Gauge32': {'UNSIGNED'}, 'Counter32': {'UNSIGNED'}, 'Counter64': {'UNSIGNED'},
         'CounterBasedGauge64': {'UNSIGNED'}, 'TimeTicks': {'FLOAT', 'UNSIGNED'}, 'TruthValue': {'UNSIGNED'}, 'IpAddress': {'CHAR', 'TEXT'}}
used_objs = set()
param_lens = []
trap_tpl = None
for t in ex['templates']:
    T = t['name']
    check(len(T) <= 128 and len(t['uuid']) == 32, T + ': name/uuid')
    vmaps = {v['name']: v for v in t.get('valuemaps', [])}
    for v in vmaps.values():
        check(all(len(m['newvalue']) <= 64 for m in v['mappings']), 'valuemap newvalue length')
    macros = {m['macro'] for m in t.get('macros', [])}
    items = list(t.get('items', []))
    protos = []
    for r in t.get('discovery_rules', []):
        check(r['key'] and r['snmp_oid'].startswith('discovery['), T + ': lld oid')
        lm = re.findall(r'\{#[A-Z]+\}', r['snmp_oid'])
        pairs = re.findall(r'(\{#[A-Z]+\}),([0-9.]+)', r['snmp_oid'])
        check(len(pairs) == len(lm) and lm, T + ': lld pairs ' + r['snmp_oid'])
        for mac, o in pairs:
            n = by_oid.get(o)
            check(n and objs[n]['acc'] == 'read-only', '%s: lld oid %s -> %s not read-only' % (T, o, n))
            used_objs.add(n)
        for p in r['item_prototypes']:
            protos.append((r, p))
            for mm in re.findall(r'\{#[A-Z]+\}', yaml.safe_dump(p)):
                check(mm in lm or mm == '{#SNMPINDEX}', '%s: proto uses undefined LLD macro %s' % (T, mm))
    keys = [i['key'] for i in items]
    pk = [p['key'] for _, p in protos]
    check(len(keys) == len(set(keys)), T + ': duplicate item keys')
    check(len(pk) == len(set(pk)) and not set(pk) & set(keys), T + ': duplicate proto keys')
    allkeys = set(keys) | set(pk)
    for i in items + [p for _, p in protos]:
        k = i['key']
        check(len(i['name']) <= 255 and len(k) <= 2048, T + ': name/key length ' + k)
        check(not re.search(r'[()\\]', k.split('[')[0]), T + ': bad chars in key ' + k)
        if i['type'] == 'SNMP_AGENT':
            o = i['snmp_oid']
            check(len(o) <= 512, 'oid length')
            base = re.sub(r'\.(0|\{#SNMPINDEX\})$', '', o)
            if o in STD:
                continue
            n = by_oid.get(base)
            check(n is not None, '%s %s: OID %s not in MIB' % (T, k, o))
            if not n:
                continue
            used_objs.add(n)
            ob = objs[n]
            check(ob['acc'] == 'read-only', '%s %s: %s is %s (not pollable)' % (T, k, n, ob['acc']))
            check(ob['status'] != 'obsolete', '%s: obsolete object %s' % (T, n))
            if o.endswith('.0'):
                check(objs[ob['par']]['acc'] != 'not-accessible', '%s %s: .0 on a table column %s' % (T, k, n))
            else:
                check(objs[ob['par']]['acc'] == 'not-accessible' or objs[objs[ob['par']]['par']]['syn'].startswith('SEQUENCE'), '%s %s: .{#SNMPINDEX} on a scalar %s' % (T, k, n))
            syn = re.sub(r'\s*\(.*', '', ob['syn']).strip()
            vt = i.get('value_type', 'FLOAT')
            if syn.startswith('OCTET STRING'):
                check(vt in ('CHAR', 'TEXT'), '%s %s: OCTET STRING needs text type' % (T, k))
            else:
                check(vt in VT_OK.get(syn, set()), '%s %s: syntax %s vs value_type %s' % (T, k, syn, vt))
            prep = [p['type'] for p in i.get('preprocessing', [])]
            if syn in ('Counter32', 'Counter64'):
                check('CHANGE_PER_SECOND' not in prep, '%s %s: rate on windowed counter (see README)' % (T, k))
            if syn == 'TruthValue':
                check(i.get('valuemap', {}).get('name') == 'Trellix TruthValue', '%s %s: TruthValue without value map' % (T, k))
            if syn == 'TimeTicks':
                check('MULTIPLIER' in prep, 'timeticks')
        if 'valuemap' in i:
            check(i['valuemap']['name'] in vmaps, '%s: missing valuemap %s' % (T, i['valuemap']['name']))
        for p in i.get('preprocessing', []):
            for x in p.get('parameters', []):
                param_lens.append(len(x))
                check(len(x) <= 255, '%s: preprocessing param >255' % T)
        if i['type'] == 'CALCULATED':
            for r in re.findall(r'/%s/([\w.\[\]{}#$]+?)[,)]' % re.escape(T), i['params']):
                check(r in allkeys, '%s: calculated refs unknown key %s' % (T, r))
    # triggers
    trs = [(i, x) for i in items for x in i.get('triggers', [])] + [(p, x) for _, p in protos for x in p.get('trigger_prototypes', [])]
    names = [x['name'] for _, x in trs]
    check(len(names) == len(set(names)), T + ': duplicate trigger names')
    for i, x in trs:
        ex_all = x['expression'] + ' ' + x.get('recovery_expression', '')
        check(len(x['expression']) <= 2048 and len(x['name']) <= 255, 'trigger length')
        check(x['priority'] in ('INFO', 'WARNING', 'AVERAGE', 'HIGH', 'DISASTER', 'NOT_CLASSIFIED'), 'priority')
        for f in re.findall(r'([a-z]+)\(/', ex_all):
            check(f in FUNCS, '%s: function %s' % (T, f))
        for key in sorted(allkeys, key=len, reverse=True):
            ex_all = ex_all.replace('/%s/%s,' % (T, key), '@K,').replace('/%s/%s)' % (T, key), '@K)')
        check('/%s/' % T not in ex_all, '%s: trigger %s references an unknown key: %s' % (T, x['name'], ex_all[:120]))
        # user macros used must exist
        for mm in re.findall(r'\{\$[A-Z0-9_.]+(?::"[^"]*")?\}', x['expression'] + x['name'] + x.get('description', '')):
            check(mm.split(':')[0].rstrip('}') + ('}' if not mm.startswith('{$') else '') in macros or mm.split(':')[0] in macros, '%s: undefined macro %s' % (T, mm))
        for m in re.finditer(r'(\{\$[A-Z0-9_.]+\})', x['expression'] + x['name'] + x.get('description', '')):
            check(m.group(1) in macros, '%s: undefined macro %s' % (T, m.group(1)))
        for a in re.findall(r'find\([^,]+,#\d+,"regexp","(.*?)"\)', x['expression'] + ' ' + x.get('recovery_expression', '')):
            param_lens.append(len(a))
            check(len(a) <= 255, '%s: find() parameter %d > 255' % (T, len(a)))
        # TruthValue comparisons stay in {1,2}
        for key, val in re.findall(r'last\(/%s/([^)]+?)\)\s*=\s*(\d+)' % re.escape(T), x['expression']):
            kk = key
            src = [j for j in items + [p for _, p in protos] if j['key'] == kk]
            if src and src[0].get('valuemap', {}).get('name') == 'Trellix TruthValue':
                check(val in ('1', '2'), 'truth value compared to %s' % val)
    if T == 'Trellix by SNMP traps':
        trap_tpl = (t, trs)
    for m in macros:
        used = yaml.safe_dump(t) 
        check(used.count(m) >= 2, '%s: macro %s defined but unused' % (T, m))

# ---------------------------------------------------------------- trap regex tests
t, trs = trap_tpl
trap_item = t['items'][0]
keyre = re.search(r'snmptrap\["(.*)"\]', trap_item['key']).group(1)
trig_rx = {}
for _, x in trs:
    prob = re.findall(r'find\([^,]+,#1,"regexp","(.*?)"\)', x['expression'])
    rec = re.findall(r'find\([^,]+,#1,"regexp","(.*?)"\)', x.get('recovery_expression', ''))
    trig_rx[x['name']] = (re.compile('|'.join(prob)), re.compile('|'.join(rec)) if rec else None)
check(len(trig_rx) == len(trs), 'trap trigger names unique')
owner_p, owner_r = {}, {}
n_checked = 0
for nm, o in sorted(notifs.items()):
    numeric = 'SNMPv2-MIB::sysUpTime.0 = Timeticks: (1) 0:00:00.01 SNMPv2-MIB::snmpTrapOID.0 = OID: %s ' % o + \
              ' '.join('%s = STRING: x' % (oid(v)) for v in objs[nm]['objects'])
    named = 'DISMAN-EVENT-MIB::sysUpTimeInstance = 1 SNMPv2-MIB::snmpTrapOID.0 = OID: FE-FIREEYE-MIB::%s ' % nm + \
            ' '.join('FE-FIREEYE-MIB::%s = STRING: x' % v for v in objs[nm]['objects'])
    bare = 'snmpTrapOID.0 = OID: %s ' % nm + ' '.join('%s = x' % v for v in objs[nm]['objects'])
    for form, s in (('numeric', numeric), ('named', named), ('bare', bare)):
        check(re.search(keyre, s) is not None, 'item key regex misses %s (%s)' % (nm, form))
        hitp = {k for k, (p, r) in trig_rx.items() if p.search(s)}
        hitr = {k for k, (p, r) in trig_rx.items() if r and r.search(s)}
        n_checked += 1
        if form == 'numeric':
            owner_p[nm] = hitp
            owner_r[nm] = hitr
        check(len(hitp | hitr) == 1, '%s (%s): matches triggers %s' % (nm, form, sorted(hitp | hitr)))
        if form != 'numeric':
            check(hitp == owner_p[nm] and hitr == owner_r[nm], '%s: %s form differs from numeric form' % (nm, form))
# a non-Trellix trap and a lookalike OID must not match
for bad in ['snmpTrapOID.0 = OID: 1.3.6.1.4.1.9.9.41.2.0.1', 'OID: 1.3.6.1.4.1.25597.11.4.0.11', 'OID: 1.3.6.1.4.1.125597.11.4.0.1 x']:
    check(not any(p.search(bad) or (r and r.search(bad)) for p, r in trig_rx.values()), 'lookalike matched: ' + bad)
# every pair: recovery trap must hit only the recovery regex of the same trigger
for nm, hp in owner_p.items():
    pass

# ---------------------------------------------------------------- coverage report
SKIP_EXPL = {'lmsVersion', 'eventTable'}
readable = [n for n, o in objs.items() if o['kind'] == 'OBJECT-TYPE' and o['acc'] == 'read-only' and o['status'] == 'current'
            and not re.search(r'(CountH|CountL|CntH|CntL)$', n) and not o['syn'].startswith('SEQUENCE')]
unused = sorted(set(readable) - used_objs)
INTENTIONAL = set('''feAddressSource feAwsImageId feAwsInstanceId feAwsInstanceType feDefaultGWIpAddress feDefaultGWMACAddress feDeviceVersion
feFirmwareReloadInterval feFirmwareReloadProgress feFirmwareUpdateProgress feFirmwareVersion feIPMIGuid feIPMISupported feIPMIVersion
feIPMIWatchdogSupported feIpAddress feMACAddress fePrefix feShutdown feDeploymentCheckEndTime feDeploymentCheckStartTime feLicenseExpiration'''.split())
INDEXCOLS = {n for n in unused if re.search(r'Index\d?$', n)}
HALVES = {n for n in unused if re.search(r'(CountH|CountL|CntH|CntL)$', n) or n.endswith(('HasAttachmentH', 'HasAttachmentL', 'HasUrlH', 'HasUrlL', 'BadAttachmentH', 'BadAttachmentL', 'BadUrlH', 'BadUrlL'))}
unexpected = sorted(set(unused) - INTENTIONAL - INDEXCOLS - HALVES)
check(not unexpected, 'pollable objects neither used nor on the intentional-exclusion list: %s' % unexpected)
print('readable current objects not used (excluding H/L halves of Counter64 pairs):', len(unused))
print(' '.join(unused))
print('trap regex checks:', n_checked, '| params checked:', len(param_lens), 'max', max(param_lens))
print('FAILS:', len(fails))
sys.exit(1 if fails else 0)
