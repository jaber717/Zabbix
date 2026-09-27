# Network Availability production deployment

This procedure installs the LAB-validated Network Availability widget from the
immutable `network-availability-v1.3.0` tag. It does not modify Zabbix core files,
restart services, or invent production Node topology.

## Install from GitHub

Run on the production Zabbix frontend VM:

```bash
git clone --depth 1 --branch network-availability-v1.3.0 https://github.com/jaber717/Zabbix.git
cd Zabbix
sha256sum --check scripts/network-availability-release.sha256
sudo ./scripts/install-network-availability.sh
sudo ./scripts/verify-network-availability.sh
```

The installer supports RHEL 9, Zabbix 7.0.x, and PHP 8.1 or newer in the PHP 8
series. It detects the frontend/module path, validates the release before any
change, adopts existing module ownership, installs directories as 0755 and
files as 0644, and performs no service restart. An existing module is moved to
`NetworkAvailability.backup-YYYYMMDD-HHMMSS`. Persistent configuration lives at
`/var/lib/zabbix/network-availability/node-definitions.json`, owned by the
detected PHP-FPM worker with directory mode 0750 and file mode 0640. It survives
module upgrades and code rollback.

In Zabbix 7.0, open **Administration → General → Modules**, select **Scan
directory** if the module is not listed, enable **Network Availability v1**,
and add the **Network Availability v1** widget to the intended dashboard.

## Configure Nodes

The installed default remains deliberately empty, so unmatched Hosts appear as
**Unassigned** with Tier unset. Administrators with the native Zabbix
Administration → General permission can use **Assign to site →** or **Edit
sites** in the widget. Read-only and kiosk users do not receive editing controls.
The fake `config/node-definitions.example.json` remains reference-only.

After editing, verify the runtime file and module installation:

```bash
sudo ./scripts/verify-network-availability.sh
```

## Upgrade

From a clean checkout of an immutable tag, verify its release checksums, then run
the same install and verify commands. The installer backs
up module code and preserves the external runtime configuration.

## Rollback

First disable **Network Availability v1** under **Administration → General →
Modules**. Restore the newest installer-created backup:

```bash
sudo ./scripts/rollback-network-availability.sh --confirm-module-disabled --restore-latest
```

Rollback validates the backup's structure and PHP syntax before restoring it.
An older backup may predate the `VERSION` and `RELEASE.sha256` markers, so the
current release verifier is not expected to pass against such a legacy module.
The runtime Site/Node configuration is never removed or rolled back with module
code.

If this was the first installation and no backup exists, move the module out of
the Zabbix scan path without deleting it:

```bash
sudo ./scripts/rollback-network-availability.sh --confirm-module-disabled --remove-current
```

Return to **Administration → General → Modules** and scan the directory again
if required. The scripts never delete unrelated modules or restart Zabbix,
nginx, or PHP-FPM.
