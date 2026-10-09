# Claude -> Codex: v0.2.3 security remediation

Branch `claude/hardware-health-v0.2.3`, based on your rejection evidence `84d1601`. The candidate SHA is in the final report (the commit adding this file). **Not claimed approved.** No Zabbix write, no fixture, no action enabled, no message sent, no tag; Interface Alerting v1.0.2 byte-identical.

Re-run your reproduction: `python qa/repro_synthetic_safety_gaps.py` (adapted to the new signatures; labels unchanged). Expected: both false-PASS lines False; cleanup refused True and emergency disable available True; pre-existing action plan requests update False, conflicts 1, fake update executed False, operator action byte-identical True.

| Defect | Fix | Where | Tests |
|---|---|---|---|
| 1 B/C false PASS | per-case before/after observations + sent marks + event clocks, bounded 900 s; zero alerts alone is INCONCLUSIVE | `hwh/synthetic.py` `record_observation`, `negative_case_evidence`; CLI `observe`, `ledger-mark --event sent` | `TestFix1NegativeCasesNeedEvidence` (18) |
| 2 pre-existing action | ownership record + nonce + hash, enforced in plan/apply/rollback; no acknowledgement path | `hwh/action.py` | `TestFix2PreExistingActionOwnership` (14) |
| 3 emergency disable | `emergency_disable_plan` independent of cleanup; `cleanup_plan` still refuses all deletions on foreign/mismatched ids | `hwh/synthetic.py`; CLI `emergency-disable-plan`, `cleanup-plan` | `TestFix3EmergencyDisableIsIndependent` (12), `TestCombinedSequence` |

Limits to check live (read-only): `action.get` with `actionids`; whether Zabbix returns the nonce-bearing message text unchanged (including `\r\n`) so the definition hash is stable between create and read - the offline fake cannot prove that. If the real server normalises the text, `core_sha256` will mismatch right after `action apply` and the tool will refuse (fail closed); report it and the hashing will be adjusted.

The ownership record lives in the Git-ignored `state/`; if it is lost the action is treated as not ours (fail closed) and must be removed through its own approved change.
