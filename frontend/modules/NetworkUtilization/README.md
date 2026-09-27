# Network Utilization 1.0.0

A Zabbix 7.0 widget for operator-selected network Links. It reads existing Zabbix Items; it does not poll devices.

## Data semantics

- Stable Link identity is monitored Host name plus interface name. ifIndex is resolved only at runtime.
- IN and OUT utilization are calculated independently; ranking uses the greater direction.
- `bps` rate Items are used directly. `Bps` rate Items are converted once to bits per second.
- Capacity comes from a fresh speed Item or an explicit operator override. Unknown capacity never produces a percentage.
- P95 uses a bounded 24-hour history query and requires at least 20 samples. Seven-day details use trends when available.
- Errors and discards remain separate and counter resets do not create false deltas.
- Hidden Links remain monitored and counted but are omitted from the main table and Site cards.

Runtime configuration is stored outside the module at:

`/var/lib/zabbix/network-utilization/link-definitions.json`

The installer preserves this file and its last-known-good copy. Production-specific Hosts, interfaces, Sites, aliases and capacities are never stored in source control.

Use **Edit links → Add link** to choose a monitored Host and one of its interfaces. Do not enter item IDs or ifIndex values.
