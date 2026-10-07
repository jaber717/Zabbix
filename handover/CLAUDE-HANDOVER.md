# CLAUDE START HERE

This is the implementation handoff for the Zabbix Interface Alerting-as-Code phase-1 LAB deployment. Discovery was read-only; no Zabbix object, router configuration, route, SNMP setting, action, media type, or firewall rule was changed.

## Zabbix

```text
repo: C:\Users\jaber\Documents\Home-Server\zabbix-platform
remote: https://github.com/jaber717/Zabbix
branch: codex/daily-reporting
SHA: 2fb5f19a2e8611e7f241f70ed1eb9b95a1d537bc
frontend: https://192.168.1.91:8443/
API: https://192.168.1.91:8443/api_jsonrpc.php
how to authenticate: protected bundle/credential references below; never put values in Git
templates to reuse: Cisco IOS by SNMP (template ID 10218)
```

Credential references:

- Controller: `C:\Users\jaber\.config\netops\claude-access\claude-access.env`
- Zabbix VM: `/etc/credstore.encrypted/nbzsync-zabbix-password`
- VM SSH: alias/details in the shared `ssh-config`; key `C:\Users\jaber\.ssh\netbox-codex-rhel96`

The normal `nbzsync` account is least-privileged. It can read hosts but cannot inspect/modify discovery rules or actions. Claude must use an explicitly approved administrative method for implementation; do not expand the integration account casually.

## Devices

```text
how to SSH: use the existing protected network-device.env + proven plink snapshot method
SSH/config paths:
  C:\Users\jaber\.config\netops\claude-access\network-device.env
  C:\Users\jaber\.config\netops\claude-access\ssh-config
  C:\Users\jaber\Documents\Home-Server\WAN-LAB\validation-harness\router-snapshot.ps1
inventory/topology:
  C:\Users\jaber\Documents\Home-Server\WAN-LAB\inventory\devices.yaml
  C:\Users\jaber\Documents\Home-Server\WAN-LAB\topology\current-topology.md
live devices inspected: 8 Cisco IOSv routers
Zabbix-monitored WAN routers: 7
selected P2P interface objects: 18
selected physical/logical links represented: 11 (some peers are not monitored)
```

## Implementation input

Use [p2p-interfaces.yaml](p2p-interfaces.yaml) as the authoritative machine-readable phase-1 selection. It uses exact live Zabbix `{#IFNAME}` values (`Gi0/x`), not expanded CLI names. `link_id` joins the two ends of the same link and should be retained for incident correlation/deduplication.

Supporting documents:

- [zabbix-current-state.md](zabbix-current-state.md)
- [network-device-inventory.md](network-device-inventory.md)
- [p2p-review-required.md](p2p-review-required.md)

## Critical warnings

1. **SNMP polling is currently broken for all seven WAN routers.** Zabbix reports SNMPv3 authentication failure following recent router restarts. Fix/reconcile this deliberately before validating alerting behavior; do not silently overwrite router or Zabbix credentials.
2. The existing stock link/utilization/error trigger prototypes are already active in the template. Avoid creating duplicate incidents. The stock defaults are link-down Average, utilization 90% with 3-point recovery, and errors threshold 2. The desired 70%/65% policy is a new override/policy decision.
3. Current polling is one minute through a bulk SNMP walk. Do not claim or configure 10-second utilization unless separately load-tested and approved.
4. Both endpoints are selected where both are monitored. Correlate on `link_id` or deliberately choose an event-owning end; do not emit two independent notifications for one physical failure without a deduplication policy.
5. `SAIX-CORE` and `PALO-LAB` are not currently in Zabbix. Their endpoints are in the review file, not the selected YAML.
6. SNMP traps are not configured. Do not enable UDP/162, trap daemons, or router traps as an implicit part of the first implementation.
7. Existing problem actions and media types are disabled/example-only. Do not enable the broad default action. Prefer a dedicated tag-filtered action after real SMTP/media and recipients are approved.
8. The repository was already dirty before this handover (`PROJECT-STATUS.md`, `README.md`, `docs/NETBOX-ZABBIX-SYNC.md`, Grafana/evidence files). Preserve those unrelated changes.
9. Do not touch Network Availability, Network Utilization, NetFlow, routing, BGP, OSPF, router interfaces, or the mock DR devices.

## Selected P2P interfaces

`Interface` below is the exact Zabbix `{#IFNAME}`. Speeds are nominal IOSv GigabitEthernet speeds; live Zabbix speed values are unavailable while SNMP authentication is failing.

| Device | Interface | Description | Peer | Local IP | Speed | Severity | Link | Util >70% |
|---|---|---|---|---|---|---|---|---|
| INT-CORE | Gi0/0 | TO-STC-Gi0/0 | STC Gi0/0 | 172.16.0.1/30 | 1 Gbps | Disaster | Yes | Yes |
| INT-CORE | Gi0/1 | TO-MOBILY-Gi0/0 | MOBILY Gi0/0 | 172.16.0.5/30 | 1 Gbps | Disaster | Yes | Yes |
| STC | Gi0/0 | TO-INT-CORE-Gi0/0 | INT-CORE Gi0/0 | 172.16.0.2/30 | 1 Gbps | Disaster | Yes | Yes |
| STC | Gi0/1 | TO-SITE-B-Gi0/1 | SITE-B Gi0/1 | 172.16.1.1/30 | 1 Gbps | Disaster | Yes | Yes |
| MOBILY | Gi0/0 | TO-INT-CORE-Gi0/1 | INT-CORE Gi0/1 | 172.16.0.6/30 | 1 Gbps | Disaster | Yes | Yes |
| MOBILY | Gi0/1 | TO-SITE-A-Gi0/1 | SITE-A Gi0/1 | 172.16.1.5/30 | 1 Gbps | Disaster | Yes | Yes |
| SAIX-A | Gi0/0 | TO-SAIX-CORE-Gi0/0 | SAIX-CORE Gi0/0 | 172.16.2.2/30 | 1 Gbps | Disaster | Yes | Yes |
| SAIX-A | Gi0/1 | TO-SITE-A-Gi0/0 | SITE-A Gi0/0 | 172.16.3.1/30 | 1 Gbps | Disaster | Yes | Yes |
| SAIX-B | Gi0/0 | TO-SAIX-CORE-Gi0/1 | SAIX-CORE Gi0/1 | 172.16.2.6/30 | 1 Gbps | Disaster | Yes | Yes |
| SAIX-B | Gi0/1 | TO-SITE-B-Gi0/0 | SITE-B Gi0/0 | 172.16.3.5/30 | 1 Gbps | Disaster | Yes | Yes |
| SITE-A | Gi0/0 | TO-SAIX-A-Gi0/1 | SAIX-A Gi0/1 | 172.16.3.2/30 | 1 Gbps | Disaster | Yes | Yes |
| SITE-A | Gi0/1 | TO-MOBILY-Gi0/1 | MOBILY Gi0/1 | 172.16.1.6/30 | 1 Gbps | Disaster | Yes | Yes |
| SITE-A | Gi0/2 | INTER-EDGE-TO-SITE-B-Gi0/2 | SITE-B Gi0/2 | 172.16.255.1/30 | 1 Gbps | Disaster | Yes | Yes |
| SITE-A | Gi0/3 | TO-PALO-TRANSIT-A | PALO ethernet1/1 | 10.255.1.1/30 | 1 Gbps | High | Yes | Yes |
| SITE-B | Gi0/0 | TO-SAIX-B-Gi0/1 | SAIX-B Gi0/1 | 172.16.3.6/30 | 1 Gbps | Disaster | Yes | Yes |
| SITE-B | Gi0/1 | TO-STC-Gi0/1 | STC Gi0/1 | 172.16.1.2/30 | 1 Gbps | Disaster | Yes | Yes |
| SITE-B | Gi0/2 | INTER-EDGE-TO-SITE-A-Gi0/2 | SITE-A Gi0/2 | 172.16.255.2/30 | 1 Gbps | Disaster | Yes | Yes |
| SITE-B | Gi0/3 | TO-PALO-TRANSIT-B | PALO ethernet1/2 | 10.255.2.1/30 | 1 Gbps | High | Yes | Yes |

## Recommended implementation order

1. Restore verified SNMPv3 polling without changing the intended authPriv security posture.
2. Re-query the 18 item sets and confirm fresh status, bps, speed, errors, and discards.
3. Import/validate policy in a non-destructive dry run. Confirm it targets exactly 18 interfaces.
4. Reuse the existing discovered item keys; do not create duplicate polling items.
5. Apply interface-specific alert policy/tags/macros with explicit 70% warning and 65% recovery semantics.
6. Add flapping logic only from real state history and bounded windows.
7. Validate deduplication by `link_id` before connecting notifications.
8. Configure and test a dedicated notification action only after a real media type/recipient path is approved.
