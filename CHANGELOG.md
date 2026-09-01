# Changelog

## Unreleased

### Added

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
