# Zabbix Platform

Enterprise-ready, offline-capable Zabbix platform targeting RHEL 9.6 and a
restricted corporate destination. NetBox is authoritative for intended state;
Zabbix owns observed health.

## Start here

1. Read `docs/SPEC-00-CONSTRAINTS.md`; it has the highest priority.
2. Read all remaining `docs/SPEC-*.md` files.
3. Read `docs/DISCOVERY.md` and the cited raw evidence.
4. Read `PLAN.md` and `PROJECT-STATUS.md` before proposing work.

Milestone 0 created specifications and read-only discovery only. No Zabbix
installation, offline build, NetBox change, or Proxmox guest change is included.
Future milestones require explicit approval one at a time.

## Repository versus artifact

This is the source repository. A future corporate deployment artifact will be a
curated, verified subset and must exclude development-only and lab-only content.
