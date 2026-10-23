# Network Health Alerting (v1.0.3) — **UNTESTED**

> **Status: UNTESTED.** Written without access to any Zabbix, LAB or Production system. No unit, integration,
> LAB or Production test has been run for Network Health. Not Production-ready. Validate in LAB first (section 8).

Second, independent component of the same project and release. Interface Alerting (`apply.sh`,
`config/interfaces.<env>.yaml`) is unchanged and does not read anything below.

| | Interface Alerting (v1.0.2, unchanged) | Network Health (new, v1.0.3) |
|---|---|---|
| Inventory | `config/interfaces.<env>.yaml` | `config/network-health.<env>.yaml` |
| Command | `./apply.sh` | `./apply-health.sh` |
| Alerts | link down/up, utilization, errors, discards, flapping, speed | OSPF neighbor, BGP peer, device unreachable, CPU, memory, SNMP stale |
| Owns | template `NETOPS Interface Alerting`, `{$NETOPS.*}` host macros, action `NETOPS-IaC …` | templates `NETOPS Health …`, `{$NHEALTH.*}` host macros |
| Ownership marker | `managed_by=zabbix-alerting-as-code` | `managed_by=network-health-as-code` |
| Item keys | `netops.if.*` | `nhealth.*`, `icmpping[,3,1000]` |

## 1. Disabled by default

* `config/network-health.production.yaml` ships as `devices: {}`. With an empty file the tool imports, links and changes nothing.
* Upgrading to v1.0.3 and running `./apply.sh` never touches Network Health. Only `./apply-health.sh` does, and only for devices you list.
* Each template also keeps its alerts off by default (`{$NHEALTH.*.ON}=0`). A template only reaches a host when that host selects a feature that needs it.

## 2. Coexistence with Interface Alerting (same host in both files)

* Different template names, item keys, LLD rules and macro namespaces, so there are no duplicate keys and no shared triggers.
* Each tool deletes only macros with its own marker and its own prefix. `apply.sh` ignores `{$NHEALTH.*}`, and `apply-health.sh` ignores `{$NETOPS.*}`.
* Unlinking uses `templateids_clear` for the tool's own templates only. Stock templates and the other tool's template stay linked.
* Both use the same `config/environments/<env>.yaml`, `.env`, identity macro and `--confirm production` gate. `apply-health.sh` never creates the identity macro: claim the server once with `./apply.sh --env production --init-identity --confirm production`.
* **Not a duplicate, but note:** stock vendor templates may already poll CPU/memory or ping the host under their own keys and triggers. Those stay active, so double alerting depends on your existing actions (same as review finding L1).

## 3. E-mail notification (existing setup reused, nothing changed)

Every Network Health event carries the event tag `netops_alert` (values `ospf_neighbor`, `bgp_peer`, `device_unreachable`,
`snmp_stale`, `cpu_high`, `memory_high`). The existing **NETOPS-IaC Interface Alerts** action filters on that tag name,
so it sends Problem and Recovery e-mails through the configured Production Email media type and user group. No action, media
type or user is created or changed. The e-mail fields map as follows: Interface = object (e.g. `OSPF 10.0.0.2`),
Description = router-id / AS / metric, Role = `OSPF` / `BGP` / `HEALTH`, Site = `site:` from the inventory.
If that action is not configured (`alert_action` unset), events still appear in Zabbix and reach any other action whose conditions match.

## 4. Inventory format

```yaml
defaults:                         # optional; changes settings, never enables a feature
  bgp: {severity: disaster}

devices:
  EDGE-RTR-01:                    # exact Zabbix technical Host name
    site: DC1
    platform: cisco-ios           # required only for cpu/memory
    device_unreachable: {severity: disaster, window: 3m}
    snmp_stale: {timeout: 5m}
    cpu: {threshold: 90, recovery: 80, window: 5m}
    memory: {threshold: 90, recovery: 85, window: 5m}
    ospf: {severity: high}
    bgp: {exclude: ["192.0.2.9"]}
  CORE-SW-01:
    platform: cisco-nxos
    cpu: {}                       # {} or true = on with defaults; omit or false = off
```

| Feature | Settings (defaults) | Template linked |
|---|---|---|
| `device_unreachable` | `severity: disaster`, `window: 3m` | NETOPS Health Reachability |
| `snmp_stale` | `severity: high`, `timeout: 5m` | NETOPS Health Reachability |
| `cpu` | `severity: high`, `threshold: 90`, `recovery: 80`, `window: 5m` | per `platform` (section 6) |
| `memory` | `severity: high`, `threshold: 90`, `recovery: 85`, `window: 5m` | per `platform` |
| `ospf` | `severity: high`, `exclude: [router-id, …]` | NETOPS Health OSPF (OSPF-MIB) |
| `bgp` | `severity: high`, `exclude: [peer address, …]` | NETOPS Health BGP (BGP4-MIB) |

Unknown keys, bad severities, recovery ≥ threshold, or a device with no feature are rejected by `--check`.

## 5. Alert logic

| Alert | Problem | Recovery |
|---|---|---|
| OSPF Neighbor DOWN | neighbor was **Full** within 24 h (`{$NHEALTH.NBR.LOOKBACK}`) and has not been Full for 2 min (`{$NHEALTH.NBR.DOWN.TIME}`). A neighbor that **disappears** from `ospfNbrTable` reads as state 0 and alerts. | state Full |
| BGP Peer DOWN | peer was **Established** within 24 h and not Established for 2 min, and the peer is not admin-stopped | Established |
| Device UNREACHABLE | every ICMP poll failed for `window` | one ICMP reply |
| SNMP Data STALE | no SNMP sysUpTime value for `timeout` while the device still answers ping (when unreachable alerting is off, ping is ignored) | SNMP data returns, or the device becomes unreachable (that alert takes over) |
| CPU / Memory HIGH | every sample in `window` above `threshold` % | latest sample below `recovery` % |

* **No false alerts on discovery:** neighbors and peers that have never been Full/Established (new, still forming, or OSPF DROTHER 2-Way) never alert.
* A vanished neighbor's item stays enabled for 7 days (`DISABLE_NEVER`, delete after 7d), so its problem stays open. After 7 days the item is deleted and the problem closes. For a deliberately removed neighbor, add it to `exclude` or close the problem manually.
* If the device is unreachable over SNMP, the neighbor items receive no values, so no neighbor alerts fire. Device Unreachable / SNMP Stale cover that case.
* Severity is fixed per feature per device (4 trigger variants, exactly one can fire).

## 6. Platform support — verify each platform before relying on it

Do **not** assume one SNMP implementation fits all. Before selecting a feature for a device, check it answers from the Zabbix
server or proxy (read-only):

```bash
snmpwalk -v2c -c '<community>' <device-ip> 1.3.6.1.2.1.14.10.1.6      # OSPF neighbor states (8 = full)
snmpwalk -v2c -c '<community>' <device-ip> 1.3.6.1.2.1.15.3.1.2       # BGP peer states (6 = established)
snmpwalk -v2c -c '<community>' <device-ip> <cpu/memory OID from the table below>
```

| Feature / template | MIB (OIDs) | Expected to work on | Known limitations |
|---|---|---|---|
| OSPF | OSPF-MIB RFC 1850/4750, `ospfNbrTable` 1.3.6.1.2.1.14.10.1 | Cisco IOS/IOS-XE, IOS-XR, NX-OS; Huawei VRP | **OSPFv2 / IPv4 only** (OSPFv3 is not covered). Usually **one OSPF instance**: the default/global process. Cisco VRF or extra processes need SNMP context configuration (IOS/XR: `snmp context` under the OSPF process; NX-OS: `snmp-server context … instance … vrf …`), and Zabbix then needs an SNMPv3 context, i.e. effectively a separate host interface. Huawei VRP exposes one process in the standard MIB (select it with `ospf mib-binding <process-id>`). Virtual links (`ospfVirtNbrTable`) are not covered. Unnumbered links are indexed by ifIndex, so keep ifIndex persistent (`snmp-server ifindex persist`) or a reboot creates new items and the old ones alert as vanished. |
| BGP | BGP4-MIB RFC 4273, `bgpPeerTable` 1.3.6.1.2.1.15.3.1 | Cisco IOS/IOS-XE, NX-OS; Huawei VRP | **IPv4 peers in the default/global table only.** IPv6 and VRF/VPN-instance peers are not in BGP4-MIB (they need CISCO-BGP4-MIB `cbgpPeer2Table` or HUAWEI-BGP-VPN-MIB, which are not implemented). 4-byte ASNs display as 23456 (AS_TRANS); alerting is unaffected. |
| Reachability | ICMP (`icmpping`, needs fping on the Zabbix server/proxy) + SNMPv2-MIB sysUpTime 1.3.6.1.2.1.1.3.0 | any SNMP device | ICMP must be permitted from the Zabbix server/proxy. |
| `cisco-ios` | CISCO-PROCESS-MIB `cpmCPUTotal1minRev` …9.9.109.1.1.1.1.7; CISCO-ENHANCED-MEMPOOL-MIB `cempMemPoolHCUsed/HCFree` …9.9.221.1.1.1.1.18/.20 | IOS 15.x, IOS-XE | Memory pools filtered by `{$NHEALTH.CISCO.MEMPOOL.MATCHES}` (default `^Processor$`). Older IOS without the HC objects is not supported. IOS-XR not covered. |
| `cisco-nxos` | CISCO-SYSTEM-EXT-MIB `cseSysCPUUtilization` / `cseSysMemoryUtilization` …9.9.305.1.1.1.0/.2.0 | Nexus NX-OS | System-wide values (no per-module breakdown). |
| `huawei-vrp` | HUAWEI-ENTITY-EXTENT-MIB `hwEntityCpuUsage` / `hwEntityMemUsage` 1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5/.7 | Huawei VRP routers/switches | Discovers entities with non-zero memory usage. Board selection via `{$NHEALTH.HUAWEI.ENTITY.MATCHES}`. Some models report per-board values only. |
| `host-resources` | HOST-RESOURCES-MIB `hrProcessorLoad`, `hrStorage` (RAM) | Linux-based appliances; firewalls that implement it (e.g. Palo Alto management plane) | **Firewall data-plane CPU/session load is NOT covered.** RAM detection depends on the `hrStorageRam` type. No vendor-specific firewall template is included; FortiGate and others need their own template (not provided). |

## 7. Install and enable (manual, per device)

v1.0.3 is **not tagged yet**. Until a `v1.0.3` tag exists, the bundle must be made from this branch's commit.
For the transfer itself, use the same `git bundle` method as `docs/OFFLINE-INSTALL-v1.0.2.md`, replacing `v1.0.2` with the reviewed ref.

```bash
cd Zabbix/zabbix-alerting
vi config/network-health.production.yaml                 # list devices and features
./apply-health.sh --env production --check               # every device PASS
./apply-health.sh --env production --dry-run             # review ADD template / link / macro lines; get approval
./apply-health.sh --env production --confirm production  # backup -> import -> link -> macros -> verification plan is empty
./apply-health.sh --env production --dry-run             # No changes required.
```

* **Disable a feature:** remove its key from the device, then dry-run and apply. Removing the last feature that needs a template unlinks and clears that template.
* **Disable everything:** set `devices: {}`, then apply with `--confirm production --allow-empty`. The templates stay in Zabbix but are unlinked; delete them in the UI for a full removal.
* **Rollback:** `git checkout <good-commit> -- config/network-health.production.yaml`, then dry-run and apply. Every apply first writes `state/backups/network-health-<env>-<time>.json`.
* API account: same as Interface Alerting (template import, host linking and host macros).

## 8. Required LAB validation before any Production use

1. Import and idempotency: on a LAB device in both inventories, run `apply-health.sh` (apply), then dry-run must say `No changes required.`; run `apply.sh --dry-run`, which must also say `No changes required.` (proves coexistence).
2. Template import is accepted by Zabbix 7.0 (walk items, `SNMP_WALK_TO_JSON` / `SNMP_WALK_VALUE`, calculated items, value maps, lifetime settings).
3. Discovered OSPF neighbors / BGP peers / CPU / memory entries match `snmpwalk` output on each platform.
4. Fault tests, each with Problem and Recovery e-mail: shut one OSPF neighbor interface; shut one BGP neighbor (admin shutdown must **not** alert); clear a peer; block ICMP+SNMP (only Unreachable must fire); block SNMP only (Stale fires); lower a CPU threshold temporarily.
5. Remove a feature and a device from the inventory: only Network Health objects are removed; Interface Alerting is unaffected.
