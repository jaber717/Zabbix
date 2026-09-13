# Existing Zabbix Work Inventory

Date: 2026-09-13

The running RHEL host `netbox-dev` is source material only.
This inventory was collected read-only before release construction. Credential
file names are recorded where operationally necessary; values were not read.

| Path | Type / purpose | Active | Decision | Reason |
|---|---|---:|---|---|
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform` | Existing source repository with accepted discovery, build, installation, and integration work | No | KEEP | Primary engineering source and audit trail; it was not turned directly into the publication repository. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\installer` | Offline bootstrap and Ansible roles | N/A | REWORK | Proven on the lab runtime; retain generic roles but add a simple release entry point, clean-database guards, Admin credential setup, and sanitized configuration. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\build` | Clean-installroot offline staging implementation | N/A | REWORK | Preserve deterministic resolution, module metadata, signature, provenance, and checksum mechanics; exclude generated work roots and payloads. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\compat\zabbix-7.0.yaml` | Exact target/version/source policy | N/A | KEEP | Pins RHEL 9.6 x86_64, Zabbix 7.0.30, PostgreSQL 16, PHP 8.3, and nginx 1.24. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\rpm-lockfile.txt` | 313-entry package lock/provenance manifest | N/A | KEEP | Reproducibility input; contains no RPM payload. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\dist\m1-accepted-build2\zabbix-rhel96-offline-1.0.0-build1.tar.gz` | 178,093,296-byte local airgap bundle | No | EXCLUDE | Verified local operator artifact containing RPMs, including Red Hat content; never publish to GitHub. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\evidence` | Historical raw logs and milestone evidence | No | EXCLUDE | Valuable locally but contains lab paths, addresses, runtime facts, and excessive source-system detail. Summarize only sanitized results. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\environments\lab` | Current lab inventory and variables | No | EXCLUDE | Contains lab-specific hosts, addresses, listener choices, and source-system details. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\integration\netbox_zabbix_sync` | Custom standard-library NetBox-to-Zabbix reconciler | Yes, deployed copy | REWORK | Preserve sanitized reusable code and tests; deployment must be optional and disabled by default. |
| `C:\Users\jaber\Documents\Home-Server\zabbix-platform\integration\mappings\lab.json` | Current NetBox role/platform/site mappings | Yes, deployed copy | EXCLUDE | Contains current environment policy and site naming; replace with a generic example. |
| `/etc/systemd/system/netbox-zabbix-sync.service` | Hardened custom reconciliation service | Timer-driven | REWORK | Preserve a sanitized optional unit template; do not enable it by default. |
| `/etc/systemd/system/netbox-zabbix-sync.timer` | Approximately ten-minute dry-run schedule | Yes | REWORK | Preserve as optional example only; fresh deployment stays disabled. |
| `/usr/libexec/netbox-zabbix-sync/netbox_zabbix_sync/` | Deployed custom Python source, not RPM-owned | Yes | KEEP | Matches reusable project code; release copy comes from reviewed source control, not the live filesystem. |
| `/etc/netbox-zabbix-sync/` | Live sync endpoints, mappings, and CA | Yes | EXCLUDE | Runtime configuration contains internal endpoints and environment-specific policy. |
| `/etc/credstore.encrypted/nbzsync-*` | Host-encrypted integration credentials | Yes | EXCLUDE | Credential material must never be copied, documented by value, or published. |
| `/var/lib/netbox-zabbix-sync/` | Current reconciliation reports | Yes | EXCLUDE | Contains current operational inventory counts and state. |
| `/etc/zabbix/` | Running Zabbix server, Agent 2, and frontend configuration | Yes | EXCLUDE | Never copy live configuration; generate templates/configuration from installer variables. |
| `/opt/zabbix-offline/release/` | Installed accepted 313-RPM offline release | Yes | EXCLUDE payload / KEEP manifests | Preserve only sanitized locks, source policy, and staging logic; do not publish RPMs or the installed tree. |
| `/opt/zabbix-offline/installer/` | Deployed installer snapshot | Yes | EXCLUDE | Release source is taken from the reviewed repository, not runtime files. |
| `/var/backups/zabbix-offline/` | Root-private operational backups | Timer-managed | EXCLUDE | Database/configuration backups are runtime data and must never enter Git. |
| `/home/jaber/zabbix-platform-m1-*` | Historical M1 build worktrees | No | EXCLUDE | Superseded build work and generated state. |
| `/home/jaber/m3-*`, `/home/jaber/m4-*` | Historical validation logs/work directories | No | EXCLUDE | Retain locally only; do not publish lab evidence or data. |

## Existing offline bundle audit

The accepted bundle was generated twice in fresh empty RPM/install roots. Its
313 locked RPMs came from RHEL BaseOS (167), RHEL AppStream (132), the official
Zabbix repository (13), and the official Zabbix non-supported repository solely
for `fping` (1). EPEL contributed 0 packages and no other repository contributed
content. Module metadata for PostgreSQL 16, PHP 8.3, and nginx 1.24 was retained;
all RPM signatures and payload checksums passed. The bundle remains a local
operator artifact because it contains redistributable-restricted Red Hat RPMs.

## Test capacity decision

Proxmox read-only inventory found stopped QEMU guests `PNET4.2.4`, `EVE-LAB`,
and `Ansible`, plus active production/lab workloads. None is identified or
approved as a disposable clean RHEL 9.6 installation target. No guest was
started, stopped, cloned, created, or reconfigured. Clean installation and
reboot qualification therefore remain `UNTESTED` unless a disposable target is
separately approved.
