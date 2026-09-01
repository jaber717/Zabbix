# M4 Apply and Second Reconciliation

## Actual Zabbix apply

Status: **NOT-EXECUTED**.

Required NetBox reads are denied, all readable device eligibility decisions are
UNKNOWN, VM population is UNKNOWN, and the current Zabbix credential is
explicitly dry-run only. The dry-run therefore failed the required-read,
candidate-resolution, and credential-scope gates. No `--apply` command ran.

Observed result: 0 Zabbix host creates, 0 updates, 0 deletes, 0 template unlinks,
0 group removals, and 0 management-IP changes.

## Post-apply validation and second reconciliation

Status: **NOT-EXECUTED** because no apply was authorized by the gates. It would
be misleading to claim post-apply idempotency. Two pre-apply dry-runs were
executed instead and were byte-identical; this proves deterministic blocked
planning only.

Resume after the four exact NetBox view permissions and a dedicated scoped
Zabbix credential are available. Re-run dry-run, review mappings and the 10%
budget, then explicitly apply and perform the required second reconciliation.
