# Zabbix current state

Captured read-only on 2026-10-07 (Asia/Riyadh).

## Installation and access

| Field | Verified value |
|---|---|
| Zabbix version | 7.0.30 |
| Server OS hostname | `netbox-dev` |
| Frontend title | `ZABBIX-01: Zabbix` |
| Frontend | `https://192.168.1.91:8443/` |
| API | `https://192.168.1.91:8443/api_jsonrpc.php` |
| Zabbix server package | `zabbix-server-pgsql-7.0.30-release1.el9` |
| Frontend package | `zabbix-web-pgsql-7.0.30-release1.el9` |
| PHP | 8.3.19 |
| Services | `zabbix-server`, `nginx`, `php-fpm`, and `postgresql` active |

The normal integration credential is the least-privileged `nbzsync` account. Its password is referenced by `/etc/credstore.encrypted/nbzsync-zabbix-password` on the Zabbix VM and by `C:\Users\jaber\.config\netops\claude-access\claude-access.env` on the controller. No API token is currently populated in that bundle. The `nbzsync` role can read hosts but cannot read discovery rules/actions. Read-only template discovery for this handover used the protected retired administrator credential locally on the VM; its value was never copied or printed.

## Current host/template inventory

| Template | ID | Current hosts | Phase-1 relevance |
|---|---:|---|---|
| Cisco IOS by SNMP | 10218 | 7 live WAN-LAB routers | Authoritative phase-1 template |
| Cisco Nexus 9000 Series by SNMP | 10551 | DR-LEAF01, DR-LEAF02 | Mock DCIM objects; fake/non-routable addresses; not phase 1 |
| FortiGate by SNMP | 10604 | DR-FW01 | Mock DCIM object; not phase 1 |
| F5 Big-IP by SNMP | 10419 | DR-LB01 | Mock DCIM object; not phase 1 |

There is no Zabbix host for `SAIX-CORE` or `PALO-LAB`. No Huawei host/template is attached in the current host inventory. The four `DR-*` hosts are intentional mock objects and their SNMP unavailability is expected.

## Cisco IOS interface discovery

- Rule: `Network interfaces discovery`
- Discovery-rule ID: `40652`
- Key: `net.if.discovery`
- Master walk item: `Cisco IOS: SNMP walk network interfaces`
- Master key: `net.if.walk`
- Master interval: `1m`
- Discovery macros used by the live rule/filter: `{#IFADMINSTATUS}`, `{#IFALIAS}`, `{#IFDESCR}`, `{#IFNAME}`, `{#IFOPERSTATUS}`, `{#IFTYPE}`, and `{#SNMPINDEX}` in item keys.
- Default exclusion: administratively down (`ifAdminStatus=2`), not-present interfaces, loopbacks, null/system and common virtual interfaces.
- Stable selector for this lab: exact `{#IFNAME}` plus Zabbix host. The current IOSv names are `Gi0/x`; do not substitute the device CLI's expanded `GigabitEthernet0/x` in machine input.

### Interface item prototypes

| Metric | Prototype/key | Source and preprocessing | Effective cadence |
|---|---|---|---|
| Operational status | `net.if.status[ifOperStatus.{#SNMPINDEX}]` | IF-MIB `ifOperStatus` | one-minute master walk |
| Inbound traffic | `net.if.in[ifHCInOctets.{#SNMPINDEX}]` | 64-bit `ifHCInOctets`, change/sec, multiply by 8, unit bps | one-minute master walk |
| Outbound traffic | `net.if.out[ifHCOutOctets.{#SNMPINDEX}]` | 64-bit `ifHCOutOctets`, change/sec, multiply by 8, unit bps | one-minute master walk |
| Speed | `net.if.speed[ifHighSpeed.{#SNMPINDEX}]` | `ifHighSpeed`, multiply by 1,000,000, unit bps | source polled each minute; unchanged value throttled for 1h |
| In errors | `net.if.in.errors[ifInErrors.{#SNMPINDEX}]` | counter delta; unchanged value throttled for 3m | one-minute source |
| Out errors | `net.if.out.errors[ifOutErrors.{#SNMPINDEX}]` | counter delta; unchanged value throttled for 3m | one-minute source |
| In discards | `net.if.in.discards[ifInDiscards.{#SNMPINDEX}]` | counter delta; unchanged value throttled for 3m | one-minute source |
| Out discards | `net.if.out.discards[ifOutDiscards.{#SNMPINDEX}]` | counter delta; unchanged value throttled for 3m | one-minute source |

The traffic items are already rates in **bits per second**. Claude must not apply a second octet-to-bit or counter-rate conversion. `ifHighSpeed` avoids the 32-bit `ifSpeed` ceiling for interfaces above 4.294 Gbps; the current IOSv interfaces are nominal 1 Gbps.

### Existing trigger prototypes

| Prototype | ID | Current default |
|---|---:|---|
| Link down | 21645 | Average severity; gated by contextual `{$IFCONTROL:"{#IFNAME}"}`; default `{$IFCONTROL}=1` |
| High bandwidth usage | 21643 | Warning; `{$IF.UTIL.MAX}=90`; recovery is threshold minus 3 percentage points |
| High error rate | 21644 | Warning; `{$IF.ERRORS.WARN}=2`; 80% recovery expression |
| Lower Ethernet speed | 21642 | Information |
| Half-duplex | 21646 | Warning |

There is no separate discard trigger prototype in the stock Cisco IOS template. The discard items exist and can be reused by the new framework. A 70%/65% utilization policy therefore requires an explicit interface policy/context override or dedicated trigger implementation; it is not the current stock 90%/87% behavior.

## All discovered interfaces versus selected interfaces

The seven monitored WAN routers currently have **27** discovered operational-status items:

- Selected routed P2P objects: 18.
- Excluded OOB management objects: 8 (`SITE-A` has both stale `Gi0/5` and active `Gi0/7`; the other routers expose one OOB interface each).
- Excluded non-infrastructure endpoint: `INT-CORE Gi0/2`, description `TO-INTERNET-ENDPOINT`, currently down/down on a `/24` endpoint segment.

The 18 selected names in `p2p-interfaces.yaml` were cross-checked against both the live Zabbix item names and current router interface/BGP state.

## Current SNMP state

All seven monitored routers are configured in Zabbix as SNMPv3, bulk enabled, security level `authPriv`. The credential bundle declares SHA authentication and AES-128 privacy, with the Zabbix server as the intended source. Secret values remain only in the existing protected bundle/credential mechanisms.

At capture time all seven Zabbix SNMP interfaces were unavailable with the same explicit error: authentication failure (incorrect password, community, or key). The routers had restarted only minutes before live verification. This is a current blocker for fresh item values and alert validation; it does not invalidate the already-created item identities or the device-side interface/BGP verification. Do not silently change SNMP credentials—reconcile the router startup configuration and Zabbix macros deliberately before implementation validation.

## SNMP traps

Status: **NOT READY**.

- `snmptrapd` is inactive and the `net-snmp` packages are not installed on the Zabbix VM.
- No `StartSNMPTrapper` or `SNMPTrapperFile` configuration is present.
- Nothing is listening on UDP/162.
- firewalld is active and does not permit UDP/162.
- Checked router configurations contain no proven trap destination/enable configuration for this Zabbix server.

Claude would need a separately approved trap design: install/configure the receiver, configure the Zabbix trapper/file, open only the required source-restricted UDP/162 path, create trap items, and configure routers. None of that was changed in this handover.

## Actions and media

- Problem action `Report problems to Zabbix administrators` (action ID 3) exists but is **disabled**. It has no event filter, targets user group ID 7, and includes recovery notifications.
- Default Email and Email (HTML) media types are **disabled** and still carry example SMTP values.
- Other packaged media types are also disabled.

Existing notification infrastructure is therefore **not immediately reusable**. A dedicated, tag-filtered Interface Alerting action is cleaner once the operator supplies and validates a real media type and recipient group. Do not enable the broad existing action without narrowing its filters.
