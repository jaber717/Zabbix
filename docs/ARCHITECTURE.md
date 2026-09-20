# Architecture

## Deployment

One RHEL 9.x x86_64 host runs Zabbix Server 7.0.30, PostgreSQL 16, nginx,
PHP-FPM, and Zabbix Agent 2 under systemd. PostgreSQL listens only on loopback;
the server uses `DBHost=127.0.0.1` with SCRAM-SHA-256. This release does not add
containers, an external database, Zabbix HA, traps, or a second orchestrator.

The entry point converts a protected root-owned configuration file into
ephemeral files below `/run`, verifies an immutable offline bundle, and invokes
the retained Ansible roles locally. All DNF installation transactions disable
every repository except the generated `file://` repository.

## Connected and airgapped paths

Both modes converge on the same local bundle:

- `connected`: an authorized RHEL 9.x staging host runs
  `scripts/stage-offline-bundle.sh`. If `OFFLINE_BUNDLE_ROOT` is empty,
  `install.sh` stages locally first.
- `airgapped`: the operator transfers an already generated bundle and sets
  `OFFLINE_BUNDLE_ROOT` to its extracted release tree.

RPMs are transport artifacts, never Git content. The 313-package lock permits
167 BaseOS packages, 132 AppStream packages, 13 official Zabbix packages, and
one official Zabbix non-supported package (`fping`) under a package-specific
assertion. EPEL is unused.

## Security boundaries

SELinux remains Enforcing. The vendor Zabbix policy is required; only
`httpd_can_network_connect_db` and `zabbix_can_network` are enabled. Firewalld
uses explicit source-CIDR rich rules for the frontend, TCP/10051, and TCP/10050.
UDP/162 is not opened. SNMP polling leaves the server toward devices on UDP/161.

Runtime DB and Admin passwords are never arguments or tracked files. The DB
password is sealed with a host-bound systemd credential. The frontend receives
its DB configuration only in `/run`.

## Initial sizing

Final device and interface counts are unknown. The baseline is intentionally
modest: five pollers, one pinger, four-second timeout, 32 MiB main cache,
16 MiB history cache, 4 MiB trend cache, and 8 MiB value cache.

**INITIAL BASELINE — REASSESS AFTER DEVICE COUNT IS CONFIRMED.** Review poller
busy percentage, queue depth, database connections, cache utilization, and
interface count before changing `StartPollers`, `StartPingers`, `Timeout`,
`CacheSize`, `HistoryCacheSize`, or `ValueCacheSize`.
