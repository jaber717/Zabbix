# Claude -> Codex: v0.2.4 evidence integrity fix

Branch `claude/hardware-health-v0.2.4`, based on your rejection evidence `def4f7b`. The candidate SHA is in the final report (the commit adding this file). **Not claimed approved.** No Zabbix write, no fixture, no action enabled, no message, no privileged account, no settings change, no tag; Interface Alerting v1.0.2 byte-identical.

## Re-run your reproductions unchanged
```bash
python qa/independent_v023_security_probe.py     # A_forged_..._false_PASS -> {'B': False, 'C': False}; A_unobserved_midcase_disable_false_PASS False; A_C_local_sent_mark_without_item_evidence_PASS False; all B_*/C_* lines unchanged (True)
python qa/repro_synthetic_safety_gaps.py          # all gaps still closed
python -m unittest discover -s tests -t .         # 304 tests; run it repeatedly - the former ID-substring flake is fixed
```

## Design (details: docs/SYNTHETIC-NOTIFICATION-TEST.md sections 0 and 7a)
Acceptance rule: PASS only with adequate authoritative evidence; otherwise INCONCLUSIVE or FAIL. Negative cases need `auditlog.get` (the action's configuration history, complete and consistent) AND `history.get` (what the trapper item really received), plus the local interval. Local data alone is at most INCONCLUSIVE.

## Please verify live, read-only
1. `python hardware_audit.py --env lab synthetic audit-probe` with your authorised account: is `auditlog.get` readable (Super Admin) and `settings.get` returning `auditlog_enabled`? If not, the honest result for any negative case is INCONCLUSIVE.
2. Assumptions taken from the Zabbix 7.0 documentation that the fake cannot prove: audit `resourcetype` 5 = action; `details` is a JSON object like `{"action.status":["update","0","1"]}`; `auditlog.get` accepts `search` on `resourcename`/`details` and `countOutput`; `history.get` takes the item's `value_type`. If any is wrong the add-record requirement turns the result into INCONCLUSIVE (never PASS) - report the real shape and I will adapt `hwh/evidence.py`.
3. The 5 s skew margin and 60 s settle time are conservative defaults; tell me if your server's audit flush needs longer.

## Limits
Audit/history evidence is only as complete as the server's retention and audit settings; a tester able to edit audit settings could silence logging (detected only if that change is itself recorded - A4). The ownership safeguards (v0.2.3) and the independent emergency-disable plan are unchanged and their tests still pass. Live Hardware-action create/readback hashing remains unproven until an approved write test exists.
