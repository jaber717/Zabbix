# v0.3.1-rc2 - evidence for the five rejected defects (engineering, not acceptance)

Engineering evidence only; independent acceptance is Codex's. Environment: LAB VM `netbox-dev`, Python 3.12.9 (PyYAML), offline fake transport for all template sequences. **No Zabbix write, no live import, no host linking, no action enablement, no Telegram message, no Production access, no tag.**

## Codex reproductions, run unchanged (`qa/acceptance_v03_security_repro.py`, byte-identical to Codex commit `5529012`)

| # | Defect | BEFORE (candidate `c1f96cb`) | AFTER (this branch) |
|---|---|---|---|
| 1 | copied marker adopts an operator template | `CONFIRMED` | the first sequence stops with `AuditError: refusing to apply: a template named NETOPS-HW cisco-iosxe (id 501) already exists and there is NO ownership record for it ...` - the script no longer reaches a CONFIRMED line (exit 1, traceback = refusal) |
| 2 | manual content drift invisible | `CONFIRMED` | (not reached by the unchanged script, see below) |
| 3 | rollback deletes a recreated template | `CONFIRMED` | (not reached) |
| 4 | linked template update proceeds | `CONFIRMED` | (not reached) |
| 5 | `deleteMissing` enabled for children | `CONFIRMED` | (not reached) |

Because the unchanged script aborts at its first refusal, each sequence is also run on its own by `qa/acceptance_v031_regression.py` (same sequences, plus the *owned-template* variants of 2 and 4):

```
1 copied-marker foreign template imported: FIXED - refusing to apply: ... NO ownership record ...
2 manual content drift invisible with same marker: FIXED - owned-template drift: ADDED item:operator.added
3 rollback deletes recreated same-name template: FIXED - result=already-absent, recreated id 999 untouched (recorded id 900)
4 linked template update not blocked: FIXED - linked ids reported: ['600']
5 deleteMissing enabled for template children: FIXED - IMPORT_RULES deleteMissing = {'discoveryRules': False, 'items': False, 'triggers': False, 'valueMaps': False}
ALL FIVE FIXED
```

(`FakeTpl` in `tests/test_v03_tplmgr.py`, which Codex's script imports, was kept constructor- and attribute-compatible and now also answers `importcompare`, UUID filters and exports.)

## Test and gate results (LAB VM, Python 3.12.9)

| Gate | Result |
|---|---|
| Hardware Health suite | **442 tests OK**, three consecutive runs (12.0 s each) |
| New regression tests | `test_v03_tplmgr.py` (65: ownership, create races, drift, rollback, interrupted operations, linked, non-destructive import, immutable backups), `test_v031_sequences.py` (9 combined sequences), `test_v03_release.py` (8: + state preservation across install/upgrade/rollback, reproducible package), `test_v03rc2_pan_auth.py`, `test_v03rc2_cisco_mibs.py`, `test_v024_evidence.py` (+2 for `auditlog_mode`) |
| Syntax gate (Python 3.8 grammar, `bash -n`) | 52 Python files, 6 shell scripts OK |
| `vendors check` / `simulate` / `messages` | PASS / 109 scenario checks, 0 failed / PASS |
| Interface Alerting v1.0.2 | `git diff v1.0.2 -- zabbix-alerting` = 0 lines; its suite 182 tests OK; release gate PASS (git-history parts and ShellCheck do not run on the VM: **not a pass for those**) |
| Hardware Action ownership / audit evidence / emergency disable | `test_v023_regressions.py`, `test_v024_evidence.py`, `test_synthetic_safety.py` OK; Codex's `independent_v023_security_probe.py` and `repro_synthetic_safety_gaps.py` rerun: all expectations hold |
| Dependency scan | stdlib + PyYAML `>=6.0,<7.0` only |
| Secret scan | no credential-like value, no private key in tracked files |
