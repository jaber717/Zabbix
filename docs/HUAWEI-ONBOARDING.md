# Huawei onboarding

Zabbix 7.0.30 supplies the official **Huawei VRP by SNMP** template in its stock
database. Live API inspection found 12 direct items, five discovery rules,
18 item prototypes, and 13 trigger prototypes. Coverage includes ICMP/SNMP
availability, uptime, CPU, memory, temperature, fans, identity, software and
serial facts, and interface status/speed/traffic/errors/discards. Dedicated PSU
coverage was not proven; validate entity discovery on the actual chassis.

## 1. Prepare VRP

Restrict SNMP to the Zabbix poller address with a VRP ACL. Enable SNMPv3 only,
create a dedicated read-only group/view, and create a user interactively with
authPriv, SHA-256, and AES-128 when the VRP release supports them. Conceptually:

```text
snmp-agent
snmp-agent sys-info version v3
snmp-agent mib-view included <READ_VIEW> iso
snmp-agent group v3 <READ_GROUP> privacy read-view <READ_VIEW> acl <ACL_ID>
snmp-agent usm-user v3 <SNMPV3_USER> group <READ_GROUP>
snmp-agent usm-user v3 <SNMPV3_USER> authentication-mode sha2-256
snmp-agent usm-user v3 <SNMPV3_USER> privacy-mode aes128
```

VRP syntax varies by family/release. Use the device command reference and enter
passphrases only at protected interactive prompts. If SHA-256 is unavailable,
document and risk-accept the strongest supported fallback; do not silently
weaken all hosts.

## 2. Add the host

1. In Zabbix, create a host with the device management name and IP.
2. Add one SNMP interface on UDP/161 and select SNMPv3 authPriv.
3. Supply credential values through host macros such as `{$SNMPV3_USER}`,
   `{$SNMPV3_AUTH_PASSPHRASE}`, `{$SNMPV3_PRIV_PASSPHRASE}`,
   `{$SNMPV3_CONTEXT}`, and `{$SNMPV3_SECURITY_LEVEL}`. Keep values out of Git.
4. Choose SHA-256 and AES-128 and attach `Huawei VRP by SNMP`.
5. Wait for polling. In Data collection → Hosts → Discovery, open the host and
   use **Execute now** on `Network interfaces discovery` when immediate LLD is
   required. Its observed default interval is one hour.

Expected first results are ICMP/SNMP availability, identity and uptime, then MPU
CPU/memory, entity sensors, fans, and interfaces. Interface traffic and state
items normally appear after LLD and their next collection interval.

## 3. Control interface noise

The official template references these host-overridable filters:
`{$NET.IF.IFNAME.MATCHES}`, `{$NET.IF.IFNAME.NOT_MATCHES}`,
`{$NET.IF.IFALIAS.MATCHES}`, `{$NET.IF.IFALIAS.NOT_MATCHES}`,
`{$NET.IF.IFDESCR.MATCHES}`, `{$NET.IF.IFDESCR.NOT_MATCHES}`,
`{$NET.IF.IFADMINSTATUS.MATCHES}`, `{$NET.IF.IFOPERSTATUS.MATCHES}`, and
`{$NET.IF.IFTYPE.MATCHES}`. Use them to exclude shutdown access ports,
loopbacks, NULL interfaces, and irrelevant logical interfaces.

Use context overrides of `{$IFCONTROL}`, `{$IF.UTIL.MAX}`, and
`{$IF.ERRORS.WARN}` for named uplinks identified by a controlled alias pattern.
Do not classify every physical port as an uplink. Retain the stock sustained
trigger behavior rather than alerting on a single sample.

## 4. Diagnose

From the Zabbix server, run a bounded walk against a real device using protected
credential input (never command history), first for `sysUpTime.0`, then the
Huawei entity and interface subtrees. Confirm ACL, UDP/161 path, engine ID,
security name, auth/privacy protocols, context, and time synchronization. Review
unsupported item error text before changing a template.

Optical DDM, Eth-Trunk/LACP, BGP, and OSPF additions are **NOT IMPLEMENTED**.
Exact model-specific OIDs, MIB licensing, and real-device behavior were not
available to validate; guessed OIDs were deliberately rejected.
