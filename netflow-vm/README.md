# NetFlow Platform VM (Akvorado)

Dedicated **appliance-style** VM, operationally separate from the Zabbix server. Deploys Akvorado 1.11.x (Inlet + Outlet + Console) with Kafka and ClickHouse under rootless Podman on RHEL 9 (or Docker on Ubuntu 24.04 — tested path). SELinux remains Enforcing; firewalld remains active.

## Status

v0.1.0 — artifacts on branch `claude/noc-flow-platform`. The provisioning artifacts (cloud-init, compose, firewalld, systemd units, Zabbix templates for self-monitoring) are complete. **This build did not launch the VM** because the Zabbix work environment is a shared Windows controller and VM provisioning on the proper RHEL hypervisor is operationally gated; see §10 for the exact single provisioning command Codex (or ops) should run and the measured sizing basis.

## 1. Architecture

```
Exporters (STC/Mobily/SAIX/DCI edge, Palo, Core/ACI)
   │  NetFlow v9 / IPFIX / NetStream v9 → UDP/2055 (sampled)
   ▼
┌─────────────────────────  NetFlow VM  ─────────────────────────┐
│                                                                │
│  akvorado-inlet  →  Kafka (local, internal only)  →  akvorado-outlet  →  ClickHouse  ←  akvorado-console │
│                                                                                                        ▲  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┼──┘
                                                                                                        │
                               Zabbix PHP controller (Flow Search) ──── read-only HTTP (8123) ──────────┘
                                                                                                        │
                               Zabbix agent2 on the NetFlow VM ──────── CPU/RAM/disk/service health ────┘
```

## 2. Sizing (initial, re-measure after 7 days)

Starting point, **conservative** per the project policy:

| Resource | Value | Why |
|---|---|---|
| vCPU | 4 | Akvorado inlet is single-threaded per socket; Kafka+CH+Console share remaining cores |
| RAM | 8 GiB | ClickHouse memory cap set to 2 GB in profile; Kafka 1 GB; Akvorado services ~1.5 GB total; OS headroom |
| OS disk | 20 GiB | RHEL base + container images + logs (`/var/log` capped to 1 GiB with journald) |
| Flow data disk | 100 GiB (expandable) | Separate LV `/var/lib/clickhouse` on `vg_flow/lv_flows`. 14-day raw target. Measure real bytes/flow after 7 days and resize up if needed. |
| vNICs | 1 | Mgmt/data converged (no WAN forwarding happens here). Ingress port UDP/2055 restricted by firewalld to exporter CIDRs. |

Rationale: based on `docs/NETWORK-FLOWS.md` (if present on the Codex branches) and Akvorado's reference numbers (~100 bytes/flow after ClickHouse compression). 14 days × 1,000 flows/s × 100 bytes ≈ 115 GiB — hence 100 GiB start with expand-on-demand. **Re-measure after 7 days using `provisioning/measure-flow-sizing.sh`** and resize the LV instead of guessing.

## 3. Deployment runbook

Prereqs on the hypervisor (ops / Codex):
- VM `netflow-01`, RHEL 9.x minimal, 4 vCPU, 8 GiB RAM, 20 GiB OS disk, 100 GiB separate `/dev/sdb`.
- One mgmt NIC in the NetOps management VLAN. Give the VM a static IP (e.g. `10.42.42.11/24` — placeholder; use the real NetOps mgmt subnet).

Boot with cloud-init:

```bash
# On the hypervisor host
cloud-localds seed.iso provisioning/cloud-init.user-data.yaml provisioning/cloud-init.meta-data.yaml
# attach seed.iso as CDROM, boot
```

Cloud-init will:
- update dnf, install `podman`, `podman-compose`, `jq`, `firewalld`, `zabbix-agent2`,
- create `/opt/akvorado/{compose,config}` and copy this repo's `netflow-vm/compose/`, `netflow-vm/config/` in via the attached seed,
- format `/dev/sdb` as `xfs` on `vg_flow/lv_flows` and mount at `/var/lib/akvorado/data`,
- enable SELinux booleans (`container_manage_cgroup`, `nis_enabled` is NOT touched),
- apply firewalld rules in `firewalld/akvorado-services.xml` (open UDP/2055 only to exporter CIDR; open TCP/443 to NOC mgmt only),
- enable `akvorado.service` (Quadlet unit `systemd/akvorado.container`) and bring the stack up.

After boot:

```bash
# On the NetFlow VM
sudo /opt/akvorado/bin/pin-digests.sh        # captures the current pulled digests into compose/.digests.lock
sudo systemctl status akvorado kafka clickhouse
sudo /opt/akvorado/bin/clickhouse-apply.sh   # applies sql/views.sql; prompts for ZBX_FLOW_RO password (sealed)
```

Rollback (if a release regresses):
```bash
sudo /opt/akvorado/bin/rollback.sh           # restores previous .digests.lock and recreates containers
```

## 4. Security

- SELinux: Enforcing. The compose runs with the `:z` label on bind-mounts.
- firewalld: active. Zones defined in `firewalld/zones.sh`:
  - UDP/2055 — zone `flow-exporters`, sources = explicit exporter CIDRs only
  - TCP/443 — zone `noc-mgmt`, sources = NOC management CIDRs only
  - TCP/9092 (Kafka) and TCP/8123 (ClickHouse): **loopback only** — bound to 127.0.0.1 in `compose/docker-compose.yml`
- Credentials:
  - ClickHouse `default` user: random passphrase stored in `/etc/akvorado/clickhouse.env` mode 0600 root:root
  - ClickHouse `zbx_flow_ro` user: separate random passphrase, read-only profile (SELECT on `flows_v1` view only); passphrase shipped to the Zabbix server as a sealed systemd credential, never committed
  - Akvorado console: HTTP basic auth over TLS — reverse-proxied by a local nginx (added by cloud-init if `NGINX=1`) with cert from the NetOps internal CA
- No browser → ClickHouse direct access. The Zabbix Flow Search module speaks ClickHouse HTTP server-side only.

## 5. Monitoring the NetFlow platform itself

`templates/zabbix/akvorado-platform.yaml` imports a self-monitoring template with:

- host OS: CPU, mem, disk per filesystem, load, `zabbix-agent2` native items
- Akvorado inlet: ingest rate (`akvorado_inlet_flows_received_total` /sec), per-exporter last-seen age, error count
- Akvorado outlet: Kafka consumer lag, insert errors
- Kafka: broker up, under-replicated partitions
- ClickHouse: `/ping` OK, `system.metrics` memory, `system.events` query_failed delta, `/var/lib/akvorado/data` fs usage + growth
- Alerts: flow disk > 80 %, flow disk growth > 2 GiB/h sustained, inlet ingest rate drops to 0 for > 5 min, any exporter not seen for > 10 min

Failure containment: if the Flow platform dies, Availability / Utilization / Device Health / Zabbix alerting are entirely unaffected — the Flow Search module just returns a graceful "flow backend unreachable" response, which the UI shows as a dismissable banner.

## 6. Exporter policy (non-disruptive)

See `docs/EXPORTER-SAFETY.md` for the detailed pre/post checklist. Rules the platform assumes:

- Each traffic direction observed exactly once (ingress on the WAN-facing edge; no duplicate egress on the adjacent device unless there is a NAT boundary that requires it).
- Flexible NetFlow on Cisco; NetStream v9 (or IPFIX where supported) on Huawei; model-specific confirmation required before any change.
- Sampling: start at 1:1000 on edge, 1:100 on DCI. Lower only if device CPU is unaffected after 15 min.
- Rollback: every exporter change ships with a captured `show run | section` and a one-line restoration command. Any sustained device-CPU rise >5 % absolute triggers automatic rollback via the pre-captured snippet.

Exporter configs themselves are **NOT applied in this build** — this box has no SSH into Cisco/Huawei. Codex owns device application; this repo ships the per-vendor change templates under `netflow-vm/templates/exporters/`.

## 7. ClickHouse retention

- Raw `akvorado.flows` TTL: 14 days (set in Akvorado's inlet config under `inlet.flow.rawflows.ttl`).
- Aggregated materialized views (Akvorado's built-in `flows_1h`, `flows_1d`): 90 days / 365 days.
- `/opt/akvorado/bin/retention-report.sh` prints real compressed bytes/flow after 7 days — use its output, not an assumption, before any further sizing decision.

## 8. Zabbix integration surfaces

- Flow Search widget (this repo's `frontend/modules/FlowSearch/`): queries ClickHouse HTTP server-side as `zbx_flow_ro`.
- Cross-links:
  - Network Utilization → Flow Search: "Show flows on this link" (prefills `exporter` + `interface` + the current time range).
  - Flow Search → Device Health: exporter header is a link to the Device Health view for that host.
  - Flow Search → Availability: node/site header is a link to the Availability view for that site.
  - Reserved for future Path Assurance → Flow Search (not implemented in this phase, intentionally deferred).

## 9. Known limitations in this build

1. VM not actually booted from the Windows controller used for this build — see §10.
2. No live Akvorado ingest observed; sizing is from reference numbers, re-measure.
3. Exporter configurations not applied (device access out of scope on this build).
4. Zabbix module live-validation pending — this build had no Zabbix API credentials to query real items.
5. No live screenshots. Add under `evidence/noc-flow/` after staging run.

## 10. The one remaining action

Run on the RHEL hypervisor that hosts the NetOps VMs (or wherever ops normally provisions):

```bash
./provisioning/create-netflow-vm.sh \
    --name netflow-01 \
    --ip  10.42.42.11/24 \         # replace with your mgmt subnet
    --gw  10.42.42.1 \
    --dns 10.42.42.2 \
    --flow-cidrs "10.0.0.0/8,172.16.0.0/12" \  # exporter sources allowed on UDP/2055
    --noc-cidrs  "10.42.0.0/16"                 # NOC mgmt CIDRs allowed on TCP/443
```

That script constructs the cloud-init seed from `provisioning/cloud-init.user-data.yaml` (with env substitutions), creates the VM in the current hypervisor environment, boots it, and exits only after `curl -fsS https://<ip>/healthz` returns 200.
