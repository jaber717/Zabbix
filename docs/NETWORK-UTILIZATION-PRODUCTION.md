# Network Utilization v1.4.0 — production upgrade

Network Utilization is independent of Network Availability. It modifies no Zabbix core file and requires no service restart.

## Upgrade from v1.2.1

Run from a temporary checkout on the Zabbix frontend host:

```bash
git clone --depth 1 --branch network-utilization-v1.4.0 https://github.com/jaber717/Zabbix.git
cd Zabbix
sha256sum -c scripts/network-utilization-release.sha256
sudo ./scripts/install-network-utilization.sh
sudo ./scripts/verify-network-utilization.sh
```

Refresh the Zabbix frontend and confirm that Network Utilization reports version 1.4.0 in Administration → General → Modules. Existing dashboards, Links, service capacities, and runtime configuration remain in place. Existing Links initially have no pinned graph until an authorized operator uses **Add to graphs**.

Configuration is preserved at `/var/lib/zabbix/network-utilization/link-definitions.json` across upgrades and rollback. Existing `capacity_override_bps` values are interpreted as symmetric service bandwidth on load. Use Edit links to choose Auto — interface speed or Service / circuit bandwidth. A 1 Gbps Ethernet port carrying a 50 Mbps circuit needs the 50 Mbps service override; physical speed is not the service-utilization denominator. Asymmetric IN/OUT values are supported. Links with unresolved automatic speed show a configuration warning until service capacity is set or the warning is explicitly accepted.

The details chart uses bounded Zabbix history for 1h, 6h and 24h. Its 7d range uses hourly trend averages. Its X-axis uses actual timestamps and its Y-axis follows observed bits per second, independent of both physical and service capacity.

## Rollback

Disable the module in the Zabbix UI first, then restore the most recent module backup:

```bash
sudo ./scripts/rollback-network-utilization.sh --confirm-module-disabled --restore-latest
```

To move the current module out of the scan path without deleting it:

```bash
sudo ./scripts/rollback-network-utilization.sh --confirm-module-disabled --remove-current
```

Rollback never deletes operator Link configuration.
