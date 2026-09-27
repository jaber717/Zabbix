# Network Utilization v1 — production installation

Network Utilization is independent of Network Availability. It modifies no Zabbix core file and requires no service restart.

## Install the signed Git release

Run from a temporary checkout on the Zabbix frontend host:

```bash
git clone --depth 1 --branch network-utilization-v1.0.0 https://github.com/jaber717/Zabbix.git
cd Zabbix
sudo ./scripts/install-network-utilization.sh
sudo ./scripts/verify-network-utilization.sh
```

Enable **Network Utilization** in Administration → General → Modules, then add the widget to a dashboard. Use **Edit links** to create production-specific Sites and Links.

Configuration is preserved at `/var/lib/zabbix/network-utilization/link-definitions.json` across upgrades and rollback. Capacity overrides must be entered in bits per second and should only be used where Zabbix has no trustworthy speed Item.

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
