# Independent LAB acceptance — Hardware Health v0.2.2

Verdict: **REJECTED** for synthetic notification execution. This is a QA finding, not a release or live-change record.

## Scope and baseline

- Exact candidate: `7b6559fe45b338fe4baa3f47cebae513fc0f59ad` from `claude/hardware-health-synthetic-safety-fixes`; detached dedicated worktree was verified at that SHA before testing.
- LAB: RHEL 9.6 host with Python 3.12.9 and Zabbix API 7.0.30. `{$NETOPS.ENVIRONMENT}` returned `lab`.
- No synthetic test was executed. No hosts, items, triggers, actions, notifications, network devices, Production objects, or Interface Alerting files were changed. The live API probe used `ZabbixAPI(write=False)` and logged zero writes. The fake reproductions are entirely in memory.
- `git diff --name-only v1.0.2 7b6559f -- zabbix-alerting` returned no files; Interface Alerting v1.0.2 is byte-identical.

## Automated and live read-only results

- Python 3.12.9, declared PyYAML dependency: 219/219 unit tests PASS, including ResourceWarning-as-error. `compileall` for `hardware_audit.py`, `hwh`, `tests`, and `qa`: PASS.
- Candidate `git diff --check`: PASS. Targeted tracked/untracked secret-pattern scan: zero match files. No application shell scripts are present in this project.
- Real `action.get` with `actionids` returns one Interface Alerting action with `status` as a string (`"0"`), populated filter/operations/recovery-operations keys. No Hardware Health action exists in LAB.
- Real `user.get` with `selectMedias` returns a `medias` list; the bounded sample was empty. The proposed `Network Operations` recipient group is not present in this LAB. Telegram media type exists. Therefore actual recipient readiness is **not established** and preflight must refuse.
- Real `event.get` has `r_eventid`; real `alert.get` has `p_eventid`. A bounded sample included recovery alerts. No assumption about delivery expansion was made.
- Fixed synthetic namespace: zero hostgroups, hosts, items, and triggers. Diagnostic-only review and execute preflight, using an expired in-memory window and absent approved recipient group, both returned `ok=false` and `execution_allowed=false`. The shipped example approval is refused by `load_scope` tests. No fixture was created.
- Read-only API client rejects `action.update` before transport. `writes_made()` remained empty.

## Critical negative safety cases

Run `python qa/repro_synthetic_safety_gaps.py` (in-memory fake only) to reproduce the following. The script prints no credentials or object identifiers.

1. **Case B/C false PASS after action disabled — FAIL.** With Case A's earlier successful alert in history, `enabled_at` in the ledger, and the live Hardware Action now disabled before B and C, `verify_case(..., "B")` and `verify_case(..., "C")` both return `ok=true`. `hwh/synthetic.py::verify_case` checks the historical Case A alert and ledger mark but not live status or case-specific evidence that the action stayed enabled during B/C. A zero alert count is therefore inconclusive. Required: fail closed unless each negative case has proof the action was enabled throughout that case; at minimum reject a disabled live action at verification, and record/validate per-case enable-state evidence if verification can occur after disable.
2. **Pre-existing action adoption — FAIL.** A disabled operator-owned same-name Hardware Action yields an unconstrained `UPDATE action` plan with zero conflicts. With an in-memory write-enabled fake client, `hwh/action.py::apply` actually calls `action.update` against it. The synthetic acknowledgement is not an ownership grant. Required: action apply must refuse modification/adoption of a pre-existing action in this workflow absent a separate explicit, scoped operator-approved change and a matching pre-change definition/ID guard. The synthetic path must leave it byte-identical.
3. **Foreign IDs/deletion — PASS.** Ownership checks and namespace checks reject foreign trigger/host/item/group IDs and do not plan their deletion.
4. **Enabled-action emergency disable on failure — FAIL.** When the recorded test action is live-enabled and a foreign trigger appears in the synthetic namespace, `cleanup_plan` raises during namespace verification *before* it can return its first-step `action.update(status=1)` disable. An incomplete ledger likewise can prevent a safe disable plan. Required: separate the verified emergency-disable step from deletion planning; refuse all deletions on foreign/incomplete ownership, but offer a clearly scoped, independently verifiable disable of the recorded test action. Never disable an unowned action merely by name.
5. **Before/after manifest — PASS in isolated tests.** Definition hash/signature and ID/status comparisons catch filter, message, recipient, ID, and status changes. Live Hardware Action comparison cannot be exercised because the action does not exist in this LAB.
6. **Read-only client — PASS.** The real read-only probe's attempted `action.update` was refused before transport and logged zero writes.

The existing 219 tests cover positive controls and several independent negative cases, but do not cover the combined sequences in findings 1, 2, and 4. Add focused regression tests for those exact sequences before another acceptance request.

## Acceptance decision

**REJECTED.** Do not run the synthetic delivery procedure or enable a Hardware Action from this candidate. The LAB also lacks the proposed recipient group, so a later approved test will need explicit recipient configuration/approval. Re-test the exact corrected SHA after the three safety defects are fixed. No release tag was created.
