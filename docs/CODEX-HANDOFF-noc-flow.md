# Codex handoff — NOC Graph Wall + Flow platform

Branch: `claude/noc-flow-platform`
Author: Claude (Opus 4.7)
Date: 2026-10-03

## 1. What this branch contains

| Area | Status | Path |
|---|---|---|
| NOC Graph Wall widget module | **scaffold complete, not live-validated** (no Zabbix API creds in this environment) | `frontend/modules/NocGraphWall/` |
| Flow Search widget module | **scaffold complete, not live-validated** | `frontend/modules/FlowSearch/` |
| NetFlow VM deployment artifacts | **complete, VM not booted from this host** | `netflow-vm/` |
| Huawei CPU multi-OID guidance + per-model overrides | **documented, template edit deferred to Codex** | `docs/HUAWEI-CPU-MULTI-OID.md`, `templates/huawei/cpu-multi-oid/` |
| Device Health column mapping fix | **documented, code change deferred to Codex** on the `codex/device-health-v1` branch | `docs/DEVICE-HEALTH-ITEM-MAPPING.md` |

Nothing on this branch is yet immutable-tagged.

## 2. Honest limits of this build

This build ran on a Windows engineering workstation that is also the WAN lab controller (`DESKTOP-T2C5JBN`). It does **not** have:

- Zabbix API credentials — I could not query real items, so neither module's `item.get` wiring was executed against a real server, and the six NOC Graph Wall slots are intentionally left `itemid: null` for Codex (or ops) to fill from the real Zabbix.
- SSH into any WAN device — no exporter configuration was applied. The `netflow-vm/docs/EXPORTER-SAFETY.md` runbook and per-vendor templates are shipped for Codex to execute under a change window.
- The RHEL hypervisor that hosts the NetOps VMs — the NetFlow VM was not booted here. `netflow-vm/provisioning/create-netflow-vm.sh` is the single command to run on the right hypervisor.
- Access to Zabbix module code on the `codex/*` branches to actually edit the Device Health column resolver — proposed design is documented, change is Codex's.

Everything that **could** be built end-to-end on this box (code, compose, cloud-init, firewalld rules, SELinux posture, security guardrails, documentation) is on this branch.

## 3. NOC Graph Wall

Follows the existing module convention observed on `codex/network-utilization-v1.4` (manifest.json + Widget.php + actions/ + views/widget.view.php + assets/).

- Six fixed slots. Positions stable, never reordered by the backend.
- Server-side resolution. One `item.get` across all slot items; one `history.get` (1h/6h) or `trend.get` (24h/7d). No N+1.
- Config persists server-side at `${ZABBIX_DATA_DIR}/noc_graph_wall/slot-definitions.json` (atomic file write).
- Edit mode is admin-gated and CSRF-checked. Item search is a bounded server action (`nocgraphwall.items.search`, 50/page); browser never calls `item.get` directly.
- Themes: Blue/light and Dark via CSS variables that match the existing module conventions.
- Fullscreen toggle; 30 s auto-refresh with single-flight guarding.

Next for Codex:
1. Review `WidgetView.php` resolution logic against the real `codex/network-utilization-v1.4` collector to make sure the two use the same bulk pattern.
2. On the staging Zabbix: query real items (STC/Mobily/SAIX edge interfaces, DCI, Internet-edge firewall throughput, core WAN trend) and populate `/var/lib/zabbix/noc_graph_wall/slot-definitions.json` from `slot-definitions.example.json` as a seed.
3. Real-browser validation at 2200/1920/1440/1200/900 — add screenshots under `evidence/noc-graph-wall/`.
4. Tag `noc-graph-wall-v0.1.0` after sign-off.

## 4. Flow Search

- All queries server-side. Browser only submits a declarative filter.
- Hard caps: 7-day window, 10 000 rows, 4 GB bytes read, 10 s execution, 2 GB memory per query — enforced via ClickHouse `SETTINGS` on every statement.
- Dedicated read-only user `zbx_flow_ro` on a `flows_v1` view (SQL in `frontend/modules/FlowSearch/sql/views.sql`); no SELECT on the raw table.
- Filter whitelist: IP / CIDR / src/dst port / protocol / exporter / interface. Every value is a bind parameter — no string concatenation.
- Top-N endpoint covers Sources / Destinations / Conversations / Ports / Protocols / Exporters / Ingress interfaces.
- Pagination: 50 rows / page.
- UI: Blue/light + Dark; summary tiles for traffic/packets/flows/peak; results table; pagination controls.

Next for Codex:
1. Add cross-link URL builders — `Network Utilization` link row → `Flow Search` with `exporter` + `interface` + current time range prefilled; `Flow Search` exporter header → `Device Health` for that host; node/site header → `Availability`.
2. Live-test against a staging Akvorado with injected sample flows.
3. Add the Zabbix server's env for the module: `FLOW_CLICKHOUSE_URL=http://netflow-01:8123`, `FLOW_CLICKHOUSE_USER=zbx_flow_ro`, `FLOW_CLICKHOUSE_PASS=<sealed>` (systemd-creds, not file-based).
4. Tag `flow-search-v0.1.0` after sign-off.

## 5. NetFlow platform (Akvorado)

- Rocky 9 Generic Cloud base; podman + podman-compose on RHEL (compose file is docker-compose.yml-compatible).
- Akvorado 1.11.4 (inlet, outlet, console), Kafka 7.6.1 + Zookeeper, ClickHouse 24.8.4.13 — all **pinned by tag** with digests captured on first pull by `pin-digests.sh`.
- SELinux Enforcing throughout. firewalld active with explicit zones:
  - `flow-exporters` — UDP/2055 from exporter CIDRs only
  - `noc-mgmt` — TCP/443 (nginx-fronted console) + SSH from NOC CIDRs only
  - `zabbix` — TCP/10050 from Zabbix server IP (Codex sets the source at onboarding)
- Internal services (Kafka 9092, ClickHouse 8123/9000) bound to **127.0.0.1 only**.
- Dedicated flow-data disk on `vg_flow/lv_flows` mounted at `/var/lib/akvorado/data`. 100 GiB start, expand on measurement after 7 days.
- `/opt/akvorado/bin/pin-digests.sh` captures running digests after first pull; `rollback.sh` reverts to the previous `.digests.lock`.
- Zabbix self-monitoring template outlined under `netflow-vm/README.md §5`; template XML not generated here (needs an active Zabbix to export the final YAML from).

Next for Codex:
1. On the hypervisor:
   ```
   export NETOPS_ADMIN_PUBKEY='<the standard netops admin key>'
   ./netflow-vm/provisioning/create-netflow-vm.sh \
       --name netflow-01 --ip <real-ip>/24 --gw <real-gw> --dns <real-dns> \
       --flow-cidrs "<real-exporter-CIDRs>" \
       --noc-cidrs  "<real-noc-mgmt-CIDRs>"
   ```
2. On the VM once the stack is healthy: `sudo /opt/akvorado/bin/clickhouse-apply.sh` to install `flows_v1` + `zbx_flow_ro`.
3. Attach the Zabbix self-monitoring template (`akvorado-platform.yaml`) when exported from the staging Zabbix.
4. First exporter under the change-window process in `netflow-vm/docs/EXPORTER-SAFETY.md`. Measure sampling vs CPU on an Internet-edge router before expanding scope.

## 6. Zabbix cleanup

- `docs/HUAWEI-CPU-MULTI-OID.md` + `templates/huawei/cpu-multi-oid/model-overrides.json` — configuration-driven multi-OID with CLI-validated per-model overrides. Dependent item + preprocessing recipe documented; **template edit is Codex's** on the Huawei template release branch.
- `docs/DEVICE-HEALTH-ITEM-MAPPING.md` — vendor-aware, key-based column mapping to stop Power/Fan columns matching unrelated items. Design is written; **code change belongs on `codex/device-health-v1`**.

Both docs make the proposed changes concrete enough for Codex to implement without re-deriving the design.

## 7. Security posture (summary)

- No secrets committed. The compose uses `secrets:` with files generated at provisioning time; no plaintext passwords in Git.
- SELinux Enforcing. firewalld active with explicit source-CIDR rich rules.
- Kafka/ClickHouse not exposed outside the VM.
- Zabbix integration uses a read-only ClickHouse user (`zbx_flow_ro`), SELECT only on the `flows_v1` view.
- CSRF-checked admin actions in both widget modules.
- Browser never issues SQL or `item.get` directly.

## 8. Git

- Branch: `claude/noc-flow-platform` (based on `staging`).
- Commits: staged in logical sequence (`feat(zabbix): NOC graph wall module scaffold`, `feat(flow): Akvorado platform deployment artifacts`, `feat(zabbix): Flow Search module scaffold`, `docs(monitoring): Huawei CPU + Device Health item-mapping fixes`, `docs(netops): Codex handoff for NOC + flow`).
- Push: regular push to origin, no force. No immutable release tag created yet — tags should follow Codex sign-off and live validation.

## 9. Known limitations

1. Zabbix modules not live-validated — no API access on this build host.
2. NetFlow VM not booted — provisioning requires the RHEL hypervisor used by NetOps.
3. No exporter configuration applied — needs device SSH access.
4. Akvorado digests pinned by tag, not by sha256 — digests should be captured on first pull on the NetFlow VM (`pin-digests.sh`) and the compose file updated to the `@sha256:...` form on commit from the VM.
5. No real screenshots — add `evidence/noc-graph-wall/` and `evidence/flow-search/` after real-browser validation.

## 10. Next three actions

1. Boot the NetFlow VM on the proper hypervisor (`provisioning/create-netflow-vm.sh`) and run `pin-digests.sh` + `clickhouse-apply.sh`.
2. Populate NOC Graph Wall slot bindings from real Zabbix items (STC/Mobily/SAIX/DCI/edge FW/core).
3. Pick one Internet-edge router, apply the Flexible NetFlow (Cisco) or NetStream (Huawei) config from `netflow-vm/templates/exporters/` under the change-window checklist, confirm flows land in Akvorado, confirm Flow Search sees them.
