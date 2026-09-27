# Network Utilization v1.4 validation

Validated in the isolated LAB on 2026-09-27. Production was not accessed.

## Authenticated LAB validation

- Zabbix module: `Network Utilization 1.4.0`, enabled on Zabbix 7.0.30.
- Candidate interface: `ZABBIX-01 / ens18` (the only live interface candidate available in the LAB).
- Empty configuration: no graph selected automatically; 2 bulk API calls, 0 history rows, 0 trend rows, 73.073 ms server-side widget time.
- Explicitly pinned configuration: selection and order survived a save and dashboard reload.
- Pinned render: 4 bulk API calls, 1,553 history rows, 36 trend rows, 6.414 ms graph-history collection, 79.250 ms collector, 0.769 ms analytics, 81.265 ms total widget time.
- Native Zabbix history and seven-day trend averages matched the normalized chart data.
- Service-capacity, utilization, P95, remaining-capacity, quality, stale-state and invalid-configuration checks passed.
- The test restored the LAB runtime configuration to an empty document at revision 45.

## Real-browser component validation

The fixture renders the production `widget.view.php`, module CSS, chart renderer, and widget controller with Zabbix-shaped data. Headless Chrome passed:

- Blue/light and Dark themes at 1200, 900, 640 and 420 px.
- No page, Link-list, or pinned-graph overflow at any tested width.
- Link-list sorting and filtering remain independent from pinned graph order/visibility.
- Add, remove, reorder and refresh persistence for operator-selected graphs.
- Zero-graph state does not select the highest-utilization Link.
- Five simultaneous graph blocks update together for 1h, 6h, 24h and 7d.
- Real timestamp axes, shared IN/OUT throughput scale, tooltip and crosshair.
- Unknown capacity retains raw traffic and suppresses percentages/micro-bars.
- Read-only users see graphs but no Add/Remove/Reorder controls.
- No browser exceptions.

Screenshots in this directory cover the main dashboard and pinned graph stack in Blue/light and Dark at representative desktop and narrow widths.

## Bulk collector scaling check

An isolated LAB test exercised the real collector/resolver with the same ten configured Links while varying only the pin count. Mocked Zabbix API payloads make these CPU timings suitable for detecting N+1 behavior, not for estimating network latency.

| Pinned graphs | API calls | History rows | Trend rows | Collector | Analytics | Total |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 4 | 480 | 140 | 0.596 ms | 0.470 ms | 1.100 ms |
| 1 | 4 | 480 | 140 | 0.481 ms | 0.719 ms | 1.222 ms |
| 5 | 4 | 480 | 140 | 0.502 ms | 0.422 ms | 0.978 ms |
| 10 | 4 | 480 | 140 | 0.527 ms | 0.479 ms | 1.030 ms |

The constant four calls prove the pinned graph count does not introduce one API request per graph. The collector intentionally retains bounded history/trend data for every configured Link so the Details chart remains available for unpinned Links.
