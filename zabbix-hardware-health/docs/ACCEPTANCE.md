# Hardware Health — Scope and acceptance

## Coverage categories

| Category | Expected telemetry and condition | Target recovery |
| --- | --- | --- |
| fan | Operational status per fan/tray, failed/degraded/unknown | Restore healthy |
| power | PSU presence/failure, per supply (not just chassis uptime) | PSU healthy |
| temperature | Named sensor actual value and manufacturer-relevant warn/crit | Below recovery |
| redundancy | Loss of N+1 PSU/fan redundancy, where vendor exposes it | Redundancy restored |

Also track sensor stale/no data and device SNMP availability **separately**.
A device unreachable through SNMP is NOT proof that any particular PSU
or fan has failed. Prefer one parent availability/monitoring alert,
not a storm of per-component no-data alerts.

## Vendor strategy

1. Cisco IOS / IOS-XE: evaluate stock Cisco IOS by SNMP vendor template
   and its fan, PSU and thermal discoveries.
2. Cisco Nexus: evaluate Cisco Nexus 9000 Series by SNMP and ENTITY/
   Cisco FRU sensor items.
3. Cisco IOS-XR/ASR 8500, Huawei, Palo Alto, F5, FortiGate:
   inventory the exact model/software, discover the real supported
   MIB/API coverage; do not assume generic ENTITY-MIB alone detects
   all PSU/fan failures. Use official/vendor templates first.
4. Every model must pass a coverage matrix before being labeled protected.

## Acceptance gates (Codex on real LAB)

- Real SNMP data supported/fresh under tested template heartbeat policy.
- Missing model sensors explicitly marked UNVERIFIED, never green.
- Real sensor fault or safe controlled simulation causes Problem event.
- Recovery produces a matching recovered event.
- One separate Action delivers hardware alerts, with strict verified
  filtering and does not route interface alerts.
- Fan, PSU, temperature and redundancy each get separate PASS/FAIL/N/A
  evidence. Do not claim physical fan/PSU fault testing without a real fault.
- Device unreachable creates a monitoring availability signal rather
  than false hardware failures.
- Action changes have dry-run, backup, idempotency, ownership guard and
  rollback validation before they can be automated or used in Production.
- No changes to Interface Alerting v1.0.2.
- Production has its own inventory, identity, recipient group and media.
- Security: no API tokens, SNMP secrets, email passwords in Git.
