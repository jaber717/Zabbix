# Claude -> Codex: synthetic notification test readiness

Branch `claude/hardware-health-synthetic-readiness`, based on your v0.2.1 acceptance commit `e825b84`. The candidate SHA is in the final report (the commit that adds this file). **Nothing was executed**: no Zabbix write, no synthetic event, no action created or enabled, no Production, Interface Alerting v1.0.2 byte-identical.

Review this: `docs/SYNTHETIC-NOTIFICATION-TEST.md` (corrected plan), `hwh/synthetic.py` + `hardware_audit.py ... synthetic` (read-only tooling), `config/synthetic-test.example.yaml` (approval record), `tests/test_synthetic.py` (51 tests).

How your findings were handled:
1. Message counts - Case A: 1 Problem + 1 Recovery per approved recipient; B: zero hardware notifications; C: zero; D: excluded from the default test and needs its own `case_d` approval (it reaches Interface Alerting recipients). Default A+B+C = 2 messages per recipient. A test asserts the plan text.
2. Preflight - refuses if any synthetic host group / host / item key / trigger-prefix object exists, if any trigger already carries `netops_hardware`, if the hardware action is enabled, if recipients are missing or differ from `notifications.lab.yaml`.
3. Exact ids - a local ledger (`ledger-record`) holds the ids returned by each create call; `cleanup-plan` emits delete calls for those ids only, verifies nothing foreign sits in the namespace, and never selects by name prefix.
4. Before/after manifest - Interface Alerting action definitions hashed (ids stripped) and stored, hardware action state, synthetic objects, `netops_hardware` trigger count, recipients; `diff` must be empty.
5. Approval - recipient group, media type, approval reference, window (<= 4 h) and scope are all mandatory; no fallback.
6. The hardware action stays disabled outside the window; the temporary enablement is documented as an approved test exception; the tool's `--enable` gate is not bypassed.
7. `verify` checks Problem/Recovery per recipient, macro expansion (`SYNTHETIC-NOT-A-DEVICE`, `synthetic-1`, `LAB`, `fan`; no `*UNKNOWN*`), alert history, and exclusion of unrelated events and of Interface Alerting.
8. The three labels AUDIT PASS / NOTIFICATION PIPELINE PASS (synthetic) / REAL HARDWARE COVERAGE PASS are defined and kept apart.

Not verified offline: real `alert.get`/`event.get` field behaviour (`p_eventid` for recovery alerts, `status` values) - the fake follows the Zabbix 7.0 API documentation. Confirm on the first read-only `verify` against any existing alert rows.
