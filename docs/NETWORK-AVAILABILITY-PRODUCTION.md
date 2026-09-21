# Network Availability production deployment

This procedure installs the LAB-validated Network Availability widget from the
immutable `availability-v1.0.2` tag. It does not modify Zabbix core files,
restart services, or invent production Node topology.

## Install from GitHub

Run on the production Zabbix frontend VM:

```bash
git clone https://github.com/jaber717/Zabbix.git
cd Zabbix
git fetch --tags origin
git checkout --detach availability-v1.0.2
test "$(git rev-parse HEAD)" = "$(git rev-list -n 1 availability-v1.0.2)"
sha256sum --check scripts/network-availability-release.sha256
sudo ./scripts/install-network-availability.sh
sudo ./scripts/verify-network-availability.sh
```

The installer supports RHEL 9, Zabbix 7.0.x, and PHP 8.1 or newer in the PHP 8
series. It detects the frontend/module path, validates the release before any
change, adopts existing module ownership, installs directories as 0755 and
files as 0644, and performs no service restart. An existing module is moved to
`NetworkAvailability.backup-YYYYMMDD-HHMMSS`. Existing
`config/node-definitions.json` is preserved during an upgrade.

In Zabbix 7.0, open **Administration → General → Modules**, select **Scan
directory** if the module is not listed, enable **Network Availability v1**,
and add the **Network Availability v1** widget to the intended dashboard.

## Configure Nodes

The installed default remains deliberately empty, so unmatched Hosts appear as
`UNCLASSIFIED / Configuration required`. Copy fields from
`config/node-definitions.example.json` only after replacing every fake example
with operator-approved production values. Configure Site, Node name, members,
kind, aggregation policy (`MIN_N_REQUIRED` and `min_n` where appropriate),
criticality, order, and each member's availability item/source. Never treat the
example `DC-01`, `Internet Edge`, `RTR-01`, or `RTR-02` values as production.

After editing the installed configuration, run:

```bash
sudo ./scripts/verify-network-availability.sh
```

## Upgrade

From a clean checkout of a future immutable tag, verify its tag and release
checksums, then run the same install and verify commands. The installer backs
up the current module and preserves the active Node definition.

## Rollback

First disable **Network Availability v1** under **Administration → General →
Modules**. Restore the newest installer-created backup:

```bash
sudo ./scripts/rollback-network-availability.sh --confirm-module-disabled --restore-latest
```

Rollback validates the backup's structure and PHP syntax before restoring it.
An older backup may predate the `VERSION` and `RELEASE.sha256` markers, so the
current release verifier is not expected to pass against such a legacy module.

If this was the first installation and no backup exists, move the module out of
the Zabbix scan path without deleting it:

```bash
sudo ./scripts/rollback-network-availability.sh --confirm-module-disabled --remove-current
```

Return to **Administration → General → Modules** and scan the directory again
if required. The scripts never delete unrelated modules or restart Zabbix,
nginx, or PHP-FPM.
