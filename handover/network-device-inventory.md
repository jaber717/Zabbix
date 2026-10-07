# Network-device inventory

Captured read-only on 2026-10-07. Eight Cisco IOSv routers were inspected live. `PALO-LAB` is documented from the preserved topology/configuration evidence but was not inspected live because its password is intentionally not stored in the access bundle.

## Management and access path

The controller is this Windows workstation. Router management is on untagged `192.168.1.0/24` through the PNET management switch/bridge. The proven automation path uses PuTTY `plink.exe` with keyboard-interactive/password authentication from:

- credential reference: `C:\Users\jaber\.config\netops\claude-access\network-device.env`
- SSH aliases/config reference: `C:\Users\jaber\.config\netops\claude-access\ssh-config`
- validation implementation: `C:\Users\jaber\Documents\Home-Server\WAN-LAB\validation-harness\router-snapshot.ps1`

The SSH config also documents a jump-host form through alias `PNET`. The currently proven snapshot harness reaches the router management addresses directly with the protected credential file. Do not copy its password into Git or command output. IOS privilege is already sufficient for read-only `show` commands; configuration mode is not needed for this handover.

PNET host access is separately referenced by `C:\Users\jaber\.config\netops\claude-access\pnet.env`. Claude does not need Proxmox access for alerting implementation.

## Devices

| Device | Vendor/model/software | Management | Zabbix host / ID | SNMP | Template | Site | Role | Live inspection |
|---|---|---:|---|---|---|---|---|---|
| SITE-A | Cisco IOSv, IOS 15.6(2)T | 192.168.1.180 | PNET-SITE-A / 10687 | v3 authPriv | Cisco IOS by SNMP | SITE-A | Enterprise WAN edge | PASS |
| SITE-B | Cisco IOSv, IOS 15.6(2)T | 192.168.1.181 | PNET-SITE-B / 10688 | v3 authPriv | Cisco IOS by SNMP | SITE-B | Enterprise WAN edge | PASS |
| STC | Cisco IOSv, IOS 15.6(2)T | 192.168.1.182 | PNET-STC / 10689 | v3 authPriv | Cisco IOS by SNMP | WAN-LAB | STC provider simulator | PASS |
| MOBILY | Cisco IOSv, IOS 15.6(2)T | 192.168.1.183 | PNET-MOBILY / 10690 | v3 authPriv | Cisco IOS by SNMP | WAN-LAB | Mobily provider simulator | PASS |
| INT-CORE | Cisco IOSv, IOS 15.6(2)T | 192.168.1.184 | PNET-INT-CORE / 10691 | v3 authPriv | Cisco IOS by SNMP | WAN-LAB | Internet core | PASS |
| SAIX-CORE | Cisco IOSv, IOS 15.6(2)T | 192.168.1.185 | Not present | configured device-side; not polled | None | WAN-LAB | SAIX route core | PASS; not selectable yet |
| SAIX-A | Cisco IOSv, IOS 15.6(2)T | 192.168.1.186 | PNET-SAIX-A / 10692 | v3 authPriv | Cisco IOS by SNMP | WAN-LAB | SAIX provider edge A | PASS |
| SAIX-B | Cisco IOSv, IOS 15.6(2)T | 192.168.1.187 | PNET-SAIX-B / 10693 | v3 authPriv | Cisco IOS by SNMP | WAN-LAB | SAIX provider edge B | PASS |
| PALO-LAB | Palo Alto PA-VM; exact current PAN-OS version not re-read | 192.168.1.188 | Not present | Not configured in Zabbix | None | WAN-LAB | Firewall/edge virtual router AS65020 | Preserved evidence only |

The four `DR-*` Zabbix devices are intentional mock DCIM objects with fake/non-routable addresses and are excluded from this live WAN P2P deployment.

## Live routed topology

Every Cisco interface below was up/up during capture. Every listed peer address appeared Established in BGP. No OSPF adjacency is used in this topology.

| Link | A endpoint | B endpoint | Addressing | Routing |
|---|---|---|---|---|
| int-core--stc | INT-CORE Gi0/0 | STC Gi0/0 | 172.16.0.1/30 ↔ 172.16.0.2/30 | eBGP AS64497↔64498 |
| int-core--mobily | INT-CORE Gi0/1 | MOBILY Gi0/0 | 172.16.0.5/30 ↔ 172.16.0.6/30 | eBGP AS64497↔64499 |
| stc--site-b | STC Gi0/1 | SITE-B Gi0/1 | 172.16.1.1/30 ↔ 172.16.1.2/30 | eBGP AS64498↔64496 |
| mobily--site-a | MOBILY Gi0/1 | SITE-A Gi0/1 | 172.16.1.5/30 ↔ 172.16.1.6/30 | eBGP AS64499↔64496 |
| saix-core--saix-a | SAIX-CORE Gi0/0 | SAIX-A Gi0/0 | 172.16.2.1/30 ↔ 172.16.2.2/30 | iBGP AS64500 |
| saix-core--saix-b | SAIX-CORE Gi0/1 | SAIX-B Gi0/0 | 172.16.2.5/30 ↔ 172.16.2.6/30 | iBGP AS64500 |
| saix-a--site-a | SAIX-A Gi0/1 | SITE-A Gi0/0 | 172.16.3.1/30 ↔ 172.16.3.2/30 | eBGP AS64500↔64496 |
| saix-b--site-b | SAIX-B Gi0/1 | SITE-B Gi0/0 | 172.16.3.5/30 ↔ 172.16.3.6/30 | eBGP AS64500↔64496 |
| site-a--site-b | SITE-A Gi0/2 | SITE-B Gi0/2 | 172.16.255.1/30 ↔ 172.16.255.2/30 | iBGP AS64496 |
| site-a--palo-transit-a | SITE-A Gi0/3 | PALO ethernet1/1 | 10.255.1.1/30 ↔ 10.255.1.2/30 | eBGP AS64496↔65020 |
| site-b--palo-transit-b | SITE-B Gi0/3 | PALO ethernet1/2 | 10.255.2.1/30 ↔ 10.255.2.2/30 | eBGP AS64496↔65020 |

## LAG/Port-Channel assessment

No selected phase-1 routed link uses Port-Channel, Bundle-Ether, Eth-Trunk, LAG, or AE. All selected objects are individual IOSv routed GigabitEthernet interfaces. There is therefore no logical/member duplication decision in this LAB scope. If production later introduces a routed bundle, make the logical bundle the primary link object and handle member loss separately.

## Explicit exclusions

- OOB management interfaces on `192.168.1.0/24`.
- Loopbacks.
- Administratively down and unused interfaces.
- `INT-CORE Gi0/2` to the non-infrastructure Internet test endpoint; it is currently down/down and uses an endpoint `/24`.
- Palo DMZ and loopback/VIP interfaces.
- The four mock DR device interfaces.
