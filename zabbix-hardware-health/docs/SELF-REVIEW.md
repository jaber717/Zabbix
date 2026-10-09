# Phase 6 self-review (v0.3.0-rc1)

Method: for each risk class in the brief I looked for a concrete way the code could be wrong, wrote a failing test where I found one, and fixed it. "Open" items are carried into KNOWN-LIMITATIONS or the Codex checklist. Earlier rejections by Codex (false PASS for negative cases, adoption of an operator-owned action, emergency disable blocked by cleanup, flaky evidence test) are kept as regression tests (`test_v023_regressions.py`, `test_v024_evidence.py`) and still pass.

## Defects found and fixed during this release

| ID | Risk class | Finding | Fix + guard |
|---|---|---|---|
| S1 | incorrect trigger matching / false negative | Trigger-bearing items carried `DISCARD_UNCHANGED_HEARTBEAT 3m` (copied from the official shape). Zabbix then stores a sample only on change or every 3 min, so `last(#2)` means *two heartbeats* and a failure would be confirmed after ~3-6 min while the simulator (which assumed one stored sample per poll) said ~2 min. A simulator that is more optimistic than the real server is a false-PASS source. | Status items with triggers store every sample; heartbeat discard is restricted to informational readings. `importcheck` fails any item feeding `last(#n>1)` that discards unchanged values (`test_importcheck_flags_discarding_item`, `test_trigger_items_store_every_sample`). |
| S2 | false positives / stale | The raw walk master item had `history: 0` while the stale trigger uses `nodata()` on it. | Master/raw items keep 1h of history. |
| S3 | missing isolation / false PASS | `labsim` isolation used `event_matches`, which returns *False for an action with no conditions*. In Zabbix an unconditioned action matches **every** event, so an enabled catch-all (e.g. "Report problems to Zabbix administrators") would have passed the isolation check while notifying on the hardware events. | `labsim.may_match` is fail-closed (no conditions = match; unmodelled condition type = assumed match unless an AND-ed tag condition excludes). Tests: catch-all, unmodelled, AND-excluded. |
| S4 | missing isolation (pre-existing gap since v0.2.1) | Synthetic `preflight`/`review` checked the Interface Alerting action and the hardware action only; it never checked that no *other* enabled action could match a synthetic hardware event. A catch-all would have sent test events to recipients outside the approved list. | New preflight check "no OTHER enabled trigger action can match a synthetic hardware event" (uses `may_match`); tests `OtherActionIsolation`. |
| S5 | audit-evidence weakness | The first `labsim` evidence draft queried alerts by the Problem event id only; a Recovery notification is attached to the *recovery* event id, so Recovery deliveries would have been counted as missing. | Query uses problem and recovery event ids; test `test_problem_and_recovery_alerts_counted_from_hardware_action`. |
| S6 | incomplete coverage | The generated coverage matrix had cells (FortiProxy / PAN-OS `sensor`) with neither a definition nor a reason. | Reasons added; test `test_unsupported_blocked_cells_have_reasons` requires a reason for every non-implemented cell. |
| S7 | crash | Simulator tried to read `value.semantics` on informational readings. | Skips sensors without triggers. |

## Risk-class checklist

| Class | Result |
|---|---|
| Unsafe action updates | Unchanged from v0.2.4 (ownership record + nonce in live text + definition hash; re-read by id before write). Template writes follow the same pattern (marker + definition id; re-read; backup; read-back; foreign template = CONFLICT). API allowlist: template writes only with `write_templates=True`, which only `template apply|rollback` set; production refused before any contact. |
| Ownership violations | Rollback acts only on the recorded id/template; tool-created template deleted only if unlinked. Tests: foreign, other-definition marker, linked, production, writes-disabled. |
| Incorrect trigger matching | Action filter unchanged (`netops_hardware=1` AND `netops_alert` absent). `importcheck` forbids `netops_alert` on any generated trigger and requires the six routing tags. Modelled crossover + live labsim/preflight. |
| Missing notifications | Message contract test; every generated alarm trigger carries `netops_hardware=1`; stale triggers also notify (documented). **Open:** notification only proven offline - needs the live window. |
| Incorrect recovery handling | Every alarm trigger uses RECOVERY_EXPRESSION with consecutive-normal samples; simulator covers recovery and recovery-flap; `importcheck` rejects an alarm trigger without a recovery expression. |
| False-PASS conditions | Verdicts remain PASS only with authoritative evidence (v0.2.4). Coverage level is derived, never typed: REAL DEVICE VERIFIED only from `device-evidence.yaml` entries that carry device, recorder and capture reference. |
| Audit-evidence weaknesses | See S5. `labsim --evidence-since` is read-only and fails on unlinked Problems or alerts from other actions. |
| Incomplete cleanup | Release lifecycle tests: tampered package refused, nothing left at `current`; upgrade preserves config/state; rollback restores prior release. Tag change on sim triggers is print-only with an exact RESTORE plan. |
| Compatibility | Zabbix 7.0.30 export shape copied from the official 7.0 templates (item-nested trigger prototypes, `SNMP_WALK_TO_JSON`, dependent LLD). Python 3.12 on the LAB VM runs the full suite; the syntax gate (`check-syntax.py`) still enforces the 3.8 grammar for the library. **Open:** live import of generated templates (L3). |

## Residual risks
L1-L17 in `KNOWN-LIMITATIONS.md`. The two that matter most for go-live: no real-device evidence (L1) and no live template import / Telegram delivery (L3, L4).
