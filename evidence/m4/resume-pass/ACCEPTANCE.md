# M4 Acceptance

Date: 2026-09-02

Verdict: **M4 ACCEPTED — M5 READY**.

The NetBox permission blocker is resolved for the credential actually used by
`nbzsync`. Live source collection is complete, every candidate decision is
deterministic, the 10% breaker passes, a dedicated least-privilege Zabbix
credential is installed, explicit apply passed, and the second reconciliation
is zero-change.

The current source has no opted-in objects. Consequently, acceptance proves the
live collection, planning, gating, credential, apply, and convergence paths but
does not claim that any NetBox-managed Zabbix host was created. Future
eligibility remains an explicit NetBox-side operational choice.

No NetBox write, change-budget override, host deletion, template unlink, group
removal, blind IP change, M5/M6 work, or external push occurred.
