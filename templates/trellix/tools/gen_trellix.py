#!/usr/bin/env python3
"""Generates the Trellix (FireEye) Zabbix 7.0 SNMP templates from FE-FIREEYE-MIB (enterprise 25597).
Every Trellix OID, table column and notification OID is taken from the MIB parsed by mibtree.py, never typed by hand."""
import hashlib
import re
import sys
import yaml
from mibtree import Mib

MIBFILE = sys.argv[2] if len(sys.argv) > 2 else '/home/claude/trellix/TRELLIX-MIB.txt'
OUT = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/trellix/zbx_templates_trellix_snmp.yaml'
mib = Mib([MIBFILE])
O = mib.oid
GROUP = 'Templates/Security'
TA = 'Trellix by SNMP'
TCMS = 'Trellix CMS by SNMP'
TE = 'Trellix EMPS by SNMP'
TW = 'Trellix WMPS by SNMP'
TM = 'Trellix MAS by SNMP'
TT = 'Trellix by SNMP traps'
ENT = '1.3.6.1.4.1.'
PFX = 'TRELLIX'


def uid(*parts):
    h = hashlib.sha256(('trellix:' + ':'.join(parts)).encode()).hexdigest()
    return h[:12] + '4' + h[13:16] + '8' + h[17:32]


def pretty(n):
    n = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', n.replace('-', ' ')).strip().lower()
    return n[:1].upper() + n[1:]


def tags(**kw):
    return [{'tag': k, 'value': v} for k, v in kw.items()]


def item(tpl, name, key, oid, vt='UNSIGNED', obj=None, delay='1m', hist='31d', units=None, vmap=None, prep=None, desc='',
         tg=None, triggers=None, itype='SNMP_AGENT', params=None, disabled=False):
    d = {'uuid': uid(tpl, 'item', key), 'name': name, 'type': itype}
    if oid:
        d['snmp_oid'] = oid
    d['key'] = key
    d['delay'] = delay
    d['history'] = hist
    d['trends'] = '365d' if vt in ('UNSIGNED', 'FLOAT') else '0'
    if vt != 'FLOAT_DEFAULT':
        d['value_type'] = vt
    if units:
        d['units'] = units
    if params:
        d['params'] = params
    text = desc
    if obj:
        text = (desc + ' ' if desc else '') + 'MIB object %s (%s).' % (obj, O(obj))
    if text:
        d['description'] = text
    if vmap:
        d['valuemap'] = {'name': vmap}
    if prep:
        d['preprocessing'] = prep
    if disabled:
        d['status'] = 'DISABLED'
    d['tags'] = tg or []
    if triggers:
        d['triggers'] = triggers
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
    if 'triggers' in d:
        d['trigger_prototypes'] = d.pop('triggers')
    return d


def lld(tpl, name, key, parts, protos, desc, delay='1h'):
    oid = 'discovery[' + ','.join('%s,%s' % (m, o) for m, o in parts) + ']'
    return {'uuid': uid(tpl, 'lld', key), 'name': name, 'type': 'SNMP_AGENT', 'snmp_oid': oid, 'key': key, 'delay': delay,
            'lifetime': '7d', 'description': desc, 'item_prototypes': [proto(p) for p in protos]}


def macro(m, v, desc):
    return {'macro': m, 'value': v, 'description': desc}


HB = lambda t: [{'type': 'DISCARD_UNCHANGED_HEARTBEAT', 'parameters': [t]}]
TV = 'Trellix TruthValue'


def vms(tpl):
    return [
        {'uuid': uid(tpl, 'vm', 'svc'), 'name': 'Trellix service state', 'mappings': [{'value': '0', 'newvalue': 'Down'}, {'value': '1', 'newvalue': 'Up'}]},
        {'uuid': uid(tpl, 'vm', 'snmpav'), 'name': 'Trellix SNMP availability',
         'mappings': [{'value': '0', 'newvalue': 'Not available'}, {'value': '1', 'newvalue': 'Available'}, {'value': '2', 'newvalue': 'Unknown'}]},
        # TruthValue comes from SNMPv2-TC (imported by the MIB, not defined in it): true(1), false(2)
        {'uuid': uid(tpl, 'vm', 'tv'), 'name': TV, 'mappings': [{'value': '1', 'newvalue': 'True'}, {'value': '2', 'newvalue': 'False'}]},
    ]


def scalar(tpl, obj, name, key, **kw):
    assert mib.access[obj] == 'read-only', obj
    kw.setdefault('tg', tags(component='system'))
    return item(tpl, name, key, O(obj) + '.0', obj=obj, **kw)


def col(tpl, obj, name, key, **kw):
    assert mib.access[obj] == 'read-only', obj
    return proto(item(tpl, name, key, O(obj) + '.{#SNMPINDEX}', obj=obj, **kw))


def template(name, desc, items, lld_rules, macros, vmaps, tagz):
    t = {'uuid': uid(name, 'template'), 'template': name, 'name': name, 'description': desc, 'groups': [{'name': GROUP}]}
    if items:
        t['items'] = items
    if lld_rules:
        t['discovery_rules'] = lld_rules
    if macros:
        t['macros'] = macros
    t['tags'] = tagz
    if vmaps:
        t['valuemaps'] = vmaps
    return t


def avail_items(T, P):
    return [
        item(T, 'ICMP ping', 'icmpping', None, itype='SIMPLE', vmap='Trellix service state', tg=tags(component='availability'),
             triggers=[trig(T, 'max(/%s/icmpping,#3)=0' % T, 'Trellix: Unavailable by ICMP ping', 'HIGH', 'No ICMP echo reply in 3 consecutive checks.', 'availability')]),
        item(T, 'ICMP loss', 'icmppingloss', None, vt='FLOAT', itype='SIMPLE', units='%', tg=tags(component='availability'),
             triggers=[trig(T, 'min(/%s/icmppingloss,5m)>{$%s.ICMP.LOSS.WARN} and min(/%s/icmppingloss,5m)<100' % (T, P, T), 'Trellix: High ICMP ping loss ({ITEM.VALUE})', 'WARNING', scope='availability')]),
        item(T, 'ICMP response time', 'icmppingsec', None, vt='FLOAT', itype='SIMPLE', units='s', tg=tags(component='availability'),
             triggers=[trig(T, 'min(/%s/icmppingsec,5m)>{$%s.ICMP.RESPONSE.TIME.WARN}' % (T, P), 'Trellix: High ICMP ping response time ({ITEM.VALUE})', 'WARNING', scope='availability')]),
        item(T, 'SNMP agent availability', 'zabbix[host,snmp,available]', None, itype='INTERNAL', vmap='Trellix SNMP availability',
             desc='Availability of the SNMP interface as seen by the Zabbix server/proxy.', tg=tags(component='availability'),
             triggers=[trig(T, 'max(/%s/zabbix[host,snmp,available],{$%s.SNMP.TIMEOUT})=0' % (T, P), 'Trellix: No SNMP data collection', 'AVERAGE',
                            'SNMP polling failed for the whole {$%s.SNMP.TIMEOUT}: check community/credentials, the SNMP allow-list on the appliance and UDP/161 reachability. Counter64 objects need SNMPv2c or v3.' % P, 'availability')]),
    ]


def avail_macros(P):
    return [macro('{$%s.ICMP.LOSS.WARN}' % P, '20', 'ICMP loss (%) above which the warning fires.'),
            macro('{$%s.ICMP.RESPONSE.TIME.WARN}' % P, '0.15', 'ICMP response time (s) above which the warning fires.'),
            macro('{$%s.SNMP.TIMEOUT}' % P, '5m', 'How long SNMP must be unavailable before the trigger fires.')]


# ============================================================================ A: common (all appliances)
A = TA
SYS = {'sysDescr': '1.3.6.1.2.1.1.1.0', 'sysObjectID': '1.3.6.1.2.1.1.2.0', 'sysUpTime': '1.3.6.1.2.1.1.3.0', 'sysName': '1.3.6.1.2.1.1.5.0'}
A_items = avail_items(A, PFX) + [
    item(A, 'System description', 'system.descr', SYS['sysDescr'], vt='TEXT', hist='7d', delay='1h', desc='MIB-II sysDescr.', prep=HB('1d'), tg=tags(component='system')),
    item(A, 'System name', 'system.name', SYS['sysName'], vt='CHAR', hist='7d', delay='1h', desc='MIB-II sysName.', prep=HB('1d'), tg=tags(component='system')),
    item(A, 'System object ID', 'system.objectid', SYS['sysObjectID'], vt='CHAR', hist='7d', delay='1h',
         desc='MIB-II sysObjectID (expected under 1.3.6.1.4.1.25597; not verified against a live appliance).', prep=HB('1d'), tg=tags(component='system')),
    item(A, 'Uptime', 'system.uptime', SYS['sysUpTime'], vt='FLOAT', units='uptime', desc='MIB-II sysUpTime (timeticks / 100).',
         prep=[{'type': 'MULTIPLIER', 'parameters': ['0.01']}], tg=tags(component='system'),
         triggers=[trig(A, 'last(/%s/system.uptime)<10m' % A, 'Trellix: Restarted (uptime {ITEM.LASTVALUE})', 'INFO', 'Uptime below 10 minutes: the appliance restarted or the SNMP agent was reset.', 'availability'),
                   trig(A, 'nodata(/%s/system.uptime,{$TRELLIX.NODATA.TIMEOUT})=1' % A, 'Trellix: No SNMP data for {$TRELLIX.NODATA.TIMEOUT}', 'AVERAGE', scope='availability')]),
    scalar(A, 'feHardwareModel', 'Hardware model', 'trellix.model', vt='CHAR', hist='7d', delay='1h', prep=HB('1d')),
    scalar(A, 'feSerialNumber', 'Serial number', 'trellix.serial', vt='CHAR', hist='7d', delay='1h', prep=HB('1d')),
    scalar(A, 'feSystemStatus', 'Overall system status (text)', 'trellix.system.status', vt='TEXT', hist='31d', delay='1m', prep=HB('6h'),
           desc='Free-text status string. The MIB does not define its possible values, so no trigger is based on it; health is judged from the *IsHealthy truth-value objects and from traps.'),
    scalar(A, 'feTemperatureValue', 'Temperature', 'trellix.temperature', vt='FLOAT', units='°C', tg=tags(component='temperature'),
           desc='System temperature in Celsius.',
           triggers=[trig(A, 'min(/%s/trellix.temperature,5m)>{$TRELLIX.TEMP.WARN}' % A, 'Trellix: High temperature ({ITEM.VALUE})', 'WARNING',
                          'The default threshold is a tunable assumption, not a vendor figure. The appliance also sends feExcessiveTemperature.', 'temperature')]),
    scalar(A, 'feTemperatureStatus', 'Temperature status (text)', 'trellix.temperature.status', vt='CHAR', hist='7d', delay='5m', prep=HB('6h'), tg=tags(component='temperature')),
    scalar(A, 'feTemperatureIsHealthy', 'Temperature is healthy', 'trellix.temperature.healthy', vmap=TV, tg=tags(component='temperature'),
           triggers=[trig(A, 'last(/%s/trellix.temperature.healthy)=2' % A, 'Trellix: Temperature not healthy', 'HIGH', 'TruthValue false(2): the appliance reports an abnormal temperature.', 'temperature',
                          recovery='last(/%s/trellix.temperature.healthy)=1' % A)]),
    scalar(A, 'feRaidStatus', 'RAID status (text)', 'trellix.raid.status', vt='TEXT', prep=HB('6h'), tg=tags(component='storage')),
    scalar(A, 'feRaidIsHealthy', 'RAID is healthy', 'trellix.raid.healthy', vmap=TV, tg=tags(component='storage'),
           triggers=[trig(A, 'last(/%s/trellix.raid.healthy)=2' % A, 'Trellix: RAID not healthy', 'HIGH', 'TruthValue false(2): RAID is degraded or failed.', 'storage', recovery='last(/%s/trellix.raid.healthy)=1' % A)]),
    scalar(A, 'fePowerSupplyOverallStatus', 'Power supply status (text)', 'trellix.psu.status', vt='TEXT', prep=HB('6h'), tg=tags(component='power')),
    scalar(A, 'fePowerSupplyOverallIsHealthy', 'Power supply is healthy', 'trellix.psu.healthy', vmap=TV, tg=tags(component='power'),
           triggers=[trig(A, 'last(/%s/trellix.psu.healthy)=2' % A, 'Trellix: Power supply not healthy', 'HIGH', 'TruthValue false(2).', 'power', recovery='last(/%s/trellix.psu.healthy)=1' % A)]),
    scalar(A, 'feFanOverallStatus', 'Fan status overall (text)', 'trellix.fan.status', vt='TEXT', prep=HB('6h'), tg=tags(component='fan')),
    scalar(A, 'feFanOverallIsHealthy', 'Fans are healthy', 'trellix.fan.healthy', vmap=TV, tg=tags(component='fan'),
           triggers=[trig(A, 'last(/%s/trellix.fan.healthy)=2' % A, 'Trellix: Fan not healthy', 'AVERAGE', 'TruthValue false(2).', 'fan', recovery='last(/%s/trellix.fan.healthy)=1' % A)]),
    scalar(A, 'feInstalledSystemImage', 'Installed system image', 'trellix.image.installed', vt='CHAR', hist='7d', delay='1h', prep=HB('1d'), tg=tags(component='software')),
    scalar(A, 'feSystemImageVersionCurrent', 'System image version (current)', 'trellix.image.current', vt='CHAR', hist='7d', delay='1h', prep=HB('1d'), tg=tags(component='software')),
    scalar(A, 'feSystemImageVersionLatest', 'System image version (latest)', 'trellix.image.latest', vt='CHAR', hist='7d', delay='1h', prep=HB('1d'), tg=tags(component='software')),
    scalar(A, 'feIsSystemImageLatest', 'System image is the latest', 'trellix.image.is_latest', vmap=TV, delay='1h', tg=tags(component='software'),
           triggers=[trig(A, 'last(/%s/trellix.image.is_latest)=2' % A, 'Trellix: A newer system image is available', 'INFO', scope='software')]),
    scalar(A, 'feSecurityContentVersion', 'Security content version', 'trellix.content.version', vt='CHAR', hist='31d', delay='1h', prep=HB('1d'), tg=tags(component='software')),
    scalar(A, 'feLastContentUpdatePassed', 'Last security content update passed', 'trellix.content.update.passed', vmap=TV, delay='5m', tg=tags(component='software'),
           triggers=[trig(A, 'last(/%s/trellix.content.update.passed)=2' % A, 'Trellix: Last security content update failed', 'AVERAGE', scope='software',
                          recovery='last(/%s/trellix.content.update.passed)=1' % A)]),
    scalar(A, 'feLastContentUpdateTime', 'Last security content update time', 'trellix.content.update.time', vt='CHAR', hist='7d', delay='1h', prep=HB('1d'), tg=tags(component='software')),
    scalar(A, 'feActiveVMs', 'Active VMs', 'trellix.vms.active', tg=tags(component='analysis'), delay='5m'),
    scalar(A, 'feProductLicenseActive', 'Product licence is active', 'trellix.license.product', vmap=TV, delay='1h', tg=tags(component='license'),
           triggers=[trig(A, 'last(/%s/trellix.license.product)=2' % A, 'Trellix: Product licence not active', 'AVERAGE', scope='license', recovery='last(/%s/trellix.license.product)=1' % A)]),
    scalar(A, 'feContentLicenseActive', 'Content licence is active', 'trellix.license.content', vmap=TV, delay='1h', tg=tags(component='license'),
           triggers=[trig(A, 'last(/%s/trellix.license.content)=2' % A, 'Trellix: Content licence not active', 'AVERAGE', scope='license', recovery='last(/%s/trellix.license.content)=1' % A)]),
    scalar(A, 'feSupportLicenseActive', 'Support licence is active', 'trellix.license.support', vmap=TV, delay='1h', tg=tags(component='license'),
           triggers=[trig(A, 'last(/%s/trellix.license.support)=2' % A, 'Trellix: Support licence not active', 'WARNING', scope='license', recovery='last(/%s/trellix.license.support)=1' % A)]),
    scalar(A, 'feAvcOverloadStatus', 'AVC overload status', 'trellix.avc.overload', vmap=TV, delay='5m', tg=tags(component='analysis'),
           desc='AVC-provided appliance overloaded status (true = overloaded).',
           triggers=[trig(A, 'last(/%s/trellix.avc.overload)=1' % A, 'Trellix: Appliance overloaded (AVC)', 'WARNING', scope='analysis', recovery='last(/%s/trellix.avc.overload)=2' % A)]),
    scalar(A, 'feAvcMoreOverloadStats', 'AVC overload statistics (text)', 'trellix.avc.stats', vt='TEXT', hist='7d', delay='5m', prep=HB('1d'), tg=tags(component='analysis')),
    scalar(A, 'feAvcSuggestedMaxVMs', 'AVC suggested max VMs', 'trellix.avc.maxvms', delay='5m', tg=tags(component='analysis')),
]
# submission counters: H/L halves of a 64-bit value (feSubmission is the common, non-deprecated tree)
SUBM = [('Count', 'Submissions total'), ('DoneCount', 'Submissions done'), ('TimedOutCount', 'Submissions timed out'),
        ('Aging50to74Cnt', 'Submissions 50-74% aged'), ('Aging75to100Cnt', 'Submissions 75-100% aged')]
for suf, title in SUBM:
    lo, hi = 'feSubmission%sL' % suf, 'feSubmission%sH' % suf
    k = 'trellix.submission.' + suf.lower()
    A_items.append(scalar(A, lo, title + ' (low 32 bit)', k + '.low', hist='7d', delay='5m', tg=tags(component='submission')))
    A_items.append(scalar(A, hi, title + ' (high 32 bit)', k + '.high', hist='7d', delay='5m', tg=tags(component='submission')))
    A_items.append(item(A, title, k, None, itype='CALCULATED', delay='5m', tg=tags(component='submission'),
                        params='last(/%s/%s.high)*4294967296+last(/%s/%s.low)' % (A, k, A, k),
                        desc='(high << 32) + low. The MIB calls it the "total submission count"; whether it is cumulative or windowed is not stated, so it is stored unchanged (no rate).'))

A_lld = [
    lld(A, 'Physical disk discovery', 'trellix.disk.discovery', [('{#DISKNAME}', O('fePhysicalDiskName'))], [
        col(A, 'fePhysicalDiskStatus', 'Disk {#DISKNAME}: Status (text)', 'trellix.disk.status[{#SNMPINDEX}]', vt='CHAR', hist='7d', delay='5m', prep=HB('6h'), tg=tags(component='storage', disk='{#DISKNAME}')),
        col(A, 'fePhysicalDiskIsHealthy', 'Disk {#DISKNAME}: Is healthy', 'trellix.disk.healthy[{#SNMPINDEX}]', vmap=TV, delay='5m', tg=tags(component='storage', disk='{#DISKNAME}'),
            triggers=[trig(A, 'last(/%s/trellix.disk.healthy[{#SNMPINDEX}])=2' % A, 'Trellix: Disk {#DISKNAME} not healthy', 'HIGH', scope='storage', recovery='last(/%s/trellix.disk.healthy[{#SNMPINDEX}])=1' % A)]),
        col(A, 'fePhysicalDiskSelfAssess', 'Disk {#DISKNAME}: Self assessment (text)', 'trellix.disk.selfassess[{#SNMPINDEX}]', vt='CHAR', hist='7d', delay='1h', prep=HB('1d'), tg=tags(component='storage', disk='{#DISKNAME}')),
        col(A, 'fePhysicalDiskDeviceSupport', 'Disk {#DISKNAME}: Device configuration (text)', 'trellix.disk.devsupport[{#SNMPINDEX}]', vt='CHAR', hist='7d', delay='1h', prep=HB('1d'), tg=tags(component='storage', disk='{#DISKNAME}')),
        col(A, 'fePhysicalDiskTotalBytes', 'Disk {#DISKNAME}: Capacity (text)', 'trellix.disk.size[{#SNMPINDEX}]', vt='CHAR', hist='7d', delay='1h', prep=HB('1d'), tg=tags(component='storage', disk='{#DISKNAME}'),
            desc='The MIB types this as OCTET STRING, so the value is kept as text.'),
    ], 'fePhysicalDiskTable'),
    lld(A, 'Fan discovery', 'trellix.fan.discovery', [('{#FANNAME}', O('feFanName'))], [
        col(A, 'feFanStatus', 'Fan {#FANNAME}: Status (text)', 'trellix.fan.st[{#SNMPINDEX}]', vt='CHAR', hist='7d', delay='5m', prep=HB('6h'), tg=tags(component='fan', fan='{#FANNAME}')),
        col(A, 'feFanIsHealthy', 'Fan {#FANNAME}: Is healthy', 'trellix.fan.ok[{#SNMPINDEX}]', vmap=TV, delay='5m', tg=tags(component='fan', fan='{#FANNAME}'),
            triggers=[trig(A, 'last(/%s/trellix.fan.ok[{#SNMPINDEX}])=2' % A, 'Trellix: Fan {#FANNAME} not healthy', 'AVERAGE', scope='fan', recovery='last(/%s/trellix.fan.ok[{#SNMPINDEX}])=1' % A)]),
        col(A, 'feFanSpeed', 'Fan {#FANNAME}: Speed', 'trellix.fan.speed[{#SNMPINDEX}]', units='rpm', delay='5m', tg=tags(component='fan', fan='{#FANNAME}')),
    ], 'feFanStatusTable'),
    lld(A, 'Guest image discovery', 'trellix.gi.discovery', [('{#GINAME}', O('feGIName'))], [
        col(A, 'feGIVersion', 'Guest image {#GINAME}: Version', 'trellix.gi.version[{#SNMPINDEX}]', vt='CHAR', hist='31d', delay='1h', prep=HB('1d'), tg=tags(component='analysis', guestimage='{#GINAME}')),
        col(A, 'feGIEnabled', 'Guest image {#GINAME}: Enabled', 'trellix.gi.enabled[{#SNMPINDEX}]', vmap=TV, hist='31d', delay='1h', prep=HB('1d'), tg=tags(component='analysis', guestimage='{#GINAME}')),
        col(A, 'feGIInstallDateTime', 'Guest image {#GINAME}: Install date/time', 'trellix.gi.installed[{#SNMPINDEX}]', vt='CHAR', hist='31d', delay='1h', prep=HB('1d'), tg=tags(component='analysis', guestimage='{#GINAME}')),
    ], 'feGIVersionTable'),
    lld(A, 'Licensed feature discovery', 'trellix.licfeature.discovery', [('{#LICFEATURE}', O('feLicenseFeature'))], [
        col(A, 'feLicenseActive', 'Licence {#LICFEATURE}: Active', 'trellix.licfeature.active[{#SNMPINDEX}]', vmap=TV, delay='1h', tg=tags(component='license', feature='{#LICFEATURE}'),
            triggers=[trig(A, 'last(/%s/trellix.licfeature.active[{#SNMPINDEX}])=2' % A, 'Trellix: Licence {#LICFEATURE} not active', 'AVERAGE', scope='license', recovery='last(/%s/trellix.licfeature.active[{#SNMPINDEX}])=1' % A)]),
        col(A, 'feLicenseFeatureDescr', 'Licence {#LICFEATURE}: Description', 'trellix.licfeature.descr[{#SNMPINDEX}]', vt='CHAR', hist='7d', delay='1d', prep=HB('7d'), tg=tags(component='license', feature='{#LICFEATURE}')),
        col(A, 'feLicenseDaysUntilExpiration', 'Licence {#LICFEATURE}: Days until expiration', 'trellix.licfeature.days[{#SNMPINDEX}]', delay='1h', units='d', tg=tags(component='license', feature='{#LICFEATURE}'),
            disabled=True,
            desc='DISABLED by default: the MIB says this object returns nothing for perpetual, inactive or expired features, which would leave the item unsupported. Enable it only for features you know expire.',
            triggers=[trig(A, 'last(/%s/trellix.licfeature.days[{#SNMPINDEX}])<{$TRELLIX.LICENSE.DAYS.WARN}' % A, 'Trellix: Licence {#LICFEATURE} expires in {ITEM.LASTVALUE} days', 'WARNING', scope='license')]),
    ], 'feLicenseFeatureTable'),
]
for r in A_lld:   # description: name the MIB table the rule walks
    r['description'] = 'Discovers rows of %s (%s).' % (r['description'], O(r['description']))
A_macros = avail_macros(PFX) + [
    macro('{$TRELLIX.NODATA.TIMEOUT}', '30m', 'No-data period for the uptime item.'),
    macro('{$TRELLIX.TEMP.WARN}', '70', 'Temperature (C) warning threshold. Assumed default, not a vendor value.'),
    macro('{$TRELLIX.LICENSE.DAYS.WARN}', '30', 'Days left on a licensed feature below which the (disabled-by-default) expiry trigger fires.'),
]

# ============================================================================ CMS
C = TCMS
C_items = [scalar(C, o, pretty(o[2:]).replace('Total ', 'Total ') + '', 'trellix.cms.' + o[7:].lower(), delay='5m', tg=tags(component='cms'))
           for o in ['feTotalAppliancesAttached', 'feTotalWMPSAttached', 'feTotalEMPSAttached', 'feTotalFMPSAttached', 'feTotalMASAttached']]
for it, o in zip(C_items, ['Appliances attached', 'WMPS attached', 'EMPS attached', 'FMPS attached', 'MAS attached']):
    it['name'] = o
CHK = [('feCMSApplianceDiskSpacePassed', 'Disk space check passed', 'disk'), ('feCMSApplianceFanPassed', 'Fan check passed', 'fan'),
       ('feCMSAppliancePowerSupplyPassed', 'Power supply check passed', 'psu'), ('feCMSApplianceRaidPassed', 'RAID check passed', 'raid'),
       ('feCMSApplianceTemperaturePassed', 'Temperature check passed', 'temp')]
C_protos = []
for o, nm, k in CHK:
    key = 'trellix.cms.app.%s[{#SNMPINDEX}]' % k
    C_protos.append(col(C, o, 'Appliance {#CMSAPP}: ' + nm, key, vmap=TV, delay='5m', tg=tags(component='cms', appliance='{#CMSAPP}'),
                        triggers=[trig(C, 'last(/%s/%s)=2' % (C, key), 'Trellix CMS: Appliance {#CMSAPP} failed %s' % nm.replace(' passed', ''), 'AVERAGE', scope='cms', recovery='last(/%s/%s)=1' % (C, key))]))
C_lld = [lld(C, 'CMS managed appliance discovery', 'trellix.cms.discovery', [('{#CMSAPP}', O('feCMSApplianceName'))], C_protos, 'Discovers rows of feCMSApplianceTable (%s).' % O('feCMSApplianceTable'))]

# ============================================================================ EMPS
E = TE
kids = {}
for n, (p, i) in mib.parent.items():
    kids.setdefault(p, []).append((i, n))
E_items = []
for _, o in sorted(kids['feEMPSInfo']):
    if mib.access.get(o) != 'read-only' or re.search(r'(Count)?[HL]$', o) and mib.syntax.get(o) == 'Counter32':
        continue
    syn = mib.syntax[o]
    k = 'trellix.emps.' + o[2:].lower()
    if syn == 'Counter64':
        E_items.append(scalar(E, o, pretty(o[2:]) + ' (past window)', k, delay='5m', tg=tags(component='email'),
                              desc='Counter64 whose MIB description says it is the value for the past hour (configurable), maintained across reboots - a windowed value, not a monotonic counter, so no rate is calculated.'))
    elif o in ('feSamplingEmailStartTime', 'feSamplingEmailEndTime'):
        E_items.append(scalar(E, o, pretty(o[2:]), k, vt='CHAR', hist='7d', delay='5m', prep=HB('1d'), tg=tags(component='email')))
    else:
        assert 'Unsigned32' in syn, (o, syn)
        E_items.append(scalar(E, o, 'Quarantine usage' if o == 'feeQuarantineUsage' else pretty(o[2:]), k, delay='5m', tg=tags(component='email'), units='%' if o == 'feeQuarantineUsage' else None))
for it in E_items:
    if it['key'] == 'trellix.emps.equarantineusage':
        it['triggers'] = [trig(E, 'min(/%s/%s,10m)>{$TRELLIX.EMPS.QUARANTINE.WARN}' % (E, it['key']), 'Trellix EMPS: Quarantine usage high ({ITEM.VALUE}%)', 'WARNING', 'Default threshold is an assumption.', 'email')]
E_macros = [macro('{$TRELLIX.EMPS.QUARANTINE.WARN}', '80', 'Quarantine usage (%) above which the warning fires. Assumed default.')]

# ============================================================================ WMPS
W = TW
W_items = [
    scalar(W, 'feDeploymentCheckStatus', 'Deployment check status (text)', 'trellix.wmps.dc.status', vt='TEXT', prep=HB('6h'), delay='5m', tg=tags(component='deployment-check')),
    scalar(W, 'feDeploymentCheckIsHealthy', 'Deployment check is healthy (raw)', 'trellix.wmps.dc.healthy', delay='5m', tg=tags(component='deployment-check'),
           desc='Typed Unsigned32 (not TruthValue); the MIB does not define the values, so it is stored raw and not used in a trigger. feDeploymentCheckFailure/Recover traps are used instead.'),
    scalar(W, 'feDeploymentCheckMessage', 'Deployment check message', 'trellix.wmps.dc.message', vt='TEXT', prep=HB('6h'), delay='5m', tg=tags(component='deployment-check')),
]
for _, o in sorted(kids['feWMPSInfo']):
    if mib.syntax.get(o) == 'CounterBasedGauge64' and mib.access[o] == 'read-only':
        W_items.append(scalar(W, o, pretty(o[2:]), 'trellix.wmps.dc.' + o[len('feDeploymentCheck'):].lower(), delay='5m', tg=tags(component='deployment-check'),
                              units='B' if o.endswith('DataSize') else None))
for _, o in sorted(kids['feWMPSSizing']):
    W_items.append(scalar(W, o, pretty(o[2:]), 'trellix.wmps.sizing.' + o[len('feWMPS'):].lower(), delay='5m', tg=tags(component='sizing'),
                          desc='Typed Counter32 but described as a utilization/status measure; stored raw (no rate). Threshold crossings arrive as feWMPSSizingThresholdExceeded/Normal traps.'))
W_items += [scalar(W, o, pretty(o[2:]) + ' (text)', 'trellix.wmps.' + o[2:].lower(), vt='CHAR', hist='31d', delay='5m', prep=HB('1h'), tg=tags(component='traffic'),
                   desc='The MIB types this as OCTET STRING without stating the format, so it is stored as text.') for o in ['fePercentageInputTrafficLost', 'fePercentageFlowIncompleteData']]


def c64cols(table):
    ent = sorted(kids[table])[0][1]
    return [c for _, c in sorted(kids[ent]) if mib.syntax.get(c) == 'Counter64']


stat_protos = [col(W, c, pretty(c[len('feWMPS'):]) + ' [{#TIMESPAN}]', 'trellix.wmps.det.%s[{#SNMPINDEX}]' % c[len('feWMPS'):].lower(), delay='5m', tg=tags(component='detection', timespan='{#TIMESPAN}'),
               desc='Windowed count for the time span (not a monotonic counter).') for c in c64cols('feWMPSDetectionStatsTable')]


def named_table(table, nameobj, cntobj, label, key):
    return col(W, cntobj, '%s {#NAME} [{#TIMESPAN}]: Count' % label, key + '[{#SNMPINDEX}]', delay='5m', tg=tags(component='detection', timespan='{#TIMESPAN}', name='{#NAME}'),
               desc='Windowed count for the time span (not a monotonic counter).')


W_lld = [
    lld(W, 'Detection statistics discovery', 'trellix.wmps.det.discovery', [('{#TIMESPAN}', O('feWMPSDetectionStatsTimeSpan'))], stat_protos, 'Discovers rows of feWMPSDetectionStatsTable (%s).' % O('feWMPSDetectionStatsTable'), delay='1h'),
    lld(W, 'Alert type discovery', 'trellix.wmps.alert.discovery', [('{#TIMESPAN}', O('feWMPSAlertTimeSpan')), ('{#NAME}', O('feWMPSAlertName'))],
        [named_table('feWMPSAlertTable', 'feWMPSAlertName', 'feWMPSAlertCount', 'Alert', 'trellix.wmps.alert')], 'Discovers rows of feWMPSAlertTable (%s).' % O('feWMPSAlertTable')),
    lld(W, 'Threat type discovery', 'trellix.wmps.threat.discovery', [('{#TIMESPAN}', O('feWMPSThreatTimeSpan')), ('{#NAME}', O('feWMPSThreatName'))],
        [named_table('feWMPSThreatTable', 'feWMPSThreatName', 'feWMPSThreatCount', 'Threat', 'trellix.wmps.threat')], 'Discovers rows of feWMPSThreatTable (%s).' % O('feWMPSThreatTable')),
    lld(W, 'File type discovery', 'trellix.wmps.filetype.discovery', [('{#TIMESPAN}', O('feWMPSFileTypeTimeSpan')), ('{#NAME}', O('feWMPSFileTypeName'))],
        [named_table('feWMPSFileTypeTable', 'feWMPSFileTypeName', 'feWMPSFileTypeCount', 'File type', 'trellix.wmps.filetype')], 'Discovers rows of feWMPSFileTypeTable (%s).' % O('feWMPSFileTypeTable')),
]

# ============================================================================ MAS
M = TM
M_items = []
for _, o in sorted(kids['feMASInfo']):
    if mib.syntax.get(o) == 'Counter64' and mib.access[o] == 'read-only':
        M_items.append(scalar(M, o, pretty(o[2:]), 'trellix.mas.' + o[2:].lower(), delay='5m', tg=tags(component='analysis'),
                              desc='Counter64 described as a count of objects. Cumulative vs windowed is not stated by the MIB, so the raw value is stored (use change()/delta in your own graphs).'))

# ============================================================================ traps
T = TT
notifs = {n: mib.oid(n) for n, k in mib.kind.items() if k.startswith('NOTIF')}
assert len(notifs) == 55, len(notifs)
BASE = '25597'
nums = {n: o[len(ENT):].replace('.', '[.]') for n, o in notifs.items()}
TRAPKEY = 'snmptrap["25597[.]|FE-FIREEYE-MIB|fe[A-Z]|trellixAlert|executionAnomaly|networkAnomaly|signatureMatch|ccConnect|ccSigmatch|osChange|ipsAlert"]'
MAXP = 240


def rx_parts(names):
    out = []
    for n in names:
        assert n in notifs, n
        out.append('%s([^A-Za-z0-9]|$)' % n)
        out.append('(^|[^0-9])%s([^0-9]|$)' % nums[n])
    return out


def chunks(names):
    res, cur = [], ''
    for p in rx_parts(names):
        cand = p if not cur else cur + '|' + p
        if len(cand) > MAXP and cur:
            res.append(cur)
            cur = p
        else:
            cur = cand
    res.append(cur)
    assert all(len(c) <= MAXP for c in res)
    return res


def expr_for(names):
    return ' or '.join('find(/%s/%s,#1,"regexp","%s")=1' % (T, TRAPKEY, c) for c in chunks(names))


PAIRS = [  # (title, problem notifications, recovery notifications, priority)
    ('Excessive temperature', ['feExcessiveTemperature'], ['feNormalTemperature'], 'HIGH'),
    ('RAID failure', ['feRaidFailure'], ['feRaidRecover'], 'HIGH'),
    ('Physical disk failure', ['fePhysicalDiskFailure'], ['fePhysicalDiskRecover'], 'HIGH'),
    ('Power supply failure', ['fePowerSupplyFailure'], ['fePowerSupplyRecover'], 'HIGH'),
    ('Fan failure', ['feFanFailure'], ['feFanRecover'], 'AVERAGE'),
    ('Token server unreachable', ['feTokenServerUnreachable'], ['feTokenServerReachable'], 'AVERAGE'),
    ('SMTP interface refusing connections', ['feSmtpInterfaceRefuseConnection'], ['feSmtpInterfaceRecover'], 'AVERAGE'),
    ('EMPS in bypass state', ['feEMPSBypassStateEntered'], ['feEMPSBypassStateExited'], 'AVERAGE'),
    ('Deployment check failed', ['feDeploymentCheckFailure'], ['feDeploymentCheckRecover'], 'AVERAGE'),
    ('Sizing threshold exceeded', ['feWMPSSizingThresholdExceeded'], ['feWMPSSizingThresholdNormal'], 'AVERAGE'),
]
MANUAL = [  # (title, notifications, priority)
    ('Threat detection (alert / anomaly / signature / callback)', ['trellixAlert', 'executionAnomaly', 'networkAnomaly', 'signatureMatch', 'ccConnect', 'ccSigmatch', 'osChange', 'ipsAlert', 'feMaliciousMaid'], 'AVERAGE'),
    ('Process crash', ['feProcessCrash'], 'HIGH'),
    ('CMS HA failover or NX health failure', ['feCMSHAUnexpectedFailover', 'feCMSHANxHealthFailure'], 'HIGH'),
    ('CMS HA manual failover', ['feCMSHAManualFailover'], 'WARNING'),
    ('CMS aggregation failure', ['feAggregationFailure'], 'AVERAGE'),
    ('MVX cluster state / utilisation / enrollment problem', ['feMVXClusterStateChanged', 'feMVXClusterUtilExceedThreshold', 'feMVXEnrollmentFailed'], 'AVERAGE'),
    ('Security content update failed', ['feSecurityUpdateFailed'], 'AVERAGE'),
    ('Guest image download failed', ['feGIDownloadFailureLowDiskSpace', 'feGIDownloadFailureGeneric'], 'AVERAGE'),
    ('Licence or token state changed / duplicate token', ['feLicenseStateChanged', 'feTokenStateChanged', 'feTokenDupeDetected'], 'AVERAGE'),
    ('Email queue / bypass threshold exceeded', ['feDeferredQueueThreshold', 'feBypassCountThreshold'], 'AVERAGE'),
    ('Hardware bypass entered / HTTP throughput not increasing', ['feHardwareBypassEntered', 'feHttpThroughputNotIncrease'], 'AVERAGE'),
    ('AVC overload / suggested max VM changed', ['feAvcOverloadStateEvent', 'feAvcSuggestedMaxVMEvent'], 'WARNING'),
    ('Interface link change / FaaS VPN change', ['feIfLinkChange', 'feFaasVpnConnectionChange'], 'WARNING'),
    ('Login / logout / syslog rotation / test trap', ['feLogin', 'feLogout', 'feSyslogRotation', 'feTestTrap'], 'INFO'),
]
covered = [n for _, p, r, _ in PAIRS for n in p + r] + [n for _, ns, _ in MANUAL for n in ns]
assert sorted(covered) == sorted(notifs), (set(notifs) ^ set(covered))
assert len(covered) == len(set(covered))
T_trigs = []
for title, p, r, prio in PAIRS:
    T_trigs.append(trig(T, expr_for(p), 'Trellix: ' + title, prio, 'Raised by %s; recovers automatically on %s.' % (', '.join(p), ', '.join(r)), 'trap', recovery=expr_for(r)))
for title, ns, prio in MANUAL:
    T_trigs.append(trig(T, expr_for(ns), 'Trellix: ' + title, prio, 'Notification(s): %s. No recovery notification exists; close manually after investigation.' % ', '.join(ns), 'trap', manual=True))
T_items = [
    item(T, 'SNMP traps: Trellix notifications', TRAPKEY, None, vt='LOG', itype='SNMP_TRAP', hist='30d', delay='0', tg=tags(component='traps'), triggers=T_trigs,
         desc='All FE-FIREEYE-MIB notifications (55, under %s). Matches numeric OIDs or MIB names, so it works with or without the MIB loaded in snmptrapd. Receiver setup is in the README.' % (ENT + BASE)),
    item(T, 'SNMP traps (fallback)', 'snmptrap.fallback', None, vt='LOG', itype='SNMP_TRAP', hist='7d', delay='0', tg=tags(component='traps'),
         desc='Traps from this host that match no snmptrap[] item.'),
]
for i in T_items:
    i.pop('trends', None)

doc = {'zabbix_export': {'version': '7.0', 'template_groups': [{'uuid': uid('group', GROUP), 'name': GROUP}], 'templates': [
    template(A, 'Trellix (FireEye) appliance by SNMP, built from FE-FIREEYE-MIB (1.3.6.1.4.1.25597): ICMP/SNMP availability, MIB-II system data, temperature, RAID/disks, power, fans, '
                'software/content/licence state, AVC, submission totals. Link to every NX/EX/FX/AX/CM-class appliance that answers SNMP. Not verified on a live appliance.',
             A_items, A_lld, A_macros, vms(A), tags(**{'class': 'security', 'target': 'trellix'})),
    template(C, 'Trellix Central Management (feCMS, 25597.12): attached-appliance counts and per-appliance disk/fan/PSU/RAID/temperature check results. Link in addition to "Trellix by SNMP" on CMS appliances.',
             C_items, C_lld, [], vms(C), tags(**{'class': 'security', 'target': 'trellix'})),
    template(E, 'Trellix email appliance (feEMPS, 25597.13): email/URL/attachment statistics and queue snapshots. Link in addition to "Trellix by SNMP" on email-analysis appliances.',
             E_items, None, E_macros, None, tags(**{'class': 'security', 'target': 'trellix'})),
    template(W, 'Trellix network appliance (feWMPS, 25597.14): deployment check, MVX sizing, traffic/flow loss, detection statistics by time span, alert/threat/file-type counts. Link in addition to "Trellix by SNMP" on network-analysis appliances.',
             W_items, W_lld, [], None, tags(**{'class': 'security', 'target': 'trellix'})),
    template(M, 'Trellix malware analysis (feMAS, 25597.15): analysed/malicious object, URL, file and live-mode counts. Link in addition to "Trellix by SNMP" on analysis appliances.',
             M_items, None, [], None, tags(**{'class': 'security', 'target': 'trellix'})),
    template(T, 'All 55 FE-FIREEYE-MIB notifications (25597.*) received as SNMP traps, with automatic recovery for failure/recover pairs. Needs snmptrapd + zabbix_trap_receiver and a host whose SNMP interface IP equals the trap source address. Link to every appliance.',
             T_items, None, [], None, tags(**{'class': 'security', 'target': 'trellix'})),
]}}
with open(OUT, 'w', encoding='utf-8') as f:
    yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False, allow_unicode=True, width=10000)
print('written', OUT)
