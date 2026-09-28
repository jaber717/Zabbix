# Device Health & Capacity v1.0.0 LAB validation

Date: 2026-09-28

Environment: RHEL 9.6, Zabbix 7.0.30, PHP 8.3.19

Scope: isolated LAB only; production was not accessed.

## Result

- Live authenticated widget render: PASS
- Module install / verify / checksum: PASS
- Real Chromium component fixture: PASS
- Real Chromium live-LAB render: PASS
- Blue/light and Dark: PASS
- Widths 2200, 1920, 1440, 1200, 900, 640, 420 px: PASS
- Domain/static/shell/PHP/JavaScript tests: PASS
- Network Availability regression: PASS (41 resolver + 11 configuration assertions)
- Network Utilization regression: PASS (27 analytics + persistence + performance + static)

## Live data-path evidence

The live render resolved five monitored hosts, 261 Items, four evidence-based capability profiles, and six current Zabbix problems. The collector made four bulk API calls and no history/trend calls.

| Metric | Result |
|---|---:|
| API calls | 4 |
| History rows | 0 |
| Trend rows | 0 |
| Collector | 79.702 ms |
| Resolver | 0.377 ms |
| Total server-side widget | 81.041 ms |

Profiles observed: `firewall`, `linux_host`, `load_balancer`, `router_switch`.

The four network devices are intentional LAB mock objects with non-routable management addresses. Their current no-poll conditions validate problem/freshness presentation, not vendor hardware telemetry. No production or physical vendor hardware validation is claimed.

## Storage rollup decision

Live Linux discovery exposed `/`, `/home`, and `/boot`. `/` and `/home` are included in the main worst-storage rollup. `/boot` remains visible in Details but is excluded from the main rollup because the current template/item evidence does not establish an explicit operational rollup policy for it. This unresolved pattern is documented rather than guessed.

## Deferred item

Pinned trends are deferred from v1.0.0. The core Matrix, Needs Attention, and Details release is complete and bounded. No unsafe per-device history shortcut or N+1 collection was added.
