# Network Utilization 1.4.0

A Zabbix 7.0 widget for operator-selected network Links. It reads existing Zabbix Items; it does not poll devices.

## Data semantics

- Stable Link identity is monitored Host name plus interface name. ifIndex is resolved only at runtime.
- IN and OUT utilization are calculated independently; ranking uses the greater direction.
- `bps` rate Items are used directly. `Bps` rate Items are converted once to bits per second.
- Physical port speed is informational. Monitored capacity comes from a fresh interface-speed Item only when `capacity_source=interface_speed`, or from explicit IN/OUT service bandwidth when `capacity_source=service_override`. All utilization, P95 percentages, sustained state and remaining capacity use monitored capacity, independently by direction. Unconfigured capacity never produces a percentage.
- The v1 runtime schema remains readable. A legacy `capacity_override_bps` is migrated to symmetric IN/OUT service capacity when loaded; existing Links and the runtime file are preserved.
- Symmetric service bandwidth needs one input; the server copies it to both directions before validating. Physical speed is not required for service override. Unchanged auto-speed Links with missing speed remain in a visible configuration-warning state without blocking an unrelated service-capacity edit.
- P95 uses a bounded 24-hour history query and requires at least 20 samples. Seven-day details use trends when available.
- Errors and discards remain separate and counter resets do not create false deltas.
- All configured Links remain monitored and visible in the operator Link index; the existing `visible` field remains preserved for configuration compatibility.
- Operators explicitly select persistent dashboard graphs with **Add to graphs**. Selection and order are stored as `show_graph` and `graph_order` in the existing runtime document; legacy Links migrate to unpinned. There is no automatic highest-utilization or first-Link graph selection.
- Pinned graphs are vertically stacked, share one global 1h/6h/24h/7d range, and remain independent from Link-list search and sorting. Add/remove/reorder uses the existing authenticated RBAC/CSRF configuration action.
- History and seven-day trends remain bounded bulk reads. Multiple graphs reuse the same collected Link datasets and never create an API call per graph.
- The details chart plots actual Zabbix sample times and bits per second. Its Y-axis follows observed traffic, not interface capacity. The 7-day range uses hourly Zabbix trend averages; shorter ranges use bounded raw history. The tooltip shows a direction as unavailable when no sufficiently close sample exists.

Runtime configuration is stored outside the module at:

`/var/lib/zabbix/network-utilization/link-definitions.json`

The installer preserves this file and its last-known-good copy. Production-specific Hosts, interfaces, Sites, aliases and capacities are never stored in source control.

Use **Edit links → Add link** to choose a monitored Host and one of its interfaces. Do not enter item IDs or ifIndex values.

## NOC interface

The compact Link index supports configured order, Current, P95, Remaining, and Errors/Discards sorting. Each row exposes current IN/OUT throughput, utilization micro-bars, P95, remaining capacity, quality counters, and graph controls without requiring Details. Capacity-unconfigured rows show the warning once while retaining raw traffic. The inspector retains the same chart engine used by pinned graphs. Blue and Dark themes and narrow dashboard cells use the same module components; graph presentation adds no per-Link API calls.
