# NetFlow exporter safety

Non-disruptive by construction. The following checklist is **required** before touching any WAN device.

## 0. Scope

- Internet edge: STC, Mobily, SAIX.
- DCI: site-to-site routed links.
- Key routed boundaries: core/ACI, Internet-edge firewalls where supported.
- Not in v1: access ports, every leaf switch, inside the DMZ. Reason: duplicate observation and no operational payoff.

Each traffic direction is observed **exactly once**. The chosen observation point is the WAN-facing routed interface on the enterprise edge. Internal (NATed) sources are preserved by observing them on the LAN-facing interface of the NAT device.

## 1. Pre-change capture (per device)

Save these verbatim into `netflow-vm/evidence/exporters/<device>/pre/`:

- `show running-config | section flow` (Cisco) or `display current-configuration | include netstream` (Huawei)
- `show flow exporter` / `display netstream export`
- `show flow monitor` / `display netstream`
- `show processes cpu history 1min` — 5-min baseline average
- `show processes memory | i Processor` — baseline
- `show interface <wan>` — baseline packets/sec and errors
- `show ip bgp summary` + `show ip ospf neighbor` — baseline adjacency state

The platform's `provisioning/capture-exporter-baseline.sh <device>` runs all of these over SSH and writes them under `evidence/`.

## 2. Change

Apply the per-vendor change file (`templates/exporters/cisco-fnf.cfg` or `templates/exporters/huawei-netstream.cfg`) with these guardrails:

- Sampling rate: **1:1000** on Internet edge, **1:100** on DCI. Start conservative; lower only after measuring.
- Flow timeout: `active 60`, `inactive 15`.
- Export destination: UDP/2055 → NetFlow VM mgmt IP; source interface = the device's loopback used for mgmt.
- Monitor applied **ingress only** on the WAN interface (one-direction-once rule).
- **No reload. No shutdown. No routing policy edit.** If the required change would need an interface flap or a reload, abort and schedule a maintenance window.

## 3. Post-change validation

- Reread the same five baseline commands. Expected deltas:
  - `show processes cpu history 1min` — ≤ +5 % absolute over 15 min.
  - `show interface <wan>` — no PPS or error delta beyond normal variance.
  - `show ip bgp summary` / `show ip ospf neighbor` — adjacency state unchanged.
- On the NetFlow VM: `curl -fsS http://127.0.0.1:8080/api/v0/inlet/flows-received | jq .` returns a non-zero flow count for the new exporter within 30 s.

If CPU rises >5 % absolute or any adjacency flaps:

- Automatic rollback: apply `templates/exporters/<vendor>-rollback.cfg`.
- Record incident under `evidence/exporters/<device>/incident-YYYYMMDD-HHMMSS/`.

## 4. Platform limits trigger rollback

- CPU on exporting device > baseline + 5 %, sustained 15 min
- Flow disk growth > 2 GiB/h sustained
- Inlet ingest 0 for > 5 min on a healthy exporter

All three are monitored by Zabbix (`templates/zabbix/akvorado-platform.yaml`). The first two trigger an operator-visible warning; the third page's the oncall.

## 5. Vendor notes

- **Cisco IOS-XE (C8500/ASR):** Flexible NetFlow is the right fit. `flow record TYPE-NetFlow-V9-FULL`, `flow monitor NETFLOW-MONITOR`, `flow exporter NETFLOW-EXP`. IPFIX is also supported.
- **Cisco NX-OS (Nexus):** NetFlow v9 as `feature netflow`. Confirm software license and release — some lines gate NetFlow behind a license tier.
- **Huawei (VRP):** NetStream v9. Command set varies by release (`netstream enable inbound`/`outbound`, `netstream export`). **Always consult the device's command reference first** — do not copy a command from a different family/VRP release. If the chassis is a newer VRP that supports IPFIX, prefer IPFIX.
- **Palo Alto:** NetFlow v9 via `Device → Setup → Operations → NetFlow Server Profiles` and per-interface enablement. Zone enforcement is unchanged.
- **FortiGate / FTD / F5:** NetFlow is supported on all three; version depends on OS release. Deploy only if the device's observation is not already covered by its upstream router (one-direction-once).

Device application is **owned by Codex / Ops** on an actual change-window. The platform repo ships the templates and the baseline/rollback automation.
