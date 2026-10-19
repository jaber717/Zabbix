#!/usr/bin/env python3
"""Generates the Gigamon Zabbix 7.0 templates. Every Gigamon OID and every value-map entry is taken from the
vendor MIBs (parsed by mibtree.py), never typed by hand."""
import hashlib
import re
import sys
import yaml
from mibtree import Mib

MIBDIR = '/root/.claude/uploads/d610f59a-ffc4-54bb-b482-e4b7ab6c7482/'
MIBS = [MIBDIR + '9f302649-GIGAMON-FM-SNMP.mib', MIBDIR + '5c680e8a-GIGAMONINLINEBYPASS-61203.mib', MIBDIR + 'd7fdf7fa-GIGAMONGIGASMART-61203.mib']
OUT = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/gigamon/zbx_templates_gigamon_snmp.yaml'
mib = Mib(MIBS)

TA = 'Gigamon GigaVUE by SNMP'
TB = 'Gigamon GigaVUE Inline Bypass by SNMP'
TC = 'Gigamon GigaVUE GigaSMART by SNMP'
TD = 'Gigamon GigaVUE-FM by SNMP traps'
GROUP = 'Templates/Network devices'


def uid(*parts):
    h = hashlib.sha256(('gigamon:' + ':'.join(parts)).encode()).hexdigest()
    return h[:12] + '4' + h[13:16] + '8' + h[17:32]


def pretty(n):
    n = n.replace('-', ' ')
    n = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', n)
    n = n.strip().lower()
    return n[:1].upper() + n[1:]


def valuemap(tpl, name, enum):
    return {'uuid': uid(tpl, 'vm', name), 'name': name,
            'mappings': [{'value': str(k), 'newvalue': pretty(v)} for k, v in sorted(enum.items())]}


def tags(**kw):
    return [{'tag': k, 'value': v} for k, v in kw.items()]


def mibdesc(obj, extra=''):
    return ('MIB object %s (%s)%s' % (obj, mib.oid(obj), (' ' + extra) if extra else ''))


def item(tpl, name, key, oid, vt='UNSIGNED', obj=None, delay='1m', hist='31d', units=None, vmap=None, prep=None,
         desc='', tg=None, triggers=None, itype='SNMP_AGENT'):
    d = {'uuid': uid(tpl, 'item', key), 'name': name, 'type': itype}
    if oid:
        d['snmp_oid'] = oid
    d['key'] = key
    d['delay'] = delay
    d['history'] = hist
    if vt in ('UNSIGNED', 'FLOAT'):
        d['trends'] = '365d'
    else:
        d['trends'] = '0'
    if vt != 'FLOAT_DEFAULT':
        d['value_type'] = vt
    if units:
        d['units'] = units
    text = desc
    if obj:
        text = (desc + ' ' if desc else '') + mibdesc(obj)
    if text:
        d['description'] = text
    if vmap:
        d['valuemap'] = {'name': vmap}
    if prep:
        d['preprocessing'] = prep
    d['tags'] = tg or []
    if triggers:
        d['triggers' if itype != 'PROTO' else 'trigger_prototypes'] = triggers
    return d


def trig(tpl, expr, name, prio, desc='', scope='health', recovery=None, manual=False):
    d = {'uuid': uid(tpl, 'trigger', name), 'expression': expr, 'name': name}
    if recovery:
        d['recovery_mode'] = 'RECOVERY_EXPRESSION'
        d['recovery_expression'] = recovery
    d['priority'] = prio
    if desc:
        d['description'] = desc
    if manual:
        d['recovery_mode'] = 'NONE'
        d['manual_close'] = 'YES'
    d['tags'] = tags(scope=scope)
    return d


def proto(d):
    """turn an item dict into an item prototype (triggers -> trigger_prototypes)"""
    if 'triggers' in d:
        d['trigger_prototypes'] = d.pop('triggers')
    return d


def lld(tpl, name, key, parts, protos, desc, flt=None, delay='1h'):
    oid = 'discovery[' + ','.join('%s,%s' % (m, o) for m, o in parts) + ']'
    d = {'uuid': uid(tpl, 'lld', key), 'name': name, 'type': 'SNMP_AGENT', 'snmp_oid': oid, 'key': key,
         'delay': delay, 'lifetime': '7d', 'description': desc}
    if flt:
        d['filter'] = flt
    d['item_prototypes'] = [proto(p) for p in protos]
    return d


def counter_rate(mult=None):
    p = [{'type': 'CHANGE_PER_SECOND', 'parameters': ['']}]
    if mult:
        p.append({'type': 'MULTIPLIER', 'parameters': [str(mult)]})
    return p


def macro(m, v, desc):
    return {'macro': m, 'value': v, 'description': desc}


def template(name, desc, items, lld_rules, macros, vms, tagz):
    t = {'uuid': uid(name, 'template'), 'template': name, 'name': name, 'description': desc,
         'groups': [{'name': GROUP}]}
    if items:
        t['items'] = items
    if lld_rules:
        t['discovery_rules'] = lld_rules
    t['macros'] = macros
    t['tags'] = tagz
    if vms:
        t['valuemaps'] = vms
    return t


# ============================================================================== A: base (system + IF-MIB)
IFO = {  # standard IF-MIB / IF-MIB(ifX) columns
    'ifName': '1.3.6.1.2.1.31.1.1.1.1', 'ifAlias': '1.3.6.1.2.1.31.1.1.1.18', 'ifDescr': '1.3.6.1.2.1.2.2.1.2',
    'ifAdminStatus': '1.3.6.1.2.1.2.2.1.7', 'ifOperStatus': '1.3.6.1.2.1.2.2.1.8', 'ifHighSpeed': '1.3.6.1.2.1.31.1.1.1.15',
    'ifHCInOctets': '1.3.6.1.2.1.31.1.1.1.6', 'ifHCOutOctets': '1.3.6.1.2.1.31.1.1.1.10',
    'ifInErrors': '1.3.6.1.2.1.2.2.1.14', 'ifOutErrors': '1.3.6.1.2.1.2.2.1.20',
    'ifInDiscards': '1.3.6.1.2.1.2.2.1.13', 'ifOutDiscards': '1.3.6.1.2.1.2.2.1.19',
}
SYS = {'sysDescr': '1.3.6.1.2.1.1.1.0', 'sysObjectID': '1.3.6.1.2.1.1.2.0', 'sysUpTime': '1.3.6.1.2.1.1.3.0', 'sysName': '1.3.6.1.2.1.1.5.0'}

A = TA
A_items = [
    item(A, 'ICMP ping', 'icmpping', None, itype='SIMPLE', vmap='Gigamon service state', tg=tags(component='availability'),
         triggers=[trig(A, 'max(/%s/icmpping,#3)=0' % A, 'Gigamon: Unavailable by ICMP ping', 'HIGH',
                        'The node did not answer ICMP echo in 3 consecutive checks.', 'availability')]),
    item(A, 'ICMP loss', 'icmppingloss', None, vt='FLOAT', itype='SIMPLE', units='%', tg=tags(component='availability'),
         triggers=[trig(A, 'min(/%s/icmppingloss,5m)>{$GIGAMON.ICMP.LOSS.WARN} and min(/%s/icmppingloss,5m)<100' % (A, A),
                        'Gigamon: High ICMP ping loss ({ITEM.VALUE})', 'WARNING', scope='availability')]),
    item(A, 'ICMP response time', 'icmppingsec', None, vt='FLOAT', itype='SIMPLE', units='s', tg=tags(component='availability'),
         triggers=[trig(A, 'min(/%s/icmppingsec,5m)>{$GIGAMON.ICMP.RESPONSE.TIME.WARN}' % A,
                        'Gigamon: High ICMP ping response time ({ITEM.VALUE})', 'WARNING', scope='availability')]),
    item(A, 'SNMP agent availability', 'zabbix[host,snmp,available]', None, itype='INTERNAL', vmap='Gigamon SNMP availability',
         desc='Availability of the SNMP interface as seen by the Zabbix server/proxy.', tg=tags(component='availability'),
         triggers=[trig(A, 'max(/%s/zabbix[host,snmp,available],{$GIGAMON.SNMP.TIMEOUT})=0' % A,
                        'Gigamon: No SNMP data collection', 'AVERAGE',
                        'SNMP polling has failed for the whole {$GIGAMON.SNMP.TIMEOUT}: check community/credentials, ACLs on the node, UDP/161 path. Counter64 objects need SNMPv2c or v3.',
                        'availability')]),
    item(A, 'System description', 'system.descr', SYS['sysDescr'], vt='TEXT', hist='7d', delay='1h', desc='MIB-II sysDescr.',
         prep=[{'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['1d']}], tg=tags(component='system')),
    item(A, 'System name', 'system.name', SYS['sysName'], vt='CHAR', hist='7d', delay='1h', desc='MIB-II sysName.',
         prep=[{'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['1d']}], tg=tags(component='system')),
    item(A, 'System object ID', 'system.objectid', SYS['sysObjectID'], vt='CHAR', hist='7d', delay='1h',
         desc='MIB-II sysObjectID (a Gigamon node is expected under 1.3.6.1.4.1.26866; not verified against a live device).',
         prep=[{'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['1d']}], tg=tags(component='system')),
    item(A, 'Uptime', 'system.uptime', SYS['sysUpTime'], vt='FLOAT', units='uptime', desc='MIB-II sysUpTime (timeticks / 100).',
         prep=[{'type': 'MULTIPLIER', 'parameters': ['0.01']}], tg=tags(component='system'),
         triggers=[trig(A, 'last(/%s/system.uptime)<10m' % A, 'Gigamon: Restarted (uptime {ITEM.LASTVALUE})', 'INFO',
                        'Uptime is below 10 minutes: the node restarted or the SNMP agent was reset.', 'availability'),
                   trig(A, 'nodata(/%s/system.uptime,{$GIGAMON.NODATA.TIMEOUT})=1' % A, 'Gigamon: No SNMP data for {$GIGAMON.NODATA.TIMEOUT}', 'AVERAGE',
                        scope='availability')]),
]


def ifitem(name, key, col, **kw):
    kw.setdefault('tg', tags(component='network', interface='{#IFNAME}'))
    return proto(item(A, name, key, IFO[col] + '.{#SNMPINDEX}', desc=kw.pop('desc', ''), **kw))


IFC = '{$GIGAMON.IFCONTROL:"{#IFNAME}"}'
ifprotos = [
    ifitem('Interface {#IFNAME}: Operational status', 'net.if.status[{#SNMPINDEX}]', 'ifOperStatus', vmap='Gigamon ifOperStatus',
           desc='IF-MIB ifOperStatus. Physical monitoring/tap ports without link are normal, the trigger therefore fires only on an up->down transition.',
           triggers=[trig(A, '%s=1 and last(/%s/net.if.status[{#SNMPINDEX}])=2 and (last(/%s/net.if.status[{#SNMPINDEX}],#1)<>last(/%s/net.if.status[{#SNMPINDEX}],#2))' % (IFC, A, A, A),
                          'Interface {#IFNAME}: Link down', 'AVERAGE',
                          'Operational status changed from up to down. Disable per port with {$GIGAMON.IFCONTROL:"<ifName>"}=0.', 'network',
                          recovery='last(/%s/net.if.status[{#SNMPINDEX}])<>2 or %s=0' % (A, IFC))]),
    ifitem('Interface {#IFNAME}: Administrative status', 'net.if.admin[{#SNMPINDEX}]', 'ifAdminStatus', vmap='Gigamon ifAdminStatus', hist='7d',
           prep=[{'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['6h']}], delay='5m'),
    ifitem('Interface {#IFNAME}: Speed', 'net.if.speed[{#SNMPINDEX}]', 'ifHighSpeed', units='bps', hist='7d', delay='1h',
           prep=[{'type': 'MULTIPLIER', 'parameters': ['1000000']}, {'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['1d']}],
           desc='ifHighSpeed (Mbps) converted to bit/s.'),
    ifitem('Interface {#IFNAME}: Bits received', 'net.if.in[{#SNMPINDEX}]', 'ifHCInOctets', vt='FLOAT', units='bps', prep=counter_rate(8),
           desc='ifHCInOctets as bit/s (64-bit counter: needs SNMPv2c/v3).'),
    ifitem('Interface {#IFNAME}: Bits sent', 'net.if.out[{#SNMPINDEX}]', 'ifHCOutOctets', vt='FLOAT', units='bps', prep=counter_rate(8),
           desc='ifHCOutOctets as bit/s.'),
    ifitem('Interface {#IFNAME}: Inbound packets with errors', 'net.if.in.errors[{#SNMPINDEX}]', 'ifInErrors', vt='FLOAT', units='!pps', prep=counter_rate()),
    ifitem('Interface {#IFNAME}: Outbound packets with errors', 'net.if.out.errors[{#SNMPINDEX}]', 'ifOutErrors', vt='FLOAT', units='!pps', prep=counter_rate()),
    ifitem('Interface {#IFNAME}: Inbound packets discarded', 'net.if.in.discards[{#SNMPINDEX}]', 'ifInDiscards', vt='FLOAT', units='!pps', prep=counter_rate()),
    ifitem('Interface {#IFNAME}: Outbound packets discarded', 'net.if.out.discards[{#SNMPINDEX}]', 'ifOutDiscards', vt='FLOAT', units='!pps', prep=counter_rate()),
]
# error trigger sits on the inbound-errors prototype and looks at both directions
for p in ifprotos:
    if p['key'] == 'net.if.in.errors[{#SNMPINDEX}]':
        e1 = 'net.if.in.errors[{#SNMPINDEX}]'
        e2 = 'net.if.out.errors[{#SNMPINDEX}]'
        p['trigger_prototypes'] = [trig(
            A, '%s=1 and (min(/%s/%s,5m)>{$GIGAMON.IF.ERRORS.WARN} or min(/%s/%s,5m)>{$GIGAMON.IF.ERRORS.WARN})' % (IFC, A, e1, A, e2),
            'Interface {#IFNAME}: High error rate', 'WARNING',
            'Input or output errors above {$GIGAMON.IF.ERRORS.WARN} packets/s for 5 minutes.', 'network',
            recovery='max(/%s/%s,5m)<{$GIGAMON.IF.ERRORS.WARN}*0.8 and max(/%s/%s,5m)<{$GIGAMON.IF.ERRORS.WARN}*0.8' % (A, e1, A, e2))]

A_lld = [lld(A, 'Network interfaces discovery', 'net.if.discovery',
             [('{#IFNAME}', IFO['ifName']), ('{#IFDESCR}', IFO['ifDescr']), ('{#IFALIAS}', IFO['ifAlias'])], ifprotos,
             'IF-MIB interfaces. Gigamon GigaVUE physical ports are monitoring ports, so the link trigger only reacts to up->down changes.',
             flt={'evaltype': 'AND', 'conditions': [
                 {'macro': '{#IFNAME}', 'value': '{$GIGAMON.IF.NAME.MATCHES}', 'formulaid': 'A'},
                 {'macro': '{#IFNAME}', 'operator': 'NOT_MATCHES_REGEX', 'value': '{$GIGAMON.IF.NAME.NOT_MATCHES}', 'formulaid': 'B'}]})]
A_macros = [
    macro('{$GIGAMON.ICMP.LOSS.WARN}', '20', 'ICMP loss warning threshold, %.'),
    macro('{$GIGAMON.ICMP.RESPONSE.TIME.WARN}', '0.15', 'ICMP response time warning threshold, seconds.'),
    macro('{$GIGAMON.SNMP.TIMEOUT}', '5m', 'Period of failed SNMP polling before the "No SNMP data collection" trigger fires.'),
    macro('{$GIGAMON.NODATA.TIMEOUT}', '15m', 'No-data period for sysUpTime.'),
    macro('{$GIGAMON.IF.NAME.MATCHES}', '.*', 'Regex: interfaces to discover.'),
    macro('{$GIGAMON.IF.NAME.NOT_MATCHES}', '^$', 'Regex: interfaces to exclude from discovery (default excludes nothing).'),
    macro('{$GIGAMON.IFCONTROL}', '1', '1 = raise link-down and error triggers. Override per interface with {$GIGAMON.IFCONTROL:"<ifName>"}.'),
    macro('{$GIGAMON.IF.ERRORS.WARN}', '2', 'Interface error rate (packets/s, 5 min) that raises the warning.'),
]
A_vms = [
    {'uuid': uid(A, 'vm', 'svc'), 'name': 'Gigamon service state', 'mappings': [{'value': '0', 'newvalue': 'Down'}, {'value': '1', 'newvalue': 'Up'}]},
    {'uuid': uid(A, 'vm', 'snmpav'), 'name': 'Gigamon SNMP availability', 'mappings': [{'value': '0', 'newvalue': 'Not available'}, {'value': '1', 'newvalue': 'Available'}, {'value': '2', 'newvalue': 'Unknown'}]},
    {'uuid': uid(A, 'vm', 'ifoper'), 'name': 'Gigamon ifOperStatus', 'mappings': [{'value': str(k), 'newvalue': v} for k, v in
        {1: 'up', 2: 'down', 3: 'testing', 4: 'unknown', 5: 'dormant', 6: 'notPresent', 7: 'lowerLayerDown'}.items()]},
    {'uuid': uid(A, 'vm', 'ifadmin'), 'name': 'Gigamon ifAdminStatus', 'mappings': [{'value': str(k), 'newvalue': v} for k, v in {1: 'up', 2: 'down', 3: 'testing'}.items()]},
]

# ============================================================================== B: inline bypass
B = TB
O = mib.oid
tool_status_enum = mib.enum('intPortAStatus')
B_vms = [
    valuemap(B, 'Gigamon inline tool port status', tool_status_enum),
    valuemap(B, 'Gigamon inline heartbeat status', mib.enum('intHBStatus')),
    valuemap(B, 'Gigamon inline tool aggregate status', mib.enum('intAggregateStatus')),
    valuemap(B, 'Gigamon inline network port status', mib.enum('inlNetworkPortAStatus')),
    valuemap(B, 'Gigamon inline forward state', mib.enum('inlForwardState')),
]


def bproto(name, key, obj, vmap, **kw):
    kw.setdefault('tg', tags(component='inline-bypass'))
    return proto(item(B, name, key, O(obj) + '.{#SNMPINDEX}', obj=obj, vmap=vmap, **kw))


TCTL = '{$GIGAMON.INLINE.TOOL.CONTROL:"{#TOOL.ALIAS}"}'
t = lambda k: '/%s/gigamon.inline.tool.%s[{#SNMPINDEX}]' % (B, k)
B_tool_protos = [
    bproto('Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Aggregate status', 'gigamon.inline.tool.agg[{#SNMPINDEX}]', 'intAggregateStatus', 'Gigamon inline tool aggregate status',
           desc='Overall state of the inline tool (disable / down / up / ready).',
           triggers=[trig(B, '%s=1 and last(%s)=1' % (TCTL, t('agg')), 'Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}] is down', 'HIGH',
                          'The inline tool is reported down. Depending on the inline-network configuration traffic is bypassed (uninspected) or dropped. Disable per tool with {$GIGAMON.INLINE.TOOL.CONTROL:"<alias>"}=0.', 'inline',
                          recovery='last(%s)<>1 or %s=0' % (t('agg'), TCTL))]),
    bproto('Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Heartbeat', 'gigamon.inline.tool.hb[{#SNMPINDEX}]', 'intHBStatus', 'Gigamon inline heartbeat status',
           triggers=[trig(B, '%s=1 and last(%s)=1 and last(%s)<>1' % (TCTL, t('hb'), t('agg')), 'Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Heartbeat down', 'HIGH',
                          'Heartbeat lost while the aggregate status is not yet down. Suppressed when the aggregate-down trigger already covers the tool.', 'inline',
                          recovery='last(%s)<>1 or %s=0' % (t('hb'), TCTL))]),
    bproto('Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Negative heartbeat', 'gigamon.inline.tool.nhb[{#SNMPINDEX}]', 'intNegativeHBStatus', 'Gigamon inline heartbeat status',
           triggers=[trig(B, '%s=1 and last(%s)=1' % (TCTL, t('nhb')), 'Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Negative heartbeat down', 'WARNING',
                          scope='inline', recovery='last(%s)<>1 or %s=0' % (t('nhb'), TCTL))]),
    bproto('Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Port A status', 'gigamon.inline.tool.pa[{#SNMPINDEX}]', 'intPortAStatus', 'Gigamon inline tool port status',
           triggers=[trig(B, '%s=1 and last(%s)=1 and last(%s)<>0 and last(%s)<>1' % (TCTL, t('pa'), t('agg'), t('agg')),
                          'Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Port A down', 'AVERAGE', scope='inline',
                          recovery='last(%s)<>1 or %s=0' % (t('pa'), TCTL))]),
    bproto('Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Port B status', 'gigamon.inline.tool.pb[{#SNMPINDEX}]', 'intPortBStatus', 'Gigamon inline tool port status',
           triggers=[trig(B, '%s=1 and last(%s)=1 and last(%s)<>0 and last(%s)<>1' % (TCTL, t('pb'), t('agg'), t('agg')),
                          'Inline tool {#TOOL.ALIAS} [{#SNMPINDEX}]: Port B down', 'AVERAGE', scope='inline',
                          recovery='last(%s)<>1 or %s=0' % (t('pb'), TCTL))]),
]
NCTL = '{$GIGAMON.INLINE.NET.CONTROL:"{#NET.ALIAS}"}'
n = lambda k: '/%s/gigamon.inline.net.%s[{#SNMPINDEX}]' % (B, k)
FS = '%s=1 and last(%s)' % (NCTL, n('fwd'))
B_net_protos = [
    bproto('Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Forward state', 'gigamon.inline.net.fwd[{#SNMPINDEX}]', 'inlForwardState', 'Gigamon inline forward state',
           desc='Forwarding state of the inline network pair. 5 = normal-forwarding.',
           triggers=[
               trig(B, FS + '=7', 'Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Failure introduced DROP (traffic is being dropped)', 'DISASTER',
                    'forward state = failure-introduced-drop: production traffic through this inline network is dropped.', 'inline', recovery='last(%s)<>7 or %s=0' % (n('fwd'), NCTL)),
               trig(B, '%s=1 and (last(%s)=6 or last(%s)=9 or last(%s)=8)' % (NCTL, n('fwd'), n('fwd'), n('fwd')),
                    'Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Abnormal forward state ({ITEM.LASTVALUE})', 'HIGH',
                    'failure-introduced-bypass (6), network-ports-forced-down (8) or abnormal-forwarding (9).', 'inline',
                    recovery='(last(%s)<>6 and last(%s)<>8 and last(%s)<>9) or %s=0' % (n('fwd'), n('fwd'), n('fwd'), NCTL)),
               trig(B, '%s=2' % FS, 'Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Network disconnected', 'AVERAGE',
                    'forward state = inline-network-disconnected.', 'inline', recovery='last(%s)<>2 or %s=0' % (n('fwd'), NCTL)),
               trig(B, '%s=1 and (last(%s)=0 or last(%s)=3 or last(%s)=4)' % (NCTL, n('fwd'), n('fwd'), n('fwd')),
                    'Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Bypass active, tools are not inspecting traffic ({ITEM.LASTVALUE})', 'WARNING',
                    'physical-bypass (0), forced-bypass (3) or forced-bypass-monitoring (4). Expected during maintenance: silence per network with {$GIGAMON.INLINE.NET.CONTROL:"<alias>"}=0.', 'inline',
                    recovery='(last(%s)<>0 and last(%s)<>3 and last(%s)<>4) or %s=0' % (n('fwd'), n('fwd'), n('fwd'), NCTL))]),
    bproto('Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Port A status', 'gigamon.inline.net.pa[{#SNMPINDEX}]', 'inlNetworkPortAStatus', 'Gigamon inline network port status',
           triggers=[trig(B, '%s=1 and last(%s)=1 and last(%s)<>1' % (NCTL, n('pa'), n('fwd')),
                          'Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Port A down', 'AVERAGE', scope='inline',
                          recovery='last(%s)<>1 or %s=0' % (n('pa'), NCTL))]),
    bproto('Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Port B status', 'gigamon.inline.net.pb[{#SNMPINDEX}]', 'inlNetworkPortBStatus', 'Gigamon inline network port status',
           triggers=[trig(B, '%s=1 and last(%s)=1 and last(%s)<>1' % (NCTL, n('pb'), n('fwd')),
                          'Inline network {#NET.ALIAS} [{#SNMPINDEX}]: Port B down', 'AVERAGE', scope='inline',
                          recovery='last(%s)<>1 or %s=0' % (n('pb'), NCTL))]),
]
B_lld = [
    lld(B, 'Inline tools discovery', 'gigamon.inline.tool.discovery',
        [('{#TOOL.ALIAS}', O('intAlias')), ('{#TOOL.PORTA}', O('intPortA')), ('{#TOOL.PORTB}', O('intPortB'))], B_tool_protos,
        'GIGAMONINLINEBYPASS inlineToolStatusTable (%s). Unsupported on nodes without inline bypass: link this template only where the feature exists.' % O('inlineToolStatusTable')),
    lld(B, 'Inline networks discovery', 'gigamon.inline.net.discovery',
        [('{#NET.ALIAS}', O('inlNetworkAlias')), ('{#NET.PORTA}', O('inlNetworkPortA')), ('{#NET.PORTB}', O('inlNetworkPortB'))], B_net_protos,
        'GIGAMONINLINEBYPASS inlineNetworkStatusTable (%s).' % O('inlineNetworkStatusTable')),
]
B_macros = [
    macro('{$GIGAMON.INLINE.TOOL.CONTROL}', '1', '1 = raise inline-tool triggers. Override per tool: {$GIGAMON.INLINE.TOOL.CONTROL:"<alias>"}=0 (for example during maintenance).'),
    macro('{$GIGAMON.INLINE.NET.CONTROL}', '1', '1 = raise inline-network triggers. Override per network: {$GIGAMON.INLINE.NET.CONTROL:"<alias>"}=0.'),
]

# ============================================================================== C: GigaSMART
C = TC
C_vms = [
    valuemap(C, 'Gigamon eport heartbeat status', mib.enum('ePortStatus')),
    valuemap(C, 'Gigamon eport admin status', mib.enum('adminStatus')),
    valuemap(C, 'Gigamon eport link status', mib.enum('linkStatus')),
]


def cproto(name, key, obj, **kw):
    kw.setdefault('tg', tags(component='gigasmart'))
    return proto(item(C, name, key, O(obj) + '.{#SNMPINDEX}', obj=obj, **kw))


ec = '{$GIGAMON.GS.EPORT.CONTROL:"{#EPORT.ID}"}'
ic = '{$GIGAMON.GS.IF.CONTROL:"{#EPORT.IFNAME}"}'
C_hb_protos = [
    cproto('Eport {#EPORT.ID} [{#SNMPINDEX}]: Heartbeat status', 'gigamon.gs.eport.status[{#SNMPINDEX}]', 'ePortStatus', vmap='Gigamon eport heartbeat status',
           desc='0 = not applicable, 1 = down, 2 = up.',
           triggers=[trig(C, '%s=1 and last(/%s/gigamon.gs.eport.status[{#SNMPINDEX}])=1' % (ec, C), 'Eport {#EPORT.ID} [{#SNMPINDEX}]: Heartbeat down', 'HIGH',
                          'The GigaSMART eport reports down. Silence per eport with {$GIGAMON.GS.EPORT.CONTROL:"<id>"}=0.', 'gigasmart',
                          recovery='last(/%s/gigamon.gs.eport.status[{#SNMPINDEX}])<>1 or %s=0' % (C, ec))]),
    cproto('Eport {#EPORT.ID} [{#SNMPINDEX}]: Tx count rate', 'gigamon.gs.eport.tx[{#SNMPINDEX}]', 'ePortTxCount', vt='FLOAT', units='!/s', prep=counter_rate(),
           desc='Counter64 as rate. The MIB does not state what is counted.'),
    cproto('Eport {#EPORT.ID} [{#SNMPINDEX}]: Rx count rate', 'gigamon.gs.eport.rx[{#SNMPINDEX}]', 'ePortRxCount', vt='FLOAT', units='!/s', prep=counter_rate(),
           desc='Counter64 as rate. The MIB does not state what is counted.'),
]
C_if_protos = [
    cproto('Eport interface {#EPORT.IFNAME} [{#SNMPINDEX}]: Link status', 'gigamon.gs.if.link[{#SNMPINDEX}]', 'linkStatus', vmap='Gigamon eport link status',
           triggers=[trig(C, '%s=1 and last(/%s/gigamon.gs.if.admin[{#SNMPINDEX}])=1 and last(/%s/gigamon.gs.if.link[{#SNMPINDEX}])<>1' % (ic, C, C),
                          'Eport interface {#EPORT.IFNAME} [{#SNMPINDEX}]: Link not up while administratively up ({ITEM.LASTVALUE})', 'AVERAGE',
                          'Admin status is up but link status is not up(1).', 'gigasmart',
                          recovery='last(/%s/gigamon.gs.if.link[{#SNMPINDEX}])=1 or last(/%s/gigamon.gs.if.admin[{#SNMPINDEX}])<>1 or %s=0' % (C, C, ic))]),
    cproto('Eport interface {#EPORT.IFNAME} [{#SNMPINDEX}]: Admin status', 'gigamon.gs.if.admin[{#SNMPINDEX}]', 'adminStatus', vmap='Gigamon eport admin status', hist='7d', delay='5m'),
    cproto('Eport interface {#EPORT.IFNAME} [{#SNMPINDEX}]: Speed', 'gigamon.gs.if.speed[{#SNMPINDEX}]', 'speed', units='bps', hist='7d', delay='1h',
           prep=[{'type': 'MULTIPLIER', 'parameters': ['1000000']}, {'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['1d']}],
           desc='Mbps in the MIB, converted to bit/s.'),
]
gw_oid_note = ('tunnelGwStatus is declared MAX-ACCESS accessible-for-notify in the MIB, i.e. it may not be readable by GET/WALK. '
               'The TUNGWSTATUS enumeration lives in GIGAMON-COMMON-SMI, which was not supplied, so the raw integer is stored and no value map is applied.')
gwc = '{$GIGAMON.GS.TUNNEL.GW.OK}'
dc = '{$GIGAMON.GS.TUNNEL.DEST.OK}'
C_gw_protos = [
    cproto('Tunnel gateway {#GW.IP} on {#GW.EPORT} [{#SNMPINDEX}]: Status (raw)', 'gigamon.gs.tun.gw.status[{#SNMPINDEX}]', 'tunnelGwStatus',
           desc=gw_oid_note,
           triggers=[trig(C, '%s>0 and last(/%s/gigamon.gs.tun.gw.status[{#SNMPINDEX}])<>%s' % (gwc, C, gwc),
                          'Tunnel gateway {#GW.IP} on {#GW.EPORT} [{#SNMPINDEX}]: Status is not the healthy value ({ITEM.LASTVALUE})', 'AVERAGE',
                          'Inactive until {$GIGAMON.GS.TUNNEL.GW.OK} is set to the integer that TUNGWSTATUS uses for a healthy gateway (see README).', 'gigasmart')]),
    cproto('Tunnel gateway {#GW.IP} on {#GW.EPORT} [{#SNMPINDEX}]: MAC', 'gigamon.gs.tun.gw.mac[{#SNMPINDEX}]', 'tunnelGwMac', vt='CHAR', hist='7d', delay='1h',
           prep=[{'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['1d']}]),
]
C_dest_protos = [
    cproto('Tunnel destination {#DEST.IP} on {#DEST.EPORT} [{#SNMPINDEX}]: Status (raw)', 'gigamon.gs.tun.dest.status[{#SNMPINDEX}]', 'tunnelDestStatus',
           desc='The TUNDESTSTATUS enumeration lives in GIGAMON-COMMON-SMI, which was not supplied: the raw integer is stored.',
           triggers=[trig(C, '%s>0 and last(/%s/gigamon.gs.tun.dest.status[{#SNMPINDEX}])<>%s' % (dc, C, dc),
                          'Tunnel destination {#DEST.IP} on {#DEST.EPORT} [{#SNMPINDEX}]: Status is not the healthy value ({ITEM.LASTVALUE})', 'AVERAGE',
                          'Inactive until {$GIGAMON.GS.TUNNEL.DEST.OK} is set to the integer that TUNDESTSTATUS uses for a healthy destination (see README).', 'gigasmart')]),
]
nf = 'gigamon.gs.gsop.nffail[{#SNMPINDEX}]'
C_gsop_protos = [
    cproto('GSOP {#GSOP.ALIAS} [{#SNMPINDEX}]: NetFlow resource failures rate', nf, 'netflowResourceFailureStat', vt='FLOAT', units='!/s', prep=counter_rate(),
           triggers=[trig(C, 'min(/%s/%s,{$GIGAMON.GS.NF.FAIL.WINDOW})>0' % (C, nf), 'GSOP {#GSOP.ALIAS} [{#SNMPINDEX}]: NetFlow resource failures are increasing', 'WARNING',
                          'netflowResourceFailureStat has increased continuously for {$GIGAMON.GS.NF.FAIL.WINDOW}.', 'gigasmart')])]
C_items = [
    item(C, 'GigaSMART eports, number', 'gigamon.gs.eports.count', O('numberofeports') + '.0', obj='numberofeports', delay='1h', hist='31d',
         desc='Scalar: instance .0 appended.', tg=tags(component='gigasmart'),
         prep=[{'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': ['1d']}]),
]
C_lld = [
    lld(C, 'GigaSMART eport heartbeat discovery', 'gigamon.gs.eport.discovery', [('{#EPORT.ID}', O('ePortIdentifier'))], C_hb_protos,
        'GIGAMONGIGASMART ePortHBStatusTable (%s).' % O('ePortHBStatusTable')),
    lld(C, 'GigaSMART eport interface discovery', 'gigamon.gs.if.discovery', [('{#EPORT.IFNAME}', O('ifName')), ('{#EPORT.IFTYPE}', O('ifType'))], C_if_protos,
        'GIGAMONGIGASMART ePortInterfaceTable (%s). txUtil/rxUtil are OCTET STRING of undocumented format and are not collected.' % O('ePortInterfaceTable')),
    lld(C, 'GigaSMART tunnel gateway discovery', 'gigamon.gs.tun.gw.discovery',
        [('{#GW.EPORT}', O('ePortIdentify')), ('{#GW.PORT}', O('tunnelPort')), ('{#GW.IP}', O('tunnelGwIP'))], C_gw_protos,
        'GIGAMONGIGASMART tunnelGwHealthTable (%s).' % O('tunnelGwHealthTable')),
    lld(C, 'GigaSMART tunnel destination discovery', 'gigamon.gs.tun.dest.discovery',
        [('{#DEST.IP}', O('tunnelDestIP')), ('{#DEST.EPORT}', O('ePortIdent'))], C_dest_protos,
        'GIGAMONGIGASMART tunnelDestHealthTable (%s).' % O('tunnelDestHealthTable')),
    lld(C, 'GigaSMART GSOP discovery', 'gigamon.gs.gsop.discovery', [('{#GSOP.ALIAS}', O('gigaSmartMapAndGsopAlias'))], C_gsop_protos,
        'GIGAMONGIGASMART gsopStatsTable. Effective OID %s (the OID comment in the MIB says 1.3.6.1.4.1.26866.5.7, but gigaSmartStatus is 5.1 so the table is at 5.1.7).' % O('gsopStatsTable')),
]
C_macros = [
    macro('{$GIGAMON.GS.EPORT.CONTROL}', '1', '1 = raise eport heartbeat triggers; override per eport identifier.'),
    macro('{$GIGAMON.GS.IF.CONTROL}', '1', '1 = raise eport interface link triggers; override per ifName.'),
    macro('{$GIGAMON.GS.TUNNEL.GW.OK}', '0', 'Integer of TUNGWSTATUS meaning "gateway healthy". 0 = trigger disabled (enumeration not in the supplied MIBs).'),
    macro('{$GIGAMON.GS.TUNNEL.DEST.OK}', '0', 'Integer of TUNDESTSTATUS meaning "destination healthy". 0 = trigger disabled.'),
    macro('{$GIGAMON.GS.NF.FAIL.WINDOW}', '15m', 'Period during which the NetFlow resource-failure rate must stay above 0.'),
]

# ============================================================================== D: FM traps
D = TD
FMOID = mib.oid('gigamonFM')   # 1.3.6.1.4.1.26866.6.1
FMNUM = FMOID.replace('1.3.6.1.4.1.', '').replace('.', '[.]')   # 26866[.]6[.]1
ALLKEY = 'snmptrap["%s[.]|gigamonFM|gigamonFabric|gigamonVSeries|gigamonMonitoring|gigamonFloating|gigamonAdd"]' % FMNUM
notifs = {nm: int(par[1]) for nm, par in mib.parent.items() if par[0] == 'gigamonFM'}


MAXP = 240   # Zabbix limits a trigger-function parameter to 255 characters; stay below it


def trap_chunks(names):
    """Regex alternatives (MIB name or numeric OID, numeric ones merged into one group), packed into
    chunks of at most MAXP characters. One find() per chunk, joined with 'or'."""
    for nm in names:
        assert nm in notifs, nm
    nums = '|'.join(str(notifs[nm]) for nm in names)
    parts = list(names) + ['%s[.](%s)([^0-9]|$)' % (FMNUM, nums)]
    chunks, cur = [], ''
    for p in parts:
        cand = p if not cur else cur + '|' + p
        if len(cand) > MAXP and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = cand
    chunks.append(cur)
    assert all(len(c) <= MAXP for c in chunks), chunks
    return chunks


def trap_trigger(title, prio, names, desc):
    expr = ' or '.join('find(/%s/%s,#1,"regexp","%s")=1' % (D, ALLKEY, c) for c in trap_chunks(names))
    return trig(D, expr, 'Gigamon FM: ' + title, prio, desc + ' Close manually after investigation (traps carry no automatic recovery here).', 'trap', manual=True)


D_triggers = [
    trap_trigger('Fabric node unreachable / unrecoverable / restart or reboot failed', 'HIGH',
                 ['gigamonFabricNodeUnreachableNotification', 'gigamonFabricNodeUnrecoverableNotification',
                  'gigamonFabricNodeRestartFailedNotification', 'gigamonFabricNodeRebootFailedNotification'], 'Fabric-node failure notification from GigaVUE-FM.'),
    trap_trigger('V Series node operationally unhealthy', 'HIGH', ['gigamonVSeriesOperationalUnhealthyNotification'], 'V Series node reported unhealthy.'),
    trap_trigger('Monitoring session unhealthy (config or traffic)', 'AVERAGE',
                 ['gigamonMonitoringSessionConfigUnhealthyNotification', 'gigamonMonitoringSessionTrafficUnhealthyNotification'], 'Monitoring session unhealthy.'),
    trap_trigger('Traffic drop threshold exceeded', 'AVERAGE', ['gigamonFMTrafficDropThresholdExceededEventNotification'], 'Traffic drop above threshold.'),
    trap_trigger('Licence expired', 'AVERAGE', ['gigamonFMLicensesExpiredNotification', 'gigamonFloatingLicensesExpiredEventNotification'], 'Licences have expired.'),
    trap_trigger('Licence expiring / grace period', 'WARNING',
                 ['gigamonFMLicensesExpiringSoonNotification', 'gigamonFMLicensesExpiringIn90DaysNotification', 'gigamonFloatingLicensesGraceEventNotification'], 'Licences expiring or in grace.'),
    trap_trigger('Disk space / reclaim threshold', 'AVERAGE', ['gigamonFMDiskReclaimEventNotification', 'gigamonFMDiskSpaceEventNotification'], 'FM disk usage above threshold.'),
    trap_trigger('Cluster member not reachable / high availability event', 'AVERAGE',
                 ['gigamonFMClusterMemberNotReachableEventNotification', 'gigamonFMHighAvailabilityNotification'], 'Cluster or HA event.'),
    trap_trigger('Image upgrade failed', 'AVERAGE', ['gigamonFMImageUpgradeFailedNotification'], 'Image upgrade failed.'),
    trap_trigger('Flow computation error / flow health changed', 'WARNING',
                 ['gigamonFMFlowComputationErrorEventNotification', 'gigamonFMSFlowHealthStateChangedNotification'], 'Flow computation error or flow health change.'),
]
D_items = [
    item(D, 'SNMP traps: Gigamon FM notifications', ALLKEY, None, vt='LOG', itype='SNMP_TRAP', hist='30d', delay='0',
         desc='All GIGAMON-FM-SNMP notifications (%s.*). Matches the numeric OID or the MIB notification name, so it works with or without MIBs loaded in snmptrapd. Receiver setup in the README.' % FMOID,
         tg=tags(component='traps'), triggers=D_triggers),
    item(D, 'SNMP traps (fallback)', 'snmptrap.fallback', None, vt='LOG', itype='SNMP_TRAP', hist='7d', delay='0',
         desc='Traps from this host that match no snmptrap[] item.', tg=tags(component='traps')),
]
for i in D_items:
    i.pop('trends', None)

doc = {'zabbix_export': {'version': '7.0', 'template_groups': [{'uuid': uid('group', GROUP), 'name': GROUP}], 'templates': [
    template(TA, 'Gigamon GigaVUE node by SNMP: ICMP/SNMP availability, MIB-II system data and IF-MIB interface discovery (status, 64-bit traffic, errors, discards).\n'
                 'Link to every Gigamon node. Chassis hardware health (fans, power, temperature, ports, maps) is NOT covered: that lives in GIGAMON-SNMP-MIB, which was not among the MIBs this template was built from.',
             A_items, A_lld, A_macros, A_vms, tags(**{'class': 'network', 'target': 'gigamon'})),
    template(TB, 'Gigamon inline bypass (GIGAMONINLINEBYPASS, 1.3.6.1.4.1.26866.4): inline tool and inline network status, heartbeat, forward state. Link only to nodes that run inline bypass.',
             None, B_lld, B_macros, B_vms, tags(**{'class': 'network', 'target': 'gigamon'})),
    template(TC, 'Gigamon GigaSMART (GIGAMONGIGASMART, 1.3.6.1.4.1.26866.5): eport heartbeat, eport interfaces, tunnel gateway/destination health, GSOP NetFlow resource failures. Link only to nodes with GigaSMART.',
             C_items, C_lld, C_macros, C_vms, tags(**{'class': 'network', 'target': 'gigamon'})),
    template(TD, 'GigaVUE-FM notifications (GIGAMON-FM-SNMP, 1.3.6.1.4.1.26866.6.1.*) received as SNMP traps. The MIB defines no pollable objects for FM. Needs snmptrapd + zabbix_trap_receiver and a host whose SNMP interface IP equals the trap source address.',
             D_items, None, [], None, tags(**{'class': 'software', 'target': 'gigamon-fm'})),
]}}
# trap items must not carry trends/units; SNMP_TRAP LOG items have no value-type quirks
with open(OUT, 'w', encoding='utf-8') as f:
    yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False, allow_unicode=True, width=10000)
print('written', OUT)
