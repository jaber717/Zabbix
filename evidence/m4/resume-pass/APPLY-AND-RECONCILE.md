# M4 Apply and Second Reconciliation

All gates passed before the explicit apply. The apply ran once in a hardened
transient unit using the dedicated encrypted credential.

| Result | Apply | Second reconciliation |
|---|---:|---:|
| Create | 0 | 0 |
| Update | 0 | 0 |
| Unmapped | 57 | 57 |
| Skipped mapped/ineligible | 24 | 24 |
| Ambiguous | 0 | 0 |
| Needs review | 0 | 0 |
| Orphans | 0 | 0 |
| Template drift | 0 | 0 |
| Errors | 0 | 0 |

`apply_result.status=PASS`; no Zabbix host object required modification. The
second reconciliation exited 0 and repeated a zero-change plan. The regular
service remains immutable dry-run by default; explicit apply is not embedded in
the timer unit.

Raw evidence: `raw/apply-report.json`, `raw/second-reconcile.json`, and
`raw/dry-run-scoped-credential.json`.
