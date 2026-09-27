# Network Utilization 1.3.0

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
- Hidden Links remain monitored and counted but are omitted from the main table and Site cards.
- The details chart plots actual Zabbix sample times and bits per second. Its Y-axis follows observed traffic, not interface capacity. The 7-day range uses hourly Zabbix trend averages; shorter ranges use bounded raw history. The tooltip shows a direction as unavailable when no sufficiently close sample exists.

Runtime configuration is stored outside the module at:

`/var/lib/zabbix/network-utilization/link-definitions.json`

The installer preserves this file and its last-known-good copy. Production-specific Hosts, interfaces, Sites, aliases and capacities are never stored in source control.

Use **Edit links → Add link** to choose a monitored Host and one of its interfaces. Do not enter item IDs or ifIndex values.

## NOC interface

The compact attention rows distinguish operational alerts from neutral configuration/data issues. The Top Links view supports Current, P95, Remaining, Errors and Discards sorting; clicking the active sort reverses direction. Long identity text truncates in the list and remains available in Details. The inspector pairs every label with its value and retains the traffic chart's real-time and throughput axes. The 1h/6h/24h/7d range buttons redraw the existing bounded history/trend datasets. Blue and Dark themes and narrow dashboard cells use the same module components; no new API calls are made for presentation.
