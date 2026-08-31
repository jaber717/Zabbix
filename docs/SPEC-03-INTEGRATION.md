# SPEC-03 — NetBox/Zabbix Integration

## Contract

NetBox is the source of intended inventory; Zabbix is the source of observed
health. The integration must consume both devices and virtual machines and map
them through explicit environment configuration.

## Pipeline

The future service performs: fetch -> validate -> resolve -> compare -> report
drift -> optionally reconcile. It defaults to dry run; writes require `--apply`.
Separate audit, mapping, resolution, planning, and application so the exact plan
can be reviewed and tested before mutation.

## Identity

Use `source=netbox`, `netbox_type=device|vm`, and `netbox_id=<pk>` as the stable
correlation tuple. Do not rely on hostname uniqueness or a NetBox integer PK
without object type. Do not store Zabbix internal host IDs in NetBox as the
primary identity.

## Change safety

- Abort by default if approximately more than 10% of managed hosts would change;
  make the exact threshold configurable and report the calculation.
- Never automatically delete hosts or unlink templates.
- Never change a management interface/IP blindly. Ambiguity is a blocked plan.
- Define lifecycle states for managed, ignored, missing, disabled, orphaned,
  invalid, unresolved, and conflict conditions. Orphans are reported, not deleted.
- All apply operations need structured audit records without credentials.

## Mapping and eligibility

Resolve site, tenant, role, platform, status, tags/custom fields, template groups,
proxy choice, interfaces, and monitoring eligibility through configuration.
Mock DCIM and non-running test infrastructure must be explicitly excludable.
Lab-specific values must not appear in generic resolver logic.

## Credentials and permissions

Use separate least-privilege credentials: read-only NetBox and minimally scoped
Zabbix API/service credentials. Validate permissions before planning. Never log
headers or tokens. Store credentials in approved runtime facilities and document
rotation and recovery ownership.

## Operation

Provide deterministic dry-run output, machine-readable results, bounded retries,
timeouts, pagination, rate handling, self-monitoring, and safe failure behavior.
A systemd service/timer may schedule sync only after manual validation. Concurrent
runs must be prevented. Zabbix/NetBox outage results in UNKNOWN and an alertable
sync failure, not inferred device failure.
