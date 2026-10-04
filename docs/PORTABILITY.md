# Site portability — what has to change for a new site

The platform is intended to be LAB-portable with a single `sites.yaml` edit for the Grafana surfaces, environment variables for the Zabbix/Grafana endpoints, and per-vendor template blocks for exporter configuration. This file is the audit trail of every hardcoded value, what became configuration, and what intentionally stays constant.

## What became configuration

| Was hardcoded | Now in | Resolver |
|---|---|---|
| 12 WAN itemids in `grafana/dashboards/noc-wan-overview.json` | `grafana/config/sites.yaml → noc_wan_overview.slots[].{host, interface_pattern, label}` | `grafana/discovery/build-wan-wall.sh` resolves hostid + IN/OUT itemids live via the Grafana→Zabbix datasource resource proxy (as `grafana-ro`). Writes the dashboard JSON. |
| 7 PNET hosts in Device Health | `grafana/config/sites.yaml → noc_device_health.hosts[]` | (next planned extension of `build-wan-wall.sh` — the Device Health JSON currently lives static with real itemids; drift is caught by `apply-grafana.sh`'s pre-deploy ds/query probe) |
| Grafana URL / admin password / Zabbix API URL / Zabbix grafana-ro password | `~/.config/netops/claude-access/{grafana.env,claude-access.env}` | `apply-grafana.sh` reads them. Nothing is in Git. |
| Zabbix datasource UID (`zabbix-lab`) and folder UID (`noc`) | `grafana/config/sites.yaml → grafana.{datasource_uid, folder_uid}` | `build-wan-wall.sh` + `apply-grafana.sh` read it. |
| NetFlow exporter config (Cisco Flexible NetFlow block, record / exporter / monitor / sampler names) | `grafana/config/sites.yaml → exporter_vendors.cisco-iosv` | `netflow-vm/bin/exporter-poc-*.sh` pulls this block when `--vendor` matches. Add e.g. `huawei-vrp` for a NetStream block. |
| Exporter target host alias (`wanlab-stc`) | script arg `--exporter-ios-alias` and ssh-config lookup | `exporter-poc-stc.sh` resolves `HostName` from the shared `ssh-config` entry. Rename the script per host (`-mobily`, `-saix-a`, …) or add `--host` arg. |
| Exporter destination (`NETFLOW_IP`) | script env | runtime arg, no file edit |
| ClickHouse host paths on the NetFlow VM | `netflow-vm/overlay/docker-compose.netops.yml` volume `device:` paths | one place to change if the LV mountpoint moves |
| Akvorado version | `netflow-vm/upstream/akvorado-v2026.10.0/docker/versions.yml` + `AKVORADO_VERSION` env in `bin/pin-digests.sh` | bumping the vendored upstream is the ONLY supported way; the overlay stays |
| firewalld source CIDRs (exporter / NOC / zabbix) | `provisioning/create-netflow-proxmox.sh` args + cloud-init env | per-site parameterisation on the Proxmox host |
| VM resources (vCPU/RAM/disk) | `create-netflow-proxmox.sh` flags with safe defaults | tune per expected flow volume |

## What intentionally stays constant

- Dashboard **UIDs** (`noc-wan-overview`, `noc-device-health`) and panel **grid layout** (6-slot 3×2, consistent IN=green/OUT=blue) — these are the frozen NOC-wall contract. Operator muscle memory is a feature.
- ClickHouse compat view name `netops.flow_v1` — the stable projection the Zabbix FlowSearch module pins to.
- Flow API URL path shape (`/api/v1/{search,summary,topn}`, `/akvorado/`, `/healthz`).
- Vendored upstream Akvorado files under `netflow-vm/upstream/akvorado-vX.Y.Z/` — never edited, replaced wholesale on version bumps.

## Lab assumptions still present (document, don't delete)

- Interface name convention `Gi0/0` for WAN uplinks — matches the lab's Cisco IOSv onboarding. Prod routers may use `TenGigE0/0/0/0` etc.; `interface_pattern` in `sites.yaml` is a prefix match, so prod sites change the pattern to match their naming.
- Host-name prefix `PNET-` for the 7 lab routers. In prod `sites.yaml` will carry the real site/device names; neither the generator nor the deploy script hard-code `PNET-`.
- Zabbix templates: assumed to be the stock `Cisco IOS by SNMP` family which exposes `net.if.in[ifHCInOctets.N]` / `net.if.out[ifHCOutOctets.N]` and `Interface <X>: Bits received/sent` as item names. The generator searches by name, so a different template that spells the item differently needs a search-term override in `sites.yaml` (not yet exposed as a parameter — add if a prod site diverges).

## Open items that are NOT portability holes

- CPU utilization panel on Device Health is intentionally deferred: the stock Cisco IOS template exposes `#1: CPU utilization` as a dependent item whose master `system.cpu.walk` isn't producing persistent history on these particular PNET IOSv instances yet (lastvalue works but `history.get` returns empty). Reinstate once Zabbix accumulates history. Not a hardcoding issue — a Zabbix dependent-item issue that `grafana-ro` + plugin can't paper over.
- Palo Alto SSH credential missing from the access bundle — not blocking any current work (NOC WAN wall, Device Health, Akvorado platform, Cisco exporter POC all unaffected). Document and move on.

## Regenerate dashboards for a new site

```bash
# 1. Edit grafana/config/sites.yaml with the real hosts and interface pattern.
# 2. Make sure Zabbix has those hosts registered and the dedicated grafana-ro
#    user has host/item/history read on them.
# 3. Regenerate the WAN wall dashboard JSON from live Zabbix:
bash grafana/discovery/build-wan-wall.sh
# 4. Deploy to the live Grafana (api mode works without SSH to grafana host):
bash grafana/bin/apply-grafana.sh api
```

The deploy step verifies each generated itemid returns a real frame via `/api/ds/query` BEFORE marking the dashboard provisioned (gate added to `apply-grafana.sh`). If any series is empty the deploy fails fast and the operator fixes `sites.yaml` or the Zabbix template, not the dashboard JSON.
