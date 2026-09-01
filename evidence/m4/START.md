# M4 Start Record

Date: 2026-09-01

Authorized milestone: M4 — NetBox to Zabbix read-only source integration.

Authoritative endpoints:

- NetBox source: LXC 9000 (`netbox-demo`), `192.168.1.89`, REST API read only.
- Zabbix destination: `192.168.1.91`, logical `ZABBIX-01`; bounded Zabbix API
  reconciliation writes are permitted only after dry-run safety gates pass.

Repository baseline:

- Branch: `main`
- M3 closeout: `e0e417131b707c3760d7775ed33913fd8b2ffa28`
- Initial worktree: clean
- External push: not authorized and not attempted

Hard boundary:

- No NetBox POST, PATCH, PUT, or DELETE; no NetBox permission/schema/data change.
- No Zabbix `host.delete`, automatic template unlink, destructive cleanup, or
  over-budget apply.
- Implement and test safely even if NetBox read permissions remain incomplete;
  denied data must remain UNKNOWN/NEEDS_REVIEW and cannot be treated as empty.
- Stop after M4. Do not start M5 or M6.
