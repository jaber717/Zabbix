"""The optional, fully owned Network Health templates (Zabbix 7.0 import format). UNTESTED.

Nothing here is imported or linked unless a device in config/network-health.<env>.yaml selects a feature
that needs it. Every alert is OFF at template level ({$NHEALTH.*.ON}=0) or only exists on hosts the
inventory links, so a template on its own changes nothing.

Separate from the Interface Alerting template: different template names, item keys (nhealth.*), macro
namespace ({$NHEALTH.*}) and ownership marker. Events carry the `netops_alert` tag so the existing
NETOPS-IaC e-mail action (filtered on that tag) delivers them without being changed.
"""
import hashlib
import json

TOOL_VERSION = "1.0.3"
MARKER = "managed_by=network-health-as-code"
MACRO_PREFIX = "{$NHEALTH."
GROUP = "Templates/Network devices"
GROUP_UUID = "36bff6c29af64692839d077febfc7079"      # stock uuid of this group in Zabbix 7.0

REACH = "NETOPS Health Reachability"
OSPF = "NETOPS Health OSPF (OSPF-MIB)"
BGP = "NETOPS Health BGP (BGP4-MIB)"
CPU_IOS = "NETOPS Health CPU-Memory Cisco IOS-XE"
CPU_NXOS = "NETOPS Health CPU-Memory Cisco NX-OS"
CPU_VRP = "NETOPS Health CPU-Memory Huawei VRP"
CPU_HR = "NETOPS Health CPU-Memory HOST-RESOURCES-MIB"
ALL = (REACH, OSPF, BGP, CPU_IOS, CPU_NXOS, CPU_VRP, CPU_HR)
PLATFORM_TEMPLATE = {"cisco-ios": CPU_IOS, "cisco-nxos": CPU_NXOS, "huawei-vrp": CPU_VRP, "host-resources": CPU_HR}

SEVS = (("warning", 2, "WARNING"), ("average", 3, "AVERAGE"), ("high", 4, "HIGH"), ("disaster", 5, "DISASTER"))
ICMP_KEY = "icmpping[,3,1000]"          # deliberately not the stock 'icmpping' key: no duplicate-key clash


def uuid_for(seed):
    h = list(hashlib.md5(("netops-health:" + seed).encode("utf-8")).hexdigest())
    h[12] = "4"
    h[16] = "89ab"[int(h[16], 16) % 4]
    return "".join(h)


def macro(name, value, desc):
    return {"macro": name, "value": value, "description": desc}


COMMON_MACROS = [
    macro("{$NHEALTH.POLL}", "1m", "Poll interval of Network Health SNMP/ICMP items."),
    macro("{$NHEALTH.SITE}", "", "Site label (event tag 'site'). Set per host from network-health yaml."),
]
CPU_MEM_MACROS = [
    macro("{$NHEALTH.CPU.ON}", "0", "CPU High alert: 1=on, 0=off (default off)."),
    macro("{$NHEALTH.CPU.SEV}", "4", "CPU High severity 2..5."),
    macro("{$NHEALTH.CPU.MAX}", "90", "CPU problem threshold, percent, sustained for CPU.WINDOW."),
    macro("{$NHEALTH.CPU.RECOVER}", "80", "CPU recovery threshold, percent."),
    macro("{$NHEALTH.CPU.WINDOW}", "5m", "CPU must stay above CPU.MAX for this long."),
    macro("{$NHEALTH.MEM.ON}", "0", "Memory High alert: 1=on, 0=off (default off)."),
    macro("{$NHEALTH.MEM.SEV}", "4", "Memory High severity 2..5."),
    macro("{$NHEALTH.MEM.MAX}", "90", "Memory problem threshold, percent, sustained for MEM.WINDOW."),
    macro("{$NHEALTH.MEM.RECOVER}", "85", "Memory recovery threshold, percent."),
    macro("{$NHEALTH.MEM.WINDOW}", "5m", "Memory must stay above MEM.MAX for this long."),
]


# --------------------------------------------------------------------------- building blocks

def _tags(alert, obj, descr, role, threshold="-"):
    return [{"tag": "netops_alert", "value": alert}, {"tag": "if_name", "value": obj},
            {"tag": "if_descr", "value": descr}, {"tag": "if_role", "value": role},
            {"tag": "link_id", "value": ""}, {"tag": "site", "value": "{$NHEALTH.SITE}"},
            {"tag": "direction", "value": "-"}, {"tag": "threshold", "value": threshold},
            {"tag": "component", "value": "network-health"}]


def _item(t, name, key, item_type, value_type="UNSIGNED", **kw):
    it = {"uuid": uuid_for("%s:item:%s" % (t, key)), "name": name, "type": item_type, "key": key,
          "value_type": value_type, "tags": [{"tag": "component", "value": "network-health"}]}
    if value_type != "TEXT":
        it.setdefault("history", "7d")
        it["trends"] = "0"
    it.update(kw)
    return it


def _walk(t, name, key, oids):
    return _item(t, name, key, "SNMP_AGENT", "TEXT", snmp_oid="walk[%s]" % ",".join(oids),
                 delay="{$NHEALTH.POLL}", history="0")


def _dep(t, name, key, master, oid, missing=None, value_type="UNSIGNED", units="", valuemap=None):
    step = {"type": "SNMP_WALK_VALUE", "parameters": [oid, "0"]}
    if missing is not None:                 # row gone from the table -> explicit value, not an error
        step["error_handler"] = "CUSTOM_VALUE"
        step["error_handler_params"] = missing
    it = _item(t, name, key, "DEPENDENT", value_type, master_item={"key": master}, preprocessing=[step])
    if units:
        it["units"] = units
    if valuemap:
        it["valuemap"] = {"name": valuemap}
    return it


def _lld(t, name, key, master, fields, conditions=None):
    params = []
    for macro_name, oid in fields:
        params += [macro_name, oid, "0"]
    rule = {"uuid": uuid_for("%s:lld:%s" % (t, key)), "name": name, "type": "DEPENDENT", "key": key,
            "master_item": {"key": master},
            "preprocessing": [{"type": "SNMP_WALK_TO_JSON", "parameters": params}],
            # a neighbor that vanishes keeps its (enabled) item for 7 days, so "gone" is alerted, not deleted
            "lifetime_type": "DELETE_AFTER", "lifetime": "7d", "enabled_lifetime_type": "DISABLE_NEVER",
            "item_prototypes": [], "trigger_prototypes": []}
    if conditions:
        rule["filter"] = {"evaltype": "AND", "conditions": [
            {"macro": m, "value": v, "operator": "MATCHES_REGEX", "formulaid": chr(65 + i)}
            for i, (m, v) in enumerate(conditions)]}
    return rule


def _triggers(t, ident, name, sev_macro, expr, recovery, opdata, tags, desc):
    """Four severity variants; exactly one can fire, chosen by the value of sev_macro (2..5)."""
    out = []
    for sname, prio, label in SEVS:
        tr = {"uuid": uuid_for("%s:trigger:%s:%s" % (t, ident, sname)), "name": name, "event_name": name,
              "opdata": opdata, "expression": "%s=%d and %s" % (sev_macro, prio, expr), "priority": label,
              "description": desc, "manual_close": "YES",
              "tags": tags + [{"tag": "severity_label", "value": sname}]}
        if recovery:
            tr["recovery_mode"] = "RECOVERY_EXPRESSION"
            tr["recovery_expression"] = recovery
        out.append(tr)
    return out


def _ref(t, key):
    return "/%s/%s" % (t, key)


def _cpu_triggers(t, key, obj):
    k = _ref(t, key)
    return _triggers(t, "cpu:" + key, "{HOST.NAME} CPU HIGH %s > {$NHEALTH.CPU.MAX}%%" % obj, "{$NHEALTH.CPU.SEV}",
                     "{$NHEALTH.CPU.ON}=1 and min(%s,{$NHEALTH.CPU.WINDOW})>{$NHEALTH.CPU.MAX}" % k,
                     "last(%s)<{$NHEALTH.CPU.RECOVER}" % k, "CPU {ITEM.LASTVALUE1}",
                     _tags("cpu_high", obj, "CPU utilization", "HEALTH", "{$NHEALTH.CPU.MAX}"),
                     "CPU above CPU.MAX for the whole CPU.WINDOW; recovers below CPU.RECOVER.")


def _mem_triggers(t, key, obj):
    k = _ref(t, key)
    return _triggers(t, "mem:" + key, "{HOST.NAME} Memory HIGH %s > {$NHEALTH.MEM.MAX}%%" % obj, "{$NHEALTH.MEM.SEV}",
                     "{$NHEALTH.MEM.ON}=1 and min(%s,{$NHEALTH.MEM.WINDOW})>{$NHEALTH.MEM.MAX}" % k,
                     "last(%s)<{$NHEALTH.MEM.RECOVER}" % k, "Memory {ITEM.LASTVALUE1}",
                     _tags("memory_high", obj, "Memory utilization", "HEALTH", "{$NHEALTH.MEM.MAX}"),
                     "Memory above MEM.MAX for the whole MEM.WINDOW; recovers below MEM.RECOVER.")


def _pct(t, name, key, part_key, whole_formula):
    return _item(t, name, key, "CALCULATED", "FLOAT", delay="{$NHEALTH.POLL}", units="%",
                 params="100*last(//%s)/(%s)" % (part_key, whole_formula))


# --------------------------------------------------------------------------- templates

def _reachability():
    t = REACH
    items = [
        _item(t, "ICMP reachability (3 packets)", ICMP_KEY, "SIMPLE", delay="{$NHEALTH.POLL}",
              valuemap={"name": "NHEALTH ICMP"}),
        _item(t, "SNMP sysUpTime", "nhealth.snmp.uptime", "SNMP_AGENT", "FLOAT", snmp_oid="1.3.6.1.2.1.1.3.0",
              delay="{$NHEALTH.POLL}", units="uptime",
              preprocessing=[{"type": "MULTIPLIER", "parameters": ["0.01"]}]),
    ]
    icmp, up = _ref(t, ICMP_KEY), _ref(t, "nhealth.snmp.uptime")
    trig = _triggers(t, "unreachable", "{HOST.NAME} Device UNREACHABLE (ICMP)", "{$NHEALTH.UNREACH.SEV}",
                     "{$NHEALTH.UNREACH.ON}=1 and max(%s,{$NHEALTH.UNREACH.WINDOW})=0" % icmp,
                     "last(%s)=1" % icmp, "ping {ITEM.LASTVALUE1}",
                     _tags("device_unreachable", "{HOST.NAME}", "ICMP", "HEALTH"),
                     "No ICMP reply for the whole UNREACH.WINDOW. Needs fping on the Zabbix server/proxy.")
    # Stale: SNMP silent while the device still answers ping (or ping alerting is off), so a device outage
    # raises only 'Device UNREACHABLE', never both. Recovers when SNMP data returns.
    trig += _triggers(t, "stale", "{HOST.NAME} SNMP data STALE", "{$NHEALTH.STALE.SEV}",
                      "{$NHEALTH.STALE.ON}=1 and nodata(%s,{$NHEALTH.STALE.TIMEOUT})=1 and "
                      "({$NHEALTH.UNREACH.ON}=0 or max(%s,{$NHEALTH.STALE.TIMEOUT})=1)" % (up, icmp),
                      None, "", _tags("snmp_stale", "{HOST.NAME}", "SNMP", "HEALTH", "{$NHEALTH.STALE.TIMEOUT}"),
                      "No SNMP value (sysUpTime) for STALE.TIMEOUT.")
    macros = COMMON_MACROS + [
        macro("{$NHEALTH.UNREACH.ON}", "0", "Device Unreachable alert: 1=on, 0=off (default off)."),
        macro("{$NHEALTH.UNREACH.SEV}", "5", "Device Unreachable severity 2..5."),
        macro("{$NHEALTH.UNREACH.WINDOW}", "3m", "All pings must fail for this long."),
        macro("{$NHEALTH.STALE.ON}", "0", "SNMP Data Stale alert: 1=on, 0=off (default off)."),
        macro("{$NHEALTH.STALE.SEV}", "4", "SNMP Data Stale severity 2..5."),
        macro("{$NHEALTH.STALE.TIMEOUT}", "5m", "No SNMP data for this long = stale."),
    ]
    vmaps = [("NHEALTH ICMP", [("0", "No reply"), ("1", "Reachable")])]
    return t, items, [], trig, macros, vmaps, "Device Unreachable (ICMP) and SNMP Data Stale. Vendor-neutral."


NBR_MACROS = [
    macro("{$NHEALTH.NBR.DOWN.TIME}", "2m", "Neighbor/peer must stay not-established for this long."),
    macro("{$NHEALTH.NBR.LOOKBACK}", "24h", "Alert only if the neighbor/peer was established within this period."),
]


def _ospf():
    t, w = OSPF, "nhealth.ospf.walk"
    # ospfRouterId (scalar) keeps the walk non-empty when the neighbor table is empty
    items = [_walk(t, "OSPF: neighbor table walk", w, ["1.3.6.1.2.1.14.1.1", "1.3.6.1.2.1.14.10.1.1",
                                                       "1.3.6.1.2.1.14.10.1.3", "1.3.6.1.2.1.14.10.1.6"])]
    rule = _lld(t, "OSPF neighbor discovery", "nhealth.ospf.discovery", w,
                [("{#NH_NBR_IP}", "1.3.6.1.2.1.14.10.1.1"), ("{#NH_NBR_RTRID}", "1.3.6.1.2.1.14.10.1.3")])
    key = "nhealth.ospf.state[{#SNMPINDEX}]"
    rule["item_prototypes"].append(_dep(t, "OSPF neighbor {#NH_NBR_RTRID} ({#NH_NBR_IP}): state", key, w,
                                        "1.3.6.1.2.1.14.10.1.6.{#SNMPINDEX}", missing="0",
                                        valuemap="NHEALTH OSPF neighbor state"))
    k = _ref(t, key)
    rule["trigger_prototypes"] = _triggers(
        t, "ospf", "{HOST.NAME} OSPF neighbor {#NH_NBR_RTRID} ({#NH_NBR_IP}) DOWN", "{$NHEALTH.OSPF.SEV}",
        "max(%s,{$NHEALTH.NBR.DOWN.TIME})<8 and count(%s,{$NHEALTH.NBR.LOOKBACK},\"eq\",\"8\")>0 and "
        "{$NHEALTH.OSPF.ALERT:\"{#NH_NBR_RTRID}\"}=1" % (k, k),
        "last(%s)=8" % k, "state {ITEM.LASTVALUE1}",
        _tags("ospf_neighbor", "OSPF {#NH_NBR_IP}", "router-id {#NH_NBR_RTRID}", "OSPF"),
        "Adjacency was Full within NBR.LOOKBACK and has not been Full for NBR.DOWN.TIME (includes the neighbor "
        "disappearing from ospfNbrTable = state 0). Never-Full neighbors (e.g. DROTHER 2-Way) never alert. "
        "Recovers when the state is Full again.")
    macros = COMMON_MACROS + NBR_MACROS + [
        macro("{$NHEALTH.OSPF.SEV}", "4", "OSPF Neighbor Down severity 2..5."),
        macro("{$NHEALTH.OSPF.ALERT}", "1", "Per-neighbor switch, context = neighbor router-id. 0 = do not alert."),
    ]
    vmaps = [("NHEALTH OSPF neighbor state", [("0", "Not in neighbor table"), ("1", "Down"), ("2", "Attempt"),
                                              ("3", "Init"), ("4", "Two-way"), ("5", "ExStart"),
                                              ("6", "Exchange"), ("7", "Loading"), ("8", "Full")])]
    return t, items, [rule], [], macros, vmaps, "OSPFv2 neighbor Down/Recovery from OSPF-MIB (RFC 1850/4750) ospfNbrTable."


def _bgp():
    t, w = BGP, "nhealth.bgp.walk"
    items = [_walk(t, "BGP: peer table walk", w, ["1.3.6.1.2.1.15.2", "1.3.6.1.2.1.15.3.1.2", "1.3.6.1.2.1.15.3.1.3",
                                                  "1.3.6.1.2.1.15.3.1.7", "1.3.6.1.2.1.15.3.1.9"])]
    rule = _lld(t, "BGP peer discovery", "nhealth.bgp.discovery", w,
                [("{#NH_PEER}", "1.3.6.1.2.1.15.3.1.7"), ("{#NH_PEER_AS}", "1.3.6.1.2.1.15.3.1.9")])
    sk, ak = "nhealth.bgp.state[{#SNMPINDEX}]", "nhealth.bgp.admin[{#SNMPINDEX}]"
    rule["item_prototypes"] += [
        _dep(t, "BGP peer {#NH_PEER} AS{#NH_PEER_AS}: state", sk, w, "1.3.6.1.2.1.15.3.1.2.{#SNMPINDEX}",
             missing="0", valuemap="NHEALTH BGP peer state"),
        _dep(t, "BGP peer {#NH_PEER} AS{#NH_PEER_AS}: admin status", ak, w, "1.3.6.1.2.1.15.3.1.3.{#SNMPINDEX}",
             missing="0", valuemap="NHEALTH BGP admin status"),
    ]
    s, a = _ref(t, sk), _ref(t, ak)
    rule["trigger_prototypes"] = _triggers(
        t, "bgp", "{HOST.NAME} BGP peer {#NH_PEER} (AS{#NH_PEER_AS}) DOWN", "{$NHEALTH.BGP.SEV}",
        "max(%s,{$NHEALTH.NBR.DOWN.TIME})<6 and count(%s,{$NHEALTH.NBR.LOOKBACK},\"eq\",\"6\")>0 and last(%s)<>1 and "
        "{$NHEALTH.BGP.ALERT:\"{#NH_PEER}\"}=1" % (s, s, a),
        "last(%s)=6" % s, "state {ITEM.LASTVALUE1}",
        _tags("bgp_peer", "BGP {#NH_PEER}", "AS{#NH_PEER_AS}", "BGP"),
        "Session was Established within NBR.LOOKBACK and has not been Established for NBR.DOWN.TIME. "
        "Administratively stopped peers (bgpPeerAdminStatus=stop) do not alert. Recovers on Established.")
    macros = COMMON_MACROS + NBR_MACROS + [
        macro("{$NHEALTH.BGP.SEV}", "4", "BGP Peer Down severity 2..5."),
        macro("{$NHEALTH.BGP.ALERT}", "1", "Per-peer switch, context = peer address. 0 = do not alert."),
    ]
    vmaps = [("NHEALTH BGP peer state", [("0", "Not in peer table"), ("1", "Idle"), ("2", "Connect"),
                                         ("3", "Active"), ("4", "OpenSent"), ("5", "OpenConfirm"),
                                         ("6", "Established")]),
             ("NHEALTH BGP admin status", [("0", "Not in peer table"), ("1", "Stop"), ("2", "Start")])]
    return t, items, [rule], [], macros, vmaps, "BGP-4 peer Down/Recovery from BGP4-MIB (RFC 4273) bgpPeerTable, IPv4 peers."


def _cpu_ios():
    t = CPU_IOS
    cw, mw = "nhealth.cpu.walk", "nhealth.mem.walk"
    items = [_walk(t, "CPU table walk (CISCO-PROCESS-MIB)", cw, ["1.3.6.1.4.1.9.9.109.1.1.1.1.2",
                                                                 "1.3.6.1.4.1.9.9.109.1.1.1.1.7"]),
             _walk(t, "Memory pool walk (CISCO-ENHANCED-MEMPOOL-MIB)", mw, ["1.3.6.1.4.1.9.9.221.1.1.1.1.3",
                                                                            "1.3.6.1.4.1.9.9.221.1.1.1.1.18",
                                                                            "1.3.6.1.4.1.9.9.221.1.1.1.1.20"])]
    cpu = _lld(t, "CPU discovery", "nhealth.cpu.discovery", cw, [("{#NH_CPU_PHYS}", "1.3.6.1.4.1.9.9.109.1.1.1.1.2")])
    ck = "nhealth.cpu.util[{#SNMPINDEX}]"
    cpu["item_prototypes"].append(_dep(t, "CPU {#SNMPINDEX}: utilization (1 min)", ck, cw,
                                       "1.3.6.1.4.1.9.9.109.1.1.1.1.7.{#SNMPINDEX}", units="%"))
    cpu["trigger_prototypes"] = _cpu_triggers(t, ck, "CPU {#SNMPINDEX}")
    mem = _lld(t, "Memory pool discovery", "nhealth.mem.discovery", mw,
               [("{#NH_POOL}", "1.3.6.1.4.1.9.9.221.1.1.1.1.3")],
               [("{#NH_POOL}", "{$NHEALTH.CISCO.MEMPOOL.MATCHES}")])
    uk, fk, pk = "nhealth.mem.used[{#SNMPINDEX}]", "nhealth.mem.free[{#SNMPINDEX}]", "nhealth.mem.util[{#SNMPINDEX}]"
    mem["item_prototypes"] += [
        _dep(t, "Memory {#NH_POOL}: used", uk, mw, "1.3.6.1.4.1.9.9.221.1.1.1.1.18.{#SNMPINDEX}", units="B"),
        _dep(t, "Memory {#NH_POOL}: free", fk, mw, "1.3.6.1.4.1.9.9.221.1.1.1.1.20.{#SNMPINDEX}", units="B"),
        _pct(t, "Memory {#NH_POOL}: utilization", pk, uk, "last(//%s)+last(//%s)" % (uk, fk)),
    ]
    mem["trigger_prototypes"] = _mem_triggers(t, pk, "pool {#NH_POOL}")
    macros = COMMON_MACROS + CPU_MEM_MACROS + [
        macro("{$NHEALTH.CISCO.MEMPOOL.MATCHES}", "^Processor$", "Memory pools to monitor (regex on pool name).")]
    return t, items, [cpu, mem], [], macros, [], "CPU (cpmCPUTotal1minRev) and memory (cempMemPoolHCUsed/HCFree) for Cisco IOS/IOS-XE."


def _cpu_nxos():
    t = CPU_NXOS
    items = [_item(t, "CPU utilization (cseSysCPUUtilization)", "nhealth.cpu.util", "SNMP_AGENT",
                   snmp_oid="1.3.6.1.4.1.9.9.305.1.1.1.0", delay="{$NHEALTH.POLL}", units="%"),
             _item(t, "Memory utilization (cseSysMemoryUtilization)", "nhealth.mem.util", "SNMP_AGENT",
                   snmp_oid="1.3.6.1.4.1.9.9.305.1.1.2.0", delay="{$NHEALTH.POLL}", units="%")]
    trig = _cpu_triggers(t, "nhealth.cpu.util", "system") + _mem_triggers(t, "nhealth.mem.util", "system")
    return t, items, [], trig, COMMON_MACROS + CPU_MEM_MACROS, [], "CPU and memory for Cisco NX-OS (CISCO-SYSTEM-EXT-MIB)."


def _cpu_vrp():
    t, w = CPU_VRP, "nhealth.entity.walk"
    base = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1"
    items = [_walk(t, "Entity CPU/memory walk (HUAWEI-ENTITY-EXTENT-MIB)", w,
                   ["1.3.6.1.2.1.47.1.1.1.1.7", base + ".5", base + ".7"])]
    rule = _lld(t, "Board discovery", "nhealth.entity.discovery", w,
                [("{#NH_ENT}", "1.3.6.1.2.1.47.1.1.1.1.7"), ("{#NH_ENT_MEM}", base + ".7")],
                [("{#NH_ENT_MEM}", "^[1-9][0-9]*$"), ("{#NH_ENT}", "{$NHEALTH.HUAWEI.ENTITY.MATCHES}")])
    ck, mk = "nhealth.cpu.util[{#SNMPINDEX}]", "nhealth.mem.util[{#SNMPINDEX}]"
    rule["item_prototypes"] += [
        _dep(t, "{#NH_ENT}: CPU utilization", ck, w, base + ".5.{#SNMPINDEX}", units="%"),
        _dep(t, "{#NH_ENT}: memory utilization", mk, w, base + ".7.{#SNMPINDEX}", units="%"),
    ]
    rule["trigger_prototypes"] = _cpu_triggers(t, ck, "{#NH_ENT}") + _mem_triggers(t, mk, "{#NH_ENT}")
    macros = COMMON_MACROS + CPU_MEM_MACROS + [
        macro("{$NHEALTH.HUAWEI.ENTITY.MATCHES}", ".*", "Boards to monitor (regex on entPhysicalName).")]
    return t, items, [rule], [], macros, [], "CPU and memory per board for Huawei VRP (hwEntityCpuUsage/hwEntityMemUsage)."


def _cpu_hr():
    t, cw, mw = CPU_HR, "nhealth.cpu.walk", "nhealth.mem.walk"
    items = [_walk(t, "Processor walk (HOST-RESOURCES-MIB)", cw, ["1.3.6.1.2.1.25.3.3.1.2"]),
             _walk(t, "Storage walk (HOST-RESOURCES-MIB)", mw, ["1.3.6.1.2.1.25.2.3.1.2", "1.3.6.1.2.1.25.2.3.1.3",
                                                                "1.3.6.1.2.1.25.2.3.1.5", "1.3.6.1.2.1.25.2.3.1.6"])]
    cpu = _lld(t, "Processor discovery", "nhealth.cpu.discovery", cw, [("{#NH_CPU_LOAD}", "1.3.6.1.2.1.25.3.3.1.2")])
    ck = "nhealth.cpu.util[{#SNMPINDEX}]"
    cpu["item_prototypes"].append(_dep(t, "Processor {#SNMPINDEX}: load", ck, cw, "1.3.6.1.2.1.25.3.3.1.2.{#SNMPINDEX}",
                                       units="%"))
    cpu["trigger_prototypes"] = _cpu_triggers(t, ck, "processor {#SNMPINDEX}")
    mem = _lld(t, "RAM discovery", "nhealth.mem.discovery", mw,
               [("{#NH_STYPE}", "1.3.6.1.2.1.25.2.3.1.2"), ("{#NH_SDESCR}", "1.3.6.1.2.1.25.2.3.1.3")],
               [("{#NH_STYPE}", "(1\\.3\\.6\\.1\\.2\\.1\\.25\\.2\\.1\\.2|hrStorageRam)$"),
                ("{#NH_SDESCR}", "{$NHEALTH.HR.MEM.MATCHES}")])
    sk, uk, pk = "nhealth.mem.size[{#SNMPINDEX}]", "nhealth.mem.used[{#SNMPINDEX}]", "nhealth.mem.util[{#SNMPINDEX}]"
    mem["item_prototypes"] += [
        _dep(t, "{#NH_SDESCR}: size (units)", sk, mw, "1.3.6.1.2.1.25.2.3.1.5.{#SNMPINDEX}"),
        _dep(t, "{#NH_SDESCR}: used (units)", uk, mw, "1.3.6.1.2.1.25.2.3.1.6.{#SNMPINDEX}"),
        _pct(t, "{#NH_SDESCR}: utilization", pk, uk, "last(//%s)" % sk),
    ]
    mem["trigger_prototypes"] = _mem_triggers(t, pk, "{#NH_SDESCR}")
    macros = COMMON_MACROS + CPU_MEM_MACROS + [
        macro("{$NHEALTH.HR.MEM.MATCHES}", ".*", "RAM storage entries to monitor (regex on hrStorageDescr).")]
    return t, items, [cpu, mem], [], macros, [], "CPU and RAM from HOST-RESOURCES-MIB (hrProcessorLoad, hrStorageRam)."


BUILDERS = {REACH: _reachability, OSPF: _ospf, BGP: _bgp, CPU_IOS: _cpu_ios, CPU_NXOS: _cpu_nxos,
            CPU_VRP: _cpu_vrp, CPU_HR: _cpu_hr}


def _payload(name, tpl_hash):
    t, items, rules, triggers, macros, vmaps, summary = BUILDERS[name]()
    doc = {"zabbix_export": {
        "version": "7.0",
        "template_groups": [{"uuid": GROUP_UUID, "name": GROUP}],
        "templates": [{
            "uuid": uuid_for("template:" + t), "template": t, "name": t,
            "description": "%s. UNTESTED (v%s). %s version=%s hash=%s" % (summary, TOOL_VERSION, MARKER,
                                                                         TOOL_VERSION, tpl_hash),
            "groups": [{"name": GROUP}], "items": items, "discovery_rules": rules,
            "macros": macros,
            "valuemaps": [{"uuid": uuid_for("%s:valuemap:%s" % (t, vn)), "name": vn,
                           "mappings": [{"value": v, "newvalue": nv} for v, nv in maps]} for vn, maps in vmaps],
        }],
    }}
    if triggers:
        doc["zabbix_export"]["triggers"] = triggers
    return doc


def content_hash(name):
    blob = json.dumps(_payload(name, ""), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def build(name):
    return _payload(name, content_hash(name))


IMPORT_RULES = {
    "template_groups": {"createMissing": True, "updateExisting": False},
    "templates": {"createMissing": True, "updateExisting": True},
    "items": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "triggers": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "discoveryRules": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "valueMaps": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
}


def templates_for(device):
    """Template names a device needs, from its selected features."""
    f = device["features"]
    out = set()
    if "device_unreachable" in f or "snmp_stale" in f:
        out.add(REACH)
    if "ospf" in f:
        out.add(OSPF)
    if "bgp" in f:
        out.add(BGP)
    if "cpu" in f or "memory" in f:
        out.add(PLATFORM_TEMPLATE[device["platform"]])
    return out
