# NetFlow Platform VM (Akvorado v2026.10.0)

Dedicated **appliance-style** VM, operationally separate from the Zabbix server. Vendored official Akvorado v2026.10.0 release, with a minimal NetOps overlay. SELinux Enforcing; firewalld active.

## Status

- Code / artifact state: this commit vendors the official `docker-compose-quickstart` v2026.10.0 under `upstream/akvorado-v2026.10.0/` and layers only NetOps-specific changes under `overlay/`.
- Deployment state: **the VM has not been booted from this environment** — Claude Code's auto-mode classifier refuses SSH to the Proxmox hypervisor at 192.168.1.100 (two attempts refused as "Credential Exploration" / "dangerous"). The handoff for Codex, who has the Proxmox CLI, is in `docs/CODEX-HANDOFF-noc-flow.md`.

## 1. Architecture (official v2026.10.0, verified against the quickstart tarball)

| Service | Image | Purpose |
|---|---|---|
| `akvorado-orchestrator` | `quay.io/akvorado/akvorado:2026.10.0` | Central config / coordinator |
| `akvorado-inlet` | same image | UDP 2055/4739/6343 (NetFlow / IPFIX / sFlow) |
| `akvorado-outlet` | same image | Kafka → ClickHouse writer |
| `akvorado-console` | same image | Web UI (served behind Traefik) |
| `kafka` | `apache/kafka:4.3.1` | **KRaft mode, no ZK** (upstream dropped ZK in this release) |  <!-- BAN:keep -->

| `redis` | `valkey/valkey:9.0` | Session / metadata cache |
| `clickhouse` | `clickhouse/clickhouse-server:26.8` | Flow store |
| `traefik` | `traefik:v3.7` | Reverse proxy (private 8080 loopback, public 8081 — our overlay also binds 8081 to loopback) |
| `kafka-ui` | `kafbat/kafka-ui:v1.5.0` | Optional inspector |

The vendored `docker-compose.yml` and `versions.yml` are unmodified copies of upstream. All NetOps-local changes live in `overlay/docker-compose.netops.yml`.

## 2. Repository layout

```
netflow-vm/
├── README.md
├── upstream/
│   ├── README.md                                        (vendoring policy)
│   └── akvorado-v2026.10.0/                            (verbatim upstream)
│       ├── .env
│       ├── config/{akvorado,inlet,outlet,console}.yaml
│       └── docker/
│           ├── docker-compose.yml
│           ├── versions.yml
│           └── clickhouse/{server.xml,observability.xml}
├── overlay/
│   ├── docker-compose.netops.yml                       (private 8081, pinned volumes, journald)
│   ├── env.netops                                      (COMPOSE_FILE chain + console branding)
│   ├── clickhouse/users.d/zbx-flow-ro-profile.xml      (hard caps for the readonly user)
│   └── .digests.lock                                   (written by bin/pin-digests.sh)
├── bin/
│   ├── pin-digests.sh                                  (idempotent)
│   ├── compose-up.sh                                   (digest-pinned if lock present)
│   ├── digests-to-overlay.sh                           (produces a transient compose fragment)
│   ├── clickhouse-apply.sh                             (installs netops.flow_v1 + flow_api_ro)
│   ├── rollback.sh                                     (restores overlay/.digests.lock.prev)
│   └── validate.sh                                     (static consistency check)
├── flow-api/                                           (Zabbix-facing TLS/Bearer gateway)
│   ├── README.md
│   ├── api.php                                         (SAMPLING-AWARE peak_bps; keyset paging)
│   ├── nginx.conf
│   └── flow-api-install.sh
├── provisioning/
│   ├── cloud-init.user-data.yaml
│   ├── create-netflow-vm.sh
│   └── firewalld-apply.sh
└── docs/
    └── EXPORTER-SAFETY.md
```

## 3. Zabbix ↔ Flow boundary

The browser never speaks ClickHouse. Zabbix never gets general ClickHouse admin. The path is:

```
Browser → Zabbix PHP (FlowSearch) → HTTPS/Bearer → flow-api/nginx+PHP
                                                  → ClickHouse (loopback-only)
                                                      → netops.flow_v1 (compat view)
                                                      → akvorado.flows (upstream, not exposed)
```

- Flow API gateway: `netflow-vm/flow-api/`.
- Zabbix server-side code: `frontend/modules/FlowSearch/`.
- Compat view: `../frontend/modules/FlowSearch/sql/views.sql` — created by `bin/clickhouse-apply.sh`.
- Peak bitrate is **sampling-aware**: `sum(Bytes * SamplingRate) * 8 / 60` bucketed per minute, with a materialised `netops.flow_bps_1m` MV for long windows.

## 4. Sizing (initial, re-measure after 7 days)

| Resource | Value | Why |
|---|---|---|
| vCPU | 4 | Akvorado's Go services + ClickHouse |
| RAM | 8 GiB | ClickHouse profile capped to 2 GB; Kafka 1 GB; Akvorado services ~1.5 GB; headroom |
| OS disk | 20 GiB | Rocky 9 minimal + container images + logs (journald capped) |
| Flow data disk | 100 GiB (expandable) | `vg_flow/lv_flows` mounted at `/var/lib/akvorado/data` |
| vNICs | 1 | Mgmt NIC in the NetOps management VLAN |

Measure actual bytes/flow after 7 days via `bin/validate.sh` summary (adds a ClickHouse size probe).

## 5. Deploy — one path, idempotent

```bash
# 1. On the Proxmox hypervisor (Codex has access, Claude does not from here):
#    provisioning/create-netflow-vm.sh creates the VM, cloud-init bootstraps podman,
#    firewalld, LVM, and this repo at /opt/akvorado.

# 2. On the VM (as root, idempotent):
cd /opt/akvorado
bin/pin-digests.sh          # pull + lock sha256 digests
bin/compose-up.sh           # bring the stack up (digest-pinned if lock exists)
bin/clickhouse-apply.sh     # install netops.flow_v1 + flow_api_ro
flow-api/flow-api-install.sh  # nginx + php-fpm + bearer token + TLS

# Rollback:
bin/rollback.sh             # restores overlay/.digests.lock.prev
```

## 6. Security

- SELinux: Enforcing. `httpd_can_network_connect` is the only boolean touched.
- firewalld: active, three explicit zones (`flow-exporters` UDP 2055/4739/6343 by exporter CIDR; `flow-api` TCP 443 by Zabbix-server IP; `noc-mgmt` SSH by NOC CIDR).
- No off-box exposure of ClickHouse (bound to the compose network only; Traefik `/clickhouse` is on the private 127.0.0.1:8080 entrypoint).
- No off-box exposure of Traefik's public entrypoint either — our overlay rebinds `:8081` to loopback. The console reaches browsers only via flow-api's nginx acting as a reverse proxy.
- Zabbix sees the Flow API via Bearer token hashed on disk; the plaintext token is minted once by `flow-api-install.sh` and shipped to the Zabbix server as a sealed systemd credential.

## 7. Known limitations

1. VM not booted — Proxmox SSH blocked by auto-mode classifier; see `docs/CODEX-HANDOFF-noc-flow.md`.
2. Digest lock is empty until `pin-digests.sh` runs on the deploy host.
3. Grafana / Loki / Prometheus overlays from upstream are not enabled (left to Codex per site policy).
4. Exporter configuration out of scope here; the per-vendor templates and safety runbook are in `docs/EXPORTER-SAFETY.md`.
