# SPEC-00 — Constraints

This is the highest-priority project specification. If another document or an
implementation conflicts with it, stop and resolve the conflict explicitly.

## Hard prohibitions

- Discovery must never write to NetBox LXC 9000 or create/change NetBox objects,
  credentials, schema, permissions, webhooks, or data.
- Existing Proxmox guests, storage, bridges, and unrelated networking must not be
  stopped, deleted, resized, cloned, migrated, or reconfigured during discovery.
- Normal project code must never automatically call `host.delete` or unlink a
  Zabbix template.
- Install and upgrade paths must never drop or destructively initialize an
  existing database or remove an existing PostgreSQL data directory.
- SELinux must remain Enforcing. `setenforce 0` and permanent permissive mode are
  prohibited workarounds.
- Passwords, API tokens, SNMP credentials, private keys, and personal secrets
  must not be committed, printed in documents, or saved as evidence.
- Do not collect application content or personal/private home-lab data.
  Infrastructure metadata is the discovery boundary.
- Never fabricate results, versions, addresses, inventory, package availability,
  repository state, command output, or test evidence.
- Stop before destructive operations, NetBox schema changes, production data
  changes, architecture-changing contradictions, third-party repository
  introduction, or existing-service downtime.

## Architecture boundaries

- Production target baseline: dedicated `ZABBIX-01`, RHEL 9.6 x86_64, SELinux
  Enforcing, firewalld enabled. The M3 home-lab gate used an explicitly
  authorized exception: logical `ZABBIX-01` shares `192.168.1.91` with the
  existing NetBox runtime while preserving separate databases and web
  listeners. That exception does not change the production baseline or
  authorize future co-location. `netbox-zabbix-sync` remains future M4 scope.
- Approved architect baseline, last verified 31 August 2026: Zabbix 7.0.30 LTS,
  RHEL 9.6 x86_64, PostgreSQL 16 candidate. Upstream verification must be reported
  separately and cannot silently replace the baseline.
- Phase 1 excludes TimescaleDB, ClickHouse, Patroni, PostgreSQL/Zabbix HA,
  Grafana, Kafka, RabbitMQ, Redis, and Celery unless later justified by evidence.
- Versions are data in `compat/`, not scattered literals. Python minor version and
  ABI must be discovered and approved before wheel resolution.

## Ownership and flow

NetBox owns intended inventory: sites, locations, racks, devices, roles, types,
manufacturers, platforms, primary IPs, interfaces, cables, VLANs, VRFs, prefixes,
circuits, and virtualization inventory. Zabbix owns availability, resource and
interface metrics, latency/loss, hardware health, events, history, problems, and
operational service state. Primary configuration flows NetBox -> sync -> Zabbix.
Operational discovery must not blindly rewrite NetBox.

## Identity and modelling

- Support both `/api/dcim/devices/` and
  `/api/virtualization/virtual-machines/`.
- Correlation identity is the tuple `source=netbox`, `netbox_type=device|vm`,
  `netbox_id=<integer>`. A PK alone or hostname alone is insufficient. Zabbix
  internal host IDs are not the primary NetBox identity.
- A physical Proxmox host is `dcim.Device`; LXC and QEMU guests are
  `virtualization.VirtualMachine`. Do not model ordinary guests as physical
  devices or invent physical VM-interface cables.
- Intended physical, observed LLDP/CDP, virtualization, curated logical service,
  and Zabbix operational data remain separate and retain source and timestamps.
- Validation states are `MATCH`, `MISMATCH`, `MISSING`, `DISCOVERED`, `UNKNOWN`,
  `STALE`, and `IGNORED`; stale evidence is not mismatch.
- Do not assume LLDP local port number equals ifIndex. Do not equate a physical
  cable with a failure dependency. If Zabbix is unavailable, health is UNKNOWN /
  GREY, never inferred DOWN / RED.

## Safety defaults

The future sync defaults to dry run. Writes require `--apply`; a default change
budget aborts when approximately more than 10% of managed hosts would change.
There is no automatic deletion, template unlink, or blind management-IP change.
Secrets belong in approved runtime stores such as systemd encrypted credentials,
Zabbix secret macros, or a corporate vault, with an authoritative recovery copy.

## Lab and corporate separation

Lab identifiers, names, IPs, mock sites, and emulator labels may occur only in
lab configuration, fixtures, evidence, tests, or documentation—not generic
runtime logic. Corporate transfer must replace configuration, credentials,
certificates, mappings, and endpoints without source edits. Release validation
must detect placeholders, missing values, invalid CIDRs, unsupported profiles,
missing certificates/NetBox URL, and lab-value leakage.

## Test status policy

Every acceptance test uses exactly one state:

- `PASS`: executed and expected result directly observed.
- `FAIL`: executed and failure directly observed.
- `NOT-EXECUTED`: access or preconditions were unavailable; record reason,
  preconditions, exact human procedure, and expected evidence.
- `NOT-APPLICABLE`: genuinely outside the environment or milestone.

Never infer PASS.

## Stop and approval conditions

Future milestones listed in `PLAN.md` are not authorized by their presence.
Stop at each milestone boundary. For a material mismatch record `EXPECTED`,
`ACTUAL`, `IMPACT`, and `RECOMMENDATION`; stop if it changes the architecture.
