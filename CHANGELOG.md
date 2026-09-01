# Changelog

## Unreleased

### Added

- Revalidated M4 after the reported four-permission NetBox grant. The installed
  service credential still received HTTP 403 for VMs, VM interfaces, tags, and
  custom fields; existing device/DCIM/IP/schema reads still passed. A fresh
  dry-run kept all 81 device eligibility decisions UNKNOWN, proposed no changes,
  and stopped before Zabbix credential creation, apply, or second reconcile.
- Implemented and deployed M4's fail-closed `netbox-zabbix-sync` engine with
  GET-only NetBox access, stable device/VM identity, explicit mappings,
  deterministic primary-IP resolution, guarded planning/apply, 10% change
  budget, encrypted systemd credentials, dedicated `nbzsync` account, hardened
  service/timer, 29 passing tests, and an operations runbook.
- Executed two byte-identical live dry-runs against authoritative NetBox LXC
  9000 and Zabbix `192.168.1.91`. Devices, DCIM interfaces, IP addresses, and
  mapping schema resources were readable; VM, VM-interface, tag, and
  custom-field endpoints returned 403. Zero Zabbix changes were proposed or
  applied, denied counts remained UNKNOWN, and M4 closed blocked on the four
  exact read permissions plus a scoped Zabbix apply credential.
- Resolved the earlier version contradiction: NetBox and portal health report
  4.6.9 with API 4.6; `manage.py version` returned Django 6.0.8, not NetBox 6.0.8.
- Completed M3 on the authorized dual-purpose RHEL 9.6 host at
  `192.168.1.91`: preserved the existing NetBox/PostgreSQL workload, deployed
  Zabbix 7.0.30 from the accepted offline artifact, passed runtime/API/queue,
  zero-change convergence, check-mode, reboot, backup, security-control, and
  safe negative gates, and recorded the host's transition from pristine Build
  VM to Zabbix home-lab runtime. Destructive restore remains `NOT-EXECUTED`.
- Hardened M3-discovered runtime behavior without widening architecture or
  package sources: shared-service-safe PostgreSQL/nginx handling, protected
  systemd runtime credentials, explicit SELinux runtime labels, schema-owner and
  PID alignment, exact offline firewalld locking, handler/recovery sequencing,
  protected backup streaming, and read-only CIDR/TLS validation in check mode.
- Began M3 under the approved home-lab architecture amendment: deploy and
  runtime-validate logical `ZABBIX-01` only on the existing RHEL 9.6 VM at
  `192.168.1.91`, after a mandatory read-only database/service coexistence
  preflight. No new VM, NetBox integration, M4 work, or external push is allowed.
- Completed M2 offline installer and configuration automation against the
  immutable accepted M1 artifact: checksum-verifying bootstrap, separated
  Ansible roles, protected runtime credentials, TLS/SELinux/firewalld controls,
  backup and upgrade tooling, installed-state verification, and operational
  runbooks. Static/offline gates passed; dedicated-target runtime tests remain
  explicitly assigned to M3, which was not started.
- Began M1 with the RHEL 9.6/Zabbix 7.0.30 compatibility profile and selected
  PostgreSQL 16, PHP 8.3, nginx 1.24, and CPython 3.11.
- Added the isolated RPM resolver, upstream modular-metadata preservation,
  temporary-keyring signature verification, local-only install validation,
  deterministic lock/manifests, allow-listed artifact assembly, wheel pipeline,
  reproducibility comparison, and safe negative-test automation.
- Added the M1 offline-build, architecture, and material-decision documentation.
- Recorded the mandatory M1 stop: Zabbix Server requires `fping`, but no provider
  is available from the approved BaseOS, AppStream, and official Zabbix sources.
  No unapproved repository, artifact, or downstream PASS result was introduced.
- Resumed M1 under a narrow source-policy amendment permitting the official
  Zabbix non-supported RHEL 9 repository to provide only the pinned and
  signature-verified `fping-0:5.1-1.el9.x86_64` package; EPEL remains prohibited.
- Split mutually exclusive PostgreSQL/SQLite proxy installation checks into
  separate disposable roots and narrowed closure generation to required
  dependencies for the PostgreSQL/nginx target.
- Normalized RPM and repository-metadata timestamps to the source-date epoch so
  meaningful reproducibility includes a stable artifact file allow-list.
- Completed M1 with two fresh clean builds: 313 locked and signature-verified
  RPMs, preserved PostgreSQL 16/PHP 8.3/nginx 1.24 module metadata, local-only
  installs, an allow-listed offline artifact, nine passing negative tests, and
  a passing reproducibility comparison including byte-identical repository
  content.
- Milestone 0 repository scaffold and durable specifications.
- Capability, Proxmox, NetBox, portal-source, Internet, and build-VM discovery
  evidence.
- Discovery report, required-evidence procedures, milestone plan, and project
  status.
- Resumed M0 Build VM discovery: verified RHEL 9.6/x86_64, module/Python/storage
  facts, subscription-manager read output, and current DNF repository state.
- Recorded that M1 remains blocked on verified usable BaseOS/AppStream and other
  approved source repositories in the clean build context.
- Completed M0.5: enabled only standard RHEL 9 BaseOS/AppStream, verified official
  Zabbix 7.0.30 package metadata and signing-key information, and passed isolated
  clean-installroot source/dependency resolution with NetBox repositories excluded.
- Resolved the M1 source-readiness blocker; M1 subsequently began only after
  explicit approval.
