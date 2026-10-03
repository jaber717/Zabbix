# Grafana dashboards-as-code

Codex delivers `grafana-01` LXC with the `alexanderzobnin-zabbix-app` plugin installed and three accounts in `claude-access/grafana.env` (admin, noc viewer, zabbix-grafana API user). Claude owns the datasource + dashboards from this directory.

## Layout

```
grafana/
├── README.md
├── provisioning/
│   ├── datasources/zabbix.yaml       # Zabbix datasource via alexanderzobnin plugin, uid=zbx-noc
│   └── dashboards/noc.yaml           # dashboard provider → /var/lib/grafana/dashboards/netops-noc
├── dashboards/
│   └── noc-wan-overview.json         # 6-panel wallboard (3×2 at ≥1920px), itemid mode
├── drafts/
│   └── noc-device-health.json        # placeholder; apply-grafana.sh deliberately skips drafts/
└── bin/
    └── apply-grafana.sh              # api | files
```

## Deploy

### Mode `api` (no SSH to grafana-01 required)

```bash
bash grafana/bin/apply-grafana.sh api
```

Reads `claude-access/grafana.env`, verifies the Zabbix plugin is installed, upserts the datasource (`uid=zbx-noc`), the folder (`uid=netops-noc`), and every dashboard under `grafana/dashboards/`. Secrets are base64-decoded in memory, never printed, never written.

### Mode `files` (true dashboards-as-code; requires SSH to grafana-01)

```bash
bash grafana/bin/apply-grafana.sh files
```

Rsyncs `provisioning/` into `/etc/grafana/provisioning/` and dashboards into `/var/lib/grafana/dashboards/netops-noc/`, then reloads grafana-server. Prefer this mode when `grafana-01` appears in `ssh-config`.

## NOC — WAN Overview

Six fixed panels on a 24-column grid, each `w=8 h=10` → **3 columns × 2 rows** at ≥1920 px. Positions are stable:

| Slot | Host | IN itemid | OUT itemid |
|---|---|---|---|
| STC | PNET-STC | 51487 | 51496 |
| MOBILY | PNET-MOBILY | 51751 | 51760 |
| SAIX-A | PNET-SAIX-A | 51610 | 51619 |
| SAIX-B | PNET-SAIX-B | 51528 | 51537 |
| SITE-A | PNET-SITE-A | 51661 | 51679 |
| SITE-B | PNET-SITE-B | 51570 | 51585 |

Each panel uses the Zabbix datasource in **item-ID mode** (`queryType: "3"`, `itemids` as a single string per the alexanderzobnin plugin contract) — one itemid per target. `refId A` is always IN (green #2EA043) and `refId B` is always OUT (blue #1F6FEB), applied consistently across all six panels. For the fixed six-slot LAB wallboard the itemids are the source of truth; `apply-grafana.sh` verifies each one against the live Zabbix datasource before marking the dashboard provisioned.

Unit `bps`, auto-scaled by Grafana to Kbps/Mbps/Gbps. IN is green, OUT is blue. Dark theme. 30 s refresh. 1H default; the picker exposes 6H / 24H / 7D.

## Verification plan (runs once grafana-01 is reachable)

1. `apply-grafana.sh api` returns 0.
2. `GET $GRAFANA_URL/api/health` → `{"database":"ok"}`.
3. `GET $GRAFANA_URL/api/datasources/uid/zbx-noc` → `type=alexanderzobnin-zabbix-datasource`.
4. `GET $GRAFANA_URL/api/dashboards/uid/noc-wan-overview` returns the dashboard with 6 panels, each with 2 targets.
5. For each panel: `POST $GRAFANA_URL/api/ds/query` with its target → non-empty frames (confirms live Zabbix roundtrip).
6. One controlled traffic generation on one PNET router (ICMP flood from the lab controller via pnet-jump) — verify the matching panel's live value moves within ~30 s.
7. Screenshot in a real Chrome at 1920 and 2200: all six graphs visible without vertical scrolling.

Steps 1–5 produce signed JSON evidence; the final screenshot is a visual check captured only after the end-to-end API path returns real frames.
