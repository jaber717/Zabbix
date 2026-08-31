# SPEC-05 — Deliverables

## Repository

The source repository separates compatibility data, environments, build logic,
bootstrap, Ansible, integration code, lab fixtures, tests, scripts, documentation,
and evidence. Empty future areas remain placeholders until their milestone; fake
production code is prohibited.

## Release output

Each release produces a curated artifact tarball, `SHA256SUMS`, individual
checksum, `MANIFEST.txt`, `RPM-MANIFEST.txt`, `BUILD-INFO.json`, and `CHANGELOG`.
Artifacts exclude working-tree history, unnecessary development/lab content, raw
credentials, and secret-bearing evidence.

## Documentation

The operational set should grow only when real implementation warrants it:
`README-FIRST.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `OFFLINE-BUILD.md`,
`INSTALL.md`, `OPERATIONS.md`, `BACKUP-RESTORE.md`, `UPGRADE.md`,
`NETWORK-FLOWS.md`, and `CORPORATE-TRANSFER.md`, plus `PLAN.md`, `CHANGELOG.md`,
and `PROJECT-STATUS.md`. Git history is the primary journal.

## Corporate template and validator

Provide `environments/corporate-template/` with example site and mapping files and
instructions. A readiness validator must reject `CHANGE_ME`, missing mandatory
values, invalid CIDRs, absent certificates/NetBox URL, unsupported compatibility
profiles, and lab-value leakage. Corporate adoption must require configuration
replacement, not source edits.

## Evidence and handover

Evidence contains real, sanitized outputs only. Every acceptance item uses the
four allowed statuses. Handover includes release identity, compatibility profile,
hashes, manifests, installation/upgrade/restore procedures, known limitations,
test evidence, and credential/certificate ownership instructions without values.

## Versioning

Use semantic versioning: PATCH for compatible packaging/fixes, MINOR for new
backward-compatible capability, and MAJOR for schema/major-Zabbix migration or
breaking procedure. The anticipated Zabbix 7 platform is v1.x; a controlled
Zabbix 8 migration is v2.0.0 only after approval.

## Definition of Done

A production release is done only when it builds reproducibly from declared
inputs, installs on fresh disconnected RHEL from the same scanned artifact,
converges idempotently, keeps SELinux/firewalld enabled, passes backup/restore and
negative tests, verifies hashes/signatures, prevents destructive lifecycle
actions, contains no secrets or lab leakage, and transfers to the corporate
template without source changes. Unexecuted tests remain visible and block any
gate that requires them.
