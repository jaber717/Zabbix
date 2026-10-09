# Claude -> Codex: synthetic safety review fixes

Branch `claude/hardware-health-synthetic-safety-fixes`, based on `bc33cfc`. The candidate SHA is in the final report (the commit adding this file). Nothing was executed: no Zabbix write, no fixture, no action enabled, no message sent; Interface Alerting v1.0.2 is byte-identical. The synthetic test remains UNAPPROVED.

| Your requirement | Fix | Negative tests |
|---|---|---|
| 1. Action enabled through A, B, C; disabled right after / on failure | Plan section 7: enabled once before Case A, kept enabled through A+B+C, disabled immediately after the last case or on any failure. `verify` refuses B/C unless `enabled_at` is recorded and Case A produced a hardware-action alert (positive control); failure output says DISABLE NOW | `TestVerifyPreconditions`, `TestPlanDocumentSafety` |
| 2. Window is a mandatory gate; read-only readiness before the window | `synthetic preflight` is refused outside the window before any server contact; `ledger-record` and `ledger-mark --event enabled` are window-gated; new `synthetic review` runs any time, reports READY / NOT READY, never authorises. Wind-down commands are never gated | `TestWindowIsAnExecutionGate` |
| 3. Cleanup inspects the live recorded action | `cleanup-plan` reads the recorded action id live; if enabled, disabling it is always step 1 regardless of `enabled_at`/`disabled_at`; refuses if an enabled hardware action is not in the ledger, if the recorded id is not the hardware action, or a different hardware action exists | `TestCleanupInspectsTheLiveAction` |
| 4. Signature comparison | manifest stores the full signature and a SHA-256 of the whole action; `diff` reports changed filter/recipients/message/any field, hash-only changes, delete-and-recreate, left-enabled | `TestSignatureManifest` |
| Media type enabled | `recipients()` refuses a disabled approved media type | `TestMediaTypeAndPreexistingAction` |
| Ownership-verified ids | `verify_ownership` reads back every recorded id (group name, host name, item key + host, trigger description + host, action name); any mismatch refuses the whole plan | `TestOwnershipVerification` |
| Pre-existing disabled action not adopted/deleted | preflight requires `existing_hardware_action.acknowledged`; ledger records `action_created_by_test=false`; cleanup emits no rollback/delete, only a disable if needed; the after-manifest must be identical | preflight + cleanup tests |

Not verified offline: the live `action.get` `actionids` parameter and `status` strings, and `alert.get` `p_eventid` - they follow the Zabbix 7.0 API documentation.
