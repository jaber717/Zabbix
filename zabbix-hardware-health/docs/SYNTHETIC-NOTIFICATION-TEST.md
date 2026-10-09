# LAB synthetic notification test (HW-N4 / HW-N6)

**NOT EXECUTED. Needs explicit written authorization from the operator before any Zabbix write. LAB only. No Production, no Interface Alerting change.**
Nothing in this repository writes to Zabbix for this test. The tooling added for it (`hardware_audit.py --env lab synthetic ...`) is **read-only against Zabbix** (review, preflight, snapshot, diff, cleanup-plan, verify) plus two commands that write only a local ledger file (`ledger-record`, `ledger-mark`). The fixtures are created and deleted by the independent tester with an approved LAB token.

## 0. The acceptance rule (applies to every verdict in this document)

**PASS only when adequate authoritative evidence exists. Otherwise INCONCLUSIVE or FAIL - never an assumed PASS.**

* **PASS** - every required evidence source was available, complete and mutually consistent, and showed what the case requires.
* **FAIL** - the evidence contradicts the requirement (the action was disabled during the case, an unexpected value arrived, an unexpected notification was sent, the audit log and live state disagree ...).
* **INCONCLUSIVE** - the evidence is missing, unavailable, truncated, too recent, ambiguous under clock skew, unparseable, or only tester-supplied. An empty answer is never read as "nothing happened". `verify` exits 0 / 1 / 4 for PASS / FAIL / INCONCLUSIVE.

A negative case (B, C, D) therefore cannot pass on a zero alert count, on the tester's own snapshots, on a local "sent" mark, or on an earlier Case A alert (see section 7).

## 1. Three results that must never be confused

| Label | Meaning | Status today |
|---|---|---|
| **AUDIT PASS** | the read-only audit (`hardware_audit.py audit`) found declared sensors readable, mapped and trigger-bound | not achieved: the approved inventory is empty (`hosts: {}`), no real sensor is verified |
| **NOTIFICATION PIPELINE PASS (synthetic)** | the separate action delivered one Problem and one Recovery with expanded macros for a synthetic event, and did not act on unrelated events | this test; not yet run |
| **REAL HARDWARE COVERAGE PASS** | real fan/PSU/temperature/redundancy/HA sensors on real vendor devices, verified status mappings, dedicated-tag triggers, real or safely simulated state changes delivered | not achieved; needs real devices (VENDOR-GAPS-AND-TEST-DEVICES.md) |

A synthetic pass proves the plumbing only. It must be reported as `NOTIFICATION PIPELINE PASS (synthetic)`, never as hardware coverage and never as production readiness.

## 2. Expected notifications - per approved recipient

"Recipient" = a user in an approved user group who has an enabled medium of the approved media type. Totals scale with the number of recipients; they are not a fixed number.

| Case | What is sent to the trapper item | Hardware-action messages | Interface Alerting exposure |
|---|---|---|---|
| **Case A** - hardware-tagged trigger | `1` then `0` | **1 Problem + 1 Recovery per approved recipient** (2 per recipient) | none |
| **Case B** - stock-style tags (`scope`, `component` only) | `2` then `0` | **zero** hardware notifications (the event shows in Problems only) | none |
| **Case C** - value no trigger matches | `5` | **zero** notifications of any kind | none |
| **Case D** - tagged for both families | `3` then `0` | zero from the hardware action | **Case D is excluded from the default test.** It would produce an Interface Alerting Problem and Recovery for that action's recipients. It needs its own approval (`case_d`), including confirmation that those recipients were told |

Default test = A + B + C = **2 hardware messages per approved recipient in total** (all from Case A). Example: two approved recipients -> 4 messages.

## 3. Authorization record (no fallback of any kind)

Copy `config/synthetic-test.example.yaml` to `config/synthetic-test.yaml`. The operator fills in **every** field; a blank or missing field makes `synthetic preflight` refuse:

* `approved_by`, `approval_reference`
* `window_start`, `window_end` (ISO-8601 with offset; at most 4 hours)
* `media_type` and `usergroups` - exact existing names, and **identical** to `config/notifications.lab.yaml` (one approval, one source of truth). There is no default recipient and the Zabbix administrators group is never substituted.
* `test_scope`: the fixed namespace `NETOPS-HW-SYNTH` / `NETOPS-HW-SYNTH-01` and the list of cases (default `[A, B, C]`).
* `case_d` (approver, reference, `interface_recipients_notified: true`) only if D is listed.

## 4. Readiness review (any time) and preflight (the execution gate)

The approved window is a **mandatory execution gate**, not a hint.

```bash
python3.12 hardware_audit.py --env lab synthetic review      # read-only; may run BEFORE the window; reports READY / NOT READY; never authorises execution
python3.12 hardware_audit.py --env lab synthetic audit-probe  # read-only: can this account read the audit log, settings and item history? exit 4 = no -> negative cases will be INCONCLUSIVE
python3.12 hardware_audit.py --env lab synthetic preflight   # the gate: refused outside the approved window (before any server is contacted) and on any failed check
```

* `review` runs every readiness check below but treats the window as informational. READY means "the lab looks clean and the approval is complete"; it is never permission to start.
* `preflight` is **refused outside the approved window**. The same gate also guards `ledger-record` and `ledger-mark --event enabled`, so no fixture can be recorded and the action cannot be marked enabled outside the window. Winding down (`ledger-mark --event disabled`, `cleanup-plan`, `snapshot`, `diff`, `verify`) is deliberately never gated.

Both refuse if any of the following is false: scope complete; scope recipients equal the action configuration; the approved media type exists **and is enabled** and the approved user group(s) exist with at least one user who would receive messages; **the synthetic namespace is empty** - no host group `NETOPS-HW-SYNTH`, no host `NETOPS-HW-SYNTH-01`, no item `netops.hw.synthetic.state` on any host, no trigger whose name starts `[NETOPS-HW-SYNTH] `; no trigger anywhere already carries `netops_hardware`; the hardware action is absent or **disabled**; at least one Interface Alerting (`NETOPS-IaC`) action exists to snapshot.

**A pre-existing hardware action blocks the test, full stop.** There is no acknowledgement path (the key `existing_hardware_action` is rejected by the approval loader). An action named `NETOPS-HW Hardware Health` that this deployment did not create is never adopted, updated, enabled, disabled, rolled back or deleted by this tooling, at any stage: it must be resolved through its own separately approved change before the test. `action apply` itself enforces this at the write (section 6a), so the protection does not depend on preflight having been run.

## 5. Before manifest

```bash
python3.12 hardware_audit.py --env lab synthetic snapshot --out evidence/synth-before.json
```

The manifest holds, for every Interface Alerting action: id, name, status and a SHA-256 of its full definition (ids stripped) plus the definition itself; for the hardware action: existence, id, status, its **full signature** (filter conditions, evaluation type, recipient group ids, media type, Problem and Recovery subject/message, operation counts) and a SHA-256 of its whole definition; the (empty) synthetic object lists; the count of `netops_hardware` triggers; the recipient user ids; and a manifest hash.

## 6. Create fixtures and RECORD EVERY ID

The tester creates, with the approved LAB token, in this order: host group `NETOPS-HW-SYNTH`; host `NETOPS-HW-SYNTH-01` (no interfaces, no templates); trapper item `netops.hw.synthetic.state` (unsigned numeric); trigger A `[NETOPS-HW-SYNTH] case A hardware-tagged` (`last(...)=1`, Average, tags `netops_hardware=1`, `hardware_component=fan`, `hardware_vendor=synthetic`, `hardware_model=SYNTHETIC-NOT-A-DEVICE`, `hardware_site=LAB`, `hardware_slot=synthetic-1`); trigger B `[NETOPS-HW-SYNTH] case B stock-style tags` (`last(...)=2`, tags `scope=availability`, `component=fan`); trigger D only if approved (`last(...)=3`, tags `netops_hardware=1` and `netops_alert=synthetic_test`). Case C has no trigger.

**Immediately after each create call**, write the exact id returned into the ledger (a local file, mode 0600, Git-ignored):

```bash
L=state/synthetic/ledger-<approval_reference>.json
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind hostgroup --id <id>
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind host      --id <id>
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind item      --id <id>
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind trigger   --id <id> --case A
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind trigger   --id <id> --case B
```

Then create the hardware action (disabled) with the tool and record it:

```bash
python3.12 hardware_audit.py --env lab action apply            # prints the backup path; creates 'NETOPS-HW Hardware Health', DISABLED
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind action --id <action id> --created-by-test
```

## 6a. Ownership of the hardware action (enforced inside the write path)

A Zabbix action has no description or tag, so ownership is a conjunction of three facts, all of which must hold before the tool will update, roll back or disable an action:

1. a local ownership record, written when **this deployment created the action**, holds the exact action id, a random nonce and the hash of the definition it applied (`state/ownership/`, mode 0600, Git-ignored);
2. the same nonce appears in the live action's Problem and Recovery message text (a same-named operator action cannot contain it);
3. the live definition (everything except status) still hashes to what this deployment last applied.

`action apply` re-reads the live action by the recorded id **immediately before** `action.update` and refuses (`REFUSED at the write`) if any fact fails, so a swap between planning and writing is caught. A pre-existing or edited action is reported as a conflict and left byte-identical. `action rollback` only acts on the exact action id recorded in the backup and only if ownership holds; an old backup, a backup without an id/nonce, or a backup whose id now belongs to a different action is refused. Nothing is ever selected by name.

## 7. Temporary enablement and per-case evidence - an explicitly approved test exception

The action is **disabled at all times outside the approved test window**. The tool correctly refuses `--enable` because `config/action-validation.yaml` is all-false; that gate is not bypassed. Enabling for the test is a separate, manual, approved exception made by the tester on the recorded action id only.

For Cases B and C to prove that filtering works, the action must be live while they run. It is therefore **kept enabled through Cases A, B and C**, inside the window:

1. enable the recorded action once, before Case A (`ledger-mark --event enabled`, which is itself window-gated);
2. run Cases A, B and C (and D only if separately approved) with the action still enabled;
3. **immediately after the last case**, set the recorded action back to disabled and `ledger-mark --event disabled`; confirm in the UI.

**On any failure** (section 8) disable the action at once - do not finish the remaining cases first (section 9a gives the independent emergency path).

**A negative case (B, C, D) is only accepted with authoritative, server-side evidence.** The tester brackets each case with local observations (they tie the case to a time interval and to the exact action id) - but local data alone can never produce a PASS, because it cannot show the absence of an unobserved disable / re-enable and can be altered:

```bash
python3.12 hardware_audit.py --env lab synthetic observe --ledger $L --case B --phase before    # reads the recorded action live: id, status, definition hash; ownership must hold
python3.12 hardware_audit.py --env lab synthetic ledger-mark --ledger $L --event sent --case B   # immediately after zabbix_sender sends the value (window-gated)
# ... let the event be processed ...
python3.12 hardware_audit.py --env lab synthetic observe --ledger $L --case B --phase after
```

**Timing rules** (they exist because Zabbix and this host have different clocks and audit records are flushed asynchronously): wait **at least 10 seconds** after enabling the action before the first value is sent; wait **at least 10 seconds** after a case's `after` observation before any further change to the action; **disable the action as the last step of the test**, then run `verify` for B, C and D **at least 60 seconds later**. Running `verify` earlier, or before the final disable, is INCONCLUSIVE by design (no audit record exists after the interval, so continuity of logging after the case is not shown).

## 7a. Evidence integrity design

`verify` for a negative case needs ALL of the following. The two server-side sources decide; the local record only ties the case to a time interval.

| # | Source | What must hold | If not |
|---|---|---|---|
| L | local observations (`observe`), `sent` marks, event clocks | exactly one `before` and one `after`; both show the recorded action id, **enabled**, same definition hash; interval 1..900 s; every send/event inside it; window respected | contradiction -> FAIL; missing -> INCONCLUSIVE |
| S | `settings.get` | `auditlog_enabled=1` (and mode "log all") | INCONCLUSIVE |
| A1 | `auditlog.get` for the action (resourcetype 5, exact id), time-ascending | an **add record exists** for this exact id (proves audit logging captured this object and that the query works - an empty response is never accepted); records are complete: fewer than the 1000-row limit AND the server's `countOutput` equals the rows returned; verification at least 60 s after the interval | INCONCLUSIVE |
| A2 | the same records, parsed | status timeline rebuilt from the add record and every `action.status` update: **enabled at least 5 s before the first send/event** (clock-skew margin), **no status change until 5 s after the interval**, no delete, no update of any other field inside the interval (outside it: INCONCLUSIVE, the definition the case ran against is not established); at least one audit record **after** the interval (continuity); the audit's final status **equals the live status** | disabled / changed / deleted / contradiction -> FAIL; ambiguous or missing -> INCONCLUSIVE |
| A3 | `auditlog.get` search on the action name | no other action with the same name was added (recreate / duplicate) | FAIL |
| A4 | `auditlog.get` search on `details` for `auditlog` | no change of the audit settings since the action was created (logging could have been switched off and on) | INCONCLUSIVE |
| H | `history.get` on the **exact synthetic trapper item** (`value_type` taken from the item; `history` retention must be non-zero) | samples **actually received** in the interval: B must show `2` and `0`, C must show `5` (and at least one expected sample at or after the recorded send time); no unexpected value (the cases did not overlap, nobody else is sending) | missing / truncated -> INCONCLUSIVE; unexpected value -> FAIL |

Precision and asynchrony: audit and history timestamps are whole seconds on the server clock; every comparison carries a 5 s skew margin that always falls on the cautious side (ambiguity is INCONCLUSIVE, never PASS). The 60 s settling time covers the server's asynchronous audit flush. Positive control: B/C/D additionally need Case A's Problem delivered by the same action.

**Required live read-only permissions:** `auditlog.get` requires **Super Admin**. This project never creates a privileged account, never raises a role and never changes audit-log settings. If the tester's existing authorised account cannot read the audit log, negative cases are INCONCLUSIVE and the delivery test cannot demonstrate filtering. Check beforehand, read-only: `python3.12 hardware_audit.py --env lab synthetic audit-probe` (exit 0 = settings, audit log and history are all readable and audit logging is on; exit 4 = unavailable). Also needed: `history.get`, `item.get`, `settings.get`, `event.get`, `alert.get`, `action.get`.

**Known limits:** a tester with the right to edit audit settings could in principle silence the log; this is detected only to the extent such a change is itself recorded (A4). The `details` format and the resource type id of an action (5) are read from Zabbix 7.0 documentation: the requirement of an add record for the exact id is the empirical check - if either assumption is wrong the result is INCONCLUSIVE, not PASS.

## 8. Run the cases, then verify (read-only)

Send the values with `zabbix_sender` from the LAB Zabbix host to host `NETOPS-HW-SYNTH-01`, key `netops.hw.synthetic.state`, and wait for the trigger/alert processing between values.

```bash
python3.12 hardware_audit.py --env lab synthetic verify --ledger $L --case A    # also B, C (and D only if approved)
```

Run `verify` for the negative cases only after the final disable and at least 60 seconds after the last case (section 7a); earlier runs are INCONCLUSIVE. `verify` checks, using only event/alert/action reads plus the authoritative sources of section 7a:

* **Problem and Recovery** - exactly one Problem event for the case trigger, recovered; Case A: each approved recipient has exactly one Problem alert and one Recovery alert from the hardware action (`p_eventid` distinguishes them), nobody else, all delivered (`status` sent, no `error`);
* **Message macro expansion** - the Problem message contains the expanded values `SYNTHETIC-NOT-A-DEVICE`, `synthetic-1`, `LAB`, `fan`; neither message contains `*UNKNOWN*` or a literal `{EVENT.TAGS`; the Recovery carries the recovery wording;
* **Alert history** - the exact alert rows (ids, users, status, retries, errors) are in the report;
* **Hardware-action exclusion** - Cases B/C: zero hardware-action alerts; across the whole action, no alert exists for any event except Case A's Problem/Recovery;
* **Interface Alerting exclusion** - no alert of any `NETOPS-IaC` action for any synthetic event (except Case D, where it is expected and checked by hand).

Stop at the first failure and go to section 9: a message from the hardware action in B/C/D, more than one Problem or Recovery per recipient, an unexpanded macro, a recipient outside the approved list, a delivery error, or any change in an Interface Alerting action. If a macro does not expand, record the exact rendered text and hand it back; do not improvise another syntax live.

## 9a. Emergency disable - independent of cleanup

```bash
python3.12 hardware_audit.py --env lab synthetic emergency-disable-plan --ledger $L
```

This is separate from fixture cleanup and **does not look at the synthetic namespace or at the completeness of the fixture ids**. It needs only the exact action id in the ledger, `created-by-test`, and the ownership facts of section 6a. It prints a single `action.update` (`status` 1) for that exact id with preconditions to re-check immediately before executing (id and definition hash), or says nothing needs doing if the action is already disabled. If ownership cannot be established it prints **no** disable step and refuses with manual-recovery evidence (live id/name/status/definition hash, the record's id/hash/age, whether the nonce is in the live message - ids and hashes only, never message text). It never disables an action by name alone, and never one the ledger does not claim.

If `cleanup-plan` is refused (foreign or mismatched fixture ids, an unrecorded hardware action, an incomplete namespace) it plans **no deletion at all** but still prints this emergency step.

## 9. Cleanup - recorded ids only, ownership-verified, never by name

```bash
python3.12 hardware_audit.py --env lab synthetic cleanup-plan --ledger $L
```

Cleanup inspects the **live** state first and prints the exact calls:

1. **FIRST STEP, always:** the emergency disable (9a) whenever the recorded, owned hardware action is enabled on Zabbix *right now* - regardless of what the ledger's `enabled_at` / `disabled_at` say;
2. `trigger.delete` with the **recorded trigger ids**; `item.delete`, `host.delete`, `hostgroup.delete` with the **recorded ids**;
3. the tool rollback of the action it created, using its backup (id- and ownership-checked, never by name).

The plan is **refused** - no deletion is planned and the tester investigates - if: the ledger is empty; **ownership verification fails** (every recorded id is read back and must still be the synthetic object it was recorded as: host group name, host name, item key on the recorded host, trigger description on the recorded host); the synthetic namespace holds an object whose id is not in the ledger; or a hardware action exists that is not the recorded one. It never selects anything by name prefix, and an object already gone is simply omitted. The tester executes the printed calls with the approved token, then:

```bash
python3.12 hardware_audit.py --env lab action rollback --backup state/backups/hardware-action-lab-<stamp>.json    # id- and ownership-verified
python3.12 hardware_audit.py --env lab synthetic snapshot --out evidence/synth-after.json
python3.12 hardware_audit.py --env lab synthetic diff --before evidence/synth-before.json --after evidence/synth-after.json
```

`diff` must print no differences: Interface Alerting action definitions byte-identical (hash); synthetic namespace empty; the hardware action in its before-state - same existence, id and status **and the same signature and definition hash**; not left enabled; `netops_hardware` trigger count unchanged. Event and alert history rows and messages already delivered remain; they are listed in the evidence.

## 10. Recording the outcome

Fill `config/action-validation.yaml` truthfully and only from evidence: `problem_delivery` and `recovery_delivery` (for the synthetic pipeline) after Case A; `interface_exclusion` only if Case D was approved and run, otherwise leave it false and say so; `validated_by`. Report exactly one of: `NOTIFICATION PIPELINE PASS (synthetic)` or `FAIL (<criterion>)`. Hardware coverage stays at 0 PASS and the action stays disabled until real devices are validated.
