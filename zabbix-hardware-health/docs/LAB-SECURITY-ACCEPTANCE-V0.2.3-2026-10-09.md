# Hardware Health v0.2.3 — independent security acceptance

**Verdict: REJECTED** for synthetic notification execution. No live Zabbix writes, synthetic fixtures, Telegram delivery, action enablement, production access, release tag, or Interface Alerting changes were made.

## Exact candidate and test environment

- Tested `e2b1599187add48a9221bb12f322a203425cde3a` from `claude/hardware-health-v0.2.3` in a separate detached worktree. This report and the two independent probes are QA-only additions on a separate branch.
- LAB RHEL 9.6: Python **3.12.9**, Zabbix API **7.0.30**, `{$NETOPS.ENVIRONMENT}=lab`. LAB inventory `config/hardware.lab.yaml` remains `hosts: {}`.
- Python unit suite, declared PyYAML dependency: **first run 262/263**, second run **263/263**. The first failure is a flaky test assertion, not a rejected cleanup plan: `test_someone_elses_preexisting_fixture_is_never_planned_for_deletion` searches for the numeric bystander ID as a substring of the *entire serialized plan*. Those digits happened to occur inside the new SHA-256 precondition. The deletion params did not include the bystander. Required test correction: compare parsed deletion ID arrays, never substring-match the plan/its hashes.
- `compileall -q hardware_audit.py hwh tests qa`: PASS. Candidate whitespace check: PASS. Targeted secret-pattern scan: zero match files. `git diff --name-only v1.0.2 e2b1599 -- zabbix-alerting`: empty (Interface Alerting byte-identical).

## Original security defect A — Case B/C false PASS: **FAIL (partially fixed)**

The exact old sequence (Case A alert, action then disabled, B/C with no observations) now returns `ok=false` for both: good. Missing, disabled, wrong-ID, wrong-hash, contradictory, nonpositive-timestamp, and >900-second observations are rejected by the candidate.

However, `qa/independent_v023_security_probe.py` independently reproduces two remaining false PASS paths using the real `verify_case` implementation:

1. The action is actually **disabled throughout B/C**, but local ledger observations are manipulated to claim `status=0` with the correct action ID, time window and definition hash. Both cases return `ok=true`. `verify_case` compares the observations with each other and the live **definition** hash, but does not check the current live status or authenticate the observations against server-side status history.
2. With no forged ledger data, the actual `record_observation` reads an **enabled** action before B. The action is disabled when B's event occurs, then re-enabled before the after observation. Both genuine snapshots show enabled and B returns `ok=true`. The 900-second interval bound does not establish uninterrupted enablement.

Case C can also return PASS from two enabled observations and a **local** `sent` mark without any independent Zabbix item value/history evidence that value `5` was sent. It has no trigger/event to corroborate the send.

Smallest safe correction: do not call B/C a demonstrated filtering PASS from bracketing snapshots alone. At minimum fail if the action is disabled at verification or the interval has any contradictory observation; to establish uninterrupted enablement, correlate authoritative server-side action-change/audit history over the case interval. Bind Case C to a bounded read of the trapper item's actual sample/time (`5`), rather than only a local mark. If that evidence is unavailable, report **INCONCLUSIVE**, not PASS. Local observations cannot prove the absence of an unobserved toggle, even when honestly recorded.

## Original security defect B — pre-existing action ownership: **PASS offline**

Independent in-memory operator-owned same-name action: plan conflicts without proposing UPDATE; apply and enable refuse and leave the action byte-identical with zero API writes. Old-format/idless and foreign-nonce backups refuse; a backup for an absent different ID is a safe no-op. Missing ownership file, missing live nonce, and different recorded ID all refuse. A simulated operator definition change between planning and the guarded write is detected, with zero write calls. The write path independently re-reads by exact owned ID; it does not depend on synthetic preflight.

Live Hardware Action ownership and create/readback hashing cannot be confirmed because no Hardware Action exists in this LAB and writes were prohibited. This is a **read-only acceptance limitation**, not a claim of production readiness.

## Original security defect C — emergency disable: **PASS as a plan, not execution**

In the independent fake, an enabled owned action plus a foreign synthetic trigger makes `cleanup_plan` refuse destructive deletion. Separately, `emergency_disable_plan` returns exactly one `action.update` for the owned action ID and `status=1`, with a definition-hash precondition. It still works when fixture ownership is incomplete; an ownership/nonce mismatch or unrelated action ID refuses. The plan **does not execute** the disable. No real action was disabled or rollback performed in LAB.

## Real Zabbix 7.0.30 read-only API and hashing

`qa/independent_v023_live_probe.py` used the existing LAB token only with `ZabbixAPI(write=False)`; `api.writes_made()` was empty. The existing Interface action was read by `actionids` twice. Status was a string and was in the expected `0/1` set. `core_sha256` was stable across two reads. Returned action fields include `notify_if_canceled`, `pause_suppressed`, `pause_symptoms`, filter formula/evaluation fields, and generated operation IDs. The hash code strips generated IDs such as `operationid` but retains other returned fields; it hashes the server readback after creation, not the submitted params. The existing Interface action's Problem and Recovery messages retained CRLF (12 and 14 CRLF respectively; no bare LF/CR). This is encouraging but **does not prove** the nonce-bearing *Hardware* Action's submitted/returned message and hash behavior after creation. A separately approved, controlled LAB write test would be needed for that claim; no existing action was modified.

## Reproduction and handoff

Run the QA-only in-memory probe with Python 3.12 and PyYAML: `python qa/independent_v023_security_probe.py`. It prints booleans only, never credentials or Zabbix IDs. The live probe requires existing authorized LAB URL/token environment variables and prints shapes and counts only. Do not run any synthetic creation or action apply as part of this QA report.

**Decision:** defect B fixed offline; defect C fixed for emergency **planning**; defect A remains unsafe to call PASS. Do not enable or deliver from this candidate. Correct A and the flaky ID-substring assertion, then request independent re-acceptance. Synthetic delivery and physical hardware coverage remain untested.
